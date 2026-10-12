import {useEffect, useRef, useState} from 'react';
import {runtimeGet, runtimePost} from './api.js';
import {eventFileError} from './uploads.js';
import {validateMonitors, validateMetrics, validateQuarantine, displayMetric, matchedStaticFindings} from './product-contract.js';

export default function Observed({workspace, token, staticAnalysis = null}) {
  const [repo, setRepo] = useState('');
  const [data, setData] = useState(null); const [stats, setStats] = useState(null);
  const [error, setError] = useState(null); const [pending, setPending] = useState(false);
  const [selected, setSelected] = useState(null); const [quarantine, setQuarantine] = useState([]);
  const [owner, setOwner] = useState(''); const [issue, setIssue] = useState(''); const [reason, setReason] = useState('');
  const controller = useRef(null); const generation = useRef(0);
  useEffect(() => {
    generation.current++; controller.current?.abort(); setData(null); setStats(null); setSelected(null);
    setQuarantine([]); setError(null); setPending(false); setOwner(''); setIssue(''); setReason('');
  }, [repo, workspace, token]);
  useEffect(() => () => controller.current?.abort(), []);
  function begin() {
    controller.current?.abort(); const abort = new AbortController(); controller.current = abort;
    const id = ++generation.current; setPending(true); setError(null);
    return {abort, id};
  }
  const current = op => generation.current === op.id && !op.abort.signal.aborted;
  async function load() {
    const op = begin();
    try {
      const [response, entries, metrics] = await Promise.all([
        runtimeGet('/monitors', repo, workspace, token, op.abort.signal),
        runtimeGet('/quarantine', repo, workspace, token, op.abort.signal),
        runtimeGet(`/stats/${encodeURIComponent(repo)}`, repo, workspace, token, op.abort.signal),
      ]);
      const checked = validateMonitors(response.data); const qs = validateQuarantine(entries.data);
      const ms = validateMetrics(metrics.data);
      if (!current(op)) return;
      setData(checked); setQuarantine(qs); setStats(ms); setSelected(null);
    } catch { if (current(op)) setError('Execution history is unavailable or invalid. Verify repo, workspace and events:read permission. No zero flake rate is inferred.'); }
    finally { if (current(op)) setPending(false); }
  }
  async function upload(event) {
    const input = event.currentTarget;
    const file = input.files?.[0]; if (!file) return;
    const validationError = eventFileError(file);
    if (validationError) { setError(validationError); input.value = ''; return; }
    const op = begin();
    try {
      const text = await file.text(); if (!current(op)) return;
      const events = text.split('\n').filter(line => line.trim()).map(line => JSON.parse(line));
      await runtimePost('/events', {events}, workspace, token, op.abort.signal);
      if (current(op)) await load();
    } catch { if (current(op)) setError('Event upload rejected. Verify workspace, schema, batch size (2,000 events) and events:write permission.'); }
    finally { if (current(op)) setPending(false); input.value = ''; }
  }
  const chosenAttempt = data?.attempts.find(a => selected?.evidence_ids.some(id => a.event_ids.includes(id)));
  const eligible = selected?.status === 'detected' && selected.nodeid !== '<session>' && chosenAttempt?.complete
    && selected.monitor !== 'static_risk_only';
  async function quarantineSelected() {
    if (!eligible || !owner.trim() || !issue.trim() || reason.trim().length < 10) { setError('Select observed test evidence and provide owner, issue and a reason (10+ characters).'); return; }
    if (!window.confirm('Create a 7-day quarantine? Tests must continue running; evidence and outcomes are not changed.')) return;
    const op = begin();
    try {
      await runtimePost('/quarantine', {repo, nodeid: chosenAttempt.nodeid, source_hash: chosenAttempt.provenance.source_hash, owner, issue, reason, ttl_days: 7}, workspace, token, op.abort.signal);
      if (current(op)) await load();
    } catch { if (current(op)) setError('Quarantine requires quarantine:write and a valid exact selector.'); }
    finally { if (current(op)) setPending(false); }
  }
  async function updateQuarantine(q, action) {
    const note = window.prompt(`${action === 'renew' ? 'Renew for 7 days' : 'Revoke'} quarantine. Enter a review reason (10+ characters):`);
    if (!note || note.trim().length < 10) return;
    const op = begin();
    try {
      await runtimePost(`/quarantine/${encodeURIComponent(q.id)}/${action}`, {expected_version: q.version, reason: note, ttl_days: 7}, workspace, token, op.abort.signal);
      if (current(op)) await load();
    } catch { if (current(op)) setError('Update rejected. Refresh version, permission and expiry. No evidence was changed.'); }
    finally { if (current(op)) setPending(false); }
  }
  const timeline = data?.attempts.filter(a => !selected || selected.evidence_ids.some(id => a.event_ids.includes(id))) ?? [];
  const matched = matchedStaticFindings(staticAnalysis, chosenAttempt);
  const metrics = stats?.metrics;
  return <section className="card observed-panel">
    <p className="eyebrow">RECORDED EXECUTIONS · SEPARATE FROM STATIC RISK</p><h2>Observed behavior</h2>
    <p className="muted">Monitors compare declared provenance. Matching a static rule never establishes root cause. Independent runs and retry attempts remain distinct.</p>
    <div className="search-row"><label>Repository identity<input aria-label="Runtime repository" value={repo} onChange={e => setRepo(e.target.value)} placeholder="owner/repository"/></label><button className="secondary" disabled={!repo.trim() || pending} onClick={load}>{pending ? 'Loading…' : 'Load history'}</button></div>
    <label>Import execution history — recorder events (.jsonl only)<input aria-label="Execution events" aria-describedby="event-upload-help" type="file" disabled={pending} onChange={upload}/></label>
    <p id="event-upload-help" className="field-help">This is not the Python source checker. Use File / ZIP above to analyze test code. All files are visible here, but only recorder .jsonl files are accepted (5 MB; at most 2,000 events per batch; events:write permission).</p>
    {error && <p role="alert" className="notice warning">{error}</p>}
    {!data && <p className="notice">No execution history loaded. Runtime reliability is unavailable, not 100%.</p>}
    {data && <>
      <p>{data.attempts.length} recorded attempts · {data.observations.filter(o => o.status === 'detected').length} detected monitor observations</p>
      <div className="monitor-list">{data.observations.map(o => <button className={`monitor-row ${o.status}`} key={o.observation_id} onClick={() => setSelected(o)}><strong>{o.monitor}</strong><span>{o.status} · {o.verdict}</span><small>{o.nodeid}</small></button>)}</div>
      {selected && <article className="finding"><h3>{selected.verdict} · {selected.confidence} confidence</h3><p>{selected.nodeid}</p>
        <h4>What was observed</h4>{selected.facts.map((fact, i) => <p key={i}>{fact}</p>)}
        <h4>Not established</h4>{selected.limitations.map((fact, i) => <p key={i}>{fact}</p>)}
        <p>{selected.evidence_ids.length} event references · monitor version {selected.monitor_version}</p>
        <details><summary>Evidence identifiers</summary><pre>{selected.evidence_ids.join('\n')}</pre></details>
        <h4>Content-matched static evidence</h4>{matched.length ? matched.map(f => <p key={f.finding_id}>{f.rule_id} · {f.title}</p>) : <p>No matching source-file digest from the current static analysis.</p>}
        <p className="notice">Content matching is not authenticated repository identity. Neither a matched rule nor an uploaded event proves root cause or causal effect.</p>
      </article>}
      <details open={!!selected}><summary>Attempts and comparison boundaries</summary><div className="timeline">{timeline.map(a => <article key={`${a.run_id}:${a.invocation_id}:${a.attempt}`} className="attempt"><strong>{a.outcome} · attempt {a.attempt}</strong><span>{a.started_at} · {displayMetric(a.duration)} seconds</span><small>{a.nodeid} · worker {a.worker}</small>
        <p>Context: {a.comparison_status} · {a.complete ? 'terminal attempt' : 'incomplete attempt'}</p>{a.comparability_reasons.map((r, i) => <p key={i}>{r}</p>)}
        <details><summary>Run, invocation and recorded context</summary><pre>{JSON.stringify({run_id: a.run_id, invocation_id: a.invocation_id, revision: a.provenance.revision, dirty: a.provenance.dirty, components: a.provenance.components, event_ids: a.event_ids}, null, 2)}</pre></details></article>)}</div></details>
      {eligible && <details><summary>Governed quarantine</summary><p>Exact node ID and source hash · 7-day TTL · explicit approval. Tests continue to run.</p>
        <label>Owner<input value={owner} onChange={e => setOwner(e.target.value)}/></label><label>Issue<input value={issue} onChange={e => setIssue(e.target.value)}/></label><label>Reason<textarea value={reason} onChange={e => setReason(e.target.value)}/></label><button className="secondary" disabled={pending} onClick={quarantineSelected}>Create quarantine…</button></details>}
      <h3>Quarantine ownership</h3>{quarantine.length ? quarantine.map(q => <article className="notice" key={q.id}><strong>{q.nodeid}</strong><p>Owner {q.owner} · expires {q.expires_at} · {q.revoked_at ? 'REVOKED' : Date.parse(q.expires_at) <= Date.now() ? 'EXPIRED' : 'time-limited'} · version {q.version}</p><p>{q.issue} · {q.reason}</p>
        <button className="secondary" disabled={pending} onClick={() => updateQuarantine(q, 'renew')}>Review and renew…</button>{!q.revoked_at && <button className="secondary" disabled={pending} onClick={() => updateQuarantine(q, 'revoke')}>Revoke…</button>}</article>) : <p>No recorded quarantine entries.</p>}
      {metrics && <section className="runtime-metrics"><h3>Reliability measurements</h3><p>{metrics.population}</p>
        <dl>{[['First-attempt failure rate', metrics.first_attempt_failure_rate, true], ['Final failure rate after retries', metrics.final_failure_rate, true], ['Pass-on-retry invocations', metrics.pass_on_retry_count, false], ['Intermittent outcome rate', metrics.intermittent_outcome_rate, true], ['Independently reviewed static precision', metrics.static_finding_precision, true], ['Median time to triage (seconds)', metrics.median_time_to_triage_seconds, false], ['Median time to fix (seconds)', metrics.median_time_to_fix_seconds, false], ['Unresolved findings', metrics.unresolved_count, false], ['Expired quarantine', metrics.expired_quarantine_count, false]].map(([name, value, percent]) => <div key={name}><dt>{name}</dt><dd>{displayMetric(value, percent)}</dd></div>)}</dl>
        <p>{metrics.terminal_invocations} eligible terminal invocations · {metrics.ignored_or_incomplete} ignored/incomplete · {metrics.runs} recorded runs.</p>
        <details><summary>Daily trend (UTC)</summary>{metrics.daily.length ? <table><thead><tr><th>Date</th><th>Invocations</th><th>Failures</th><th>Rate</th></tr></thead><tbody>{metrics.daily.map(d => <tr key={d.date}><td>{d.date}</td><td>{d.invocations}</td><td>{d.failures}</td><td>{displayMetric(d.failure_rate, true)}</td></tr>)}</tbody></table> : <p>No observations.</p>}</details>
        {stats.change_points.map((signal, i) => <p key={i} className="notice warning">Exploratory change: {signal.nodeid}, {displayMetric(signal.before_rate, true)} → {displayMetric(signal.after_rate, true)}. {signal.limitation}</p>)}
        {metrics.limitations.map((l, i) => <p key={i} className="muted">{l}</p>)}
      </section>}
    </>}
  </section>;
}
