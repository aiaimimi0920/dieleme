export const SETTINGS_POLL_LIMIT_MS = 12 * 60 * 1000;

export function settingsWaitExpired(startedAt: number | null, now: number): boolean {
  return startedAt !== null && now - startedAt >= SETTINGS_POLL_LIMIT_MS;
}

export async function boundedSettingsRequest<T>(request: Promise<T>, timeoutMs = 40_000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([request, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("设置连接超时；请刷新状态确认，勿重复提交，草稿已保留")), timeoutMs);
    })]);
  } finally { clearTimeout(timer); }
}
