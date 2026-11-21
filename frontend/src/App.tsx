import { useEffect, useMemo, useState } from 'react';
import { Activity, Waves, ShieldCheck, Database, Send, Clock3, FlaskConical, ChevronRight, Download, RotateCcw, Settings2, BookOpen, AlertTriangle, ExternalLink } from 'lucide-react';
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type Observation = { date: string; sst_c: number | null; sst_samples: number; chlorophyll_mg_m3: number | null; chlorophyll_samples: number };
type Stage = { id: string; name: string; status: string; output?: any; error?: string; version?: string };
type Result = { session_id: string; query: string; created_at: string; status: string; mode: string; data_status: string; ai_status: string; stages: Stage[]; chart: { title: string; data: Observation[] }; statistics: any; data_quality: any; report: any; retrieved_at: string };
type Prompt = { id: string; name: string; version: string; role: string; objective: string; instructions: string; input_schema: string; output_schema: string };

const examples = [
  'Analyze recent sea surface temperature and chlorophyll-a conditions in the Arabian Sea.',
  'Is there an association between SST and chlorophyll-a in the Arabian Sea over the last 30 days?',
  'Compare recent SST and chlorophyll-a variability in the Bay of Bengal.',
  'Describe recent daily ocean conditions across the Indian Ocean.',
];
const regionOptions = ['Arabian Sea', 'Indian Ocean', 'Bay of Bengal', 'South China Sea'];

