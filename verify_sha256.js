'use strict';

/*
 * Manual integrity check for WFQuestLog.versionHash (the CRDT base_version).
 *
 * Known-answer + property checks; exits non-zero on any mismatch so it can
 * gate a pipeline. The digests below pin the FNV-1a 64-bit implementation:
 * a change to hash() or versionHash() that breaks environment-agnostic
 * determinism will fail this script.
 */

const { execFileSync } = require('child_process');
const path = require('path');
const QuestLog = require('./data/questlog_schema.js');

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? '✓' : '✗'} ${label}: ${actual}${ok ? '' : ` (expected ${expected})`}`);
}

// 1. Known answers for fixed states (empty + one entry at ts=10).
const op = { player: 'p', entity_id: 'e', timestamp: 10, deleted: false,
  value: { n: 'Goldshire', k: 'zone', ll: [1, 2], lv: '' } };
const oneEntry = { schema_version: 1, entries: [op] };

check('versionHash(create())', QuestLog.versionHash(QuestLog.create()), 'cbf29ce4');
check('versionHash(one entry, ts=10)', QuestLog.versionHash(oneEntry), '9730e43f');

// 2. Fresh process must return the identical digests (no process-global salt,
// no Node-only code path).
const child = execFileSync(process.execPath, ['-e',
  'const Q = require(' + JSON.stringify(path.join(__dirname, 'data', 'questlog_schema.js')) + ');' +
  'const op = { player:"p", entity_id:"e", timestamp:10, deleted:false,' +
  ' value:{ n:"Goldshire", k:"zone", ll:[1, 2], lv:"" } };' +
  'process.stdout.write(Q.versionHash(Q.create()) + " " + Q.versionHash({ schema_version:1, entries:[op] }));'
], { encoding: 'utf8' });
check('fresh-process digests', child, 'cbf29ce4 9730e43f');

// 3. Content sensitivity: same entry count, different content => different hash.
const empty = QuestLog.create();
const a = QuestLog.put(empty, 'p', { n: 'Goldshire', k: 'zone', ll: [1, 2], lv: '' }, 10);
const b = QuestLog.put(empty, 'p', { n: 'Dun Morogh', k: 'zone', ll: [1, 2], lv: '' }, 10);
check('same-count states differ', QuestLog.versionHash(a) !== QuestLog.versionHash(b), true);

// 4. Replay detection: a delta must be rejected once its base state changes.
const delta = { schema_version: 1, base_version: QuestLog.versionHash(empty), operations: [op] };
const applied = QuestLog.applyDelta(empty, delta);
const stale = QuestLog.applyDelta(applied.state, delta);
check('apply accepted', applied.accepted, true);
check('replay rejected', !stale.accepted && stale.reason === 'base_version_mismatch', true);

console.log(failures === 0 ? '\nall checks passed' : `\n${failures} check(s) FAILED`);
process.exit(failures === 0 ? 0 : 1);
