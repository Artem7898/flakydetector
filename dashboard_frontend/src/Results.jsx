import {Component, useState} from 'react';
import {diagnosticText, verdictLabel} from './contract.js';

export class ResultBoundary extends Component {
  state = {failed: false};
  static getDerivedStateFromError() { return {failed: true}; }
  render() {
    return this.state.failed
      ? <section className="notice danger" role="alert">This result could not be rendered. Run a new analysis; no successful verdict is assumed.</section>
      : this.props.children;
  }
}

function SourceEvidence({pattern, snapshots}) {
  const {location} = pattern;
  const source = snapshots.find(item => item.file_path === location.file_path);
  return <details className="source-evidence">
    <summary>Open captured source · {location.file_path}:{location.line_start}</summary>
    {source ? <>
      <p className="muted hash">SHA-256 {source.sha256} · captured by this analysis, not the current editor</p>
      <pre className="source-code" tabIndex={0}>{source.content.split('\n').map((line, index) =>
        <span className={index + 1 >= location.line_start && index + 1 <= (location.line_end ?? location.line_start) ? 'source-line highlighted' : 'source-line'} key={index}>
          <span className="line-number" aria-hidden="true">{index + 1}</span>{line || ' '}{'\n'}
        </span>)}</pre>
    </> : <p className="muted">The full source snapshot is unavailable. The available excerpt is shown below.</p>}
  </details>;
}