export default function App() {
  const [q, setQ] = useState('');
  const [region, setRegion] = useState('Arabian Sea');
  const [days, setDays] = useState(30);
  const [mode, setMode] = useState('comprehensive');
  const [prefs, setPrefs] = useState({ length: 'balanced', technical_level: 'intermediate', format: 'structured', visualization: 'recommended', evidence: 'strict' });
  const [r, setR] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('Research');
  const [config, setConfig] = useState<any>(null);
  const [sessions, setSessions] = useState<Result[]>([]);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [datasetCatalog, setDatasetCatalog] = useState<any[]>([]);
  const [cacheState, setCacheState] = useState<any>(null);
  const [retrievalLog, setRetrievalLog] = useState<any[]>([]);
  const [datasetBusy, setDatasetBusy] = useState(false);

  async function loadWorkspace() {
    const [health, history] = await Promise.all([fetch('/api/config/status'), fetch('/api/research/history')]);
    if (health.ok) setConfig(await health.json());
    if (history.ok) setSessions(await history.json());
  }
  useEffect(() => { void loadWorkspace(); }, []);

  useEffect(() => {
    if (tab === 'Prompt Lab') fetch('/api/prompts').then(x => x.json()).then(setPrompts).catch(() => setPrompts([]));
    if (tab === 'Evaluations') fetch('/api/evaluations').then(x => x.json()).then(setEvaluation).catch(() => setEvaluation(null));
    if (tab === 'Dataset Catalog' || tab === 'Data Management') void loadDatasets();
  }, [tab]);

  async function loadDatasets() {
    const [d, c, l] = await Promise.all([fetch('/api/datasets'), fetch('/api/data-management/cache'), fetch('/api/data-management/retrievals')]);
    if (d.ok) setDatasetCatalog(await d.json()); if (c.ok) setCacheState(await c.json()); if (l.ok) setRetrievalLog(await l.json());
  }

  async function retrieveOBIS() {
    setDatasetBusy(true); setError('');
    try { const response = await fetch('/api/datasets/obis/retrieve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region, limit: 100 }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'OBIS retrieval failed');
      window.alert(`Retrieved ${data.returned} occurrence records (total matching: ${data.total ?? 'unknown'}). This is record coverage, not abundance.`); await loadDatasets();
    } catch (e: any) { setError(e.message); } finally { setDatasetBusy(false); }
  }

  async function clearCache(datasetId: string) {
    if (!window.confirm(`Delete cached records for ${datasetId}?`)) return;
    await fetch(`/api/data-management/cache/${encodeURIComponent(datasetId)}?confirm=true`, { method: 'DELETE' }); await loadDatasets();
  }

  async function run() {
    if (q.trim().length < 8) { setError('Enter a research question with at least 8 characters.'); return; }
    setBusy(true); setError(''); setR(null);
    try {
      const response = await fetch('/api/research', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, region, window_days: days, mode, answer_preferences: prefs }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Research request failed.');
      setR(payload); setSessions(old => [payload, ...old.filter(item => item.session_id !== payload.session_id)]);
    } catch (e: any) { setError(e?.message || 'Could not complete this research run.'); }
    finally { setBusy(false); void loadWorkspace(); }
  }

  async function openSession(sessionId: string) {
    try {
      const response = await fetch(`/api/research/${sessionId}`);
      if (!response.ok) throw new Error('Could not load saved research.');
      setR(await response.json()); setTab('Research'); setError('');
    } catch (e: any) { setError(e.message); }
  }

  async function deleteSession(sessionId: string) {
    const response = await fetch(`/api/research/${sessionId}`, { method: 'DELETE' });
    if (response.ok) { setSessions(old => old.filter(item => item.session_id !== sessionId)); if (r?.session_id === sessionId) setR(null); }
  }

  function exportReport() {
    if (!r) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(r.report, null, 2)], { type: 'application/json' }));
    a.download = `orca-x-${r.session_id.slice(0, 8)}-report.json`; a.click(); URL.revokeObjectURL(a.href);
  }

  async function exportCsv() {
    if (!r) return;
    const response = await fetch(`/api/research/${r.session_id}/data.csv`);
    if (!response.ok) { setError('Could not export normalized observations.'); return; }
    const a = document.createElement('a'); a.href = URL.createObjectURL(await response.blob());
    a.download = `orca-x-${r.session_id.slice(0, 8)}-observations.csv`; a.click(); URL.revokeObjectURL(a.href);
  }

  const nav = [
    { name: 'Research', icon: <Activity /> }, { name: 'History', icon: <Clock3 /> },
    { name: 'Dataset Catalog', icon: <Database /> }, { name: 'Data Management', icon: <Download /> },
    { name: 'Prompt Lab', icon: <FlaskConical /> }, { name: 'Evaluations', icon: <ShieldCheck /> },
    { name: 'Settings', icon: <Settings2 /> },
  ];
  const chartData = useMemo(() => r?.chart.data ?? [], [r]);

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="mark"><Waves /></div><div><b>ORCA-X</b><small>MARINE INTELLIGENCE</small></div></div>
      <div className="navlabel">WORKSPACE</div>
      {nav.map(item => <button className={'nav ' + (tab === item.name ? 'active' : '')} onClick={() => setTab(item.name)} key={item.name}>{item.icon}{item.name}<ChevronRight size={14} /></button>)}
      <div className="sidebottom"><span className="pulse" /> LOCAL RESEARCH SYSTEM<small>Groq · NOAA · SQLite</small></div>
    </aside>

    <main>
      <header>
        <div className="mobilebrand"><Waves /> ORCA-X</div>
        <div><div className="eyebrow">MARINE RESEARCH SYSTEM</div><h1>{tab === 'Research' ? 'Research workspace' : tab}</h1></div>
        <div className="status"><span className="pulse" /> API ONLINE <span className="pill">{config?.groq_configured ? 'GROQ KEY SET' : 'GROQ KEY MISSING'}</span></div>
      </header>

      {tab === 'Research' && <>
        <section className="intro"><div><p>Live ocean data · AI-supported analysis</p><h2>Ask a question.<br /><em>Follow the evidence.</em></h2><div className="sub">NOAA daily sea surface temperature and VIIRS chlorophyll-a, analyzed with Groq and persisted locally.</div></div><div className="orb"><Waves size={54} /><span>NOAA NCEI<br />LIVE DATA</span></div></section>

        <div className="grid">
          <section className="panel querypanel">
            <div className="panelhead"><div><span className="overline">01 / RESEARCH QUERY</span><h3>What would you like to investigate?</h3></div><span className="badge">● READY</span></div>
            <textarea value={q} onChange={e => setQ(e.target.value)} placeholder="Ask about ocean conditions or relationships between SST and chlorophyll-a..." />
            <div className="controls research-controls">
              <label>REGION<select value={region} onChange={e => setRegion(e.target.value)}>{regionOptions.map(x => <option key={x}>{x}</option>)}</select></label>
              <label>DATE WINDOW<select value={days} onChange={e => setDays(Number(e.target.value))}><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={180}>Last 180 days</option><option value={365}>Last 365 days</option></select></label>
              <label>MODE<select value={mode} onChange={e => setMode(e.target.value)}><option value="quick">Quick Analysis</option><option value="comprehensive">Comprehensive Analysis</option><option value="data-driven">Data-Driven Analysis</option></select></label>
              <button className="submit" onClick={run} disabled={busy || !config?.groq_configured}>{busy ? 'Retrieving & analyzing…' : <>Run live analysis <Send size={15} /></>}</button>
            </div>
            <details className="preferences"><summary>Answer preferences</summary><div className="preference-grid">
              <label>LENGTH<select value={prefs.length} onChange={e => setPrefs({...prefs,length:e.target.value})}><option value="short">Short</option><option value="balanced">Balanced</option><option value="detailed">Detailed</option><option value="comprehensive">Comprehensive</option></select></label>
              <label>TECHNICAL LEVEL<select value={prefs.technical_level} onChange={e => setPrefs({...prefs,technical_level:e.target.value})}><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option><option value="scientific">Scientific / Research</option></select></label>
              <label>FORMAT<select value={prefs.format} onChange={e => setPrefs({...prefs,format:e.target.value})}><option value="conversational">Conversational</option><option value="bullets">Bullet points</option><option value="structured">Structured report</option><option value="table">Table</option><option value="paper">Research paper style</option></select></label>
              <label>VISUALIZATION<select value={prefs.visualization} onChange={e => setPrefs({...prefs,visualization:e.target.value})}><option value="none">None</option><option value="recommended">Recommended</option><option value="extensive">Extensive</option></select></label>
              <label>EVIDENCE<select value={prefs.evidence} onChange={e => setPrefs({...prefs,evidence:e.target.value})}><option value="normal">Normal</option><option value="strict">Strict evidence</option></select></label>
            </div></details>
            <div className="explain">The workflow fetches NOAA SST + chlorophyll grids, computes statistics, then runs Groq prompt agents. NOAA updates have a product-specific lag; the report shows actual coverage.</div>
            {error && <div className="error"><AlertTriangle size={15} /> {error}</div>}
            {!config?.groq_configured && <div className="error">Configure GROQ_API_KEY in the backend .env file and restart the API.</div>}
            <div className="examples"><span>TRY A QUESTION</span>{examples.map((x, i) => <button onClick={() => setQ(x)} key={i}>{x}</button>)}</div>
          </section>
          <section className="panel source"><span className="overline">LIVE DATA CONNECTION</span><div className="sourceicon"><Database /></div><h3>NOAA NCEI + CoastWatch</h3><p>Daily OISST v2.1 near-real-time SST via NCEI THREDDS NCSS, plus NOAA-20 VIIRS chlorophyll-a via CoastWatch ERDDAP when reachable. Availability is reported per source.</p><div className="sourcefoot"><span className="dot" /> LIVE PROVIDER REQUESTS</div><div className="source-links"><a href="https://www.ncei.noaa.gov/products/optimum-interpolation-sst" target="_blank" rel="noreferrer">NOAA SST product <ExternalLink size={12} /></a><a href="https://coastwatch.pfeg.noaa.gov/erddap/info/nesdisVHNnoaa20chlaDaily/index.html" target="_blank" rel="noreferrer">NOAA chlorophyll metadata <ExternalLink size={12} /></a></div></section>
        </div>

        {r && <>
          <div className="resulthead"><div><span className="overline">02 / RESEARCH OUTPUT</span><h2>Analysis {r.status} <span className="pill">{r.data_status.toUpperCase()} DATA</span><span className="pill">AI {r.ai_status.toUpperCase()}</span></h2></div><div className="actions"><button className="outline" onClick={() => { setQ(''); setR(null); }}><RotateCcw size={14} /> New query</button><button className="outline" onClick={exportReport}><Download size={14} /> Export JSON</button><button className="outline" onClick={() => void exportCsv()}><Download size={14} /> Export data CSV</button></div></div>
          {r.report.marine_heatwave_analysis && <section className="panel pagepanel mhw-result"><span className="overline">DETERMINISTIC EVENT ANALYSIS · HOBDAY DAILY THRESHOLD</span><h2>{r.report.marine_heatwave_analysis.status.replaceAll('_', ' ').toUpperCase()}</h2><p>{r.report.marine_heatwave_analysis.reason || r.report.executive_summary}</p>{r.report.marine_heatwave_analysis.events?.length > 0 && <div className="history-row"><b>Detected events</b><span>{r.report.marine_heatwave_analysis.events.map((event: any) => `${event.start}–${event.end}: ${event.duration_days} days, mean ${event.mean_intensity_c}°C, max ${event.maximum_intensity_c}°C, cumulative ${event.cumulative_intensity_c_days}°C·days`).join(' · ')}</span></div>}<small>Baseline: {r.report.marine_heatwave_analysis.baseline_period?.join('–') || 'unavailable'} · {r.report.marine_heatwave_analysis.spatial_scope || 'Spatial scope not calculated'}</small>{prefs.visualization !== 'none' && (r.report.marine_heatwave_analysis.daily_series?.length ?? 0) > 0 && <div className="mhw-chart"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={r.report.marine_heatwave_analysis.daily_series}><CartesianGrid stroke="#1b3541" strokeDasharray="3 3"/><XAxis dataKey="date" stroke="#6e8790" tickLine={false} tick={{fontSize:9}} minTickGap={28}/><YAxis stroke="#6e8790" tickLine={false} width={44} unit="°C"/><Tooltip contentStyle={{background:'#10232c',border:'1px solid #28434d',borderRadius:8}}/><Line type="monotone" dataKey="sst_c" name="Regional SST" stroke="#57d6cf" strokeWidth={2} dot={false} connectNulls={false}/><Line type="monotone" dataKey="threshold_c" name="Seasonal 90th percentile" stroke="#e5bf71" strokeDasharray="5 4" dot={false} connectNulls={false}/><Line type="monotone" dataKey="climatology_c" name="Daily climatology" stroke="#8095a0" strokeDasharray="2 4" dot={false} connectNulls={false}/></ComposedChart></ResponsiveContainer></div>}</section>}
          <div className="resultgrid">
            <section className="panel chartpanel"><div className="panelhead"><div><span className="overline">DAILY REGIONAL MEANS · NOAA</span><h3>{r.chart.title}</h3></div><span className="unit">SST °C · Chl mg/m³</span></div>
              <div className="chart"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={chartData}><CartesianGrid stroke="#1b3541" strokeDasharray="3 3" /><XAxis dataKey="date" stroke="#6e8790" tickLine={false} tick={{ fontSize: 9 }} minTickGap={28} /><YAxis yAxisId="sst" stroke="#63d3cc" tickLine={false} width={40} /><YAxis yAxisId="chl" orientation="right" stroke="#e5bf71" tickLine={false} width={45} /><Tooltip contentStyle={{ background: '#10232c', border: '1px solid #28434d', borderRadius: 8 }} /><Line yAxisId="sst" type="monotone" dataKey="sst_c" name="SST °C" stroke="#57d6cf" strokeWidth={2} dot={false} connectNulls={false} /><Line yAxisId="chl" type="monotone" dataKey="chlorophyll_mg_m3" name="Chlorophyll mg/m³" stroke="#e5bf71" strokeWidth={1.5} dot={false} connectNulls={false} /></ComposedChart></ResponsiveContainer></div>
              <div className="stats"><div><small>MEAN SST</small><b>{fmt(r.statistics.sst.mean_c, 2)}°C</b></div><div><small>MEAN CHL-A</small><b>{fmt(r.statistics.chlorophyll.mean_mg_m3, 3)} mg/m³</b></div><div><small>PAIRED DAYS</small><b>{r.statistics.paired_days}</b></div><div><small>PEARSON r</small><b>{fmt(r.statistics.daily_area_mean_pearson_r, 2)}</b></div></div>
              <p className="retrieved">Retrieved {new Date(r.retrieved_at).toLocaleString()} · NOAA day coverage {r.report.time_period.start} to {r.report.time_period.end}</p>
            </section>
            <section className="panel report"><span className="overline">GROQ-SUPPORTED REPORT</span><h3>{r.report.executive_summary}</h3><p>{r.report.scientific_analysis || r.report.synthesis}</p><div className="callout"><ShieldCheck size={17} /><span>{r.report.data_availability}</span></div><h4>EVIDENCE CHECKS</h4>{(r.report.claims || []).map((c: any, i: number) => <div className="claim" key={i}><span className={'dot ' + (c.evidence_status === 'Supported' ? '' : 'amber')} /><div><b>{c.evidence_status}</b><p>{c.claim}</p><small>{(c.evidence_ids || []).join(', ') || 'No matched dataset evidence'}</small></div></div>)}<h4>LIMITATIONS</h4><ul>{(r.report.uncertainty_and_limitations || []).map((x: string) => <li key={x}>{x}</li>)}</ul></section>
          </div>
          <section className="panel agents"><div className="panelhead"><div><span className="overline">ORCHESTRATION</span><h3>Research workflow stages</h3></div><span className="badge">{r.stages.filter(s => s.status === 'completed').length}/{r.stages.length} COMPLETE</span></div><div className="stagelist">{r.stages.map((s, i) => <details key={s.id} className={'stage ' + s.status}><summary><i>{String(i + 1).padStart(2, '0')}</i><span>{s.name}</span><b>{s.status.toUpperCase()}</b></summary>{s.error ? <p>{s.error}</p> : <pre>{JSON.stringify(s.output, null, 2)}</pre>}</details>)}</div></section>
        </>}

        {!r && <div className="bottomgrid"><div className="mini"><Clock3 /><div><b>Persisted research history</b><p>{sessions.length} saved runs in local SQLite.</p></div></div><div className="mini"><ShieldCheck /><div><b>Evidence is traceable</b><p>Dataset metadata, cell counts, coverage dates, and claim evidence IDs are stored.</p></div></div><div className="mini"><Activity /><div><b>Numerics are calculated</b><p>Python computes area-weighted daily means and exploratory association.</p></div></div></div>}
      </>}

      {tab === 'History' && <section className="panel pagepanel"><span className="overline">SAVED SESSIONS · SQLITE</span><h2>Research history</h2>{sessions.length === 0 ? <p>No saved analyses yet. Submit a live research query to create one.</p> : sessions.map(item => <div className="history-row" key={item.session_id}><button onClick={() => void openSession(item.session_id)}><b>{item.query}</b><small>{item.report.region} · {item.report.time_period.start}—{item.report.time_period.end} · {new Date(item.created_at).toLocaleString()}</small></button><button className="outline" onClick={() => void deleteSession(item.session_id)}>Delete</button></div>)}</section>}

      {tab === 'Dataset Catalog' && <section className="panel pagepanel"><span className="overline">SOURCE REGISTRY · VERIFIED CAPABILITIES</span><h2>Dataset Catalog</h2><p>Provider metadata and local connector status are shown separately. A status does not imply query coverage unless retrieval has succeeded.</p><div className="catalog-grid">{datasetCatalog.map(d => <article className="dataset-card" key={d.id}><div className="panelhead"><h3>{d.name}</h3><span className={'dataset-status ' + String(d.status).toLowerCase()}>{d.status.replaceAll('_', ' ')}</span></div><p><b>{d.provider}</b> · {d.category}</p><p>Variables: {(d.variables || []).join(', ') || 'literature metadata'}<br/>Units: {Object.entries(d.units || {}).map(([k,v]) => `${k}: ${v}`).join(' · ')}</p><p>Coverage: {d.coverage}<br/>Time: {d.temporal_coverage}<br/>Resolution: {d.spatial_resolution} · {d.temporal_resolution}</p><p>Access: {d.access_method}<br/>Dataset ID: <code>{d.id}</code></p><small>{d.quality_notes}</small><p><a href={d.metadata_url} target="_blank" rel="noreferrer">Provider metadata <ExternalLink size={12}/></a></p></article>)}</div></section>}

      {tab === 'Data Management' && <section className="panel pagepanel"><span className="overline">LOCAL CACHE · RETRIEVAL AUDIT</span><h2>Data Management</h2><div className="stats"><div><small>CACHED DATASETS</small><b>{cacheState?.datasets?.length ?? 0}</b></div><div><small>CACHED RECORDS</small><b>{cacheState?.records ?? 0}</b></div><div><small>CACHE SIZE</small><b>{formatBytes(cacheState?.total_bytes ?? 0)}</b></div><div><small>RETRIEVALS</small><b>{retrievalLog.length}</b></div></div><div className="data-actions"><label>OBIS region<select value={region} onChange={e => setRegion(e.target.value)}>{regionOptions.map(x => <option key={x}>{x}</option>)}</select></label><button className="submit" disabled={datasetBusy} onClick={() => void retrieveOBIS()}>{datasetBusy ? 'Retrieving…' : 'Retrieve OBIS occurrences'}</button><button className="outline" onClick={() => void loadDatasets()}>Refresh inventory</button></div>{error && <div className="error">{error}</div>}<h3>Cached source data</h3>{(cacheState?.datasets || []).length === 0 ? <p>No source records are currently cached.</p> : cacheState.datasets.map((c: any) => <div className="history-row" key={c.dataset_id}><span><b>{c.dataset_id}</b><small>{c.records} records · {formatBytes(c.bytes)} · {c.date_start}—{c.date_end}</small></span><button className="outline" onClick={() => void clearCache(c.dataset_id)}>Remove cache…</button></div>)}<h3>Recent retrieval log</h3>{retrievalLog.length === 0 ? <p>No recorded API retrievals yet.</p> : retrievalLog.map((x: any) => <div className="history-row" key={x.retrieval_id}><span><b>{x.dataset_id} · {x.status}</b><small>{x.started_at} · {x.region || 'global'} · {x.records} records{x.error ? ` · ${x.error}` : ''}</small></span></div>)}</section>}

      {tab === 'Prompt Lab' && <section className="panel pagepanel"><span className="overline">VERSIONED PROMPT REGISTRY</span><h2>Prompt Lab</h2><p>These are the instructions used by model stages. Data retrieval and numeric stages run as deterministic Python tools.</p>{prompts.map(p => <details className="prompt-row" key={p.id}><summary><b>{p.name}</b><span>v{p.version}</span></summary><p>{p.objective}</p><pre>{p.instructions}</pre><small>Input: {p.input_schema} · Output: {p.output_schema}</small></details>)}</section>}

      {tab === 'Evaluations' && <section className="panel pagepanel"><span className="overline">RUN METRICS · REAL SESSIONS</span><h2>Evaluations</h2><p>Metrics are computed only from saved runs. This page does not report fabricated benchmark scores.</p><div className="stats"><div><small>RECORDED RUNS</small><b>{evaluation?.runs?.length ?? sessions.length}</b></div><div><small>DATA + AI COMPLETE</small><b>{sessions.filter(s => s.status === 'completed' && s.ai_status === 'completed' && s.data_status === 'live').length}</b></div><div><small>AGENT FAILURES</small><b>{sessions.reduce((n, s) => n + s.stages.filter(stage => stage.status === 'failed').length, 0)}</b></div></div></section>}

      {tab === 'Settings' && <section className="panel pagepanel"><span className="overline">BACKEND CONFIGURATION</span><h2>Settings</h2><div className="settings-row"><b>Groq API</b><span>{config?.groq_configured ? 'Key configured on backend' : 'Missing key'}</span></div><div className="settings-row"><b>Model</b><span>{config?.model || 'Loading…'}</span></div><div className="settings-row"><b>Data service</b><span>{config?.data_mode || 'Loading…'}</span></div><div className="settings-row"><b>Database</b><span>{config?.database || 'Loading…'}</span></div><p>API keys stay in the ignored backend .env file. Restart the API after changing backend configuration.</p></section>}

      <footer>ORCA-X · Live data research prototype <span>Satellite products have latency and gaps. Interpretations are not causal evidence.</span></footer>
    </main>
  </div>;
}

function fmt(value: number | null | undefined, digits: number) { return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits); }
function formatBytes(bytes: number) { if (!bytes) return '0 B'; const units = ['B','KB','MB','GB']; const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1); return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`; }
