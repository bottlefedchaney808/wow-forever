'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const QuestLog = require('../data/questlog_schema.js');

function operation(player, entity_id, timestamp, deleted, value) {
  return { player, entity_id, timestamp, deleted, value: value || null };
}

test('migration assigns stable entity IDs and preserves legacy quest fields', function () {
  const legacy = [{ n: 'Goldshire', k: 'zone', ll: [1, 2], lv: '1-10' }];
  const state = QuestLog.migrateLegacy(legacy, 'player-1', 100);
  assert.equal(state.schema_version, 1);
  assert.deepEqual(QuestLog.list(state, 'player-1'), legacy);
  assert.equal(QuestLog.migrateLegacy(legacy, 'player-1', 200).entries[0].entity_id,
    state.entries[0].entity_id);
});

test('entity ID is stable across changes to non-identity metadata', function () {
  assert.equal(
    QuestLog.entityId({ n: 'Goldshire', k: 'zone', ll: [1, 2], lv: '1-10' }),
    QuestLog.entityId({ n: 'Goldshire', k: 'area', ll: [1, 2], lv: '5-12' })
  );
});

test('state merge is deterministic for concurrent edits and remove tombstones', function () {
  const initial = QuestLog.create();
  const left = QuestLog.mergeStates(initial, { schema_version: 1, entries: [
    operation('p', 'e', 10, false, { n: 'new', k: 'zone', ll: [1, 2], lv: '' })
  ] });
  const right = QuestLog.mergeStates(initial, { schema_version: 1, entries: [
    operation('p', 'e', 11, true, null)
  ] });
  assert.deepEqual(QuestLog.mergeStates(left, right), QuestLog.mergeStates(right, left));
  assert.deepEqual(QuestLog.list(QuestLog.mergeStates(left, right), 'p'), []);
});

test('same timestamp conflicts resolve identically regardless of merge order', function () {
  const initial = QuestLog.create();
  const left = { schema_version: 1, entries: [
    operation('p', 'e', 50, false, { n: 'left', k: 'zone', ll: [1, 2], lv: '' })
  ] };
  const right = { schema_version: 1, entries: [
    operation('p', 'e', 50, false, { n: 'right', k: 'zone', ll: [1, 2], lv: '' })
  ] };
  assert.deepEqual(QuestLog.mergeStates(QuestLog.mergeStates(initial, left), right),
    QuestLog.mergeStates(QuestLog.mergeStates(initial, right), left));
});

test('delta applies only when its base version matches exactly', function () {
  const state = QuestLog.create();
  const delta = {
    schema_version: 1,
    base_version: QuestLog.versionHash(state),
    operations: [operation('p', 'e', 10, false,
      { n: 'Goldshire', k: 'zone', ll: [1, 2], lv: '' })]
  };
  const applied = QuestLog.applyDelta(state, delta);
  assert.equal(applied.accepted, true);
  assert.deepEqual(QuestLog.list(applied.state, 'p'), [delta.operations[0].value]);

  const stale = QuestLog.applyDelta(applied.state, delta);
  assert.equal(stale.accepted, false);
  assert.equal(stale.reason, 'base_version_mismatch');
  assert.deepEqual(stale.state, applied.state);
});

test('entity IDs differ across distinct entries (no zero-hash collapse)', function () {
  // Regression: hash() constants were corrupted by Number() rounding, which
  // zeroed every digest and made all entity IDs 'q-0000000000000000'.
  const a = QuestLog.entityId({ n: 'Goldshire', k: 'zone', ll: [1, 2], lv: '' });
  const b = QuestLog.entityId({ n: 'Dun Morogh', k: 'zone', ll: [3, 4], lv: '' });
  assert.notEqual(a, b);
  assert.notEqual(a, 'q-0000000000000000');
});

test('migration keeps every distinct legacy entry', function () {
  // Regression: collapsed entity IDs made normalize() keep only one entry.
  const state = QuestLog.migrateLegacy([
    { n: 'A', k: 'zone', ll: [1, 2] },
    { n: 'B', k: 'zone', ll: [3, 4] }
  ], 'player-1', 100);
  assert.equal(state.entries.length, 2);
  assert.equal(QuestLog.list(state, 'player-1').length, 2);
});

test('versionHash is content-derived: same count, different content => different hash', function () {
  // Regression: the old salt was entry_count + process counter, so two
  // one-entry states hashed identically.
  const empty = QuestLog.create();
  const a = QuestLog.put(empty, 'p', { n: 'Goldshire', k: 'zone', ll: [1, 2], lv: '' }, 10);
  const b = QuestLog.put(empty, 'p', { n: 'Dun Morogh', k: 'zone', ll: [1, 2], lv: '' }, 10);
  assert.equal(a.entries.length, b.entries.length);
  assert.notEqual(QuestLog.versionHash(a), QuestLog.versionHash(b));
});

test('versionHash is deterministic across processes (known answers)', function () {
  // Fixed timestamps make the state reproducible; the digests must match a
  // fresh node process exactly (no process-global state, no env branch).
  const op = operation('p', 'e', 10, false, { n: 'Goldshire', k: 'zone', ll: [1, 2], lv: '' });
  const oneEntry = { schema_version: 1, entries: [op] };
  assert.equal(QuestLog.versionHash(QuestLog.create()), 'cbf29ce4');
  assert.equal(QuestLog.versionHash(oneEntry), '9730e43f');

  const child = require('child_process').execFileSync(process.execPath, ['-e',
    'const Q = require("' + require('path').resolve(__dirname, '..', 'data', 'questlog_schema.js') + '");' +
    'const op = { player:"p", entity_id:"e", timestamp:10, deleted:false,' +
    ' value:{ n:"Goldshire", k:"zone", ll:[1, 2], lv:"" } };' +
    'process.stdout.write(Q.versionHash(Q.create()) + " " + Q.versionHash({ schema_version:1, entries:[op] }));'
  ], { encoding: 'utf8' });
  assert.equal(child, 'cbf29ce4 9730e43f');
});
