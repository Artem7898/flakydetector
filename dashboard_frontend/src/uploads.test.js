import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {inspectSourceSelection, inspectSourceDrop, sourceUploadEndpoint,
  sourceFileError, eventFileError, SOURCE_FILE_LIMIT, SOURCE_ZIP_LIMIT} from './uploads.js';
import {initialState, reducer, captureSnapshot, analysisIsStale} from './state.js';

const file = (name, size = 16, type = '') => ({name, size, type});
for (const name of ['test_sample.py', 'TEST_SAMPLE.PY', 'tests.zip', 'TESTS.ZIP', 'проверка оплаты.py', 'тесты.ZiP']) {
  test(`source selection accepts ${name} without a MIME mapping`, () => {
    const selected = file(name);
    assert.deepEqual(inspectSourceSelection([selected]), {kind:'selected', file:selected});
    assert.equal(sourceUploadEndpoint(selected), /\.zip$/i.test(name) ? '/analyze/directory' : '/analyze/file');
  });
}
for (const type of ['', 'text/plain', 'text/x-python', 'application/octet-stream', 'application/x-zip-compressed']) {
  test(`source selection does not trust MIME value ${JSON.stringify(type)}`, () => {
    assert.equal(sourceFileError(file('test_upload.py', 16, type)), null);
    assert.equal(sourceFileError(file('tests.zip', 16, type)), null);
  });
}
for (const name of ['test.py.txt', 'test.exe', 'events.jsonl', '.env', 'test', 'report.pdf']) {
  test(`unsupported ${name} produces an explicit error, not a hidden entry`, () => {
    assert.equal(inspectSourceSelection([file(name)]).kind, 'invalid');
    assert.throws(() => sourceUploadEndpoint(file(name)), /Choose a Python/);
  });
}
test('cancel and an empty picker preserve the previous selection', () => {
  assert.deepEqual(inspectSourceSelection([]), {kind:'cancelled'});
  assert.deepEqual(inspectSourceSelection(null), {kind:'cancelled'});
});
test('multiple files are not silently truncated to the first', () => {
  assert.match(inspectSourceSelection([file('one.py'), file('two.py')]).error, /one .py/);
});
test('enforce source byte limits after selection, allowing the exact bound', () => {
  assert.equal(sourceFileError(file('test.py', SOURCE_FILE_LIMIT)), null);
  assert.match(sourceFileError(file('test.py', SOURCE_FILE_LIMIT + 1)), /1 MB/);
  assert.equal(sourceFileError(file('tests.zip', SOURCE_ZIP_LIMIT)), null);
  assert.match(sourceFileError(file('tests.zip', SOURCE_ZIP_LIMIT + 1)), /10 MB/);
  assert.ok(sourceFileError(file('test.py', NaN)));
});
test('a regular drop follows exactly the same validation path', () => {
  const selected = file('tests.zip');
  assert.deepEqual(inspectSourceDrop({files:[selected],items:[]}), {kind:'selected', file:selected});
});
test('a dropped folder requests ZIP, not a directory-only browser dialog', () => {
  const dropped = inspectSourceDrop({files:[],items:[{webkitGetAsEntry:() => ({isDirectory:true})}]});
  assert.equal(dropped.kind, 'invalid'); assert.match(dropped.error, /Create a ZIP/);
  assert.equal(inspectSourceDrop({files:[],items:[]}).kind, 'invalid');
});
test('runtime JSONL and static source selection are distinct', () => {
  assert.equal(eventFileError(file('recording.jsonl')), null);
  assert.equal(eventFileError(file('RECORDING.JSONL')), null);
  assert.match(eventFileError(file('test.py')), /File \/ ZIP/);
  assert.match(eventFileError(file('tests.zip')), /not Python source/);
  assert.match(eventFileError(file('recording.jsonl', 5_000_001)), /5 MB/);
});
test('rejecting a new upload clears old file and pending response but keeps code draft', () => {
  const previous = {...initialState, mode:'file', file:file('old.py'), code:'saved draft'};
  const started = reducer(previous, {type:'analysisStart', id:10, snapshot:captureSnapshot(previous)});
  const rejected = reducer(started, {type:'fileRejected', error:'Unsupported upload'});
  assert.equal(rejected.file, null); assert.equal(rejected.pending, null);
  assert.equal(rejected.code, 'saved draft'); assert.equal(rejected.error, 'Unsupported upload');
  assert.equal(reducer(rejected, {type:'analysisSuccess', id:10, payload:{}}), rejected);
});
test('rejecting a replacement marks an existing result stale, and valid re-selection clears error', () => {
  let state = {...initialState, mode:'file', file:file('old.py')};
  state = reducer(state, {type:'analysisStart', id:1, snapshot:captureSnapshot(state)});
  state = reducer(state, {type:'analysisSuccess', id:1, payload:{analysis_id:'old'}});
  state = reducer(state, {type:'fileRejected', error:'Unsupported upload'});
  assert.equal(analysisIsStale(state), true);
  state = reducer(state, {type:'edit', field:'file', value:file('new.py')});
  assert.equal(state.error, null); assert.equal(state.file.name, 'new.py');
});
test('both actual picker declarations omit native filters and directory-only mode', async () => {
  for (const name of ['App.jsx', 'Observed.jsx']) {
    const code = await readFile(new URL(`./${name}`, import.meta.url), 'utf8');
    const inputs = [...code.matchAll(/<input\b[\s\S]*?\/>/g)].map(match => match[0]).filter(tag => /type="file"/.test(tag));
    assert.equal(inputs.length, 1, name);
    assert.doesNotMatch(inputs[0], /\baccept\s*=|\bwebkitdirectory\s*=|\bdirectory\s*=/i, name);
  }
});
test('display version comes from frontend metadata, not a hardcoded RC badge', async () => {
  const app = await readFile(new URL('./App.jsx', import.meta.url), 'utf8');
  const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  const lock = JSON.parse(await readFile(new URL('../package-lock.json', import.meta.url), 'utf8'));
  assert.equal(pkg.version, '0.2.2');
  assert.equal(lock.version, pkg.version); assert.equal(lock.packages[''].version, pkg.version);
  assert.match(app, /import packageInfo from '\.\.\/package\.json'/);
  assert.match(app, /<small>\{packageInfo.version\}<\/small>/);
  assert.doesNotMatch(app, /0\.3\.0\s*RC1/i);
});
