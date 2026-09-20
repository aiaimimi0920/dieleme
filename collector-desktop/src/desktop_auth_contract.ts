import { object } from "./desktop_overview.ts";

const messages: Record<string, string> = {
  shared_receiving: "同一份 Cookie 正在依次同步给链接采集和详情采集，无需再次人工认证。",
  shared_retry: "认证 Cookie 已保存，交接连接暂时不可用，正在自动重试，无需再次认证。",
  shared_queued: "已保存本次认证 Cookie，等待当前交接结束后自动同步两个阶段，无需重复点击。",
  shared_succeeded: "同一份 Cookie 已用于链接和详情采集，两个阶段均已确认恢复。",
  shared_partial: "同一份 Cookie 的两个阶段处理已结束，但未全部确认恢复；请查看各阶段状态。",
  shared_snapshot_expired: "等待交接超过 30 分钟，未继续使用旧 Cookie，请重新提交当前浏览器会话。",
  existing_recovery: "已有认证恢复任务正在处理，等待 PC1 交接和 PC2 验证。",
  handoff_busy: "另一认证交接正在进行，请稍后重试。",
  invalid_snapshot: "认证快照格式无效，原有会话未被覆盖。",
  challenge_page_not_ready: "请先在打开的挑战页面完成认证，再点击已完成挑战。",
  session_not_reusable: "浏览器会话尚未通过复用验证，请完成挑战后重试；PC2 保持等待。",
  token_unavailable: "本机缺少认证同步凭据，请检查认证组件配置。",
  runtime_config_invalid: "本机认证配置无法读取，请修复桌面安装目录中的运行配置。",
  token_rejected: "认证同步凭据未被 NAS 接受。",
  api_upgrade_required: "NAS 尚未安装认证同步接口。",
  stage_api_upgrade_required: "NAS 尚未升级分阶段认证接口；未发送 Cookie，请先更新 NAS 认证组件。",
  pc2_stage_upgrade_required: "PC2 分阶段认证组件尚未就绪；未发送 Cookie，请先更新或检查 PC2 认证组件。",
  stage_probe_failed: "PC2 的链接页面仍未通过有效数据验证，请重新打开此阶段的挑战页面。",
  stage_probe_unavailable: "认证快照已到达 PC2，但浏览器或网络探测不可用；这不是人工挑战失败，请检查 PC2 后重新提交。",
  api_not_configured: "当前 API 与本机认证配置不同，未发送认证凭据。",
  challenge_changed: "当前采集页面或挑战已变化，请重新打开实际采集页面后提交；默认列表页的认证不能确认地区列表恢复。",
  browser_unavailable: "挑战浏览器未能打开，请检查本机认证组件。",
  pc2_receiving: "认证快照已提交，等待 PC2 领取。",
  pc2_importing: "PC2 已领取认证快照，正在导入会话。",
  pc2_restarting: "PC2 已导入认证会话，正在重启认证浏览器。",
  pc2_stage_verifying: "PC2 已导入认证会话，正在验证此阶段的真实页面，无需重启浏览器。",
  pc2_verifying: "PC2 已接收会话，正在确认采集恢复。",
  pc2_receive_timeout: "PC2 未在规定时间内领取认证快照，请检查 PC2 认证组件。",
  pc2_import_timeout: "PC2 已领取快照，但导入会话超时，请检查 PC2 认证组件。",
  pc2_restart_timeout: "PC2 已导入会话，但认证浏览器重启超时。",
  pc2_progress_timeout: "PC2 已接收会话，但尚未观察到采集恢复；认证恢复验证已超时。",
  operator_pause_active: "采集已被手动暂停，认证恢复没有自动解除暂停。",
};

export function authResult(value: unknown): { phase: string; message: string; completed: boolean } {
  const result = object(value);
  const phase = String(result.phase || "unavailable");
  const fallback: Record<string, string> = {
    ready_for_human: "挑战页面已打开。",
    pending_human: "认证会话尚未就绪，请完成挑战后重试。",
    pending_pc2: result.code === "pc2_verifying" ? "PC2 已接收会话，正在确认采集恢复。" : "认证快照已提交，等待 PC2 接收和验证。",
    succeeded: "此阶段认证已确认；其他阶段的认证状态独立显示。",
    failed: "PC2 未能确认恢复，请重新打开挑战页面后重试。",
    unavailable: "认证同步暂不可用，请稍后重试。",
  };
  let message = messages[String(result.code)] || fallback[phase] || fallback.unavailable;
  if (result.shared) {
    const stages = object(result.stage_results);
    const labels = { seed: "链接", detail: "详情" };
    message += " " + (Object.keys(labels) as (keyof typeof labels)[]).map((scope) => {
      const stage = object(stages[scope]);
      const detail = stage.phase === "succeeded" ? "已恢复" : stage.phase === "failed"
        ? messages[String(stage.code)] || "未确认恢复" : "等待确认";
      return `${labels[scope]}：${detail}`;
    }).join("；");
  }
  return { phase, message,
    completed: phase === "succeeded" };
}

export const AUTH_POLL_LIMIT_MS = 15 * 60 * 1000;

export function authWaitState(startedAt: number | null, now: number): { poll: boolean; hint: string } {
  if (startedAt === null || now - startedAt < AUTH_POLL_LIMIT_MS) return { poll: true, hint: "" };
  return { poll: false, hint: "等待已超过 15 分钟，已停止自动查询。点击“已完成挑战”可再次查询；这不代表认证成功。" };
}
