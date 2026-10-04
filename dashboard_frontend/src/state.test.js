import test from 'node:test';
import assert from 'node:assert/strict';
import {analysisIsStale, captureSnapshot, initialState, reducer, searchIsStale} from './state.js';
const start = (state, id) => reducer(state, {type: 'analysisStart', id, snapshot: captureSnapshot(state)});
const success = (state, id, payload = {analysis_id: id}) => reducer(state, {type: 'analysisSuccess', id, payload});

test('analysis response stays linked to submitted code even when editing in flight', () => {
  let state = start({...initialState}, 1);
  state = reducer(state, {type: 'edit', field: 'code', value: 'def test_new(): pass'});
  state = success(state, 1);
  assert.equal(state.result.snapshot.code, initialState.code);
  assert.equal(analysisIsStale(state), true);
});
for (const [field, value] of [['code', 'changed'], ['useMl', true], ['mode', 'file'], ['file', {name: 'new.py'}], ['token', 'not-persisted']]) {
  test(`editing ${field} marks completed results outdated`, () => {
    let state = success(start({...initialState}, 1), 1);
    state = reducer(state, {type: 'edit', field, value});
    assert.equal(analysisIsStale(state), true);
    assert.equal('token' in state.result.snapshot, false);
  });
}
test('out-of-order responses and failures cannot replace a newer request', () => {
  let state = start({...initialState}, 1);
  state = start(state, 2);
  const pending = state;
  state = success(state, 1);
  assert.equal(state, pending);
  state = reducer(state, {type: 'analysisFailure', id: 1, error: 'old'});
  assert.equal(state, pending);
  state = success(state, 2);
  assert.equal(state.result.payload.analysis_id, 2);
  const complete = state;
  assert.equal(success(state, 1), complete);
});
test('cancelled requests cannot publish a late result', () => {
  let state = start({...initialState}, 1);
  state = reducer(state, {type: 'analysisCancel'});
  assert.equal(success(state, 1), state);
  assert.equal(state.result, null);
});
test('clear upload restores paste-code mode without discarding the draft', () => {
  const state = reducer({...initialState, mode: 'file', file: {name: 'tests.zip'}}, {type: 'clearFile'});
  assert.equal(state.mode, 'code'); assert.equal(state.file, null);
  assert.equal(state.code, initialState.code);
});
test('a reanalysis of the edited snapshot removes staleness', () => {
  let state = success(start({...initialState}, 1), 1);
  state = reducer(state, {type: 'edit', field: 'code', value: 'different'});
  state = success(start(state, 2), 2);
  assert.equal(analysisIsStale(state), false);
  assert.equal(state.result.snapshot.code, 'different');
});
test('search results preserve the captured query and explicitly become stale', () => {
  let state = reducer({...initialState}, {type: 'query', value: 'first'});
  state = reducer(state, {type: 'searchStart', id: 1});
  state = reducer(state, {type: 'query', value: 'second'});
  state = reducer(state, {type: 'searchSuccess', id: 1, items: []});
  assert.equal(state.hits.query, 'first'); assert.equal(searchIsStale(state), true);
});
test('late search cannot overwrite the latest search', () => {
  let state = reducer({...initialState}, {type: 'searchStart', id: 1});
  state = reducer(state, {type: 'searchStart', id: 2});
  assert.equal(reducer(state, {type: 'searchSuccess', id: 1, items: []}), state);
  state = reducer(state, {type: 'searchSuccess', id: 2, items: []});
  assert.equal(searchIsStale(state), false);
});
test('captured snapshot is immutable and never contains auth credentials', () => {
  const snapshot = captureSnapshot({...initialState, token: 'never-export'});
  assert.ok(Object.isFrozen(snapshot));
  assert.ok(!JSON.stringify(snapshot).includes('never-export'));
});
