import assert from 'node:assert/strict';
import test from 'node:test';
import { boundedSettingsRequest, settingsWaitExpired, SETTINGS_POLL_LIMIT_MS } from './desktop_settings_wait.ts';

test('native request that never settles has a finite wait', async () => {
  await assert.rejects(boundedSettingsRequest(new Promise(() => {}), 5), /超时/);
  assert.equal(await boundedSettingsRequest(Promise.resolve('ready'), 5), 'ready');
});

test('pending application polling stops without declaring success or replaying', () => {
  assert.equal(settingsWaitExpired(null, 99999999), false);
  assert.equal(settingsWaitExpired(100, 100 + SETTINGS_POLL_LIMIT_MS - 1), false);
  assert.equal(settingsWaitExpired(100, 100 + SETTINGS_POLL_LIMIT_MS), true);
});
