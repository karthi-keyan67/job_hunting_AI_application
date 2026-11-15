import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import JobPreferencesWorkspace from './JobPreferencesWorkspace'

const saved = {
  user_id: 'user-1', target_job_roles: ['Backend Engineer'], required_skills: ['Python'], optional_skills: [],
  minimum_experience_months: 24, maximum_experience_months: 36, minimum_salary: 1200000, maximum_salary: 1500000,
  preferred_locations: ['Chennai'], work_modes: ['REMOTE'], excluded_companies: ['BadCo'], excluded_roles: ['Sales'],
  employment_types: ['FULL_TIME'], is_active: true, created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-02T10:00:00Z',
}
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
const requester = (getValue: any = saved) => vi.fn(async (_path: string, _token: string, init?: RequestInit) => init?.method === 'PUT' ? response({ ...JSON.parse(String(init.body)), user_id: 'user-1' }) : response(getValue))
afterEach(cleanup)

describe('JobPreferencesWorkspace', () => {
  it('loads and shows saved preferences', async () => {
    const request = requester()
    render(<JobPreferencesWorkspace token="access-token" request={request} />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading saved preferences')
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText('BadCo')).toBeInTheDocument()
    expect(request).toHaveBeenCalledWith('/preferences', 'access-token')
  })

  it('allows editing and sends the full preference object on save', async () => {
    const request = requester()
    render(<JobPreferencesWorkspace token="access-token" request={request} />)
    await screen.findByText('Backend Engineer')
    fireEvent.change(screen.getByLabelText('Target roles'), { target: { value: 'Platform Engineer' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Add' })[0])
    fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/preferences', 'access-token', expect.objectContaining({ method: 'PUT' })))
    const payload = JSON.parse(String(request.mock.calls.find(call => call[2]?.method === 'PUT')?.[2]?.body))
    expect(payload).toEqual(expect.objectContaining({
      target_job_roles: ['Backend Engineer', 'Platform Engineer'], required_skills: ['Python'], preferred_locations: ['Chennai'],
      work_modes: ['REMOTE'], excluded_companies: ['BadCo'], excluded_roles: ['Sales'], employment_types: ['FULL_TIME'],
      minimum_experience_months: 24, maximum_experience_months: 36, minimum_salary: 1200000, maximum_salary: 1500000, is_active: true,
    }))
    expect(payload.created_at).toBeUndefined()
    expect(await screen.findByRole('status')).toHaveTextContent('Job preferences saved')
  })

  it('blocks invalid experience and annual salary ranges', async () => {
    const request = requester()
    render(<JobPreferencesWorkspace token="access-token" request={request} />)
    await screen.findByText('Backend Engineer')
    fireEvent.change(screen.getByLabelText('Minimum experience (months)'), { target: { value: '40' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Minimum experience cannot exceed')
    expect(request).not.toHaveBeenCalledWith('/preferences', 'access-token', expect.objectContaining({ method: 'PUT' }))
    fireEvent.change(screen.getByLabelText('Minimum experience (months)'), { target: { value: '24' } })
    fireEvent.change(screen.getByLabelText('Minimum expected annual salary'), { target: { value: '1600000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save preferences' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Minimum annual salary cannot exceed')
  })

  it('shows starter values for an untouched new account without saving them automatically', async () => {
    const fresh = { ...saved, target_job_roles: [], required_skills: [], optional_skills: [], minimum_experience_months: null, maximum_experience_months: null, minimum_salary: null, maximum_salary: null, preferred_locations: [], work_modes: [], excluded_companies: [], excluded_roles: [], employment_types: [], created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z' }
    const request = requester(fresh)
    render(<JobPreferencesWorkspace token="access-token" request={request} />)
    expect(await screen.findByText('Python Backend Developer')).toBeInTheDocument()
    expect(screen.getByText(/unsaved draft/)).toBeInTheDocument()
    expect(request).toHaveBeenCalledTimes(1)
  })
})
