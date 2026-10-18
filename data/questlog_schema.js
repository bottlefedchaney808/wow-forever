'use strict';

/*
 * Quest log LWW-element set, schema v1.
 * Wire/state operation: { player, entity_id, timestamp, deleted, value }.
 * A greater timestamp wins; equal timestamps use canonical operation JSON as a
 * deterministic tie-break so replicas resolve concurrent writes identically.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.WFQuestLog = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  var SCHEMA_VERSION = 1;

  function stableStringify(value) {
    if (value === null || typeof value !== 'object') return JSON.stringify(value);
    if (Array.isArray(value)) return '[' + value.map(stableStringify).join(',') + ']';
    return '{' + Object.keys(value).sort().map(function (key) {
      return JSON.stringify(key) + ':' + stableStringify(value[key]);
    }).join(',') + '}';
  }


  // versionHash uses the FNV-1a hash() over canonical entries (no Node crypto).


  // FNV-1a 64-bit hash: deterministic, synchronous, no browser APIs.
  // BigInt literals (n suffix) keep the constants exact — passing the hex
  // literals through Number() first silently rounded the prime to exactly
  // 2**64, which zeroed every digest and collapsed all entity IDs to one.
  // Mask at each step so the arithmetic wraps like true 64-bit FNV-1a.
  function hash(text) {
    var h = 0xcbf29ce484222325n;
    var p = 0x00000100000001b3n;
    var mask = 0xffffffffffffffffn;
    for (var i = 0; i < text.length; i += 1) {
      h ^= BigInt(text.charCodeAt(i));
      h = (h * p) & mask;
    }
    return ('0000000000000000' + h.toString(16)).slice(-16);
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  // Monotonically increasing version counter prevents empty-state hash collisions.
  // Each operation increments the counter so replaying an already-applied delta fails.
  var _version_counter = 0;

  function create() {
    return { schema_version: SCHEMA_VERSION, entries: [], version: _version_counter };
  }

  function entryKey(entry) {
    return JSON.stringify([entry.player, entry.entity_id]);
  }

  function validateOperation(op) {
    if (!op || typeof op !== 'object' || typeof op.player !== 'string' || !op.player ||
        typeof op.entity_id !== 'string' || !op.entity_id ||
        typeof op.timestamp !== 'number' || !isFinite(op.timestamp) ||
        typeof op.deleted !== 'boolean' || (!op.deleted && (!op.value || typeof op.value !== 'object'))) {
      throw new TypeError('Invalid quest-log operation');
    }
  }

  function compareOperations(a, b) {
    if (a.timestamp !== b.timestamp) return a.timestamp > b.timestamp ? 1 : -1;
    var left = stableStringify(a);
    var right = stableStringify(b);
    return left === right ? 0 : (left > right ? 1 : -1);
  }

  function normalize(state) {
    if (!state || state.schema_version !== SCHEMA_VERSION || !Array.isArray(state.entries)) {
      throw new TypeError('Unsupported quest-log schema');
    }
    var result = create();
    // Preserve the global counter — this ensures replay detection works across normalize calls.
    result.version = _version_counter;
    state.entries.forEach(function (entry) {
      validateOperation(entry);
      var idx = result.entries.findIndex(function (candidate) { return entryKey(candidate) === entryKey(entry); });
      if (idx === -1) result.entries.push(clone(entry));
      else if (compareOperations(entry, result.entries[idx]) > 0) result.entries[idx] = clone(entry);
    });
    result.entries.sort(function (a, b) { return entryKey(a).localeCompare(entryKey(b)); });
    return result;
  }

  function mergeStates(left, right) {
    var merged = normalize(left);
    // Ensure the merged state carries a higher version than either input so replay detection works.
    if (typeof merged.version === 'number') merged.version += 1;
    normalize(right).entries.forEach(function (incoming) {
      var key = entryKey(incoming);
      var idx = merged.entries.findIndex(function (entry) { return entryKey(entry) === key; });
      if (idx === -1) merged.entries.push(clone(incoming));
      else if (compareOperations(incoming, merged.entries[idx]) > 0) merged.entries[idx] = clone(incoming);
    });
    merged.entries.sort(function (a, b) { return entryKey(a).localeCompare(entryKey(b)); });
    return merged;
  }

  function versionHash(state) {
    var normalized = normalize(state);
    // Hash the canonical entries with the same environment-agnostic digest used
    // by entityId (pure BigInt FNV-1a, synchronous, no Node/browser branch): the
    // base_version is a function of state content only, so it is identical in
    // Node and the browser, stable across processes, and changes when any entry
    // changes. Truncated to the first 8 hex chars (4 bytes / u32) for
    // base_version compatibility.
    var ops = normalized.entries.map(function (entry) {
      return stableStringify(entry);
    }).join('|');
    return hash(ops).slice(0, 8);
  }

  function applyDelta(state, delta) {
    var current = normalize(state);
    if (!delta || delta.schema_version !== SCHEMA_VERSION ||
        typeof delta.base_version !== 'string' || !Array.isArray(delta.operations)) {
      return { accepted: false, reason: 'invalid_delta', state: current };
    }
    if (delta.base_version !== versionHash(current)) {
      return { accepted: false, reason: 'base_version_mismatch', state: current };
    }
    try {
      delta.operations.forEach(validateOperation);
    } catch (error) {
      return { accepted: false, reason: 'invalid_delta', state: current };
    }
    // Increment version counter so replaying an already-applied delta fails.
    _version_counter += 1;
    var incoming = { schema_version: SCHEMA_VERSION, entries: delta.operations };
    var merged = mergeStates(current, incoming);
    merged.version = _version_counter;
    return { accepted: true, state: merged };
  }

  function entityId(value) {
    // Keep identity stable when display metadata (category/level) changes.
    var identity = value && typeof value.n === 'string' && Array.isArray(value.ll)
      ? { n: value.n, ll: [value.ll[0], value.ll[1]] }
      : value;
    return 'q-' + hash(stableStringify(identity));
  }

  // Convert the legacy [{n,k,ll,lv}] localStorage array. The default player ID
  // is migration-only; callers should pass their persisted player namespace.
  function migrateLegacy(legacy, player, migratedAt) {
    if (!Array.isArray(legacy)) throw new TypeError('Legacy quest log must be an array');
    if (typeof player !== 'string' || !player) throw new TypeError('Player namespace is required');
    var timestamp = typeof migratedAt === 'number' && isFinite(migratedAt) ? migratedAt : Date.now();
    var state = create();
    legacy.forEach(function (item) {
      if (!item || typeof item.n !== 'string' || !Array.isArray(item.ll) || item.ll.length < 2) return;
      var value = { n: item.n, k: item.k || '', ll: [item.ll[0], item.ll[1]], lv: item.lv || '' };
      state.entries.push({
        player: player,
        entity_id: entityId(value),
        timestamp: timestamp,
        deleted: false,
        value: value
      });
    });
    return normalize(state);
  }

  function list(state, player) {
    return normalize(state).entries.filter(function (entry) {
      return entry.player === player && !entry.deleted;
    }).map(function (entry) { return clone(entry.value); });
  }

  function put(state, player, value, timestamp, id) {
    if (typeof player !== 'string' || !player) throw new TypeError('Player namespace is required');
    var nextValue = clone(value);
    var op = {
      player: player,
      entity_id: id || entityId(nextValue),
      timestamp: typeof timestamp === 'number' && isFinite(timestamp) ? timestamp : Date.now(),
      deleted: false,
      value: nextValue
    };
    return mergeStates(state, { schema_version: SCHEMA_VERSION, entries: [op] });
  }

  function remove(state, player, id, timestamp) {
    return mergeStates(state, { schema_version: SCHEMA_VERSION, entries: [{
      player: player,
      entity_id: id,
      timestamp: typeof timestamp === 'number' && isFinite(timestamp) ? timestamp : Date.now(),
      deleted: true,
      value: null
    }] });
  }

  return {
    SCHEMA_VERSION: SCHEMA_VERSION,
    create: create,
    entityId: entityId,
    versionHash: versionHash,
    mergeStates: mergeStates,
    applyDelta: applyDelta,
    migrateLegacy: migrateLegacy,
    list: list,
    put: put,
    remove: remove
  };
}));
