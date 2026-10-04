import {useEffect, useReducer, useRef} from 'react';
import {analyzeCode, analyzeUpload, searchSimilarTests} from './api.js';
import {errorText, validateAnalysis, validateSearch} from './contract.js';
import {analysisIsStale, captureSnapshot, initialState, reducer, searchIsStale} from './state.js';
import Results, {ResultBoundary} from './Results.jsx';
import './App.css';

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const sequence = useRef(0);
  const analysisController = useRef(null);
  const searchController = useRef(null);
  const uploadInput = useRef(null);
  useEffect(() => () => { analysisController.current?.abort(); searchController.current?.abort(); }, []);
  const edit = (field, value) => dispatch({type: 'edit', field, value});

  async function analyze() {
    analysisController.current?.abort();
    const controller = new AbortController(); analysisController.current = controller;
    const id = ++sequence.current;
    const snapshot = captureSnapshot(state);
    dispatch({type: 'analysisStart', id, snapshot});
    function accept(data) {
      const payload = validateAnalysis(data);
      if (snapshot.mode === 'code' && !payload.source_snapshots.some(source =>
        source.file_path === snapshot.fileName && source.content === snapshot.code)) {
        throw new Error('Response source does not match the submitted snapshot. No result was accepted.');
      }
      dispatch({type: 'analysisSuccess', id, payload});
    }
    try {
      const response = state.mode === 'file'
        ? await analyzeUpload(state.file, state.useMl, state.token, controller.signal)
        : await analyzeCode({file_content: snapshot.code, file_path: snapshot.fileName, use_ml_classifier: snapshot.useMl}, state.token, controller.signal);
      accept(response.data);
    } catch (error) {
      if (controller.signal.aborted) return;
      // Syntax/coverage failures are structured results, not a silent blank screen.
      if (error?.response?.status === 422 && error.response.data?.detail?.schema_version) {
        try { accept(error.response.data.detail); return; }
        catch (invalid) { dispatch({type: 'analysisFailure', id, error: errorText(invalid)}); return; }
      }
      dispatch({type: 'analysisFailure', id, error: errorText(error)});
    }
  }
  async function search() {
    searchController.current?.abort();
    const controller = new AbortController(); searchController.current = controller;
    const id = ++sequence.current;
    dispatch({type: 'searchStart', id});
    try {
      const response = await searchSimilarTests(state.query, state.token, controller.signal);
      dispatch({type: 'searchSuccess', id, items: validateSearch(response.data)});
    } catch (error) {
      if (!controller.signal.aborted) dispatch({type: 'searchFailure', id, error: errorText(error)});
    }
  }
  function clearFile() {
    if (uploadInput.current) uploadInput.current.value = '';
    dispatch({type: 'clearFile'});
  }
  const validInput = state.mode === 'file' ? !!state.file : !!state.code.trim();
  return <div className="dashboard">
    <header className="app-header"><a className="brand" href="/">Flaky<span>Detector</span><small>0.2.1 RC1</small></a><span className="header-note">Static risks. Traceable evidence.</span></header>
    <main className="workspace">
      <aside className="input-panel">
        <p className="eyebrow">ANALYSIS WORKSPACE</p><h1>Inspect the risk.<br/>Keep the evidence.</h1>
        <p className="muted">Inspect Python source without executing it. Run history and calibrated probabilities are separate evidence layers.</p>
        <div className="mode-switch" role="group" aria-label="Input mode">
          <button className={state.mode === 'code' ? 'active' : ''} aria-pressed={state.mode === 'code'} onClick={() => edit('mode', 'code')}>Paste code</button>
          <button className={state.mode === 'file' ? 'active' : ''} aria-pressed={state.mode === 'file'} onClick={() => edit('mode', 'file')}>File / ZIP</button>
        </div>
        {state.mode === 'code' ? <label className="editor-label">test_sample.py<textarea aria-label="Python test source" value={state.code} onChange={event => edit('code', event.target.value)} rows={15} spellCheck={false}/></label>
          : <div className="upload-box"><label>Python file or ZIP<input ref={uploadInput} aria-label="Source file or ZIP" type="file" accept=".py,.zip" onChange={event => edit('file', event.target.files?.[0] ?? null)}/></label>
            {state.file && <p>{state.file.name} · {state.file.size.toLocaleString()} bytes</p>}<button className="secondary" onClick={clearFile}>Clear file and return to code</button></div>}
        <label className="check"><input type="checkbox" checked={state.useMl} onChange={event => edit('useMl', event.target.checked)}/> Request evaluated ML model</label>
        <p className="field-help">Optional. Missing models are reported as degraded mode; rules remain available.</p>
        <details className="credentials"><summary>API access token</summary><label>Token, if required<input type="password" autoComplete="off" value={state.token} onChange={event => edit('token', event.target.value)}/></label><p className="field-help">Kept in memory only. Never included in exported analysis snapshots.</p></details>
        <div className="actions"><button className="primary" disabled={!validInput} onClick={analyze}>{state.pending ? 'Restart analysis' : 'Run analysis'}</button>
          {state.pending && <button className="secondary" onClick={() => { analysisController.current?.abort(); dispatch({type: 'analysisCancel'}); }}>Cancel</button>}</div>
        {state.pending && <p role="status">Analyzing the submitted snapshot… You can continue editing.</p>}
        {state.error && <div className="notice danger" role="alert"><strong>Analysis unavailable</strong><pre>{state.error}</pre></div>}
      </aside>
      <div className="output-panel">
        {state.result ? <ResultBoundary key={state.result.payload.analysis_id}><Results payload={state.result.payload} snapshot={state.result.snapshot} stale={analysisIsStale(state)}/></ResultBoundary>
          : <section className="empty-state"><span className="eyebrow">NO ANALYSIS YET</span><h2>A warning should have a location.<br/>A number should have a meaning.</h2><p>Run a scan to inspect candidates, unique risk locations, fixture context and source evidence. An empty history is not a zero-percent flake rate.</p></section>}
        <section className="card related-section"><p className="eyebrow">OPTIONAL · RETRIEVAL</p><h2>Related explanations</h2><p className="muted">Retrieved explanations are unverified hypotheses. This is not automatic causal diagnosis.</p>
          <div className="search-row"><label>Search<input aria-label="Related explanation query" value={state.query} onChange={event => dispatch({type: 'query', value: event.target.value})} maxLength={2000}/></label><button className="secondary" onClick={search} disabled={!state.query.trim()}>{state.searchPending ? 'Restart search' : 'Search'}</button></div>
          {state.searchPending && <p role="status">Searching captured query…</p>}
          {state.searchError && <p className="notice warning" role="alert">{state.searchError}</p>}
          {state.hits && <div>{searchIsStale(state) && <p className="notice warning" role="status" data-testid="stale-search">Outdated search. The results below belong to the previous query or access settings.</p>}
            <p>Results for: <strong>{state.hits.query}</strong></p>
            {state.hits.items.map((hit, index) => <article key={`${hit.identity}:${index}`} className="finding"><h3>{hit.repo}: {hit.nodeid}</h3><p>{hit.explanation}</p><p>{hit.fix_strategy}</p><p>{hit.metric} distance: {hit.distance.toFixed(4)} · evidence: {hit.evidence_ids.join(', ')}</p></article>)}
            {state.hits.items.length === 0 && <p>No related explanations found.</p>}</div>}
        </section>
      </div>
    </main>
    <footer>FlakyDetector · Research-oriented test reliability tooling · Static risk is not observed nondeterminism.</footer>
  </div>;
}
