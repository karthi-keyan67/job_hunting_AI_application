import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import Phase7Workspace from './Phase7Workspace'

const app = { id: 'app-1', status: 'PREPARING', updated_at: '2026-10-01T10:00:00Z', notes: '', match_score: 82,
  resume_version: { id: 'resume-v1', version_number: 1, title: 'Backend CV' }, approved_documents: [], checklist: { company_verified: true },
  job: { id: 'job-1', title: 'Platform Engineer', company_name: 'Northwind', location: 'Bengaluru', work_mode: 'HYBRID', description: 'Build platform services.', job_url: 'https://example.com/job' } }
const summary = { total_jobs_discovered: 6, new_jobs: 2, strong_matches: 1, jobs_pending_review: 1, jobs_approved_for_preparation: 1,
  applications_in_preparation: 1, ready_to_apply_applications: 0, submitted_applications: 0, interviews: 0, offers: 0, rejected_applications: 0,
  recent_activity: [{ id: 'activity-1', action: 'APPLICATION_CREATED', job_title: 'Platform Engineer', company_name: 'Northwind', occurred_at: '2026-10-01T10:00:00Z' }],
  recent_matching_results: [{ id: 'match-1', title: 'Platform Engineer', company_name: 'Northwind', overall_score: 82 }], upcoming: [] }
const analytics = { application_count: 1, applications_by_status: { PREPARING: 1 }, applications_over_time: [{ period: '2026-10-01', count: 1 }],
  jobs_collected_over_time: [], match_distribution: { '80-100': 1 }, source_distribution: [],
  interview_conversion: { numerator: 0, denominator: 1, percentage: null, sample_size_sufficient: false },
  offer_conversion: { numerator: 0, denominator: 1, percentage: null, sample_size_sufficient: false } }

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear() })

function setupApi() {
  sessionStorage.setItem('job-hunt-tokens', JSON.stringify({ access_token: 'token' }))
  const interview = { id: 'interview-1', application_id: 'app-1', interview_type: 'Technical', scheduled_at: '2026-12-01T10:00:00Z', timezone: 'Asia/Kolkata', status: 'SCHEDULED' }
  const followUp = { id: 'follow-up-1', application_id: 'app-1', title: 'Email recruiter', due_at: '2026-12-02T10:00:00Z', timezone: 'Asia/Kolkata', status: 'PENDING' }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); const method = init?.method || 'GET'
    let body: any
    if (url.includes('/dashboard/summary')) body = summary
    else if (url.includes('/dashboard/upcoming')) body = []
    else if (url.includes('/dashboard/pipeline')) body = { items: [app], total: 1, offset: 0, limit: 30 }
    else if (url.endsWith('/applications')) body = [app]
    else if (url.includes('/interviews') && method === 'POST') body = { ...interview, ...JSON.parse(String(init?.body)), id: 'interview-new' }
    else if (url.includes('/interviews')) body = { items: [interview], offset: 0, limit: 100 }
    else if (url.includes('/follow-ups') && method === 'POST') body = { ...followUp, ...JSON.parse(String(init?.body)), id: 'follow-up-new' }
    else if (url.includes('/follow-ups')) body = { items: [followUp], offset: 0, limit: 100 }
    else if (url.includes('/analytics/overview')) body = analytics
    else if (url.includes('/timeline')) body = { timeline: [{ id: 'event-1', event: 'APPLICATION_CREATED', occurred_at: '2026-10-01T10:00:00Z' }] }
    else if (url.endsWith('/app-1') && method === 'GET') body = app
    else if (url.includes('/notes') && method === 'PATCH') body = { notes: JSON.parse(String(init?.body)).notes }
    else body = {}
    const status = url.includes('/interviews') && method === 'DELETE' || url.includes('/follow-ups') && method === 'DELETE' ? 204 : 200
    return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('Phase 7 dashboard and tracking', () => {
  it('renders database-backed dashboard, pipeline details, notes, timeline, and analytics', async () => {
    const fetchMock = setupApi()
    render(<Phase7Workspace />)
    expect(await screen.findByText('6')).toBeInTheDocument()
    expect(screen.getByText('Recent activity')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pipeline' }))
    fireEvent.click(await screen.findByRole('button', { name: /Platform Engineer/ }))
    expect(await screen.findByText('Build platform services.')).toBeInTheDocument()
    expect(screen.getByText('Application Created')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Private notes'), { target: { value: 'Call recruiter Friday' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save notes' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/notes'))).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Analytics' }))
    expect(await screen.findByText('Applications in range')).toBeInTheDocument()
    expect(screen.getAllByText('Sample too small').length).toBeGreaterThan(0)
  })

  it('creates interviews and follow-ups and offers cancellation/completion actions', async () => {
    const fetchMock = setupApi()
    render(<Phase7Workspace />)
    fireEvent.click(await screen.findByRole('button', { name: 'Interviews' }))
    fireEvent.change(screen.getByLabelText('Application'), { target: { value: 'app-1' } })
    fireEvent.change(screen.getByLabelText('Interview type'), { target: { value: 'Technical' } })
    fireEvent.change(screen.getByLabelText('Date and time'), { target: { value: '2026-12-01T10:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add interview' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/interviews') && call[1]?.method === 'POST')).toBe(true))
    vi.stubGlobal('prompt', vi.fn().mockReturnValueOnce('Technical round').mockReturnValueOnce('2026-12-02T10:00').mockReturnValueOnce('Asia/Kolkata').mockReturnValueOnce('').mockReturnValueOnce('Hiring manager').mockReturnValueOnce('Discuss platform work'))
    fireEvent.click(await screen.findByRole('button', { name: 'Edit interview' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/interviews/') && call[1]?.method === 'PATCH')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/interviews/') && call[1]?.method === 'DELETE')).toBe(true))

    fireEvent.click(screen.getByRole('button', { name: 'Follow-ups' }))
    fireEvent.change(screen.getByLabelText('Application'), { target: { value: 'app-1' } })
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Email recruiter' } })
    fireEvent.change(screen.getByLabelText('Due date and time'), { target: { value: '2026-12-02T10:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add follow-up' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/follow-ups') && call[1]?.method === 'POST')).toBe(true))
    expect(await screen.findByText('Email recruiter')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Complete' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/follow-ups/') && call[1]?.method === 'PATCH')).toBe(true))
  })
})
