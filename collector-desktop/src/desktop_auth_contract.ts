import { object } from "./desktop_value.ts";

import { AUTH_MESSAGES, AUTH_PHASE_MESSAGES } from "./auth_recovery_codes.generated.ts";

function messageForCode(value: unknown): string | undefined {
  return typeof value === "string" && Object.hasOwn(AUTH_MESSAGES, value)
    ? AUTH_MESSAGES[value as keyof typeof AUTH_MESSAGES] : undefined;
}

function messageForPhase(phase: string): string {
  return Object.hasOwn(AUTH_PHASE_MESSAGES, phase)
    ? AUTH_PHASE_MESSAGES[phase as keyof typeof AUTH_PHASE_MESSAGES] : AUTH_PHASE_MESSAGES.unavailable;
}

export function authResult(value: unknown): { phase: string; message: string; completed: boolean } {
  const result = object(value);
  const phase = String(result.phase || "unavailable");
  let message = messageForCode(result.code) || messageForPhase(phase);
  if (result.shared) {
    const stages = object(result.stage_results);
    const labels = { seed: "链接", detail: "详情" };
    message += " " + (Object.keys(labels) as (keyof typeof labels)[]).map((scope) => {
      const stage = object(stages[scope]);
      const detail = stage.phase === "succeeded" ? "已恢复" : stage.phase === "failed"
        ? messageForCode(stage.code) || "未确认恢复" : "等待确认";
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
