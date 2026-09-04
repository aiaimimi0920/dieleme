from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _collection_observer_auth_complete_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    global SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON
    payload = payload if isinstance(payload, dict) else {}
    completion_id = _normalize_auth_completion_id(payload.get("completion_id"))
    source = str(payload.get("source") or "operator")
    completion_scope = _normalize_challenge_scope(payload.get("scope")) or _scope_for_challenge_id(payload.get("challenge_id"))
    if source == "pc2_local_solver" and not completion_id:
        solver_status = _captcha_solver_runtime_status()
        return {
            "ok": False,
            "action": "auth_complete",
            "source": source,
            "completion_id": None,
            "auth_state_confirmed": False,
            "challenge_id": SOLVER_CHALLENGE_ID,
            "paused": bool(solver_status.get("paused")),
            "captcha_solver": solver_status,
            "error": "completion_id is required for pc2_local_solver",
        }
    if not _node_auth_challenge_matches(payload, source):
        solver_status = _captcha_solver_runtime_status()
        return {
            "ok": False,
            "action": "auth_complete",
            "source": source,
            "completion_id": completion_id,
            "auth_state_confirmed": False,
            "stale_challenge": True,
            "challenge_id": SOLVER_CHALLENGE_ID,
            "paused": bool(solver_status.get("paused")),
            "captcha_solver": solver_status,
            "error": "completion belongs to an older captcha challenge",
        }
    previously_confirmed = _auth_completion_was_confirmed(completion_id)
    before_status = _captcha_solver_runtime_status()
    completion_request = before_status.get("last_request")
    if not isinstance(completion_request, dict) or not completion_request:
        completion_request = SOLVER_LAST_REQUEST
    if completion_scope not in CHALLENGE_SCOPES:
        completion_scope = _challenge_scope_for_request(completion_request)
    if completion_scope in CHALLENGE_SCOPES:
        scoped_request = _solver_scope_runtime_status(completion_scope).get("last_request")
        if isinstance(scoped_request, dict) and scoped_request:
            completion_request = scoped_request
    reported_completion_id = str(payload.get("challenge_id") or "").strip()
    if (
        completion_scope in CHALLENGE_SCOPES
        and not _solver_scope_runtime_status(completion_scope).get("challenge_id")
        and reported_completion_id == str(SOLVER_CHALLENGE_ID or "").strip()
    ):
        completion_scope = None
    already_clear = _auth_state_is_confirmed(before_status, completion_scope)
    refresh_cookie_snapshot = _payload_flag(payload, "refresh_cookie_snapshot", True)
    snapshot_gate_required = bool(
        refresh_cookie_snapshot
        or source == "pc2_local_solver"
        or _solver_target_requires_manual_only(completion_request)
    )
    snapshot_payload = dict(payload)
    if snapshot_gate_required:
        snapshot_payload["refresh_cookie_snapshot"] = True
    expected_challenge_id = (
        str(_solver_scope_runtime_status(completion_scope).get("challenge_id") or "").strip() or None
        if completion_scope in CHALLENGE_SCOPES
        else str(SOLVER_CHALLENGE_ID or "").strip() or None
    )

    clear_error: str | None = None
    receipt_error: str | None = None
    finalization_error: str | None = None
    if previously_confirmed:
        auth_state_confirmed = already_clear
        cookie_snapshot = _auth_cookie_snapshot_runtime_status()
    elif not snapshot_gate_required or already_clear:
        clear_error = _clear_solver_manual_required_pause_compat(completion_scope or None)
        cleared_status = _captcha_solver_runtime_status()
        auth_state_confirmed = clear_error is None and _auth_state_is_confirmed(cleared_status, completion_scope)
        if auth_state_confirmed:
            receipt_error = _remember_auth_completion_confirmation(completion_id)
            auth_state_confirmed = receipt_error is None
        cookie_snapshot = _schedule_auth_cookie_snapshot_refresh(snapshot_payload, completion_id)
    else:
        # Phase one: the operator/node reported a completed browser challenge,
        # but HTTP workers must remain paused until those cookies pass the same
        # health probe used by collection.  The background retry performs phase
        # two and clears this exact challenge only after a healthy snapshot.
        auth_state_confirmed = False
        SOLVER_LAST_STATUS = "manual_required"
        SOLVER_LAST_FAILURE_REASON = "manual_required"
        _set_collection_pause_state(True, "manual_required", scope=completion_scope or None)
        cookie_snapshot = _schedule_auth_cookie_snapshot_refresh(
            snapshot_payload,
            completion_id,
            finalize_auth=True,
            expected_challenge_id=expected_challenge_id,
            completion_request=(
                dict(completion_request) if isinstance(completion_request, dict) else None
            ),
        )
        if cookie_snapshot.get("status") == "completed" and cookie_snapshot.get("refreshed") is True:
            finalization = _finalize_auth_completion_after_cookie_snapshot(
                completion_id,
                expected_challenge_id=expected_challenge_id,
                completion_request=(
                    dict(completion_request) if isinstance(completion_request, dict) else None
                ),
            )
            auth_state_confirmed = finalization.get("auth_state_confirmed") is True
            finalization_error = str(finalization.get("error") or "").strip() or None
            cookie_snapshot = {
                **cookie_snapshot,
                "auth_state_confirmed": auth_state_confirmed,
                "auth_finalization": finalization,
            }

    if auth_state_confirmed:
        SOLVER_LAST_STATUS = "manual_auth_completed"
        SOLVER_LAST_FAILURE_REASON = None
        _remember_solver_auth_completion(completion_request)
    elif not previously_confirmed:
        SOLVER_LAST_STATUS = "manual_required"
        SOLVER_LAST_FAILURE_REASON = "manual_required"
        _set_collection_pause_state(True, "manual_required", scope=completion_scope or None)
    solver_status = _captcha_solver_runtime_status()
    scoped_result_status = (
        _solver_scope_runtime_status(completion_scope)
        if completion_scope in CHALLENGE_SCOPES
        else solver_status
    )
    snapshot_status = str(cookie_snapshot.get("status") or "").strip().lower()
    auth_confirmation_pending = bool(
        not auth_state_confirmed and snapshot_status in {"pending", "running"}
    )
    result = {
        "ok": bool(auth_state_confirmed or auth_confirmation_pending),
        "action": "auth_complete",
        "source": source,
        "completion_id": completion_id,
        "auth_state_confirmed": auth_state_confirmed,
        "idempotent": bool(previously_confirmed or (already_clear and auth_state_confirmed)),
        "manual_auth_completed": auth_state_confirmed,
        "auth_confirmation_pending": auth_confirmation_pending,
        "paused": bool(solver_status.get("paused")),
        "scope": completion_scope or None,
        "scope_paused": bool(scoped_result_status.get("paused")),
        "scope_manual_required": bool(scoped_result_status.get("manual_required")),
        "scope_force_reset_required": bool(scoped_result_status.get("force_reset_required")),
        "scope_force_unlock_flag_exists": bool(
            completion_scope in CHALLENGE_SCOPES
            and os.path.exists(_solver_scope_manual_flag_path(completion_scope))
        ),
        "runtime_state": _collection_runtime_state_label(),
        "captcha_solver": solver_status,
        "cookie_snapshot": cookie_snapshot,
    }
    if clear_error is not None:
        result["error"] = f"failed to clear force unlock flag: {clear_error}"
    elif receipt_error is not None:
        result["error"] = f"failed to persist auth completion receipt: {receipt_error}"
    elif finalization_error is not None:
        result["error"] = finalization_error
    elif previously_confirmed and not auth_state_confirmed:
        result["error"] = "confirmed completion_id is stale for the current auth state"
    elif snapshot_status == "failed":
        result["error"] = "cookie snapshot refresh failed; collection remains paused"
    elif snapshot_status == "completed" and not auth_state_confirmed:
        result["error"] = "cookie snapshot completed but auth state could not be confirmed"
    elif not auth_state_confirmed:
        result["pending_reason"] = "waiting for a healthy cookie snapshot"
    return result

