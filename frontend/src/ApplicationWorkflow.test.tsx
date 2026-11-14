import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import ApplicationWorkflow from './ApplicationWorkflow'

const checklistKeys = ['job_details_verified', 'company_verified', 'application_url_verified', 'selected_resume_reviewed', 'tailored_resume_reviewed', 'cover_letter_reviewed', 'application_answers_reviewed', 'expected_salary_confirmed', 'notice_period_confirmed', 'personal_information_confirmed']

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

function setupWorkflow() {
  const review: any = { id: 'review-1', job_id: 'job-1', status: 'PENDING_REVIEW', history: [], match: {
    id: 'match-1', overall_score: 84, confidence: 90, explanation: 'Strong relevant experience.', matched_skills: ['Python'], missing_required_skills: ['SQL'], ai_analysis: {},
    job: { title: 'Backend Engineer', company_name: 'Acme', location: 'Chennai', apply_url: 'https://example.com/apply', job_url: 'https://example.com/listing' },
  } }
  const application: any = { id: 'app-1', job_id: 'job-1', resume_version_id: 'version-1', status: 'PREPARING', job: review.match.job }
  let drafts: any[] = []; let items: any = {}; let reviewStatus = 'PENDING_REVIEW'; let appStatus = 'PREPARING'
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace('http://localhost:8000/api/v1', '')
    const method = init?.method || 'GET'
    if (url === '/job-reviews' && method === 'GET') { review.status = reviewStatus; return new Response(JSON.stringify([{ ...review, status: reviewStatus }]), { status: 200 }) }
    if (url.startsWith('/job-reviews/') && method === 'POST') { reviewStatus = url.endsWith('/approve') ? 'APPROVED_FOR_PREPARATION' : url.endsWith('/save') ? 'SAVED' : 'REJECTED'; return new Response(JSON.stringify({ status: reviewStatus }), { status: 200 }) }
    if (url === '/applications' && method === 'GET') { application.status = appStatus; return new Response(JSON.stringify(appStatus === 'NONE' ? [] : [{ ...application, status: appStatus }]), { status: 200 }) }
    if (url === '/applications' && method === 'POST') { appStatus = 'PREPARING'; return new Response(JSON.stringify(application), { status: 201 }) }
    if (url === '/resumes') return new Response(JSON.stringify([{ id: 'resume-1', title: 'My CV', is_default: true, versions: [{ id: 'version-1', version_number: 3, parsing_status: 'COMPLETED' }] }]), { status: 200 })
    if (url.endsWith('/drafts') && method === 'GET') return new Response(JSON.stringify(drafts), { status: 200 })
    if (url.endsWith('/checklist') && method === 'GET') return new Response(JSON.stringify({ items, required_items: checklistKeys }), { status: 200 })
    if (url.endsWith('/audit') && method === 'GET') return new Response(JSON.stringify([]), { status: 200 })
    if (url.endsWith('/generate') && method === 'POST') {
      drafts = ['TAILORED_RESUME', 'COVER_LETTER', 'RECRUITER_MESSAGE', 'APPLICATION_ANSWERS'].map((draft_type, i) => ({ id: `draft-${i}`, application_id: 'app-1', draft_type, version_number: 1, body: `Reviewed ${draft_type}`, status: 'GENERATED', evidence: ['Python'], created_at: new Date().toISOString() }))
      return new Response(JSON.stringify(drafts), { status: 200 })
    }
    if (url.includes('/drafts/draft-') && method === 'PATCH') {
      const id = url.split('/').at(-1)!
      const old = drafts.find(item => item.id === id)
      if (old) old.status = 'SUPERSEDED'
      const next = { ...old, id: 'draft-edited', version_number: 2, body: JSON.parse(String(init?.body)).body, status: 'EDITED', created_at: new Date().toISOString() }
      drafts.push(next)
      return new Response(JSON.stringify(next), { status: 200 })
    }
    if (url.endsWith('/approve') && method === 'POST') {
      const id = url.split('/').at(-2); drafts = drafts.map(item => item.id === id ? { ...item, status: 'APPROVED' } : item); return new Response(JSON.stringify({ ok: true }), { status: 200 })
    }
    if (url.endsWith('/checklist') && method === 'PUT') { items = { ...items, ...JSON.parse(String(init?.body)).items }; return new Response(JSON.stringify({ items, required_items: checklistKeys }), { status: 200 }) }
    if (url.endsWith('/final-approval')) { appStatus = 'READY_TO_APPLY'; application.status = appStatus; return new Response(JSON.stringify({ application, approved_draft_ids: drafts.filter(item => item.status === 'APPROVED').map(item => item.id) }), { status: 200 }) }
    if (url.endsWith('/open-url')) return new Response(JSON.stringify({ url: 'https://example.com/apply', reminder: 'Submit manually.' }), { status: 200 })
    if (url.endsWith('/confirm-submission')) { appStatus = 'APPLIED'; application.status = appStatus; return new Response(JSON.stringify(application), { status: 200 }) }
    throw new Error(`Unexpected request: ${method} ${url}`)
  })
  sessionStorage.setItem('job-hunt-tokens', JSON.stringify({ access_token: 'test-token' }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('application workflow', () => {
  it('reviews a job and shows the preparation action only after user approval', async () => {
    setupWorkflow(); render(<ApplicationWorkflow />)
    expect(await screen.findByText('84% match · 90% confidence')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Approve preparation' }))
    expect(await screen.findByRole('button', { name: 'Create application' })).toBeInTheDocument()
  })

  it('edits a draft into a new version and keeps the earlier version visible', async () => {
    setupWorkflow(); render(<ApplicationWorkflow />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve preparation' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create application' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Generate application drafts' }))
    const original = await screen.findByRole('textbox', { name: 'TAILORED_RESUME version 1' })
    fireEvent.change(original, { target: { value: 'Edited Python résumé text.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save as new version' }))
    expect(await screen.findByRole('textbox', { name: 'TAILORED_RESUME version 2' })).toHaveValue('Edited Python résumé text.')
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'TAILORED_RESUME version 1' })).toHaveValue('Reviewed TAILORED_RESUME'))
    expect(screen.getByText('Version 1 · SUPERSEDED · User edited')).toBeInTheDocument()
  })

  it('generates drafts, completes the checklist, approves, opens manually, and confirms submission explicitly', async () => {
    const fetchMock = setupWorkflow();
    const popup = { location: { href: '' } }
    vi.stubGlobal('open', vi.fn(() => popup))
    render(<ApplicationWorkflow />)
    await screen.findByRole('button', { name: 'Approve preparation' })
    fireEvent.click(screen.getByRole('button', { name: 'Approve preparation' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create application' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Generate application drafts' }))
    expect(await screen.findByText('TAILORED RESUME')).toBeInTheDocument()
    for (const button of await screen.findAllByRole('button', { name: /Approve version 1/ })) fireEvent.click(button)
    for (const key of checklistKeys) fireEvent.click(screen.getByRole('checkbox', { name: new RegExp(key.replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase()), 'i') }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'I approve this application for manual submission' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'I approve this application for manual submission' }))
    expect(await screen.findByText('Final approval recorded for the exact approved document versions.')).toBeInTheDocument()
    expect(screen.getByText('Status: READY TO APPLY')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open verified application site' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/applications/app-1/open-url'))).toBe(true))
    expect(popup.location.href).toBe('https://example.com/apply')
    expect(screen.getByText('Status: READY TO APPLY')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('I manually submitted this application on the employer website.'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm manual submission' }))
    expect(await screen.findByText('Status: APPLIED')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/applications/app-1/confirm-submission'))).toBe(true)
  })
})
