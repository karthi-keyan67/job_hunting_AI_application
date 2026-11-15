import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import AutomationWorkspace from './AutomationWorkspace'
import JobPreferencesWorkspace from './JobPreferencesWorkspace'
import JobPortalConnections from './JobPortalConnections'

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
const stages = ['SAVED', 'PREPARING', 'READY_FOR_REVIEW', 'READY_TO_APPLY', 'APPLIED', 'ASSESSMENT', 'INTERVIEW', 'OFFER', 'REJECTED', 'WITHDRAWN', 'ACCEPTED']
type Tokens = { access_token: string }
type Summary = Record<string, any>
type AppItem = Record<string, any>

async function request(path: string, token: string, init: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } })
  if (!response.ok) { const value = await response.json().catch(() => ({})); const detail = value.detail; throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status})`) }
  return response.status === 204 ? null : response
}
const json = async (response: Response | null) => response ? response.json() : null
const label = (value: string) => value.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, char => char.toUpperCase())
const localDateTime = (value: string) => { const date = new Date(value); const offset = date.getTimezoneOffset() * 60000; return new Date(date.getTime() - offset).toISOString().slice(0, 16) }

export default function Phase7Workspace() {
  const [tokens, setTokens] = useState<Tokens | null>(null)
  const [section, setSection] = useState(() => window.location.hash === '#job-preferences' ? 'Job Preferences' : window.location.hash === '#job-portal-connections' ? 'Job Portal Connections' : 'Dashboard')
  const [summary, setSummary] = useState<Summary | null>(null)
  const [pipeline, setPipeline] = useState<AppItem[]>([])
  const [apps, setApps] = useState<AppItem[]>([])
  const [upcoming, setUpcoming] = useState<any[]>([])
  const [interviews, setInterviews] = useState<any[]>([])
  const [selectedInterviews, setSelectedInterviews] = useState<any[]>([])
  const [followUps, setFollowUps] = useState<any[]>([])
  const [analytics, setAnalytics] = useState<any | null>(null)
  const [selected, setSelected] = useState<AppItem | null>(null)
  const [timeline, setTimeline] = useState<any[]>([])
  const [notes, setNotes] = useState('')
  const [filters, setFilters] = useState(() => { const query = new URLSearchParams(window.location.search); return { search: query.get('search') || '', status: query.get('status') || '', location: query.get('location') || '', work_mode: query.get('work_mode') || '', date_from: query.get('date_from') || '', date_to: query.get('date_to') || '', sort_by: query.get('sort_by') || 'updated', offset: Number(query.get('offset') || 0) } })
  const [pageTotal, setPageTotal] = useState(0)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { const sync = () => { const saved = sessionStorage.getItem('job-hunt-tokens'); setTokens(saved ? JSON.parse(saved) as Tokens : null) }; sync(); window.addEventListener('job-hunt-auth', sync); return () => window.removeEventListener('job-hunt-auth', sync) }, [])
  const run = useCallback(async (action: () => Promise<void>, message?: string) => {
    setBusy(true); setError(''); setNotice('')
    try { await action(); if (message) setNotice(message) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Request failed') } finally { setBusy(false) }
  }, [])
  function navigateSection(item: string) {
    setSection(item)
    if (item === 'Job Preferences') window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#job-preferences`)
    else if (item === 'Job Portal Connections') window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#job-portal-connections`)
    else if (window.location.hash) window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  }

  const loadDashboard = useCallback(async (start = startDate, end = endDate) => {
    if (!tokens) return
    const params = new URLSearchParams(); if (start) params.set('start_date', start); if (end) params.set('end_date', end)
    setSummary(await json(await request(`/dashboard/summary?${params}`, tokens.access_token)))
    setUpcoming(await json(await request('/dashboard/upcoming?limit=12', tokens.access_token)) || [])
  }, [tokens, startDate, endDate])
  const loadPipeline = useCallback(async (nextFilters = filters) => {
    if (!tokens) return
    const params = new URLSearchParams({ offset: String(nextFilters.offset), limit: '30', sort_by: nextFilters.sort_by })
    for (const key of ['search', 'status', 'location', 'work_mode', 'date_from', 'date_to'] as const) if (nextFilters[key]) params.set(key, nextFilters[key])
    const result = await json(await request(`/dashboard/pipeline?${params}`, tokens.access_token))
    setPipeline(result.items || []); setPageTotal(result.total || 0)
  }, [tokens, filters])
  const loadTracking = useCallback(async () => {
    if (!tokens) return
    const [applications, interviewResponse, followupResponse] = await Promise.all([
      request('/applications', tokens.access_token), request('/interviews?limit=100', tokens.access_token), request('/follow-ups?limit=100', tokens.access_token),
    ])
    setApps(await json(applications) || []); setInterviews((await json(interviewResponse))?.items || []); setFollowUps((await json(followupResponse))?.items || [])
  }, [tokens])
  const loadAnalytics = useCallback(async (start = startDate, end = endDate) => {
    if (!tokens) return
    const params = new URLSearchParams(); if (start) params.set('start_date', start); if (end) params.set('end_date', end)
    setAnalytics(await json(await request(`/analytics/overview?${params}`, tokens.access_token)))
  }, [tokens, startDate, endDate])
  useEffect(() => { if (!tokens) return; void Promise.all([loadDashboard(), loadPipeline(), loadTracking()]).catch(cause => setError(cause.message)) }, [tokens, loadDashboard, loadPipeline, loadTracking])
  useEffect(() => { if (tokens && section === 'Analytics') void loadAnalytics().catch(cause => setError(cause.message)) }, [tokens, section, loadAnalytics])
  const displayStages = useMemo(() => stages.map(stage => ({ stage, items: pipeline.filter(item => item.status === stage) })), [pipeline])

  async function selectApplication(item: AppItem) {
    if (!tokens) return
    await run(async () => {
      const [detail, result, interviewResult] = await Promise.all([request(`/applications/${item.id}`, tokens.access_token), request(`/applications/${item.id}/timeline`, tokens.access_token), request(`/interviews?application_id=${item.id}&limit=100`, tokens.access_token)])
      const value = await json(detail); setSelected(value); setNotes(value.notes || ''); setTimeline((await json(result)).timeline || []); setSelectedInterviews((await json(interviewResult)).items || [])
    })
  }
  async function updateStatus(item: AppItem, next: string) {
    if (!tokens || next === item.status) return
    await run(async () => { await request(`/applications/${item.id}/status`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ status: next }) }); await Promise.all([loadPipeline(), loadDashboard()]); if (selected?.id === item.id) await selectApplication(item) }, 'Application status updated.')
  }
  async function saveNotes(event: FormEvent) {
    event.preventDefault(); if (!tokens || !selected) return
    await run(async () => { await request(`/applications/${selected.id}/notes`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ notes }) }); await selectApplication(selected) }, 'Private notes saved.')
  }
  async function filterPipeline(event: FormEvent) {
    event.preventDefault(); const next = { ...filters, offset: 0 }; setFilters(next)
    const params = new URLSearchParams(); Object.entries(next).forEach(([key, value]) => { if (value !== '' && value !== 0) params.set(key, String(value)) }); window.history.replaceState(null, '', `${location.pathname}?${params}`)
    await run(() => loadPipeline(next))
  }
  async function createInterview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!tokens) return
    const formElement = event.currentTarget; const form = new FormData(formElement); const scheduled = String(form.get('scheduled_at'))
    await run(async () => { await request('/interviews', tokens.access_token, { method: 'POST', body: JSON.stringify({ application_id: form.get('application_id'), interview_type: form.get('interview_type'), scheduled_at: new Date(scheduled).toISOString(), timezone: form.get('timezone'), meeting_url: form.get('meeting_url') || null, interviewer_name: form.get('interviewer_name') || null, notes: form.get('notes') || null }) }); await Promise.all([loadTracking(), loadDashboard()]) }, 'Interview scheduled.')
    formElement.reset()
  }
  async function editInterview(item: any) {
    if (!tokens) return
    const interview_type = prompt('Interview type', item.interview_type); if (interview_type === null) return
    const time = prompt('Interview date and time (local)', localDateTime(item.scheduled_at)); if (!time) return
    const timezone = prompt('Timezone (IANA name)', item.timezone); if (timezone === null) return
    const meeting_url = prompt('Meeting URL (blank to clear)', item.meeting_url || ''); if (meeting_url === null) return
    const interviewer_name = prompt('Interviewer name (blank to clear)', item.interviewer_name || ''); if (interviewer_name === null) return
    const notes = prompt('Interview notes (blank to clear)', item.notes || ''); if (notes === null) return
    await run(async () => { await request(`/interviews/${item.id}`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ interview_type, scheduled_at: new Date(time).toISOString(), timezone, meeting_url: meeting_url || null, interviewer_name: interviewer_name || null, notes: notes || null }) }); await Promise.all([loadTracking(), loadDashboard()]) }, 'Interview updated.')
  }
  async function completeInterview(item: any) { if (!tokens) return; await run(async () => { await request(`/interviews/${item.id}`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ status: 'COMPLETED' }) }); await Promise.all([loadTracking(), loadDashboard()]) }, 'Interview marked completed.') }
  async function cancelInterview(item: any) { if (!tokens) return; await run(async () => { await request(`/interviews/${item.id}`, tokens.access_token, { method: 'DELETE' }); await Promise.all([loadTracking(), loadDashboard()]) }, 'Interview cancelled.') }
  async function createFollowUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!tokens) return
    const formElement = event.currentTarget; const form = new FormData(formElement)
    await run(async () => { await request('/follow-ups', tokens.access_token, { method: 'POST', body: JSON.stringify({ application_id: form.get('application_id'), title: form.get('title'), description: form.get('description') || null, due_at: new Date(String(form.get('due_at'))).toISOString(), timezone: form.get('timezone') }) }); await Promise.all([loadTracking(), loadDashboard()]) }, 'Follow-up added.')
    formElement.reset()
  }
  async function updateFollowup(item: any, status: string) { if (!tokens) return; await run(async () => { await request(`/follow-ups/${item.id}`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ status }) }); await Promise.all([loadTracking(), loadDashboard()]) }, status === 'COMPLETED' ? 'Follow-up completed.' : 'Follow-up cancelled.') }

  if (!tokens) return <section className="phase7-shell"><p className="empty">Sign in to view your dashboard and application tracking.</p></section>
  const metricCards = summary ? [
    ['Jobs discovered', summary.total_jobs_discovered], ['New jobs in range', summary.new_jobs], ['Strong matches', summary.strong_matches],
    ['Pending review', summary.jobs_pending_review], ['Approved for preparation', summary.jobs_approved_for_preparation],
    ['In preparation', summary.applications_in_preparation], ['Ready to apply', summary.ready_to_apply_applications],
    ['Submitted', summary.submitted_applications], ['Interviews', summary.interviews], ['Offers', summary.offers], ['Rejected', summary.rejected_applications],
  ] : []
  return <section className="phase7-shell" aria-label="Dashboard and application tracking">
    <header className="phase7-heading"><div><p className="eyebrow">YOUR JOB SEARCH</p><h2>Dashboard &amp; application tracking</h2><p>Live counts and records from your account.</p></div><nav className="phase7-nav">{['Dashboard', 'Pipeline', 'Interviews', 'Follow-ups', 'Analytics', 'Automation', 'Job Preferences', 'Job Portal Connections'].map(item => <button key={item} className={section === item ? 'active' : 'secondary'} onClick={() => navigateSection(item)}>{item}</button>)}</nav></header>
    {error && <p role="alert" className="phase7-error">{error}</p>}{notice && <p role="status" className="phase7-notice">{notice}</p>}
    {section === 'Dashboard' && <>
      <form className="phase7-filters" onSubmit={event => { event.preventDefault(); void run(() => loadDashboard(startDate, endDate)) }}><label>From <input type="date" value={startDate} onChange={event => setStartDate(event.target.value)} /></label><label>To <input type="date" value={endDate} onChange={event => setEndDate(event.target.value)} /></label><button disabled={busy}>Apply date range</button><span>Application stages show current records created in this range; total jobs discovered is lifetime.</span></form>
      <div className="phase7-kpis">{metricCards.map(([name, value]) => <article key={name}><span>{name}</span><strong>{value ?? 0}</strong></article>)}</div>
      <div className="phase7-columns"><article className="phase7-panel"><header><h3>Recent activity</h3><button className="text-button" onClick={() => setSection('Pipeline')}>Open pipeline →</button></header>{summary?.recent_activity?.length ? <ol className="phase7-activity">{summary.recent_activity.map((item: any) => <li key={item.id}><strong>{label(item.action)}</strong><span>{item.company_name ? `${item.job_title} · ${item.company_name}` : item.job_title || 'Job review'}</span><time>{new Date(item.occurred_at).toLocaleString()}</time></li>)}</ol> : <p className="empty">No recorded activity yet.</p>}</article>
      <article className="phase7-panel"><header><h3>Upcoming interviews &amp; follow-ups</h3><button className="text-button" onClick={() => setSection('Interviews')}>Manage →</button></header>{upcoming.length ? <ul className="phase7-list">{upcoming.map(item => <li key={`${item.kind}-${item.id}`}><span className="phase7-tag">{label(item.kind)}{item.overdue ? ' · Overdue' : ''}</span><strong>{item.title}</strong><time>{new Date(item.scheduled_at).toLocaleString(undefined, { timeZone: item.timezone })} · {item.timezone}</time></li>)}</ul> : <p className="empty">Nothing scheduled. Add an interview or follow-up from its workspace.</p>}</article></div>
      <article className="phase7-panel"><header><h3>Recent matching results</h3><button className="text-button" onClick={() => document.getElementById('matches-workspace')?.scrollIntoView({ behavior: 'smooth' })}>Open matching →</button></header>{summary?.recent_matching_results?.length ? <div className="phase7-match-row">{summary.recent_matching_results.map((item: any) => <div key={item.id}><strong>{item.title}</strong><span>{item.company_name} · {item.location || 'Location unknown'} · {Math.round(item.overall_score)}% match</span></div>)}</div> : <p className="empty">No matching results available yet.</p>}</article>
      <div className="phase7-quicklinks">{[['Pipeline', 'Review application stages'], ['Interviews', 'Plan interview rounds'], ['Follow-ups', 'Track next actions'], ['Analytics', 'Explore search metrics']].map(([item, description]) => <button key={item} onClick={() => setSection(item)}><strong>{item} →</strong><span>{description}</span></button>)}</div>
    </>}
    {section === 'Pipeline' && <>
      <form className="phase7-filters" onSubmit={filterPipeline}><label>Company or role<input value={filters.search} onChange={event => setFilters({ ...filters, search: event.target.value })} /></label><label>Status<select value={filters.status} onChange={event => setFilters({ ...filters, status: event.target.value })}><option value="">All statuses</option>{stages.map(stage => <option key={stage} value={stage}>{label(stage)}</option>)}</select></label><label>Date applied from<input type="date" value={filters.date_from} onChange={event => setFilters({ ...filters, date_from: event.target.value })} /></label><label>Date applied to<input type="date" value={filters.date_to} onChange={event => setFilters({ ...filters, date_to: event.target.value })} /></label><label>Location<input value={filters.location} onChange={event => setFilters({ ...filters, location: event.target.value })} /></label><label>Work mode<select value={filters.work_mode} onChange={event => setFilters({ ...filters, work_mode: event.target.value })}><option value="">Any</option><option>REMOTE</option><option>HYBRID</option><option>ONSITE</option></select></label><label>Sort<select value={filters.sort_by} onChange={event => setFilters({ ...filters, sort_by: event.target.value })}><option value="updated">Recently updated</option><option value="created">Recently created</option><option value="company">Company</option><option value="title">Role</option></select></label><button disabled={busy}>Filter</button></form>
      <p className="phase7-count">{pageTotal} applications · page {Math.floor(filters.offset / 30) + 1}</p>
      {pipeline.length ? <div className="phase7-board">{displayStages.map(({ stage, items }) => <section className="phase7-lane" key={stage}><h3>{label(stage)} <span>{items.length}</span></h3>{items.map(item => <article className="phase7-app-card" key={item.id}><button className="phase7-app-open" onClick={() => void selectApplication(item)}><strong>{item.job.title}</strong><span>{item.job.company_name}</span><small>{item.match_score == null ? 'Match n/a' : `${Math.round(item.match_score)}% match`} · Updated {new Date(item.updated_at).toLocaleDateString()}</small></button><select aria-label={`Status for ${item.job.title}`} value={item.status} disabled={busy || ['READY_TO_APPLY', 'APPLIED'].includes(item.status)} onChange={event => void updateStatus(item, event.target.value)}><option value={item.status}>{label(item.status)}</option>{stages.filter(next => next !== item.status && !['READY_TO_APPLY', 'APPLIED'].includes(next)).map(next => <option value={next} key={next}>{label(next)}</option>)}</select></article>)}</section>)}</div> : <p className="empty">No applications match these filters.</p>}
      <div className="phase7-pagination"><button className="secondary" disabled={filters.offset === 0} onClick={() => { const next = { ...filters, offset: Math.max(0, filters.offset - 30) }; setFilters(next); void loadPipeline(next) }}>Previous</button><button className="secondary" disabled={filters.offset + 30 >= pageTotal} onClick={() => { const next = { ...filters, offset: filters.offset + 30 }; setFilters(next); void loadPipeline(next) }}>Next</button></div>
      {selected && <article className="phase7-panel phase7-detail"><header><div><p className="eyebrow">APPLICATION DETAILS</p><h3>{selected.job.title} · {selected.job.company_name}</h3></div><button className="secondary" onClick={() => setSelected(null)}>Close</button></header><div className="phase7-detail-grid"><p><b>Status:</b> {label(selected.status)}</p><p><b>Updated:</b> {new Date(selected.updated_at).toLocaleString()}</p><p><b>Match:</b> {selected.match_score == null ? 'Not available' : `${Math.round(selected.match_score)}%`}</p><p><b>Resume:</b> {selected.resume_version ? `${selected.resume_version.title} · v${selected.resume_version.version_number}` : 'Not selected'}</p></div><p><b>Location:</b> {selected.job.location || 'Not provided'} · {selected.job.work_mode || 'Work mode unknown'}</p><p>{selected.job.description}</p><p><a href={selected.job.job_url} target="_blank" rel="noreferrer">Original job listing ↗</a></p><p><b>Approved document versions:</b> {selected.approved_documents?.length ? selected.approved_documents.map((draft: any) => `${label(draft.draft_type)} v${draft.version_number}`).join(' · ') : 'None recorded'}</p><details><summary>Checklist snapshot</summary><pre>{JSON.stringify(selected.checklist || {}, null, 2)}</pre></details><form onSubmit={saveNotes}><label className="phase7-notes">Private notes<textarea value={notes} onChange={event => setNotes(event.target.value)} maxLength={20000} /></label><button disabled={busy}>Save notes</button></form><h4>Interview history</h4>{selectedInterviews.length ? <ul className="phase7-list">{selectedInterviews.map(item => <li key={item.id}><strong>{item.interview_type} · {label(item.status)}</strong><time>{new Date(item.scheduled_at).toLocaleString(undefined, { timeZone: item.timezone })} · {item.timezone}</time>{item.meeting_url && <a href={item.meeting_url} target="_blank" rel="noreferrer">Meeting link ↗</a>}{item.notes && <p>{item.notes}</p>}</li>)}</ul> : <p>No interview records yet.</p>}<h4>Timeline</h4>{timeline.length ? <ol className="phase7-timeline">{timeline.map(item => <li key={item.id}><strong>{label(item.event)}</strong><time>{new Date(item.occurred_at).toLocaleString()}</time></li>)}</ol> : <p>No historical events recorded.</p>}<button className="secondary" onClick={() => setSection('Interviews')}>Interview planning</button></article>}
    </>}
    {section === 'Interviews' && <div className="phase7-columns"><article className="phase7-panel"><h3>Schedule an interview</h3>{apps.length ? <form className="phase7-form" onSubmit={createInterview}><label>Application<select required name="application_id"><option value="">Choose an application</option>{apps.map(item => <option value={item.id} key={item.id}>{item.job.title} · {item.job.company_name}</option>)}</select></label><label>Interview type<input required name="interview_type" placeholder="Recruiter screen, technical…" /></label><label>Date and time<input required type="datetime-local" name="scheduled_at" /></label><label>Timezone<input name="timezone" defaultValue="Asia/Kolkata" /></label><label>Meeting URL<input type="url" name="meeting_url" placeholder="https://…" /></label><label>Interviewer<input name="interviewer_name" /></label><label>Notes<textarea name="notes" /></label><button disabled={busy}>Add interview</button></form> : <p className="empty">Create an application from an approved job to schedule an interview.</p>}</article><article className="phase7-panel"><h3>Upcoming and past interviews</h3>{interviews.length ? <ul className="phase7-list">{interviews.map(item => <li key={item.id}><span className="phase7-tag">{label(item.status)}{new Date(item.scheduled_at) < new Date() ? ' · Past' : ' · Upcoming'}</span><strong>{item.interview_type} · {apps.find(application => application.id === item.application_id)?.job.company_name || 'Company'}</strong><span>{apps.find(application => application.id === item.application_id)?.job.title || 'Application'}</span><time>{new Date(item.scheduled_at).toLocaleString(undefined, { timeZone: item.timezone })} · {item.timezone}</time>{item.interviewer_name && <span>{item.interviewer_name}</span>}{item.meeting_url && <a href={item.meeting_url} target="_blank" rel="noreferrer">Meeting link ↗</a>}{item.notes && <p>{item.notes}</p>}{item.status !== 'CANCELLED' && <div className="phase7-actions"><button className="secondary" onClick={() => void editInterview(item)}>Edit interview</button>{item.status === 'SCHEDULED' && <button onClick={() => void completeInterview(item)}>Mark completed</button>}<button className="secondary" onClick={() => void cancelInterview(item)}>Cancel</button></div>}</li>)}</ul> : <p className="empty">No interviews scheduled.</p>}</article></div>}
    {section === 'Follow-ups' && <div className="phase7-columns"><article className="phase7-panel"><h3>Add a follow-up</h3>{apps.length ? <form className="phase7-form" onSubmit={createFollowUp}><label>Application<select required name="application_id"><option value="">Choose an application</option>{apps.map(item => <option value={item.id} key={item.id}>{item.job.title} · {item.job.company_name}</option>)}</select></label><label>Title<input required name="title" /></label><label>Description<textarea name="description" /></label><label>Due date and time<input required type="datetime-local" name="due_at" /></label><label>Timezone<input name="timezone" defaultValue="Asia/Kolkata" /></label><button disabled={busy}>Add follow-up</button></form> : <p className="empty">Create an application before adding follow-ups.</p>}</article><article className="phase7-panel"><h3>Follow-up manager</h3>{followUps.length ? <ul className="phase7-list">{followUps.map(item => <li key={item.id}><span className="phase7-tag">{label(item.status)}{item.status === 'PENDING' && new Date(item.due_at) < new Date() ? ' · Overdue' : ''}</span><strong>{item.title}</strong><p>{item.description}</p><time>Due {new Date(item.due_at).toLocaleString(undefined, { timeZone: item.timezone })} · {item.timezone}</time>{item.status === 'PENDING' && <div className="phase7-actions"><button onClick={() => void updateFollowup(item, 'COMPLETED')}>Complete</button><button className="secondary" onClick={() => void updateFollowup(item, 'CANCELLED')}>Cancel</button></div>}</li>)}</ul> : <p className="empty">No follow-ups recorded.</p>}</article></div>}
    {section === 'Analytics' && <><form className="phase7-filters" onSubmit={event => { event.preventDefault(); void run(() => loadAnalytics(startDate, endDate)) }}><label>From <input type="date" value={startDate} onChange={event => setStartDate(event.target.value)} /></label><label>To <input type="date" value={endDate} onChange={event => setEndDate(event.target.value)} /></label><button disabled={busy}>Apply date range</button></form>{analytics && <><div className="phase7-kpis"><article><span>Applications in range</span><strong>{analytics.application_count}</strong></article><article><span>Interview conversion</span><strong>{analytics.interview_conversion.percentage == null ? 'Sample too small' : `${analytics.interview_conversion.percentage}%`}</strong><small>{analytics.interview_conversion.numerator} / {analytics.interview_conversion.denominator} records</small></article><article><span>Offer conversion</span><strong>{analytics.offer_conversion.percentage == null ? 'Sample too small' : `${analytics.offer_conversion.percentage}%`}</strong><small>{analytics.offer_conversion.numerator} / {analytics.offer_conversion.denominator} records</small></article></div><div className="phase7-columns">{[['Applications by status', analytics.applications_by_status], ['Match score bands', analytics.match_distribution]].map(([title, values]) => <article className="phase7-panel" key={String(title)}><h3>{title}</h3>{Object.entries(values as Record<string, number>).length ? Object.entries(values as Record<string, number>).map(([name, count]) => <div className="phase7-bar" key={name}><span>{label(name)}</span><strong>{count}</strong><i style={{ width: `${Math.max(4, Number(count) / Math.max(1, ...Object.values(values as Record<string, number>)) * 100)}%` }} /></div>) : <p className="empty">No records in this range.</p>}</article>)}
      <article className="phase7-panel"><h3>Applications over time</h3>{analytics.applications_over_time.length ? analytics.applications_over_time.map((item: any) => <div className="phase7-bar" key={item.period}><span>{item.period}</span><strong>{item.count}</strong><i style={{ width: `${Math.max(4, item.count / Math.max(1, ...analytics.applications_over_time.map((x: any) => x.count)) * 100)}%` }} /></div>) : <p className="empty">No application records in this range.</p>}</article>
      <article className="phase7-panel"><h3>Jobs collected over time</h3>{analytics.jobs_collected_over_time.length ? analytics.jobs_collected_over_time.map((item: any) => <div className="phase7-bar" key={item.period}><span>{item.period}</span><strong>{item.count}</strong><i style={{ width: `${Math.max(4, item.count / Math.max(1, ...analytics.jobs_collected_over_time.map((x: any) => x.count)) * 100)}%` }} /></div>) : <p className="empty">No collected jobs in this range.</p>}</article>
      <article className="phase7-panel"><h3>Application source distribution</h3>{analytics.source_distribution.length ? analytics.source_distribution.map((item: any) => <div className="phase7-bar" key={item.source}><span>{item.source}</span><strong>{item.count}</strong></div>) : <p className="empty">No application sources in this range.</p>}</article></div></>}</>}
    {section === 'Automation' && tokens && <AutomationWorkspace token={tokens.access_token} />}
    {section === 'Job Preferences' && tokens && <JobPreferencesWorkspace token={tokens.access_token} request={request} />}
    {section === 'Job Portal Connections' && tokens && <JobPortalConnections token={tokens.access_token} request={request} />}
  </section>
}