def _safe_collection_static_path(request_path: str) -> Path | None:
    if request_path.startswith("/collection/"):
        relative = unquote(request_path[len("/collection/") :]).strip("/")
    elif request_path.startswith("/assets/"):
        relative = unquote(request_path.lstrip("/")).strip("/")
    else:
        return None
    if not relative:
        relative = "index.html"
    candidate = (COLLECTOR_DESKTOP_DIST / relative).resolve()
    root = COLLECTOR_DESKTOP_DIST.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate

def _collection_observer_static_asset(request_path: str) -> tuple[bytes, str] | None:
    path = _safe_collection_static_path(request_path)
    if path is None:
        return None
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".js":
        content_type = "application/javascript"
    elif path.suffix == ".css":
        content_type = "text/css"
    elif path.suffix == ".html":
        content_type = "text/html; charset=utf-8"
    return path.read_bytes(), content_type

def _collection_observer_page_html() -> str:
    index_path = COLLECTOR_DESKTOP_DIST / "index.html"
    if index_path.is_file():
        return index_path.read_text(encoding="utf-8")
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FapaiFang 采集观察台</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%232459d6'/%3E%3Cpath d='M18 38h28v6H18zm4-18h20v6H22zm-4 9h28v6H18z' fill='white'/%3E%3C/svg%3E">
  <style>
    :root { color-scheme: light; --bg:#f5f7fb; --panel:#fff; --line:#d9e0ea; --text:#172033; --muted:#667085; --primary:#2459d6; --ok:#047857; --warn:#b45309; --bad:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, "Segoe UI", Arial, "Microsoft YaHei", sans-serif; background:var(--bg); color:var(--text); }
    header { padding:20px 24px 14px; background:linear-gradient(135deg,#172033,#2459d6); color:white; }
    header h1 { margin:0 0 8px; font-size:24px; }
    header p { margin:0; color:rgba(255,255,255,.78); }
    main { padding:18px 24px 28px; display:grid; gap:16px; }
    .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; }
    .card, .panel { background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 24px rgba(16,24,40,.06); }
    .card { padding:14px 16px; }
    .card .label { color:var(--muted); font-size:13px; }
    .card .value { font-size:28px; font-weight:760; margin-top:5px; }
    .card .hint { color:var(--muted); margin-top:6px; font-size:12px; }
    .toolbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:12px; }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; }
    button { border:1px solid var(--line); background:white; color:var(--text); padding:8px 12px; border-radius:10px; cursor:pointer; }
    button.active { background:var(--primary); color:white; border-color:var(--primary); }
    button:hover { border-color:var(--primary); }
    input, select { border:1px solid var(--line); border-radius:10px; padding:8px 10px; }
    .layout { display:grid; grid-template-columns:minmax(420px,1.15fr) minmax(360px,.85fr); gap:16px; align-items:start; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { border-top:1px solid var(--line); padding:9px 10px; text-align:left; vertical-align:top; }
    th { color:var(--muted); background:#f8fafc; font-weight:650; position:sticky; top:0; }
    tr.item-row { cursor:pointer; }
    tr.item-row:hover { background:#eef4ff; }
    .table-wrap { max-height:68vh; overflow:auto; }
    .pill { display:inline-flex; align-items:center; border-radius:999px; padding:2px 8px; font-size:12px; background:#eef2ff; color:#3538cd; }
    .pill.ok { background:#ecfdf3; color:var(--ok); }
    .pill.warn { background:#fffaeb; color:var(--warn); }
    .pill.bad { background:#fef3f2; color:var(--bad); }
    .detail { padding:14px; }
    .detail h2 { margin:0 0 8px; font-size:18px; }
    .kv { display:grid; grid-template-columns:112px 1fr; gap:6px 10px; font-size:13px; margin:10px 0 12px; }
    .kv .k { color:var(--muted); }
    pre { white-space:pre-wrap; word-break:break-word; background:#0b1020; color:#dbeafe; border-radius:12px; padding:12px; max-height:360px; overflow:auto; font-size:12px; line-height:1.45; }
    details { border-top:1px solid var(--line); padding:10px 0; }
    summary { cursor:pointer; font-weight:650; }
    a { color:var(--primary); word-break:break-all; }
    .status-line { display:flex; gap:8px; align-items:center; flex-wrap:wrap; color:var(--muted); font-size:13px; }
    .error { color:var(--bad); }
    @media (max-width: 980px) { .layout { grid-template-columns:1fr; } .table-wrap { max-height:none; } }
  </style>
</head>
<body>
  <header>
    <h1>FapaiFang 采集观察台</h1>
    <p>只读观察采集三段流水：商品链接采集、商品详情页采集、商品详情页 AI 分析。暂不包含房价分析引擎。</p>
  </header>
  <main>
    <section class="cards" id="cards"></section>
    <section class="panel">
      <div class="toolbar">
        <div class="tabs">
          <button data-stage="links" class="active">商品链接采集</button>
          <button data-stage="details">商品详情页采集</button>
          <button data-stage="analysis">商品详情页 AI 分析</button>
        </div>
        <label>每页 <select id="limit"><option>50</option><option selected>100</option><option>200</option><option>500</option></select></label>
        <button id="refresh">刷新</button>
        <button id="prev">上一页</button>
        <button id="next">下一页</button>
        <span class="status-line" id="listStatus"></span>
      </div>
    </section>
    <section class="layout">
      <div class="panel table-wrap"><table><thead><tr><th>商品</th><th>状态</th><th>列表来源</th><th>详情/AI文件</th></tr></thead><tbody id="items"></tbody></table></div>
      <aside class="panel detail" id="detail"><h2>商品详情</h2><p class="status-line">点击左侧任一商品查看采集到的实际数据。</p></aside>
    </section>
  </main>
  <script>
    const state = { stage: 'links', limit: 100, offset: 0, total: 0 };
    const $ = (id) => document.getElementById(id);
    const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const fmt = (v) => v === null || v === undefined || v === '' ? '-' : esc(v);
    const statusClass = (s) => s === 'detail_completed' ? 'ok' : (String(s || '').includes('failed') || String(s || '').includes('blocked') ? 'bad' : 'warn');

    async function getJson(url) {
      const resp = await fetch(url, { cache: 'no-store' });
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      return await resp.json();
    }

    async function loadOverview() {
      const data = await getJson('/api/collection/overview');
      const m = data.modules || {};
      const paused = data.status && data.status.paused;
      $('cards').innerHTML = `
        <div class="card"><div class="label">运行状态</div><div class="value">${paused ? '已暂停' : '运行中'}</div><div class="hint">captcha/manual 状态也会计入暂停判定</div></div>
        <div class="card"><div class="label">商品链接采集</div><div class="value">${fmt(m.links && m.links.total)}</div><div class="hint">总链接出现次数；唯一商品 ${fmt(m.links && m.links.unique_items)}</div></div>
        <div class="card"><div class="label">商品详情页采集</div><div class="value">${fmt(m.details && m.details.captured)}</div><div class="hint">待抓 ${fmt(m.details && m.details.pending)} / 失败 ${fmt(m.details && m.details.failed)} / 阻塞 ${fmt(m.details && m.details.blocked)}</div></div>
        <div class="card"><div class="label">商品详情页 AI 分析</div><div class="value">${fmt(m.analysis && m.analysis.finalized)}</div><div class="hint">待分析 ${fmt(m.analysis && m.analysis.pending)} / 失败 ${fmt(m.analysis && m.analysis.failed)} / 阻塞 ${fmt(m.analysis && m.analysis.blocked)}</div></div>
      `;
    }

    function renderItems(data) {
      state.total = data.total || 0;
      $('listStatus').textContent = `阶段 ${state.stage}，总数 ${state.total}，当前 ${state.offset + 1}-${Math.min(state.offset + state.limit, state.total)}`;
      $('items').innerHTML = (data.items || []).map(item => {
        const occ = item.latest_occurrence || {};
        const artifacts = item.artifacts || {};
        const fileHint = state.stage === 'analysis' ? item.final_json_path : artifacts.detail_html_path;
        return `<tr class="item-row" data-id="${esc(item.item_id)}">
          <td><strong>${fmt(item.title || item.item_id)}</strong><br><a href="${esc(item.source_url || '#')}" target="_blank">${fmt(item.source_url)}</a><br><span class="status-line">ID ${fmt(item.item_id)} · ${fmt(item.last_seen_at || item.updated_at)}</span></td>
          <td><span class="pill ${statusClass(item.status)}">${fmt(item.status)}</span><br>attempts ${fmt(item.detail_attempt_count)}</td>
          <td>${fmt(occ.sort_name || occ.sort_key)}<br>page ${fmt(occ.page)} / rank ${fmt(occ.rank)}<br><a href="${esc(occ.source_page_url || '#')}" target="_blank">${fmt(occ.source_page_url)}</a></td>
          <td>${fmt(fileHint)}</td>
        </tr>`;
      }).join('');
      document.querySelectorAll('tr.item-row').forEach(row => row.addEventListener('click', () => loadDetail(row.dataset.id)));
    }

    async function loadItems() {
      $('listStatus').textContent = '加载中...';
      const data = await getJson(`/api/collection/items?stage=${encodeURIComponent(state.stage)}&limit=${state.limit}&offset=${state.offset}`);
      renderItems(data);
    }

    function artifactBlock(title, artifact) {
      artifact = artifact || {};
      const content = artifact.json ? JSON.stringify(artifact.json, null, 2) : (artifact.content || '');
      return `<details open><summary>${esc(title)} ${artifact.exists ? '' : '(未找到文件)'}</summary><div class="status-line">${fmt(artifact.path)} ${artifact.truncated ? ' · 已截断' : ''} ${artifact.error ? ' · ' + esc(artifact.error) : ''}</div><pre>${esc(content || '无内容')}</pre></details>`;
    }

    async function loadDetail(itemId) {
      $('detail').innerHTML = '<h2>商品详情</h2><p class="status-line">加载中...</p>';
      const data = await getJson(`/api/collection/item?item_id=${encodeURIComponent(itemId)}&max_chars=200000`);
      if (!data.found) {
        $('detail').innerHTML = `<h2>商品详情</h2><p class="error">未找到商品 ${esc(itemId)}</p>`;
        return;
      }
      const item = data.item || {};
      const artifacts = data.artifacts || {};
      const flat = data.flat_item ? JSON.stringify(data.flat_item, null, 2) : '';
      $('detail').innerHTML = `
        <h2>${fmt(item.title || item.item_id)}</h2>
        <div class="kv">
          <div class="k">商品 ID</div><div>${fmt(item.item_id)}</div>
          <div class="k">状态</div><div><span class="pill ${statusClass(item.status)}">${fmt(item.status)}</span></div>
          <div class="k">商品链接</div><div><a href="${esc(item.source_url || '#')}" target="_blank">${fmt(item.source_url)}</a></div>
          <div class="k">首次发现</div><div>${fmt(item.first_seen_at)}</div>
          <div class="k">最后更新</div><div>${fmt(item.updated_at)}</div>
        </div>
        ${artifactBlock('详情页 HTML / 文本', artifacts.detail_html)}
        ${artifactBlock('详情页 selected.json', artifacts.selected_json)}
        ${artifactBlock('详情页 description-data.json', artifacts.description_json)}
        ${artifactBlock('AI 标准化 final.json', artifacts.final_json)}
        <details ${flat ? 'open' : ''}><summary>数据库标准化字段</summary><pre>${esc(flat || '暂无 property_listing 标准化字段')}</pre></details>
        <details><summary>列表出现记录</summary><pre>${esc(JSON.stringify(data.occurrences || [], null, 2))}</pre></details>
      `;
    }

    document.querySelectorAll('button[data-stage]').forEach(btn => btn.addEventListener('click', async () => {
      document.querySelectorAll('button[data-stage]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.stage = btn.dataset.stage;
      state.offset = 0;
      await loadItems();
    }));
    $('limit').addEventListener('change', async e => { state.limit = Number(e.target.value || 100); state.offset = 0; await loadItems(); });
    $('refresh').addEventListener('click', async () => { await loadOverview(); await loadItems(); });
    $('prev').addEventListener('click', async () => { state.offset = Math.max(0, state.offset - state.limit); await loadItems(); });
    $('next').addEventListener('click', async () => { if (state.offset + state.limit < state.total) state.offset += state.limit; await loadItems(); });
    (async function init(){ try { await loadOverview(); await loadItems(); } catch (err) { $('listStatus').innerHTML = `<span class="error">${esc(err.message)}</span>`; } })();
  </script>
</body>
</html>"""

__all__ = ["_collection_observer_auth_complete_payload", "_safe_collection_static_path", "_collection_observer_static_asset", "_collection_observer_page_html"]
