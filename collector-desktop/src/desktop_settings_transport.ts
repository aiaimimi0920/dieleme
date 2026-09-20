import { object } from "./desktop_overview.ts";
import { controlOrigin } from "./desktop_settings_contract.ts";
import { boundedSettingsRequest } from "./desktop_settings_wait.ts";

type Invoke = (command: string, args: Record<string, unknown>) => Promise<unknown>;
let nativeQueue: Promise<unknown> = Promise.resolve();

function invokeControl(invoke: Invoke, request: Record<string, unknown>): Promise<unknown> {
  const operation = nativeQueue.then(() => boundedSettingsRequest(invoke("desktop_settings_action", { request })));
  nativeQueue = operation.catch(() => undefined);
  return operation;
}

function nativeInvoke(): Invoke | undefined {
  const host = window as unknown as { __TAURI__?: { core?: { invoke?: Invoke } }; __TAURI_INTERNALS__?: { invoke?: Invoke } };
  return host.__TAURI__?.core?.invoke ?? host.__TAURI_INTERNALS__?.invoke;
}

export async function installedControlOrigin(): Promise<string | null> {
  const invoke = nativeInvoke();
  if (!invoke) return null;
  const value = object(await invokeControl(invoke, { action: "config" }));
  if (value.ok !== true || value.configured !== true || typeof value.origin !== "string") throw new Error("本机安全控制组件未配置，请更新完整桌面组件");
  return value.origin;
}

export async function settingsRequest(origin: string, path: string, token: string, body?: unknown): Promise<Record<string, unknown>> {
  origin = controlOrigin(origin);
  if (path !== "" && path !== "/apply") throw new Error("不支持的配置操作");
  const invoke = nativeInvoke();
  let value: Record<string, unknown>;
  let status: unknown;
  if (invoke) {
    value = object(await invokeControl(invoke, { action: path ? "apply" : "get", origin, body: body ?? null }));
    status = value.status;
  } else {
    if (!token) throw new Error("请先填写控制授权");
    const response = await fetch(`${origin}/api/collection/settings${path}`, {
      method: body === undefined ? "GET" : "POST", redirect: "error", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-FAPAI-Control-Token": token },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(20_000),
    });
    status = response.status;
    if (status === 404) throw new Error("线上尚未启用采集配置接口；本机草稿未应用到 PC2");
    value = object(await response.json());
    if (!response.ok) value.ok = false;
  }
  if (status === 404) throw new Error("线上尚未启用采集配置接口；本机草稿未应用到 PC2");
  if (value.ok !== true) throw new Error(status ? `控制接口未完成请求（HTTP ${status}）；请刷新状态，不要重复提交` : "安全控制连接失败；请检查证书、凭据和控制地址，不要重复提交");
  return value;
}

export async function installedRestartRequest(origin: string, requestId?: string): Promise<Record<string, unknown>> {
  const invoke = nativeInvoke();
  if (!invoke) throw new Error("本机安全控制组件不可用");
  const value = object(await invokeControl(invoke, {
    action: requestId ? "restart" : "restart_status", origin: controlOrigin(origin),
    body: requestId ? { request_id: requestId } : null,
  }));
  if (value.ok !== true) throw new Error("PC2 重启控制连接失败，请刷新状态确认");
  return value;
}
