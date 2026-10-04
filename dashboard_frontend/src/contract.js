/** Runtime boundary: every value accepted here must be safe for Results to render. */
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const string = value => typeof value === 'string';
const integer = value => Number.isSafeInteger(value) && value >= 0;
const finite = value => typeof value === 'number' && Number.isFinite(value);
const score = value => value === null || (finite(value) && value >= 0 && value <= 1);
const nullableString = value => value === null || string(value);
const arrayOf = (value, predicate) => Array.isArray(value) && value.every(predicate);
const hash = value => string(value) && /^[a-f0-9]{64}$/.test(value);
const diagnostic = value => object(value) && string(value.code) && string(value.message)
  && string(value.file_path) && (value.line === null || (integer(value.line) && value.line > 0))
  && ['error', 'warning'].includes(value.level);
const location = value => object(value) && string(value.file_path)
  && integer(value.line_start) && value.line_start > 0
  && (value.line_end === null || (integer(value.line_end) && value.line_end >= value.line_start))
  && nullableString(value.function_name) && nullableString(value.class_name);
const severity = value => ['low', 'medium', 'high', 'critical'].includes(value);
const pattern = value => object(value) && string(value.pattern_type) && string(value.category)
  && severity(value.severity) && string(value.description) && string(value.code_snippet)
  && string(value.fix_suggestion) && value.confidence !== null && score(value.confidence)
  && location(value.location) && object(value.metadata);
const logEntry = value => object(value) && string(value.level) && string(value.message)
  && string(value.raw_line) && nullableString(value.test_name) && nullableString(value.file_path)
  && (value.line_number === null || integer(value.line_number)) && nullableString(value.timestamp);
const anomaly = value => object(value) && string(value.anomaly_type) && string(value.category)
  && severity(value.severity) && string(value.description) && value.confidence !== null
  && score(value.confidence) && arrayOf(value.log_entries, logEntry) && object(value.metadata);
const fixture = value => object(value) && string(value.fixture_name) && string(value.function_name)
  && string(value.file_path) && string(value.scope) && integer(value.line)
  && nullableString(value.class_name) && arrayOf(value.dependencies, string)
  && ['has_yield', 'has_autouse', 'returns_mutable_literal', 'uses_finalizer']
    .every(key => typeof value[key] === 'boolean');
const testResult = value => object(value) && string(value.test_name) && string(value.file_path)
  && ['test_candidate', 'module', 'helper', 'unattributed_log'].includes(value.result_kind)
  && ['risk_detected', 'no_known_risk', 'inconclusive'].includes(value.verdict)
  && ['rules', 'ml'].includes(value.backend_used) && score(value.risk_score)
  && score(value.model_score) && score(value.calibrated_probability)
  && arrayOf(value.patterns, pattern) && arrayOf(value.log_anomalies, anomaly)
  && arrayOf(value.fixtures, fixture) && arrayOf(value.diagnostics, diagnostic)
  && arrayOf(value.recommendations, string);
const COUNTS = ['total_files_analyzed', 'total_patterns_found', 'files_selected', 'files_parsed',
  'files_rejected', 'context_files_selected', 'test_candidates', 'unique_risk_locations',
  'tests_with_risk', 'evidence_links', 'diagnostic_groups'];

export function validateAnalysis(value) {
  if (!object(value) || value.schema_version !== '2.1.0'
      || !['ok', 'partial', 'error'].includes(value.status)) {
    throw new Error('Unsupported analysis response; update the frontend and backend together.');
  }
  if (!string(value.analysis_id) || !hash(value.request_fingerprint)
      || !string(value.feature_schema_version) || !nullableString(value.model_version)
      || !nullableString(value.degraded_reason) || !COUNTS.every(key => integer(value[key]))
      || value.discovery_mode !== 'static_default_pytest'
      || !(value.collected_tests === null || integer(value.collected_tests))
      || !arrayOf(value.results, testResult) || !arrayOf(value.diagnostics, diagnostic)
      || !arrayOf(value.source_snapshots, item => object(item) && string(item.file_path)
        && hash(item.sha256) && string(item.content))) {
    throw new Error('Invalid analysis contract: unsafe or missing nested fields.');
  }
  if (value.files_selected !== value.files_parsed + value.files_rejected
      || value.total_files_analyzed !== value.files_parsed
      || value.total_patterns_found !== value.evidence_links
      || value.test_candidates !== value.results.filter(r => r.result_kind === 'test_candidate').length
      || value.diagnostic_groups !== value.results.filter(r => r.result_kind !== 'test_candidate').length
      || value.evidence_links !== value.results.reduce((n, r) => n + r.patterns.length + r.log_anomalies.length, 0)
      || value.tests_with_risk > value.test_candidates) {
    throw new Error('Invalid analysis contract: inconsistent measurement units.');
  }
  return value;
}

export function validateSearch(value) {
  if (!object(value) || !arrayOf(value.results, hit => object(hit)
      && ['identity', 'repo', 'nodeid', 'explanation', 'fix_strategy', 'metric'].every(k => string(hit[k]))
      && finite(hit.distance) && arrayOf(hit.evidence_ids, string))) {
    throw new Error('Invalid search response.');
  }
  return value.results;
}

export const diagnosticText = value =>
  `${value.file_path ? `${value.file_path}${value.line != null ? `:${value.line}` : ''}: ` : ''}${value.code}: ${value.message}`;

export function errorText(error) {
  const detail = error?.response?.data?.detail ?? error?.message ?? 'Request failed';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail?.diagnostics)) {
    return detail.diagnostics.map(d => object(d) ? diagnosticText(d) : 'Invalid diagnostic').join('\n');
  }
  try { return JSON.stringify(detail); } catch { return 'Request failed'; }
}

export const verdictLabel = verdict => ({risk_detected: 'Risk detected', no_known_risk: 'No known risk found', inconclusive: 'Inconclusive'}[verdict] ?? 'Unknown');
