import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import JobWorkspace from './JobWorkspace'

const source = { id: 'source-1', name: 'Acme Careers', source_type: 'CAREER_PAGE', base_url: 'https://careers.example.org', is_enabled: true, configuration: {}, last_success_at: null, last_failure_at: null, integration_status: 'CONFIGURED' }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

describe('job workspace', () => {
  it('lists a configured source and displays its collection history', async () => {
    sessionStorage.setItem('job-hunt-tokens', JSON.stringify({ access_token: 'token' }))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([source]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'run-1', status: 'SUCCEEDED', jobs_found: 2, jobs_created: 1, jobs_updated: 1, jobs_skipped: 0 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([source]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: 'run-1', status: 'SUCCEEDED', started_at: '2026-11-14T10:00:00Z', jobs_found: 2, jobs_created: 1, jobs_updated: 1, jobs_skipped: 0 }]), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<JobWorkspace />)
    expect(await screen.findByText('Acme Careers')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Collect' }))
    expect(await screen.findByRole('status')).toHaveTextContent('1 new, 1 updated')
    await waitFor(() => expect(screen.getByText(/found 2, new 1, updated 1/)).toBeInTheDocument())
  })

  it('adds a public career page using the configured selector JSON', async () => {
    sessionStorage.setItem('job-hunt-tokens', JSON.stringify({ access_token: 'token' }))
    const created = { ...source, id: 'source-2', name: 'New Careers' }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(created), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([created]), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<JobWorkspace />)
    await screen.findByRole('heading', { name: 'Add a job source' })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'New Careers' } })
    fireEvent.change(screen.getByLabelText('Public base URL'), { target: { value: 'https://careers.example.org/jobs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add source' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Job source added.')
    expect(fetchMock.mock.calls[2][0]).toContain('/sources')
    const body = JSON.parse(String(fetchMock.mock.calls[2][1]?.body))
    expect(body.source_type).toBe('CAREER_PAGE')
    expect(body.configuration.selectors.job_card).toBe('article.job')
  })

  it('imports and filters real API job data without auto-fetching the URL', async () => {
    sessionStorage.setItem('job-hunt-tokens', JSON.stringify({ access_token: 'token' }))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'job-1' }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'job-1', title: 'Python Engineer', company_name: 'Example', source_name: 'Manual imports', location: 'Chennai', work_mode: 'REMOTE', description: '', required_skills: [], preferred_skills: [], possible_duplicate: false }], total: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<JobWorkspace />)
    fireEvent.click(await screen.findByRole('button', { name: 'Jobs' }))
    fireEvent.change(screen.getByLabelText('Job title'), { target: { value: 'Python Engineer' } })
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'Example' } })
    fireEvent.change(screen.getByLabelText('Job URL'), { target: { value: 'https://8.8.8.8/jobs/1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save job' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Job saved to your manual imports.')
    expect(await screen.findByText('Python Engineer')).toBeInTheDocument()
    expect(fetchMock.mock.calls[2][0]).toContain('/jobs/import')
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('8.8.8.8'))).toBe(false)
  })
})