function exportReport(payload) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'}));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `flakydetector-${payload.analysis_id}.json`;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Results({payload, snapshot, stale}) {
  const [filter, setFilter] = useState('');
  const [onlyRisk, setOnlyRisk] = useState(false);
  const visible = payload.results.filter(test =>
    `${test.file_path}::${test.test_name}`.toLowerCase().includes(filter.toLowerCase())
    && (!onlyRisk || test.verdict === 'risk_detected'));
  const unique = new Map();
  for (const test of payload.results) for (const pattern of test.patterns) {
    if (pattern.confidence >= 0.5) unique.set(`${pattern.location.file_path}:${pattern.location.line_start}:${pattern.pattern_type}`, pattern);
  }
  const severities = ['critical', 'high', 'medium', 'low'].map(name =>
    ({name, count: [...unique.values()].filter(pattern => pattern.severity === name).length}));
  const maximum = Math.max(1, ...severities.map(item => item.count));
  return <section className="results-section" aria-live="polite">
    <div className="section-heading">
      <div><p className="eyebrow">CAPTURED ANALYSIS · {payload.schema_version}</p><h2>Evidence, not a guess</h2></div>
      <span className={`status status-${payload.status}`}>{payload.status}</span>
    </div>
    {stale && <div className="notice warning" role="status" data-testid="stale-analysis">
      <strong>Outdated result.</strong> The input or settings have changed. Findings below belong to the captured snapshot. Run analysis again to evaluate the current input.
    </div>}
    <div className="metrics-grid">
      <article className="metric"><span>Target files</span><strong>{payload.files_selected}</strong><small>{payload.files_parsed} parsed · {payload.files_rejected} rejected</small></article>
      <article className="metric"><span>Test candidates</span><strong>{payload.test_candidates}</strong><small>Static discovery · pytest collection not run</small></article>
      <article className="metric"><span>Unique risk locations</span><strong>{payload.unique_risk_locations}</strong><small>Source file + line + rule</small></article>
      <article className="metric"><span>Affected candidates</span><strong>{payload.tests_with_risk}</strong><small>Not an observed flake rate</small></article>
    </div>
    <article className="card summary-card">
      <p>Input: <strong>{snapshot.fileName ?? 'source'}</strong> · ML requested: {snapshot.useMl ? 'yes' : 'no'} · {payload.context_files_selected} context files · {payload.evidence_links} evidence links · {payload.diagnostic_groups} diagnostic groups</p>
      <p className="muted">Finding no known risks does not prove stability. Static risk, detector confidence and raw model scores are not calibrated failure probabilities. Execution history is not connected to this scan.</p>
      <div className="severity-bars" aria-label="Unique static risk locations by severity">{severities.map(item =>
        <div key={item.name} className={`severity-row severity-${item.name}`}><span>{item.name}</span><div className="bar-track"><span style={{width: `${item.count / maximum * 100}%`}}/></div><strong>{item.count}</strong></div>
      )}</div>
      {payload.degraded_reason && <p className="notice warning" role="alert">Degraded mode: {payload.degraded_reason}</p>}
      {payload.diagnostics.length > 0 && <div className="diagnostics"><h3>Analysis coverage and limitations</h3>{payload.diagnostics.map((item, index) => <p key={index}>{diagnosticText(item)}</p>)}</div>}
      <details><summary>Identity and export</summary><p className="hash">Analysis ID: {payload.analysis_id}<br/>Request fingerprint: {payload.request_fingerprint}</p><p className="muted">The JSON report includes captured source code. Review it before sharing.</p><button className="secondary" onClick={() => exportReport(payload)}>Export this report</button></details>
    </article>
    <div className="filter-bar">
      <label>Find a test or file<input aria-label="Filter results" value={filter} onChange={event => setFilter(event.target.value)} placeholder="test_api.py or TestCheckout"/></label>
      <label className="check"><input type="checkbox" checked={onlyRisk} onChange={event => setOnlyRisk(event.target.checked)}/> Risk verdicts only</label>
    </div>
    {visible.length === 0 && <p className="notice">No results match the current filter.</p>}
    {visible.map((test, index) => <article key={`${test.file_path}:${test.test_name}:${index}`} className="card test-card">
      <div className="test-heading"><span className="muted">{test.result_kind === 'test_candidate' ? 'STATIC TEST CANDIDATE' : 'DIAGNOSTIC GROUP · NOT A COLLECTED TEST'}</span><span className={`verdict verdict-${test.verdict}`}>{verdictLabel(test.verdict)}</span></div>
      <h3>{test.test_name}</h3><p className="file-name">{test.file_path}</p>
      <p className="score">Static risk index: <strong>{test.risk_score === null ? 'unavailable' : test.risk_score.toFixed(3)}</strong> · backend: {test.backend_used}
        {test.model_score !== null && <> · uncalibrated model score: {test.model_score.toFixed(3)}</>}</p>
      {test.patterns.length === 0 && test.log_anomalies.length === 0 && <p className="muted">No attributable known risk evidence in this group. This is not a runtime stability measurement.</p>}
      {test.patterns.map((pattern, item) => <section className={`finding severity-${pattern.severity}`} key={item}>
        <div className="finding-heading"><strong>{pattern.pattern_type.replaceAll('_', ' ')}</strong><span>{pattern.severity} · rule confidence {pattern.confidence.toFixed(2)}</span></div>
        <p>{pattern.description}</p>
        <p className="file-name">{pattern.location.file_path}:{pattern.location.line_start}</p>
        {pattern.code_snippet.trim() ? <pre className="snippet" tabIndex={0}>{pattern.code_snippet}</pre> : <p className="muted">No source excerpt is available for this evidence.</p>}
        {pattern.fix_suggestion && <p className="next-step"><strong>What to inspect:</strong> {pattern.fix_suggestion}</p>}
        <SourceEvidence pattern={pattern} snapshots={payload.source_snapshots}/>
      </section>)}
      {test.log_anomalies.map((anomaly, item) => <section className="finding log-finding" key={item}><strong>Log evidence · {anomaly.severity}</strong><p>{anomaly.description}</p><pre className="snippet">{anomaly.log_entries.map(entry => entry.raw_line).join('\n')}</pre></section>)}
      {test.fixtures.length > 0 && <details className="fixture-details"><summary>Resolved fixtures ({test.fixtures.length})</summary>{test.fixtures.map((fixture, item) => <p key={item}><strong>{fixture.fixture_name}</strong> · scope {fixture.scope} · {fixture.file_path}:{fixture.line} · dependencies: {fixture.dependencies.join(', ') || 'none'}</p>)}</details>}
      {test.diagnostics.map((item, key) => <p className="notice warning" key={key}>{diagnosticText(item)}</p>)}
    </article>)}
  </section>;
}
