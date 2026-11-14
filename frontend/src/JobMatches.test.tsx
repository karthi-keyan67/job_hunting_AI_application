import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import JobMatches from './JobMatches'

const resume = { id: 'resume-1', title: 'Backend CV', is_default: true, versions: [
  { id: 'version-1', version_number: 2, original_filename: 'latest.pdf', parsing_status: 'COMPLETED' },
  { id: 'version-0', version_number: 1, original_filename: 'old.pdf', parsing_status: 'COMPLETED' },
] }
const match = { id: 'match-1', job_id: 'job-1', overall_score: 82.5, confidence: 90, eligibility_status: 'PARTIAL_MATCH',
  criteria_scores: { skills: 75, experience: 100, role: 80, location: 100, salary: null }, available_criteria: ['skills', 'experience', 'role', 'location'], missing_criteria: ['salary'],
  matched_skills: ['python'], missing_required_skills: ['sql'], missing_preferred_skills: [], strengths: ['Python experience'], concerns: ['Salary unknown'], explanation: 'Score explanation', ai_analysis: { status: 'complete' }, recommendation: 'STRONG_MATCH',
  job: { title: 'Backend Engineer', company_name: 'Acme', location: 'Chennai', work_mode: 'REMOTE', employment_type: 'FULL_TIME', salary_min: null, salary_max: null, salary_currency: null, salary_period: null, experience_min: 24, experience_max: 60, description: 'Build reliable APIs.', job_url: 'https://example.com/job', apply_url: null, source_name: 'Acme Careers', required_skills: ['Python', 'SQL'], preferred_skills: [] } }

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

describe('job matches', () => {
  it('lists scores, filters, selects a resume, runs matching, and expands job details', async () => {
    sessionStorage.setItem('job-hunt-tokens', JSON.stringify({ access_token: 'token' }))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([resume]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: 'source-1', name: 'Acme Careers' }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [match], total: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [match], total: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [match], total: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [match], total: 1 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<JobMatches />)
    expect(await screen.findByText('83%')).toBeInTheDocument()
    expect(screen.getByText(/90% confidence/)).toBeInTheDocument()
    expect(screen.getByText(/Missing: salary/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: 'Resume version' }), { target: { value: 'version-0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Match jobs now' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Matching finished')
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/matching/run'))).toBe(true))
    const runCall = fetchMock.mock.calls.find(call => String(call[0]).includes('/matching/run'))!
    expect(JSON.parse(String(runCall[1]?.body)).resume_version_id).toBe('version-0')
    fireEvent.click(screen.getByRole('button', { name: 'Job details' }))
    expect(await screen.findByText('Build reliable APIs.')).toBeInTheDocument()
    expect(document.querySelector('.match-detail p:nth-of-type(2)')).toHaveTextContent('Salary: Unknown')
    fireEvent.change(screen.getByLabelText('Eligibility'), { target: { value: 'PARTIAL_MATCH' } })
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('eligibility=PARTIAL_MATCH'))).toBe(true))
  })

  it('rematches only the jobs selected by the user', async () => {
    sessionStorage.setItem('job-hunt-tokens', JSON.stringify({ access_token: 'token' }))
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([resume]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [match], total: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [match], total: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [match], total: 1 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<JobMatches />)
    await screen.findByText('83%')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Backend Engineer' }))
    fireEvent.click(screen.getByRole('button', { name: 'Rematch selected (1)' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/matching/rematch'))).toBe(true))
    const call = fetchMock.mock.calls.find(item => String(item[0]).includes('/matching/rematch'))!
    expect(JSON.parse(String(call[1]?.body)).job_ids).toEqual(['job-1'])
  })
})
