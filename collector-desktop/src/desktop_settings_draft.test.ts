import assert from "node:assert/strict";
import { test } from "node:test";
import { localCollectionDefaults } from "./collection_defaults.ts";
import { draftKey, loadDraft, saveDraft } from "./desktop_settings_draft.ts";

function storage() {
  const values = new Map<string, string>();
  return { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); } };
}

test("drafts persist edited values and live baseline separately for each NAS", () => {
  const store = storage();
  const key = draftKey("http://192.0.2.1:8001/api");
  const config = structuredClone(localCollectionDefaults);
  config.workers.details = 2;
  const draft = { config, baseline: { origin: "https://control.example.invalid", revision: 4 } };
  saveDraft(store, key, draft);
  assert.deepEqual(loadDraft(store, key), draft);
  assert.equal(loadDraft(store, draftKey("http://192.0.2.2:8001")), null);
  assert.equal(draftKey("http://192.0.2.1:8001/"), key);
});

test("draft serializer excludes AI keys and unknown fields", () => {
  const store = storage();
  const config = structuredClone(localCollectionDefaults);
  config.ai.api_key = "synthetic-not-for-storage";
  config.credentials = { operator_token: "synthetic-secret" };
  saveDraft(store, "test", { config, baseline: null });
  assert.doesNotMatch(store.getItem("test")!, /synthetic|api_key|operator_token/);
});

test("invalid drafts fail visibly instead of silently replacing edits", () => {
  const store = storage();
  for (const raw of ["broken JSON", JSON.stringify({ version: 1, config: {} }), " ".repeat(16385)]) {
    store.setItem("test", raw);
    assert.throws(() => loadDraft(store, "test"), /草稿损坏/);
    assert.equal(store.getItem("test"), raw);
  }
});

test("draft cannot persist credentials in an AI URL or API origin", () => {
  const store = storage();
  for (const url of ["https://u:secret@ai.example.invalid/v1", "https://ai.example.invalid/v1?api_key=secret", "file:///secret"]) {
    const config = structuredClone(localCollectionDefaults);
    config.ai.base_url = url;
    assert.throws(() => saveDraft(store, "test", { config, baseline: null }));
    assert.equal(store.getItem("test"), null);
  }
  assert.throws(() => draftKey("http://user:secret@example.invalid"));
});
