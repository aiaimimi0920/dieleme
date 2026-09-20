import { readConfig, type Config } from "./desktop_settings_contract.ts";

export type Baseline = { origin: string; revision: number };
export type Draft = { config: Config; baseline: Baseline | null };
type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function draftKey(api: string): string {
  const url = new URL(api);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error("API 地址无效，无法保存草稿");
  return `crow.collection-settings.draft.v1:${url.origin}`;
}

export function saveDraft(storage: DraftStorage, key: string, draft: Draft): void {
  // Rebuild from the closed schema: never persist credentials or unknown fields.
  const config = readConfig((name) => { const [group, field] = name.split("."); return String(draft.config[group]?.[field] ?? ""); });
  storage.setItem(key, JSON.stringify({ version: 1, config, baseline: draft.baseline }));
}

export function loadDraft(storage: DraftStorage, key: string): Draft | null {
  const raw = storage.getItem(key);
  if (!raw) return null;
  try {
    if (raw.length > 16384) throw new Error("oversized");
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || !("version" in value) || value.version !== 1 || !("config" in value)) throw new Error("schema");
    const configValue = value.config as Config;
    const config = readConfig((name) => { const [group, field] = name.split("."); return String(configValue[group]?.[field] ?? ""); });
    const source = "baseline" in value ? value.baseline : null;
    let baseline: Baseline | null = null;
    if (source !== null) {
      if (!source || typeof source !== "object" || !("origin" in source) || typeof source.origin !== "string" || !("revision" in source) || typeof source.revision !== "number" || !Number.isInteger(source.revision) || source.revision < 0) throw new Error("baseline");
      baseline = { origin: source.origin, revision: source.revision };
    }
    return { config, baseline };
  } catch { throw new Error("本机草稿损坏，未覆盖编辑内容；请读取线上配置后重新保存"); }
}
