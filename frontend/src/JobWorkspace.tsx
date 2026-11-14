import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Source = { id: string; name: string; source_type: string; base_url: string | null; is_enabled: boolean; configuration: Record<string, unknown>; last_success_at: string | null; last_failure_at: string | null; integration_status: string }
type Run = { id: string; status: string; started_at: string; completed_at: string | null; jobs_found: number; jobs_created: number; jobs_updated: number; jobs_skipped: number; error_message: string | null }
type Job = { id: string; source_id: string; source_name: string; title: string; company_name: string; description: string; location: string | null; work_mode: string | null; employment_type: string | null; experience_min: number | null; experience_max: number | null; salary_min: number | null; salary_max: number | null; salary_currency: string | null; salary_period: string | null; job_url: string | null; apply_url: string | null; required_skills: string[]; preferred_skills: string[]; possible_duplicate: boolean }
type Tokens = { access_token: string }
const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
const selectorTemplate = JSON.stringify({ request_interval_seconds: 1, max_pages: 1, selectors: { job_card: 'article.job', title: '.job-title', company: '.company-name', description: '.description', location: '.location', work_mode: '.work-mode', job_url: 'a[href]', required_skills: '.skill' } }, null, 2)

async function api(path: string, token: string, init: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...init.headers } })
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Request failed (${response.status})`) }
  return response.status === 204 ? null : response
}

export default function JobWorkspace() {
  const [tokens, setTokens] = useState<Tokens | null>(null)
  const [tab, setTab] = useState<'sources' | 'jobs'>('sources')
  const [sources, setSources] = useState<Source[]>([]); const [jobs, setJobs] = useState<Job[]>([])
  const [runs, setRuns] = useState<Record<string, Run[]>>({})
  const [search, setSearch] = useState(''); const [location, setLocation] = useState(''); const [workMode, setWorkMode] = useState(''); const [sourceFilter, setSourceFilter] = useState('')
  const [message, setMessage] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)

  useEffect(() => {
    const sync = () => { const raw = sessionStorage.getItem('job-hunt-tokens'); setTokens(raw ? JSON.parse(raw) as Tokens : null) }
    sync(); window.addEventListener('job-hunt-auth', sync)
    return () => window.removeEventListener('job-hunt-auth', sync)
  }, [])

  const loadSources = useCallback(async () => {
    if (!tokens) return
    const response = await api('/sources', tokens.access_token); setSources(await response!.json() as Source[])
  }, [tokens])
  const loadJobs = useCallback(async () => {
    if (!tokens) return
    const params = new URLSearchParams()
    if (search.trim()) params.set('search', search.trim())
    if (location.trim()) params.set('location', location.trim())
    if (workMode) params.set('work_mode', workMode)
    if (sourceFilter) params.set('source_id', sourceFilter)
    const response = await api(`/jobs?${params.toString()}`, tokens.access_token)
    setJobs((await response!.json() as { items: Job[] }).items)
  }, [tokens, search, location, workMode, sourceFilter])
  useEffect(() => { if (tokens) void Promise.all([loadSources(), loadJobs()]).catch(e => setError(e.message)) }, [tokens, loadSources, loadJobs])

  async function runAction(action: () => Promise<void>, success?: string) {
    setBusy(true); setError(''); setMessage('')
    try { await action(); if (success) setMessage(success) }
    catch (e) { setError(e instanceof Error ? e.message : 'Request failed') }
    finally { setBusy(false) }
  }
  async function createSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!tokens) return
    const element = event.currentTarget; const form = new FormData(element); const sourceType = String(form.get('source_type'))
    let configuration: Record<string, unknown> = {}
    try { configuration = sourceType === 'CAREER_PAGE' ? JSON.parse(String(form.get('configuration'))) as Record<string, unknown> : {} }
    catch { setError('Configuration must be valid JSON.'); return }
    await runAction(async () => {
      await api('/sources', tokens.access_token, { method: 'POST', body: JSON.stringify({ name: form.get('name'), source_type: sourceType, base_url: form.get('base_url') || null, is_enabled: true, configuration }) })
      await loadSources()
    }, 'Job source added.')
    element.reset()
  }
  async function createImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!tokens) return
    const element = event.currentTarget; const form = new FormData(element); const get = (name: string) => String(form.get(name) || '').trim() || null
    await runAction(async () => {
      const numeric = (name: string) => { const value = get(name); return value === null ? null : Number(value) }
      const skills = (name: string) => String(form.get(name) || '').split(',').map(value => value.trim()).filter(Boolean)
      await api('/jobs/import', tokens.access_token, { method: 'POST', body: JSON.stringify({ title: form.get('title'), company_name: form.get('company_name'), location: get('location'), description: get('description') || '', job_url: get('job_url'), apply_url: get('apply_url'), work_mode: get('work_mode'), employment_type: get('employment_type'), experience_min: numeric('experience_min'), experience_max: numeric('experience_max'), salary_min: numeric('salary_min'), salary_max: numeric('salary_max'), salary_currency: get('salary_currency'), salary_period: get('salary_period'), required_skills: skills('required_skills'), preferred_skills: skills('preferred_skills') }) })
      await Promise.all([loadJobs(), loadSources()]); setTab('jobs')
    }, 'Job saved to your manual imports.')
    element.reset()
  }
  async function toggleSource(source: Source) {
    if (!tokens) return
    await runAction(async () => { await api(`/sources/${source.id}`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ is_enabled: !source.is_enabled }) }); await loadSources() }, source.is_enabled ? 'Source disabled.' : 'Source enabled.')
  }
  async function editSource(source: Source) {
    if (!tokens) return
    const name = prompt('Source name', source.name); if (name === null) return
    const url = source.source_type === 'CAREER_PAGE' ? prompt('Public career page URL', source.base_url || '') : source.base_url
    if (url === null) return
    let configuration = source.configuration
    if (source.source_type === 'CAREER_PAGE') {
      const raw = prompt('Career page parsing configuration (JSON)', JSON.stringify(source.configuration, null, 2))
      if (raw === null) return
      try { configuration = JSON.parse(raw) as Record<string, unknown> } catch { setError('Configuration must be valid JSON.'); return }
    }
    await runAction(async () => { await api(`/sources/${source.id}`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ name, base_url: url, configuration }) }); await loadSources() }, 'Source updated.')
  }
  async function inspectSource(source: Source) {
    if (!tokens) return
    await runAction(async () => {
      const response = await api(`/sources/${source.id}/test`, tokens.access_token)
      const result = await response!.json() as { status: string; detail?: string; jobs_found?: number }
      setMessage(result.status === 'ok' ? `Source reachable. ${result.jobs_found || 0} jobs found.` : `${result.status}: ${result.detail || 'No connector access configured.'}`)
    })
  }
  async function collectSource(source: Source) {
    if (!tokens) return
    await runAction(async () => {
      const response = await api(`/sources/${source.id}/collect`, tokens.access_token, { method: 'POST' })
      const result = await response!.json() as Run
      setMessage(`Collection ${result.status.toLowerCase()}: ${result.jobs_created} new, ${result.jobs_updated} updated, ${result.jobs_skipped} skipped.`)
      await Promise.all([loadSources(), loadJobs(), loadRuns(source.id)])
    })
  }
  async function loadRuns(sourceId: string) {
    if (!tokens) return
    const response = await api(`/sources/${sourceId}/runs`, tokens.access_token)
    const values = await response!.json() as Run[]
    setRuns(old => ({ ...old, [sourceId]: values }))
  }
  async function removeSource(source: Source) {
    if (!tokens || !confirm(`Delete ${source.name}? Sources with collected jobs must be disabled instead.`)) return
    await runAction(async () => { await api(`/sources/${source.id}`, tokens.access_token, { method: 'DELETE' }); await loadSources() }, 'Source deleted.')
  }

  if (!tokens) return null
  return <section className="job-workspace" aria-label="Jobs and sources">
    <div className="feature-tabs"><button className={tab === 'sources' ? 'active' : ''} onClick={() => setTab('sources')}>Job sources</button><button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}>Jobs</button></div>
    {error && <p role="alert" className="notice error">{error}</p>}{message && <p role="status" className="notice">{message}</p>}
    {tab === 'sources' ? <div className="source-columns"><section><div className="section-heading"><div><h2>Configured sources</h2><p>Public pages and authorized integrations only.</p></div><span>{sources.length}</span></div>{sources.length === 0 && <p className="empty">No sources yet. Add a public company careers page or a source that is awaiting authorized access.</p>}
      {sources.map(source => <article className="source-card" key={source.id}><div className="source-card-head"><div><strong>{source.name}</strong><small>{source.source_type.replaceAll('_', ' ')}</small></div><span className={`status ${source.is_enabled ? 'status-completed' : 'status-failed'}`}>{source.is_enabled ? 'ENABLED' : 'DISABLED'}</span></div><p className="integration-state">{source.integration_status}</p>{source.base_url && <a className="source-url" href={source.base_url} target="_blank" rel="noreferrer">{source.base_url}</a>}<div className="source-times"><span>Last success: {source.last_success_at ? new Date(source.last_success_at).toLocaleString() : 'Never'}</span><span>Last failure: {source.last_failure_at ? new Date(source.last_failure_at).toLocaleString() : 'None'}</span></div><div className="source-actions"><button className="secondary" onClick={() => void inspectSource(source)}>Test</button><button className="secondary" disabled={!source.is_enabled || source.integration_status !== 'CONFIGURED' || busy} onClick={() => void collectSource(source)}>Collect</button><button className="text-button" onClick={() => void editSource(source)}>Edit</button><button className="text-button" onClick={() => void toggleSource(source)}>{source.is_enabled ? 'Disable' : 'Enable'}</button><button className="text-button danger-text" onClick={() => void removeSource(source)}>Delete</button><button className="text-button" onClick={() => void loadRuns(source.id)}>History</button></div>{runs[source.id] && <div className="run-history" aria-label={`${source.name} collection history`}>{runs[source.id].length === 0 ? 'No runs yet.' : runs[source.id].map(run => <p key={run.id}><strong>{run.status}</strong> · {new Date(run.started_at).toLocaleString()} · found {run.jobs_found}, new {run.jobs_created}, updated {run.jobs_updated}, skipped {run.jobs_skipped}{run.error_message && ` · ${run.error_message}`}</p>)}</div>}</article>)}</section>
      <section className="workspace-form"><h2>Add a job source</h2><form onSubmit={createSource}><label>Name<input name="name" required maxLength={120} placeholder="Example Careers" /></label><label>Source type<select name="source_type" defaultValue="CAREER_PAGE"><option value="CAREER_PAGE">Public company careers page</option><option value="GMAIL_ALERT">Gmail alert (OAuth pending)</option>{['LINKEDIN', 'NAUKRI', 'INSTAHYRE', 'CUTSHORT', 'HIRIST', 'INDEED', 'WELLFOUND', 'FOUNDIT'].map(value => <option key={value} value={value}>{value} (authorized feed pending)</option>)}</select></label><label>Public base URL<input name="base_url" type="url" placeholder="https://company.example/careers" /></label><label>Parsing configuration JSON<textarea name="configuration" rows={9} defaultValue={selectorTemplate} /></label><button disabled={busy}>Add source</button><p>Career pages must be publicly accessible and permitted by their robots.txt and terms. Portal entries remain inactive until an authorized API or feed exists.</p></form></section></div>
      : <div className="jobs-panel"><section className="filter-panel"><form className="job-filters" onSubmit={event => { event.preventDefault(); void runAction(loadJobs) }}><label>Search<input value={search} onChange={e => setSearch(e.target.value)} placeholder="Title or company" /></label><label>Location<input value={location} onChange={e => setLocation(e.target.value)} placeholder="Chennai, Remote…" /></label><label>Work mode<select value={workMode} onChange={e => setWorkMode(e.target.value)}><option value="">Any mode</option><option value="REMOTE">Remote</option><option value="HYBRID">Hybrid</option><option value="ONSITE">Onsite</option></select></label><label>Source<select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}><option value="">All sources</option>{sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label><button>Apply filters</button></form></section>
        <div className="jobs-columns"><section><div className="section-heading"><div><h2>Job listings</h2><p>Review original listings and apply links yourself.</p></div><span>{jobs.length}</span></div>{jobs.length === 0 ? <p className="empty">No jobs match these filters. Collect from an enabled public source or import a job manually.</p> : jobs.map(job => <article className="job-card" key={job.id}><div className="job-card-head"><div><p className="eyebrow">{job.source_name}</p><h3>{job.title}</h3><p>{job.company_name} · {job.location || 'Location not provided'}{job.work_mode && ` · ${job.work_mode}`}</p></div>{job.possible_duplicate && <span className="status status-needs_ocr">Possible duplicate</span>}</div><div className="job-facts">{job.salary_min !== null && job.salary_min !== undefined && <span>Salary {job.salary_currency} {job.salary_min.toLocaleString()}{job.salary_max ? `–${job.salary_max.toLocaleString()}` : ''} {job.salary_period?.toLowerCase()}</span>}{job.experience_min !== null && job.experience_min !== undefined && <span>Experience {job.experience_min}{job.experience_max !== null ? `–${job.experience_max}` : '+'} months</span>}{job.employment_type && <span>{job.employment_type.replaceAll('_', ' ')}</span>}</div><p className="job-description">{job.description.slice(0, 520)}{job.description.length > 520 ? '…' : ''}</p><div className="skill-tags">{[...job.required_skills.map(skill => `Required · ${skill}`), ...job.preferred_skills.map(skill => `Preferred · ${skill}`)].map(skill => <span key={skill}>{skill}</span>)}</div><div className="job-links">{job.job_url && <a href={job.job_url} target="_blank" rel="noreferrer">Original listing ↗</a>}{job.apply_url && <a href={job.apply_url} target="_blank" rel="noreferrer">Application page ↗</a>}</div></article>)}</section>
          <section className="workspace-form"><h2>Manual job import</h2><form onSubmit={createImport}><label>Job title<input name="title" required maxLength={300} /></label><label>Company<input name="company_name" required maxLength={300} /></label><label>Location<input name="location" /></label><label>Work mode<select name="work_mode" defaultValue=""><option value="">Unknown</option><option value="REMOTE">Remote</option><option value="HYBRID">Hybrid</option><option value="ONSITE">Onsite</option></select></label><label>Employment type<select name="employment_type" defaultValue=""><option value="">Unknown</option><option value="FULL_TIME">Full time</option><option value="PART_TIME">Part time</option><option value="CONTRACT">Contract</option><option value="INTERNSHIP">Internship</option><option value="TEMPORARY">Temporary</option></select></label><label>Minimum experience (months)<input name="experience_min" type="number" min="0" /></label><label>Maximum experience (months)<input name="experience_max" type="number" min="0" /></label><label>Salary minimum<input name="salary_min" type="number" min="0" step="any" /></label><label>Salary maximum<input name="salary_max" type="number" min="0" step="any" /></label><label>Salary currency<select name="salary_currency" defaultValue=""><option value="">Unknown</option><option>INR</option><option>USD</option><option>EUR</option><option>GBP</option></select></label><label>Salary period<select name="salary_period" defaultValue=""><option value="">Unknown</option><option value="ANNUAL">Annual</option><option value="MONTHLY">Monthly</option><option value="HOURLY">Hourly</option></select></label><label>Required skills<input name="required_skills" placeholder="Python, PostgreSQL" /></label><label>Preferred skills<input name="preferred_skills" placeholder="Docker, Kubernetes" /></label><label>Job description<textarea name="description" rows={6} /></label><label>Job URL<input name="job_url" type="url" placeholder="https://…" /></label><label>Application URL<input name="apply_url" type="url" placeholder="https://…" /></label><button disabled={busy}>Save job</button><p>URLs are validated but never fetched by the server.</p></form></section></div></div>}
  </section>
}
