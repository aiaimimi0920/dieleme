export type NativeInvoke = (command: string, args: Record<string, unknown>) => Promise<unknown>;

export function nativeInvoke(): NativeInvoke | undefined {
  if (typeof window === "undefined") return undefined;
  const host = window as unknown as {
    __TAURI__?: { core?: { invoke?: NativeInvoke } };
    __TAURI_INTERNALS__?: { invoke?: NativeInvoke };
  };
  const core = host.__TAURI__?.core;
  if (typeof core?.invoke === "function") return core.invoke.bind(core);
  const internal = host.__TAURI_INTERNALS__;
  return typeof internal?.invoke === "function" ? internal.invoke.bind(internal) : undefined;
}

export function isTauriRuntime(): boolean {
  return typeof nativeInvoke() === "function";
}

export async function tryInvoke(command: string, args: Record<string, unknown> = {}): Promise<unknown> {
  const invoke = nativeInvoke();
  if (!invoke) throw new Error("not running inside Tauri");
  return invoke(command, args);
}
