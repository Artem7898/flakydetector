import {useState} from 'react';
import {BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell} from 'recharts';
import {analyzeCode, searchSimilarTests} from './api';
import {Prism as SyntaxHighlighter} from 'react-syntax-highlighter';
import {vscDarkPlus} from 'react-syntax-highlighter/dist/esm/styles/prism';
import './App.css';

const SEVERITY_COLORS = {
    low: '#4ade80',
    medium: '#facc15',
    high: '#f97316',
    critical: '#ef4444',
};

const DEFAULT_CODE = `import asyncio
import time
from datetime import datetime

def test_flaky_example():
    start = time.time()
    time.sleep(0.1)
    assert time.time() - start < 0.15

async def test_async_race():
    counter = {"val": 0}
    async def inc():
        counter["val"] += 1
    await asyncio.gather(*[inc() for _ in range(10)])
    assert counter["val"] == 10
`;

export default function App() {
    const [code, setCode] = useState(DEFAULT_CODE);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const [ragQuery, setRagQuery] = useState("");
    const [ragResults, setRagResults] = useState(null);
    const [ragLoading, setRagLoading] = useState(false);
    const [ragError, setRagError] = useState(null);

    const handleAnalyze = async () => {
        setLoading(true);
        setError(null);
        setResult(null);

        try {
            const response = await analyzeCode({
                file_content: code,
                file_path: "test_sample.py",
                use_ml_classifier: true
            });
            setResult(response.data);
        } catch (err) {
            setError(err.response?.data?.detail || err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleRAGSearch = async () => {
        if (!ragQuery.trim()) return;
        setRagLoading(true);
        setRagError(null);
        setRagResults(null);
        try {
            const response = await searchSimilarTests(ragQuery);
            setRagResults(response.data);
        } catch (err) {
            console.error("RAG Search Error: ", err);
            setRagError(err.response?.data?.detail || err.message || "Failed to search vectors");
        } finally {
            setRagLoading(false);
        }
    };

    // Aggregate chart data by severity
    const chartData = result?.flaky_tests?.[0]?.patterns?.reduce((acc, p) => {
        const existing = acc.find(item => item.name === p.severity);
        if (existing) {
            existing.count += 1;
        } else {
            acc.push({name: p.severity, count: 1});
        }
        return acc;
    }, []) || [];

    const flakyProbability = result?.flaky_tests?.[0]?.flaky_probability ?? 0;
    const isFlaky = result?.flaky_tests?.[0]?.is_flaky ?? false;
    const patterns = result?.flaky_tests?.[0]?.patterns ?? [];
    const recommendations = result?.flaky_tests?.[0]?.recommendations ?? [];

    return (
        <div className="dashboard-container">
            <header className="app-header">
                <div className="header-content">
                    <div className="logo">
                        <span className="logo-icon"></span>
                        <h1>FlakyDetector</h1>
                    </div>
                    <p>Scientific-grade AST &amp; ML Flaky Test Analysis</p>
                </div>
            </header>

            <main className="app-main">
                <section className="input-section">
                    <div className="section-header">
                        <h2>Source Code</h2>
                        <span className="lang-badge">Python</span>
                    </div>
                    <textarea
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                        placeholder="Paste your Python test code here..."
                        rows={14}
                        disabled={loading}
                        spellCheck={false}
                        aria-label="Python test code input"
                    />
                    <div className="action-bar">
                        <button
                            onClick={handleAnalyze}
                            disabled={loading || !code.trim()}
                            className={loading ? 'analyzing' : ''}
                        >
                            {loading ? (
                                <>
                                    <span className="spinner"/>
                                    Analyzing AST &amp; ML...
                                </>
                            ) : (
                                'Run Analysis'
                            )}
                        </button>
                    </div>
                </section>

                {error && (
                    <div className="error-box" role="alert" aria-live="assertive">
                        <strong>Error</strong>
                        <p>{error}</p>
                    </div>
                )}

                {result && (
                    <div className="results-section" aria-live="polite">
                        {/* Metrics Overview */}
                        <section className="metrics-grid">
                            <article className="card metric-card">
                                <h3>Flaky Probability</h3>
                                <div
                                    className="big-number"
                                    style={{
                                        color: flakyProbability > 0.7 ? '#ef4444' : '#4ade80'
                                    }}
                                >
                                    {(flakyProbability * 100).toFixed(1)}%
                                </div>
                                <div className="metric-bar">
                                    <div
                                        className="metric-bar-fill"
                                        style={{
                                            width: `${flakyProbability * 100}%`,
                                            backgroundColor: flakyProbability > 0.7 ? '#ef4444' : '#4ade80'
                                        }}
                                    />
                                </div>
                            </article>

                            <article className="card metric-card">
                                <h3>Patterns Found</h3>
                                <div className="big-number">{result.total_patterns_found}</div>
                                <span className="metric-sub">detected anti-patterns</span>
                            </article>

                            <article className="card metric-card">
                                <h3>Verdict</h3>
                                <div className={`status-badge ${isFlaky ? 'flaky' : 'stable'}`}>
                                    {isFlaky ? 'FLAKY' : 'STABLE'}
                                </div>
                                <span className="metric-sub">
                                    {isFlaky ? 'Requires attention' : 'No issues detected'}
                                </span>
                            </article>
                        </section>

                        {/* Severity Chart */}
                        {chartData.length > 0 && (
                            <section className="card chart-container">
                                <div className="section-header">
                                    <h3>Severity Distribution</h3>
                                </div>
                                <ResponsiveContainer width="100%" height={280}>
                                    <BarChart data={chartData} margin={{top: 20, right: 30, left: 0, bottom: 5}}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false}/>
                                        <XAxis
                                            dataKey="name"
                                            stroke="#64748b"
                                            tick={{fill: '#94a3b8', fontSize: 12}}
                                            axisLine={{stroke: '#334155'}}
                                        />
                                        <YAxis
                                            allowDecimals={false}
                                            stroke="#64748b"
                                            tick={{fill: '#94a3b8', fontSize: 12}}
                                            axisLine={{stroke: '#334155'}}
                                        />
                                        <Tooltip
                                            cursor={{fill: 'rgba(148, 163, 184, 0.1)'}}
                                            contentStyle={{
                                                backgroundColor: '#0f172a',
                                                border: '1px solid #334155',
                                                borderRadius: '8px',
                                                boxShadow: '0 10px 15px -3px rgba(0,0,0,0.5)'
                                            }}
                                            itemStyle={{color: '#f8fafc'}}
                                            labelStyle={{color: '#94a3b8', textTransform: 'capitalize'}}
                                        />
                                        <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={60}>
                                            {chartData.map((entry, index) => (
                                                <Cell key={`cell-${index}`}
                                                      fill={SEVERITY_COLORS[entry.name] || '#888'}/>
                                            ))}
                                        </Bar>
                                    </BarChart>
                                </ResponsiveContainer>
                            </section>
                        )}

                        {/* Detected Patterns */}
                        {patterns.length > 0 && (
                            <section className="card patterns-card">
                                <div className="section-header">
                                    <h3>Detected Patterns</h3>
                                    <span className="count-badge">{patterns.length}</span>
                                </div>
                                <ul className="pattern-list">
                                    {patterns.map((p, idx) => (
                                        <li key={idx} className={`pattern-item severity-${p.severity}`}>
                                            <div className="pattern-header">
                                                <strong className="pattern-type">{p.pattern_type}</strong>
                                                <span className={`badge badge-${p.severity}`}>{p.severity}</span>
                                            </div>
                                            <p className="pattern-desc">{p.description}</p>
                                            <div className="code-block-wrapper">
                                                <SyntaxHighlighter
                                                    language="python"
                                                    style={vscDarkPlus}
                                                    customStyle={{
                                                        margin: 0,
                                                        borderRadius: '6px',
                                                        fontSize: '0.8rem',
                                                        lineHeight: '1.5'
                                                    }}
                                                >
                                                    {p.code_snippet}
                                                </SyntaxHighlighter>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            </section>
                        )}

                        {/* Recommendations */}
                        {recommendations.length > 0 && (
                            <section className="card recommendations">
                                <div className="section-header">
                                    <h3>Recommendations</h3>
                                </div>
                                <ul className="recommendation-list">
                                    {recommendations.map((rec, idx) => (
                                        <li key={idx}>{rec}</li>
                                    ))}
                                </ul>
                            </section>
                        )}

                        {/* RAG Semantic Search Section */}
                        <section className="card" style={{marginTop: '1.5rem', borderColor: 'rgba(56, 189, 248, 0.3)'}}>
                            <div className="section-header">
                                <h3>RAG Similar Test Search (ChromaDB)</h3>
                                <span className="lang-badge">Vector DB</span>
                            </div>
                            <p style={{color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '1rem'}}>
                                Find tests with semantically similar root causes (e.g., "race conditions", "state
                                leaks").
                            </p>

                            <div style={{display: 'flex', gap: '0.5rem', marginBottom: '1rem'}}>
                                <input
                                    type="text"
                                    value={ragQuery}
                                    onChange={(e) => setRagQuery(e.target.value)}
                                    placeholder="e.g. Tests failing due to random numbers or async state..."
                                    style={{
                                        flex: 1,
                                        background: 'var(--card-bg)',
                                        color: 'var(--text-main)',
                                        border: '1px solid var(--border-color)',
                                        borderRadius: 'var(--radius-sm)',
                                        padding: '0.75rem 1rem',
                                        fontSize: '0.9rem',
                                        outline: 'none'
                                    }}
                                />
                                <button
                                    onClick={handleRAGSearch}
                                    disabled={ragLoading || !ragQuery.trim()}
                                    style={{padding: '0.75rem 1.5rem', fontSize: '0.9rem'}}
                                >
                                    {ragLoading ? 'Searching...' : 'Search Vectors'}
                                </button>
                            </div>

                            {ragError && (
                                <div className="error-box" role="alert" style={{marginTop: '1rem'}}>
                                    <strong>RAG Search Error</strong>
                                    <p>{ragError}</p>
                                    <small style={{display: 'block', marginTop: '0.5rem', opacity: 0.8}}>
                                        💡 Tip: Make sure you ran <code>python scripts/build_rag.py</code> to create the vector database
                                    </small>
                                </div>
                            )}

                            {ragResults && ragResults.results.length > 0 && (
                                <ul className="pattern-list">
                                    {ragResults.results.map((res, idx) => (
                                        <li key={idx} className="pattern-item severity-medium"
                                            style={{borderLeftColor: 'var(--accent)'}}>
                                            <div className="pattern-header">
                                                <strong className="pattern-type" style={{fontSize: '0.85rem'}}>
                                                    {res.nodeid}
                                                </strong>
                                                <span className="count-badge" style={{
                                                    background: 'rgba(56, 189, 248, 0.2)',
                                                    color: 'var(--accent)'
                                                }}>
                                                    {res.similarity_score}% match
                                                </span>
                                            </div>
                                            <p className="pattern-desc" style={{fontSize: '0.8rem'}}>
                                                {res.explanation || "No LLM explanation available for this test."}
                                            </p>
                                            <div style={{fontSize: '0.75rem', color: 'var(--text-dim)'}}>
                                                Flakiness Rate: <strong>{res.flakiness_rate}%</strong>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            )}

                            {ragResults && ragResults.results.length === 0 && (
                                <p style={{color: 'var(--text-dim)', textAlign: 'center', padding: '1rem'}}>
                                    No similar tests found in the vector database.
                                </p>
                            )}
                        </section>
                    </div>
                )}
            </main>

            <footer className="app-footer">
                <p>FlakyDetector © AST + ML Powered © {new Date().getFullYear()}</p>
            </footer>
        </div>
    );
}