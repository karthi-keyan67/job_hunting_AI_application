import { useCallback, useEffect, useMemo, useState } from 'react'

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
const checklistLabels: Record<string, string> = {
  job_details_verified: 'Job details verified', company_verified: 'Company verified', application_url_verified: 'Application URL verified',
  selected_resume_reviewed: 'Selected resume reviewed', tailored_resume_reviewed: 'Tailored resume reviewed',
  cover_letter_reviewed: 'Cover letter reviewed or not required', application_answers_reviewed: 'Application answers reviewed',
  expected_salary_confirmed: 'Expected salary confirmed', notice_period_confirmed: 'Notice period confirmed', personal_information_confirmed: 'Personal information confirmed',
}
type TokenState = { access_token: string }
type Review = { id: string; job_id: string; status: string; match: any; rejection_reason?: string | null; history: any[] }
type Draft = { id: string; draft_type: string; version_number: number; body: string; status: string; generation_model?: string | null; evidence: string[]; created_at: string }
type Application = { id: string; job_id: string; resume_version_id: string; status: string; submitted_at?: string | null; job: any }
type ChecklistState = { items: Record<string, { completed?: boolean; not_applicable_reason?: string | null }>; required_items: string[] }

async function request(path: string, token: string, init: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } })
  if (!response.ok) { const result = await response.json().catch(() => ({})); const detail = result.detail; throw new Error(typeof detail === 'string' ? detail : detail?.message || `Request failed (${response.status})`) }
  return response.status === 204 ? null : response
}

