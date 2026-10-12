import test from 'node:test';
import assert from 'node:assert/strict';
import {validateMonitors, validateMetrics, validateQuarantine, matchedStaticFindings,
  displayMetric, sourceExpired, sourceFreeReport} from './product-contract.js';

const stamp = '2026-10-11T12:00:00Z';
const attempt = () => ({workspace:'local', repo:'a/b', nodeid:'test_x.py::test_x[usd]', run_id:'r', invocation_id:'i',
  worker:'main', attempt:1, started_at:stamp, ended_at:stamp, duration:0, complete:true, outcome:'passed',
  event_ids:['e'], source_file_hash:'a'.repeat(64), comparison_status:'unknown', comparability_reasons:['seed unknown'],
  provenance:{source_hash:'b'.repeat(64), environment_hash:'c'.repeat(64), revision:'d'.repeat(40),
    experiment_id:'', treatment_axis:'none', treatment_value:'', components:{python:'3.12'}, dirty:null, recorded_context_complete:false}});
const monitor = () => ({schema_version:'1', observations:[{observation_id:'o', monitor:'pass_on_retry', monitor_version:'1',
  nodeid:'test_x.py::test_x[usd]', verdict:'insufficient_evidence', confidence:'none', status:'insufficient_evidence',
  facts:[], limitations:['Root cause is not established'], evidence_ids:['e'], metrics:{passed:null}}], attempts:[attempt()]});

test('unknown history is renderable without fabricating a pass', () => {
  assert.equal(validateMonitors(monitor()).attempts[0].comparison_status, 'unknown');
});
for (const [name, change] of [
  ['missing facts', p => delete p.observations[0].facts],
  ['infinite metric', p => p.observations[0].metrics.passed = Infinity],
  ['string duration', p => p.attempts[0].duration = '1'],
  ['bad provenance', p => p.attempts[0].provenance.components.python = {}],
  ['missing reasons', p => delete p.attempts[0].comparability_reasons],
  ['bad date', p => p.attempts[0].ended_at = 'yesterday'],
  ['missing scope', p => delete p.attempts[0].workspace],
]) test(`reject ${name}`, () => {const p = monitor(); change(p); assert.throws(() => validateMonitors(p));});

test('content matching requires workspace and exact source digest', () => {
  const a = attempt(); const analysis = {workspace:'local', source_digests:{'test_x.py':a.source_file_hash},
    findings:[{rule_id:'FD-NET-001',test_nodeids:['test_x.py::test_x']}]};
  assert.equal(matchedStaticFindings(analysis,a).length,1);
  assert.deepEqual(matchedStaticFindings({...analysis,workspace:'other'},a),[]);
  assert.deepEqual(matchedStaticFindings({...analysis,source_digests:{}},a),[]);
  assert.deepEqual(matchedStaticFindings(analysis,{...a,source_file_hash:null}),[]);
});

test('source expiry purges granting capability and code without altering original', () => {
  const payload = {source_expires_at:stamp,source_grant:'private-grant',source_snapshots:[{content:'secret'}],results:[{
    patterns:[{code_snippet:'secret',metadata:{source:'secret'}}],log_anomalies:[{log_entries:['secret'],metadata:{}}]}]};
  const safe = sourceFreeReport(payload);
  assert.equal(safe.source_grant,null); assert.deepEqual(safe.source_snapshots,[]);
  assert.equal(safe.results[0].patterns[0].code_snippet,''); assert.equal(payload.source_grant,'private-grant');
  assert.equal(sourceExpired(payload,Date.parse(stamp)),true);
  assert.equal(sourceExpired(payload,Date.parse(stamp)-1),false);
});

test('missing measurements remain unavailable', () => {
  assert.equal(displayMetric(null),'Unavailable'); assert.equal(displayMetric(NaN),'Unavailable');
  assert.equal(displayMetric(0,true),'0.0%'); assert.equal(displayMetric(0.25,true),'25.0%');
  assert.throws(() => validateMetrics({metrics:{schema_version:'1'},change_points:[]}));
});

test('quarantine entries require ownership, expiry and version', () => {
  const entry = {id:'q',workspace:'local',repo:'a/b',nodeid:'test_x.py::test_x',source_hash:'a'.repeat(64),owner:'artem',
    issue:'https://example.invalid/1',reason:'Investigating',approved_by:'reviewer',created_at:stamp,expires_at:stamp,revoked_at:null,version:1};
  assert.deepEqual(validateQuarantine({entries:[entry]}),[entry]);
  assert.throws(() => validateQuarantine({entries:[{...entry,owner:null}]}));
  assert.throws(() => validateQuarantine({entries:[{...entry,version:'1'}]}));
});
