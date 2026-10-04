/** Request/snapshot state is independent of React so race contracts are directly testable. */
export const DEFAULT_CODE = `import time

def test_deadline():
    start = time.time()
    time.sleep(0.1)
    assert time.time() - start < 0.15
`;
export const initialState = {
  code: DEFAULT_CODE, file: null, mode: 'code', useMl: false, token: '', revision: 0,
  pending: null, result: null, error: null,
  query: '', queryRevision: 0, searchPending: null, hits: null, searchError: null,
};

export function captureSnapshot(state) {
  // Credentials never enter a result snapshot or exported report.
  return Object.freeze({revision: state.revision, mode: state.mode, useMl: state.useMl,
    fileName: state.mode === 'file' ? state.file?.name ?? null : 'test_sample.py',
    code: state.mode === 'code' ? state.code : null});
}
export const analysisIsStale = state => !!state.result && state.result.snapshot.revision !== state.revision;
export const searchIsStale = state => !!state.hits && state.hits.revision !== state.queryRevision;

export function reducer(state, action) {
  switch (action.type) {
    case 'edit': {
      const allowed = ['code', 'file', 'mode', 'useMl', 'token'];
      if (!allowed.includes(action.field) || state[action.field] === action.value) return state;
      return {...state, [action.field]: action.value, revision: state.revision + 1, error: null,
        queryRevision: state.queryRevision + (action.field === 'token' ? 1 : 0)};
    }
    case 'clearFile': return {...state, file: null, mode: 'code', revision: state.revision + 1, error: null};
    case 'analysisStart': return {...state, pending: {id: action.id, snapshot: action.snapshot}, error: null};
    case 'analysisSuccess':
      return state.pending?.id !== action.id ? state : {...state, pending: null,
        result: {payload: action.payload, snapshot: state.pending.snapshot}, error: null};
    case 'analysisFailure':
      return state.pending?.id !== action.id ? state : {...state, pending: null, error: action.error};
    case 'analysisCancel': return {...state, pending: null};
    case 'query': return {...state, query: action.value, queryRevision: state.queryRevision + 1, searchError: null};
    case 'searchStart': return {...state, searchPending: {id: action.id, query: state.query, revision: state.queryRevision}, searchError: null};
    case 'searchSuccess':
      return state.searchPending?.id !== action.id ? state : {...state,
        hits: {items: action.items, query: state.searchPending.query, revision: state.searchPending.revision}, searchPending: null};
    case 'searchFailure':
      return state.searchPending?.id !== action.id ? state : {...state, searchPending: null, searchError: action.error};
    case 'searchCancel': return {...state, searchPending: null};
    default: return state;
  }
}