export default function ApplicationWorkflow() {
  const [tokens, setTokens] = useState<TokenState | null>(() => { const saved = sessionStorage.getItem('job-hunt-tokens'); return saved ? JSON.parse(saved) as TokenState : null })
  const [reviews, setReviews] = useState<Review[]>([]); const [applications, setApplications] = useState<Application[]>([])
  const [resumes, setResumes] = useState<any[]>([]); const [versionId, setVersionId] = useState(''); const [selected, setSelected] = useState('')
  const [drafts, setDrafts] = useState<Draft[]>([]); const [checklist, setChecklist] = useState<ChecklistState>({ items: {}, required_items: [] })
  const [audit, setAudit] = useState<any[]>([]); const [rejectReason, setRejectReason] = useState(''); const [context, setContext] = useState({ expected_salary: '', notice_period: '' })
  const [notApplicableReasons, setNotApplicableReasons] = useState<Record<string, string>>({}); const [statusSelection, setStatusSelection] = useState('')
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('')

  useEffect(() => { const sync = () => { const saved = sessionStorage.getItem('job-hunt-tokens'); setTokens(saved ? JSON.parse(saved) as TokenState : null) }; window.addEventListener('job-hunt-auth', sync); return () => window.removeEventListener('job-hunt-auth', sync) }, [])

  const load = useCallback(async (active = tokens) => {
    if (!active) return
    const [reviewResponse, applicationResponse, resumeResponse] = await Promise.all([request('/job-reviews', active.access_token), request('/applications', active.access_token), request('/resumes', active.access_token)])
    setReviews(await reviewResponse!.json() as Review[]); setApplications(await applicationResponse!.json() as Application[])
    const rows = await resumeResponse!.json() as any[]; setResumes(rows)
    const first = rows.find(row => row.is_default) || rows[0]; const version = first?.versions.find((item: any) => item.parsing_status === 'COMPLETED') || first?.versions[0]
    setVersionId(old => old || version?.id || '')
  }, [tokens])
  useEffect(() => { if (tokens) void load().catch(e => setError(e.message)) }, [tokens, load])
  async function loadApplication(id: string) {
    if (!tokens) return
    const [draftResponse, checklistResponse, auditResponse] = await Promise.all([request(`/applications/${id}/drafts`, tokens.access_token), request(`/applications/${id}/checklist`, tokens.access_token), request(`/applications/${id}/audit`, tokens.access_token)])
    setDrafts(await draftResponse!.json() as Draft[]); setChecklist(await checklistResponse!.json() as ChecklistState); setAudit(await auditResponse!.json() as any[])
  }
  async function act(callback: () => Promise<void>, success?: string) {
    setBusy(true); setError(''); setNotice('')
    try { await callback(); if (success) setNotice(success) } catch (e) { setError(e instanceof Error ? e.message : 'Request failed') } finally { setBusy(false) }
  }
  async function reviewAction(jobId: string, action: string) {
    if (!tokens) return
    await act(async () => { await request(`/job-reviews/${jobId}/${action}`, tokens.access_token, { method: 'POST', body: action === 'reject' ? JSON.stringify({ reason: rejectReason || null }) : undefined }); await load() }, `Job ${action === 'approve' ? 'approved for preparation' : action === 'save' ? 'saved' : 'rejected'}.`)
  }
  async function createApplication(review: Review) {
    if (!tokens || !versionId) { setError('Select a resume version before creating an application.'); return }
    await act(async () => { const response = await request('/applications', tokens.access_token, { method: 'POST', body: JSON.stringify({ job_id: review.job_id, resume_version_id: versionId, job_match_id: review.match.id }) }); const row = await response!.json() as Application; await load(); setSelected(row.id); await loadApplication(row.id) }, 'Application preparation workspace created.')
  }
  async function selectApplication(id: string) { setSelected(id); setStatusSelection(applications.find(item => item.id === id)?.status || ''); await act(() => loadApplication(id)) }
  async function updateApplicationStatus(status: string) {
    if (!tokens || !selected || !status) return
    await act(async () => { await request(`/applications/${selected}/status`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ status }) }); await load(); await loadApplication(selected) }, 'Application status updated and recorded.')
  }
  async function generate(regenerate = false) {
    if (!tokens || !selected) return
    await act(async () => { await request(`/applications/${selected}/${regenerate ? 'regenerate' : 'generate'}`, tokens.access_token, { method: 'POST', body: JSON.stringify({ draft_types: ['TAILORED_RESUME', 'COVER_LETTER', 'RECRUITER_MESSAGE', 'APPLICATION_ANSWERS'], user_context: context }) }); await loadApplication(selected); await load() }, regenerate ? 'New draft versions generated; review them before approval.' : 'Drafts generated; review every document before approval.')
  }
  async function saveChecklist(key: string, value: { completed?: boolean; not_applicable_reason?: string | null }) {
    if (!tokens || !selected) return
    await act(async () => { const response = await request(`/applications/${selected}/checklist`, tokens.access_token, { method: 'PUT', body: JSON.stringify({ items: { [key]: value } }) }); setChecklist(await response!.json() as ChecklistState); await loadApplication(selected) })
  }
  async function openApplicationSite() {
    if (!tokens || !selected) return
    const popup = window.open('about:blank', '_blank')
    if (popup) popup.opener = null
    if (!popup) { setError('Allow pop-ups to open the verified application page.'); return }
    await act(async () => { const response = await request(`/applications/${selected}/open-url`, tokens.access_token, { method: 'POST' }); const result = await response!.json() as { url: string; reminder: string }; popup.location.href = result.url; setNotice(result.reminder); await loadApplication(selected) })
  }
  const current = applications.find(item => item.id === selected)
  const versions = useMemo(() => resumes.flatMap(resume => resume.versions.map((version: any) => ({ ...version, resumeTitle: resume.title }))), [resumes])
  if (!tokens) return null

  return <section className="application-workflow" aria-label="Application preparation workflow">
    <header className="workflow-heading"><div><p className="eyebrow">PHASE 6 · HUMAN APPROVAL REQUIRED</p><h2>Review and prepare applications</h2><p>Approval permits document preparation. You open the employer site and submit every application yourself.</p></div></header>
    {error && <p role="alert" className="notice error">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    <section className="workflow-panel" aria-label="Job review"><div className="section-heading"><div><h3>Matched jobs to review</h3><p>Review status is separate from application status.</p></div><label>Resume version<select aria-label="Application resume version" value={versionId} onChange={event => setVersionId(event.target.value)}><option value="">Choose resume</option>{versions.map(version => <option key={version.id} value={version.id}>{version.resumeTitle} · v{version.version_number}</option>)}</select></label></div>
      {reviews.length === 0 ? <p className="empty">Run job matching first to review opportunities.</p> : <div className="review-list">{reviews.map(review => <article className="review-card" key={review.id}><div className="review-meta"><div><p className="eyebrow">{review.match.job.company_name} · {review.match.job.location || 'Location not provided'}</p><h4>{review.match.job.title}</h4><p>{review.match.overall_score.toFixed(0)}% match · {review.match.confidence.toFixed(0)}% confidence</p></div><span className="review-status">{review.status.replaceAll('_', ' ')}</span></div><p>{review.match.explanation}</p><div className="skill-tags">{review.match.matched_skills.map((skill: string) => <span key={skill}>Strength · {skill}</span>)}{review.match.missing_required_skills.map((skill: string) => <span className="missing-skill" key={skill}>Missing · {skill}</span>)}</div>{review.match.ai_analysis?.explanation && <p>{review.match.ai_analysis.explanation}</p>}<div className="review-actions"><button onClick={() => void reviewAction(review.job_id, 'approve')} disabled={busy}>Approve preparation</button><button className="secondary" onClick={() => void reviewAction(review.job_id, 'save')} disabled={busy}>Save</button><button className="secondary danger-button" onClick={() => void reviewAction(review.job_id, 'reject')} disabled={busy}>Reject</button>{review.status === 'APPROVED_FOR_PREPARATION' && <button className="secondary" onClick={() => void createApplication(review)} disabled={busy || !versionId}>Create application</button>}</div>{review.status === 'REJECTED' && <p className="parse-note">{review.rejection_reason || 'No reason provided.'}</p>}</article>)}</div>}
      <label className="reject-reason">Optional rejection reason<input value={rejectReason} onChange={event => setRejectReason(event.target.value)} maxLength={2000} /></label>
    </section>

    <section className="workflow-panel" aria-label="Application preparation"><div className="section-heading"><div><h3>Application preparation</h3><p>Each edit and regeneration creates a new version; approved versions remain unchanged.</p></div><select aria-label="Select application" value={selected} onChange={event => void selectApplication(event.target.value)}><option value="">Choose application</option>{applications.map(item => <option value={item.id} key={item.id}>{item.job.title} · {item.job.company_name} · {item.status}</option>)}</select></div>
      {current && <><div className="application-summary"><strong>{current.job.title} · {current.job.company_name}</strong><span>Status: {current.status.replaceAll('_', ' ')}</span><span>Selected resume version: {versions.find(item => item.id === current.resume_version_id)?.resumeTitle || 'Resume'} · {versions.find(item => item.id === current.resume_version_id)?.version_number || ''}</span>{!['READY_TO_APPLY', 'ACCEPTED', 'REJECTED', 'WITHDRAWN'].includes(current.status) && <label>Track status<select aria-label="Update application status" value={statusSelection || current.status} onChange={event => { setStatusSelection(event.target.value); void updateApplicationStatus(event.target.value) }}><option value={current.status}>{current.status.replaceAll('_', ' ')}</option>{['SAVED', 'PREPARING', 'READY_FOR_REVIEW', 'ASSESSMENT', 'INTERVIEW', 'ON_HOLD', 'OFFER', 'REJECTED', 'WITHDRAWN', 'ACCEPTED'].filter(value => value !== current.status).map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></label>}</div><div className="user-context-grid"><label>Expected salary (optional)<input value={context.expected_salary} onChange={event => setContext({ ...context, expected_salary: event.target.value })} placeholder="Leave blank if unknown" /></label><label>Notice period (optional)<input value={context.notice_period} onChange={event => setContext({ ...context, notice_period: event.target.value })} placeholder="Leave blank if unknown" /></label></div><div className="review-actions"><button onClick={() => void generate(false)} disabled={busy}>Generate application drafts</button><button className="secondary" onClick={() => void generate(true)} disabled={busy}>Regenerate all documents</button></div>
        {drafts.length === 0 ? <p className="empty">No drafts yet. Generate documents when AI is configured.</p> : <div className="draft-history">{drafts.map(draft => <DraftCard key={draft.id} draft={draft} disabled={busy} onEdit={body => act(async () => { await request(`/applications/${selected}/drafts/${draft.id}`, tokens.access_token, { method: 'PATCH', body: JSON.stringify({ body }) }); await loadApplication(selected); await load() }, 'A new editable version was created; prior approvals were invalidated.')} onApprove={() => act(async () => { await request(`/applications/${selected}/drafts/${draft.id}/approve`, tokens.access_token, { method: 'POST' }); await loadApplication(selected) }, 'Exact draft version approved.')} />)}</div>}
        <div className="checklist"><h4>Required application checklist</h4>{checklist.required_items.map(key => { const value = checklist.items[key] || {}; const localReason = notApplicableReasons[key] ?? value.not_applicable_reason ?? ''; return <div className="checklist-row" key={key}><label><input type="checkbox" checked={Boolean(value.completed)} onChange={event => void saveChecklist(key, { completed: event.target.checked, not_applicable_reason: null })} />{checklistLabels[key]}</label><input aria-label={`${checklistLabels[key]} not applicable reason`} placeholder="Not applicable reason" value={localReason} onChange={event => setNotApplicableReasons(current => ({ ...current, [key]: event.target.value }))} onBlur={() => { if (localReason !== (value.not_applicable_reason || '')) void saveChecklist(key, { completed: false, not_applicable_reason: localReason || null }) }} /></div> })}</div>
        <div className="review-actions final-approval"><button onClick={() => void act(async () => { await request(`/applications/${selected}/final-approval`, tokens.access_token, { method: 'POST', body: JSON.stringify({ confirmed: true }) }); await load(); await loadApplication(selected) }, 'Final approval recorded for the exact approved document versions.')} disabled={busy}>I approve this application for manual submission</button></div>
        <div className="handoff"><h4>Manual application handoff</h4><p>Review the destination website. Fill and submit the application yourself; this system never submits it.</p><button className="secondary" disabled={busy || current.status !== 'READY_TO_APPLY'} onClick={() => void openApplicationSite()}>Open verified application site</button><div className="approved-references">{drafts.filter(draft => draft.status === 'APPROVED').map(draft => <details key={draft.id}><summary>{draft.draft_type.replaceAll('_', ' ')} · version {draft.version_number}</summary><pre>{draft.body}</pre></details>)}</div><label className="confirm-submission"><input type="checkbox" id="submitted-confirm" /> I manually submitted this application on the employer website.</label><button onClick={() => { const input = document.querySelector<HTMLInputElement>('#submitted-confirm'); if (!input?.checked) { setError('Confirm the manual submission checkbox first.'); return }; void act(async () => { await request(`/applications/${selected}/confirm-submission`, tokens.access_token, { method: 'POST', body: JSON.stringify({ submitted: true }) }); await load(); await loadApplication(selected) }, 'Submission confirmation recorded.') }} disabled={busy || current.status !== 'READY_TO_APPLY'}>Confirm manual submission</button></div>
        <section className="audit-history"><h4>Application timeline</h4>{audit.length ? <ol>{audit.map((event: any) => <li key={event.id}><strong>{event.action.replaceAll('_', ' ')}</strong><time>{new Date(event.occurred_at).toLocaleString()}</time></li>)}</ol> : <p>No recorded events.</p>}</section>
      </>}
      {!current && <p className="empty">Approve a matched job for preparation, then create an application to manage drafts and review.</p>}
    </section>
    <section className="workflow-panel" aria-label="Application tracking"><h3>Application tracking</h3>{applications.length === 0 ? <p className="empty">No applications to track.</p> : <div className="tracking-list">{applications.map(item => <button className="tracking-row" key={item.id} onClick={() => void selectApplication(item.id)}><span><strong>{item.job.title}</strong><small>{item.job.company_name}</small></span><span>{item.status.replaceAll('_', ' ')}</span>{item.submitted_at && <time>{new Date(item.submitted_at).toLocaleString()}</time>}</button>)}</div>}</section>
  </section>
}

function DraftCard({ draft, disabled, onEdit, onApprove }: { draft: Draft; disabled: boolean; onEdit: (body: string) => Promise<void>; onApprove: () => Promise<void> }) {
  const [body, setBody] = useState(draft.body)
  useEffect(() => setBody(draft.body), [draft.id, draft.body, draft.status])
  return <article className="draft-card"><header><div><strong>{draft.draft_type.replaceAll('_', ' ')}</strong><small>Version {draft.version_number} · {draft.status} · {draft.generation_model || 'User edited'}</small></div><time>{new Date(draft.created_at).toLocaleString()}</time></header><textarea aria-label={`${draft.draft_type} version ${draft.version_number}`} value={body} onChange={event => setBody(event.target.value)} disabled={draft.status === 'SUPERSEDED' || disabled} />{draft.evidence.length > 0 && <details><summary>Source evidence</summary><ul>{draft.evidence.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></details>}<div className="review-actions">{body !== draft.body && <button className="secondary" onClick={() => void onEdit(body)} disabled={disabled}>Save as new version</button>}{draft.status !== 'APPROVED' && draft.status !== 'SUPERSEDED' && <button onClick={() => void onApprove()} disabled={disabled}>Approve version {draft.version_number}</button>}</div></article>
}
