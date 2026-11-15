import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Source = { id: string; name: string; source_type: string; base_url: string | null; is_enabled: boolean; configuration: Record<string, unknown>; last_success_at: string | null; last_failure_at: string | null; integration_status: string }
type Run = { id: string; status: string; started_at: string; completed_at: string | null; jobs_found: number; jobs_created: number; jobs_updated: number; jobs_skipped: number; error_message: string | null }
type Job = { id: string; source_id: string; source_name: string; title: string; company_name: string; description: string; location: string | null; work_mode: string | null; employment_type: string | null; experience_min: number | null; experience_max: number | null; salary_min: number | null; salary_max: number | null; salary_currency: string | null; salary_period: string | null; job_url: string | null; apply_url: string | null; required_skills: string[]; preferred_skills: string[]; possible_duplicate: boolean }
type Tokens = { access_token: string }
type GmailReview = { id: string; subject: string; sender: string; received_at: string | null; status: string; reason: string; excerpt: string }
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
  const [newSourceType, setNewSourceType] = useState('CAREER_PAGE')
  const [sources, setSources] = useState<Source[]>([]); const [jobs, setJobs] = useState<Job[]>([])
  const [runs, setRuns] = useState<Record<string, Run[]>>({})
  const [search, setSearch] = useState(''); const [location, setLocation] = useState(''); const [workMode, setWorkMode] = useState(''); const [sourceFilter, setSourceFilter] = useState('')
  const [message, setMessage] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const [gmailConnected, setGmailConnected] = useState(false); const [gmailAddress, setGmailAddress] = useState<string | null>(null); const [gmailReviews, setGmailReviews] = useState<GmailReview[]>([])
  const [gmailOAuthConfigured, setGmailOAuthConfigured] = useState(false); const [gmailOAuthConfigurationMessage, setGmailOAuthConfigurationMessage] = useState('')

  useEffect(() => {
    const sync = () => { const raw = sessionStorage.getItem('job-hunt-tokens'); setTokens(raw ? JSON.parse(raw) as Tokens : null) }
    sync(); window.addEventListener('job-hunt-auth', sync)
    return () => window.removeEventListener('job-hunt-auth', sync)
  }, [])

  const loadSources = useCallback(async () => {
    if (!tokens) return
    const response = await api('/sources', tokens.access_token); setSources(await response!.json() as Source[])
  }, [tokens])
  const loadGmail = useCallback(async () => {
    if (!tokens) return
    const [statusResponse, reviewsResponse] = await Promise.all([api('/integrations/gmail/status', tokens.access_token), api('/integrations/gmail/reviews', tokens.access_token)])
    const status = await statusResponse!.json() as { connected: boolean; gmail_address: string | null; oauth_configured?: boolean; oauth_configuration_message?: string | null }
    setGmailConnected(status.connected); setGmailAddress(status.gmail_address)
    setGmailOAuthConfigured(status.oauth_configured === true)
    setGmailOAuthConfigurationMessage(status.oauth_configuration_message || '')
    setGmailReviews(await reviewsResponse!.json() as GmailReview[])
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
  useEffect(() => { if (tokens) void Promise.all([loadSources(), loadJobs(), loadGmail()]).catch(e => setError(e.message)) }, [tokens, loadSources, loadJobs, loadGmail])
  useEffect(() => { const refresh = () => { if (tokens) void loadGmail().catch(e => setError(e.message)) }; window.addEventListener('focus', refresh); return () => window.removeEventListener('focus', refresh) }, [tokens, loadGmail])

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
    try {
      if (sourceType === 'CAREER_PAGE') configuration = JSON.parse(String(form.get('configuration'))) as Record<string, unknown>
      if (sourceType === 'GMAIL_ALERT') configuration = { platform: String(form.get('gmail_platform') || 'GENERIC'), allowed_senders: String(form.get('allowed_senders') || '').split(',').map(value => value.trim()).filter(Boolean), required_terms: String(form.get('required_terms') || '').split(',').map(value => value.trim()).filter(Boolean), label_ids: String(form.get('label_ids') || '').split(',').map(value => value.trim()).filter(Boolean) }
    }
    catch { setError('Configuration must be valid JSON.'); return }
    await runAction(async () => {
      await api('/sources', tokens.access_token, { method: 'POST', body: JSON.stringify({ name: form.get('name'), source_type: sourceType, base_url: form.get('base_url') || null, is_enabled: !['LINKEDIN', 'NAUKRI', 'INSTAHYRE', 'CUTSHORT', 'HIRIST', 'INDEED', 'WELLFOUND', 'FOUNDIT'].includes(sourceType), configuration }) })
      await loadSources()
    }, 'Job source added.')
    element.reset()
    setNewSourceType('CAREER_PAGE')
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
    if (source.source_type === 'GMAIL_ALERT') {
      const senders = prompt('Allowed sender emails (comma separated)', Array.isArray(source.configuration.allowed_senders) ? source.configuration.allowed_senders.join(', ') : '')
      if (senders === null) return
      const platform = prompt('Alert platform (GENERIC, LINKEDIN, NAUKRI, INDEED, INSTAHYRE, CUTSHORT, HIRIST)', String(source.configuration.platform || 'GENERIC'))
      if (platform === null) return
      configuration = { ...source.configuration, platform: platform.trim().toUpperCase(), allowed_senders: senders.split(',').map(value => value.trim()).filter(Boolean) }
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
  async function connectGmail() {
    if (!tokens) return
    const popup = window.open('', 'gmail-oauth', 'popup,width=620,height=760')
    await runAction(async () => {
      try {
        const response = await api('/integrations/gmail/authorize', tokens.access_token, { method: 'POST' })
        const result = await response!.json() as { authorization_url: string }
        if (popup && !popup.closed) popup.location.href = result.authorization_url
        else window.location.href = result.authorization_url
      } catch (cause) {
        if (popup && !popup.closed) popup.close()
        throw cause
      }
    }, 'Complete Google read-only authorization in the opened window, then return here.')
  }
  async function disconnectGmail() {
    if (!tokens || !confirm('Disconnect Gmail read-only access?')) return
    await runAction(async () => { await api('/integrations/gmail/connection', tokens.access_token, { method: 'DELETE' }); await loadGmail() }, 'Gmail disconnected.')
  }
  async function setReviewStatus(review: GmailReview, status: 'REVIEWED' | 'IGNORED') {
    if (!tokens) return
    await runAction(async () => { await api(`/integrations/gmail/reviews/${review.id}`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ status }) }); await loadGmail() }, `Alert marked ${status.toLowerCase()}.`)
  }

  if (!tokens) return null
  return <section className="job-workspace" aria-label="Jobs and sources">
    <div className="feature-tabs"><button className={tab === 'sources' ? 'active' : ''} onClick={() => setTab('sources')}>Job sources</button><button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}>Jobs</button></div>
    {error && <p role="alert" className="notice error">{error}</p>}{message && <p role="status" className="notice">{message}</p>}
    {tab === 'sources' ? <><section className="workflow-panel gmail-panel"><div className="section-heading"><div><h2>Gmail job alerts</h2><p>Read-only access. You authorize Google manually; this app never sends, deletes or modifies email.</p></div><span className={gmailConnected ? 'status status-completed' : 'status'}>{gmailConnected ? `Connected${gmailAddress ? ` · ${gmailAddress}` : ''}` : 'Not connected'}</span></div><div className="source-actions">{gmailConnected ? <button className="secondary" onClick={() => void disconnectGmail()} disabled={busy}>Disconnect Gmail</button> : <button onClick={() => void connectGmail()} disabled={busy || !gmailOAuthConfigured}>Connect Gmail</button>}<button className="secondary" onClick={() => void runAction(loadGmail)} disabled={busy}>Refresh status</button></div>{!gmailConnected && <p className="parse-note" role={gmailOAuthConfigurationMessage ? 'alert' : undefined}>{gmailOAuthConfigurationMessage || 'Connection requires configured Google OAuth credentials and an explicit approval in Google.'}</p>}</section><div className="source-columns"><section><div className="section-heading"><div><h2>Configured sources</h2><p>Public pages and authorized integrations only.</p></div><span>{sources.length}</span></div>{sources.length === 0 && <p className="empty">No sources yet. Add a public company careers page or a source that is awaiting authorized access.</p>}
      {sources.map(source => <article className="source-card" key={source.id}><div className="source-card-head"><div><strong>{source.name}</strong><small>{source.source_type.replaceAll('_', ' ')}</small></div><span className={`status ${source.is_enabled ? 'status-completed' : 'status-failed'}`}>{source.is_enabled ? 'ENABLED' : 'DISABLED'}</span></div><p className="integration-state">{source.integration_status}</p>{source.base_url && <a className="source-url" href={source.base_url} target="_blank" rel="noreferrer">{source.base_url}</a>}<div className="source-times"><span>Last success: {source.last_success_at ? new Date(source.last_success_at).toLocaleString() : 'Never'}</span><span>Last failure: {source.last_failure_at ? new Date(source.last_failure_at).toLocaleString() : 'None'}</span></div><div className="source-actions"><button className="secondary" onClick={() => void inspectSource(source)}>Test</button><button className="secondary" disabled={!source.is_enabled || source.integration_status !== 'CONFIGURED' || busy} onClick={() => void collectSource(source)}>Collect</button><button className="text-button" onClick={() => void editSource(source)}>Edit</button><button className="text-button" onClick={() => void toggleSource(source)}>{source.is_enabled ? 'Disable' : 'Enable'}</button><button className="text-button danger-text" onClick={() => void removeSource(source)}>Delete</button><button className="text-button" onClick={() => void loadRuns(source.id)}>History</button></div>{runs[source.id] && <div className="run-history" aria-label={`${source.name} collection history`}>{runs[source.id].length === 0 ? 'No runs yet.' : runs[source.id].map(run => <p key={run.id}><strong>{run.status}</strong> · {new Date(run.started_at).toLocaleString()} · found {run.jobs_found}, new {run.jobs_created}, updated {run.jobs_updated}, skipped {run.jobs_skipped}{run.error_message && ` · ${run.error_message}`}</p>)}</div>}</article>)}</section>
      <section className="workspace-form"><h2>Add a job source</h2><form onSubmit={createSource}><label>Name<input name="name" required maxLength={120} placeholder="Example Careers" /></label><label>Source type<select name="source_type" value={newSourceType} onChange={event => setNewSourceType(event.target.value)}><option value="CAREER_PAGE">Public company careers page</option><option value="GMAIL_ALERT">Gmail job alert</option>{['LINKEDIN', 'NAUKRI', 'INSTAHYRE', 'CUTSHORT', 'HIRIST', 'INDEED', 'WELLFOUND', 'FOUNDIT'].map(value => <option key={value} value={value}>{value} (authorized feed pending)</option>)}</select></label>{newSourceType === 'CAREER_PAGE' && <><label>Public base URL<input name="base_url" type="url" placeholder="https://company.example/careers" /></label><label>Parsing configuration JSON<textarea name="configuration" rows={9} defaultValue={selectorTemplate} /></label></>}{newSourceType === 'GMAIL_ALERT' && <fieldset className="gmail-source-fields"><legend>Gmail alert settings</legend><label>Alert platform<select name="gmail_platform" defaultValue="GENERIC"><option value="GENERIC">Generic labeled format</option>{['LINKEDIN', 'NAUKRI', 'INDEED', 'INSTAHYRE', 'CUTSHORT', 'HIRIST'].map(value => <option key={value} value={value}>{value} (awaiting sanitized sample)</option>)}</select></label><label>Allowed sender emails<input name="allowed_senders" required placeholder="alerts@example.com, jobs@example.org" /></label><label>Required matching terms, optional<input name="required_terms" placeholder="python, backend" /></label><label>Gmail label IDs, optional<input name="label_ids" placeholder="INBOX, Label_123" /></label><small>Unknown formats are recorded in the review queue. Portal parsers remain inactive until a representative sanitized email format is available.</small></fieldset>}{newSourceType !== 'CAREER_PAGE' && newSourceType !== 'GMAIL_ALERT' && <p className="parse-note">This source type is disabled until official API/feed authorization is available.</p>}<button disabled={busy}>Add source</button><p>Career pages must be publicly accessible and permitted by their robots.txt and terms. Portal entries remain inactive until authorized API/feed access exists.</p></form></section></div><section className="workflow-panel gmail-review"><div className="section-heading"><div><h2>Unrecognized Gmail alerts</h2><p>Alerts that could not be safely parsed are held for your review.</p></div><span>{gmailReviews.length}</span></div>{gmailReviews.length === 0 ? <p className="empty">No alerts need review.</p> : <div className="review-list">{gmailReviews.map(item => <article className="review-card" key={item.id}><div className="review-meta"><div><strong>{item.subject || '(No subject)'}</strong><p>{item.sender} · {item.received_at ? new Date(item.received_at).toLocaleString() : 'Date unavailable'}</p></div><span className="review-status">{item.status.replaceAll('_', ' ')}</span></div><p>{item.reason}</p>{item.excerpt && <details><summary>Review message excerpt</summary><p>{item.excerpt}</p></details>}<div className="review-actions"><button className="secondary" disabled={busy} onClick={() => void setReviewStatus(item, 'REVIEWED')}>Mark reviewed</button><button className="secondary" disabled={busy} onClick={() => void setReviewStatus(item, 'IGNORED')}>Ignore</button></div></article>)}</div>}</section></>
      : <div className="jobs-panel"><section className="filter-panel"><form className="job-filters" onSubmit={event => { event.preventDefault(); void runAction(loadJobs) }}><label>Search<input value={search} onChange={e => setSearch(e.target.value)} placeholder="Title or company" /></label><label>Location<input value={location} onChange={e => setLocation(e.target.value)} placeholder="Chennai, Remote…" /></label><label>Work mode<select value={workMode} onChange={e => setWorkMode(e.target.value)}><option value="">Any mode</option><option value="REMOTE">Remote</option><option value="HYBRID">Hybrid</option><option value="ONSITE">Onsite</option></select></label><label>Source<select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}><option value="">All sources</option>{sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label><button>Apply filters</button></form></section>
        <div className="jobs-columns"><section><div className="section-heading"><div><h2>Job listings</h2><p>Review original listings and apply links yourself.</p></div><span>{jobs.length}</span></div>{jobs.length === 0 ? <p className="empty">No jobs match these filters. Collect from an enabled public source or import a job manually.</p> : jobs.map(job => <article className="job-card" key={job.id}><div className="job-card-head"><div><p className="eyebrow">{job.source_name}</p><h3>{job.title}</h3><p>{job.company_name} · {job.location || 'Location not provided'}{job.work_mode && ` · ${job.work_mode}`}</p></div>{job.possible_duplicate && <span className="status status-needs_ocr">Possible duplicate</span>}</div><div className="job-facts">{job.salary_min !== null && job.salary_min !== undefined && <span>Salary {job.salary_currency} {job.salary_min.toLocaleString()}{job.salary_max ? `–${job.salary_max.toLocaleString()}` : ''} {job.salary_period?.toLowerCase()}</span>}{job.experience_min !== null && job.experience_min !== undefined && <span>Experience {job.experience_min}{job.experience_max !== null ? `–${job.experience_max}` : '+'} months</span>}{job.employment_type && <span>{job.employment_type.replaceAll('_', ' ')}</span>}</div><p className="job-description">{job.description.slice(0, 520)}{job.description.length > 520 ? '…' : ''}</p><div className="skill-tags">{[...job.required_skills.map(skill => `Required · ${skill}`), ...job.preferred_skills.map(skill => `Preferred · ${skill}`)].map(skill => <span key={skill}>{skill}</span>)}</div><div className="job-links">{job.job_url && <a href={job.job_url} target="_blank" rel="noreferrer">Original listing ↗</a>}{job.apply_url && <a href={job.apply_url} target="_blank" rel="noreferrer">Application page ↗</a>}</div></article>)}</section>
          <section className="workspace-form"><h2>Manual job import</h2><form onSubmit={createImport}><label>Job title<input name="title" required maxLength={300} /></label><label>Company<input name="company_name" required maxLength={300} /></label><label>Location<input name="location" /></label><label>Work mode<select name="work_mode" defaultValue=""><option value="">Unknown</option><option value="REMOTE">Remote</option><option value="HYBRID">Hybrid</option><option value="ONSITE">Onsite</option></select></label><label>Employment type<select name="employment_type" defaultValue=""><option value="">Unknown</option><option value="FULL_TIME">Full time</option><option value="PART_TIME">Part time</option><option value="CONTRACT">Contract</option><option value="INTERNSHIP">Internship</option><option value="TEMPORARY">Temporary</option></select></label><label>Minimum experience (months)<input name="experience_min" type="number" min="0" /></label><label>Maximum experience (months)<input name="experience_max" type="number" min="0" /></label><label>Salary minimum<input name="salary_min" type="number" min="0" step="any" /></label><label>Salary maximum<input name="salary_max" type="number" min="0" step="any" /></label><label>Salary currency<select name="salary_currency" defaultValue=""><option value="">Unknown</option><option>INR</option><option>USD</option><option>EUR</option><option>GBP</option></select></label><label>Salary period<select name="salary_period" defaultValue=""><option value="">Unknown</option><option value="ANNUAL">Annual</option><option value="MONTHLY">Monthly</option><option value="HOURLY">Hourly</option></select></label><label>Required skills<input name="required_skills" placeholder="Python, PostgreSQL" /></label><label>Preferred skills<input name="preferred_skills" placeholder="Docker, Kubernetes" /></label><label>Job description<textarea name="description" rows={6} /></label><label>Job URL<input name="job_url" type="url" placeholder="https://…" /></label><label>Application URL<input name="apply_url" type="url" placeholder="https://…" /></label><button disabled={busy}>Save job</button><p>URLs are validated but never fetched by the server.</p></form></section></div></div>}
  </section>
}
