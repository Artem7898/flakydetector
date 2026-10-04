import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {validateAnalysis, validateSearch, errorText, verdictLabel} from './contract.js';
const load = name => JSON.parse(readFileSync(new URL(name, import.meta.url), 'utf8'));
const example = () => load('./analysis-example.json');

test('does not silently accept a legacy or incomplete contract', () => {
  for (const value of [null, {}, {flaky_tests: []}, {schema_version: '2.0.0', results: []},
    {schema_version: '2.1.0', status: 'partial', results: [{verdict: 'inconclusive', risk_score: null, patterns: []}]}]) {
    assert.throws(() => validateAnalysis(value));
  }
});
for (const name of readdirSync(new URL('./fixtures/', import.meta.url))) {
  test(`accepts actual backend response: ${name}`, () => {
    const value = load(`./fixtures/${name}`);
    assert.equal(validateAnalysis(value), value);
    assert.ok(value.source_snapshots.length);
  });
}
test('accepts actual normal and nullable fields', () => {
  const value = validateAnalysis(example());
  assert.equal(value.results.length, 2);
  assert.equal(value.results[1].verdict, 'no_known_risk');
  assert.equal(value.results[0].model_score, null);
  assert.equal(verdictLabel('inconclusive'), 'Inconclusive');
});
test('every field consumed by the renderer is required or safely nullable', () => {
  const objects = [[], ['results', 0], ['results', 0, 'patterns', 0],
    ['results', 0, 'patterns', 0, 'location'], ['source_snapshots', 0]];
  const ignored = new Set(['location_string']); // Computed display convenience; not consumed.
  for (const path of objects) {
    const baseline = path.reduce((value, key) => value[key], example());
    for (const key of Object.keys(baseline).filter(key => !ignored.has(key))) {
      const changed = example();
      const object = path.reduce((value, key) => value[key], changed);
      delete object[key];
      assert.throws(() => validateAnalysis(changed), `deletion ${path.join('.')}.${key}`);
    }
  }
});
test('numeric scores cannot be strings, objects, undefined, NaN or infinity', () => {
  for (const value of ['0.45', {}, [], undefined, NaN, Infinity, -Infinity, -0.1, 1.01]) {
    const payload = example(); payload.results[0].risk_score = value;
    assert.throws(() => validateAnalysis(payload));
  }
});
test('rejects arrays/objects that would crash map, join, toFixed or location access', () => {
  const mutations = [
    p => { p.diagnostics = null; },
    p => { p.results[0].patterns[0].confidence = '0.9'; },
    p => { p.results[0].patterns[0].location = null; },
    p => { p.results[0].log_anomalies = {}; },
    p => { p.results[0].recommendations = [42]; },
    p => { p.source_snapshots[0].content = {}; },
    p => { p.results[0].patterns[0].location.line_start = 0; },
    p => { p.results[0].patterns[0].location.line_end = 0; },
  ];
  for (const mutate of mutations) { const p = example(); mutate(p); assert.throws(() => validateAnalysis(p)); }
});
test('rejects corrupted units rather than drawing misleading metrics', () => {
  for (const field of ['files_parsed', 'test_candidates', 'evidence_links', 'diagnostic_groups']) {
    const payload = example(); payload[field] += 1; assert.throws(() => validateAnalysis(payload));
  }
});
test('structured errors keep file and line coordinates', () => {
  assert.equal(errorText({response: {data: {detail: {diagnostics: [{file_path: 'test_bad.py', line: 3, code: 'syntax_error', message: 'invalid'}]}}}}), 'test_bad.py:3: syntax_error: invalid');
  assert.equal(errorText({message: 'offline'}), 'offline');
});
test('search has its own complete runtime contract', () => {
  const value = {results: [{identity: 'i', repo: 'r', nodeid: 'n', explanation: 'x', fix_strategy: 'inspect', metric: 'cosine', distance: 0.4, evidence_ids: ['source']}]};
  assert.equal(validateSearch(value).length, 1);
  value.results[0].distance = '0.4'; assert.throws(() => validateSearch(value));
  assert.throws(() => validateSearch({results: [{}]}));
});
