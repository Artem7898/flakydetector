/** Runtime payloads are validated before a component may render their nested fields. */
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const strings = x => Array.isArray(x) && x.every(v => typeof v === 'string');
const text = x => typeof x === 'string';
const finite = x => typeof x === 'number' && Number.isFinite(x);
const timestamp = x => text(x) && Number.isFinite(Date.parse(x));
const stringMap = x => object(x) && Object.values(x).every(text);
const nullableNumber = x => x === null || finite(x);
const outcomes = ['passed', 'failed', 'error', 'skipped', 'xfailed', 'xpassed', 'unknown', 'incomplete', 'rerun'];
export function validateMonitors(payload) {
  if (!object(payload) || payload.schema_version !== '1' || !Array.isArray(payload.observations) || !Array.isArray(payload.attempts)) throw new Error('Invalid monitor response');
  for (const o of payload.observations) {
    if (!object(o) || !['observation_id', 'monitor', 'monitor_version', 'nodeid', 'verdict'].every(k => text(o[k]))
      || !['high', 'medium', 'low', 'none'].includes(o.confidence)
      || !['detected', 'not_detected', 'insufficient_evidence'].includes(o.status)
      || !strings(o.evidence_ids) || !strings(o.facts) || !strings(o.limitations) || !object(o.metrics)
      || !Object.values(o.metrics).every(nullableNumber)) throw new Error('Invalid monitor observation');
  }
  for (const a of payload.attempts) {
    if (!object(a) || !['workspace', 'repo', 'nodeid', 'run_id', 'invocation_id', 'worker'].every(k => text(a[k]))
      || !timestamp(a.started_at) || !timestamp(a.ended_at) || !outcomes.includes(a.outcome)
      || !Number.isSafeInteger(a.attempt) || a.attempt < 1 || !finite(a.duration) || a.duration < 0
      || typeof a.complete !== 'boolean' || !strings(a.event_ids) || !object(a.provenance)
      || !['source_hash', 'environment_hash', 'revision', 'experiment_id', 'treatment_axis', 'treatment_value'].every(k => text(a.provenance[k]))
      || !stringMap(a.provenance.components) || ![true, false, null].includes(a.provenance.dirty)
      || typeof a.provenance.recorded_context_complete !== 'boolean'
      || !['compatible', 'incompatible', 'unknown'].includes(a.comparison_status) || !strings(a.comparability_reasons)
      || !(a.source_file_hash === null || /^[a-f0-9]{64}$/.test(a.source_file_hash))) throw new Error('Invalid runtime attempt');
  }
  return payload;
}
export function validateQuarantine(payload) {
  if (!object(payload) || !Array.isArray(payload.entries)) throw new Error('Invalid quarantine response');
  for (const q of payload.entries) {
    if (!object(q) || !['id', 'repo', 'workspace', 'nodeid', 'source_hash', 'owner', 'issue', 'reason', 'approved_by'].every(k => text(q[k]))
      || !timestamp(q.created_at) || !timestamp(q.expires_at) || !(q.revoked_at === null || timestamp(q.revoked_at))
      || !Number.isSafeInteger(q.version) || q.version < 1) throw new Error('Invalid quarantine entry');
  }
  return payload.entries;
}
export function validateMetrics(payload) {
  if (!object(payload) || !object(payload.metrics) || payload.metrics.schema_version !== '1' || !Array.isArray(payload.change_points)) throw new Error('Invalid metrics response');
  const m = payload.metrics;
  for (const key of ['attempts', 'runs', 'invocations', 'terminal_invocations', 'ignored_or_incomplete', 'first_attempt_failure_rate', 'final_failure_rate', 'pass_on_retry_count', 'intermittent_outcome_rate', 'quarantine_count', 'expired_quarantine_count', 'quarantine_oldest_age_seconds', 'median_time_to_triage_seconds', 'median_time_to_fix_seconds', 'unresolved_count', 'oldest_unresolved_age_seconds', 'static_finding_precision', 'independently_reviewed_findings']) {
    if (!nullableNumber(m[key])) throw new Error(`Invalid metric: ${key}`);
  }
  if (!text(m.population) || !strings(m.limitations) || !Array.isArray(m.daily)
    || m.daily.some(d => !object(d) || !text(d.date) || !finite(d.invocations) || !finite(d.failures) || !finite(d.failure_rate))) throw new Error('Invalid metric population');
  if (payload.change_points.some(c => !object(c) || !text(c.nodeid) || !text(c.limitation) || !finite(c.before_rate) || !finite(c.after_rate) || !strings(c.evidence_ids))) throw new Error('Invalid change signal');
  return payload;
}
export function sourceFreeReport(payload) {
  return {...payload, source_grant: null, source_snapshots: [], source_access: 'disabled', source_expires_at: null,
    results: payload.results.map(r => ({...r, patterns: r.patterns.map(p => ({...p, code_snippet: '', metadata: {}})),
      log_anomalies: r.log_anomalies.map(a => ({...a, log_entries: [], metadata: {}}))}))};
}
export function sourceExpired(payload, now = Date.now()) {
  return !payload.source_expires_at || !Number.isFinite(Date.parse(payload.source_expires_at)) || Date.parse(payload.source_expires_at) <= now;
}
export function displayMetric(value, percentage = false) {
  if (value === null || value === undefined || !finite(value)) return 'Unavailable';
  return percentage ? `${(value * 100).toFixed(1)}%` : value.toLocaleString();
}
export function matchedStaticFindings(analysis, attempt) {
  if (!analysis || !attempt?.source_file_hash || analysis.workspace !== attempt.workspace) return [];
  const [path] = attempt.nodeid.split('::');
  if (analysis.source_digests?.[path] !== attempt.source_file_hash) return [];
  // This is content matching, not authenticated repository identity or causal attribution.
  const definition = attempt.nodeid.replace(/\[[\s\S]*$/, '');
  return analysis.findings.filter(f => f.test_nodeids.some(node => node === definition));
}
