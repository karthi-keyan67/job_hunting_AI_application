import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import JobPortalConnections from './JobPortalConnections'

const platformNames = ['LINKEDIN', 'NAUKRI', 'INDEED', 'INSTAHYRE', 'CUTSHORT', 'HIRIST']
function portal(platform: string) {
  return { platform, name: platform, mark: platform[0], direct_status: 'NOT_DOCUMENTED', limitation: 'Email alerts only.',
    connection_method: 'GMAIL_JOB_ALERTS', portal_account_connected: false, alert_source_configured: false, source_id: null,
    discovery_enabled: false, can_enable_discovery: false, alert_status: 'NOT_CONFIGURED', allowed_senders: [], required_terms: [], label_ids: [],
    last_success_at: null, last_failure_at: null, last_run: null }
}
const review = { id: 'review-1', sender: 'alerts@example.com', subject: 'New opening', received_at: '2026-11-14T10:00:00Z', status: 'NEEDS_REVIEW', reason: 'Unknown format', excerpt: 'New role details' }
afterEach(() => { cleanup(); vi.restoreAllMocks() })

function setup({ connected = false, oauthConfigured = true, oauthMessage = null }: { connected?: boolean; oauthConfigured?: boolean; oauthMessage?: string | null } = {}) {
  const items = platformNames.map(platform => platform === 'LINKEDIN' ? { ...portal(platform), source_id: 'source-1', alert_source_configured: true,
    allowed_senders: ['jobs@linkedin.example'], last_success_at: '2026-11-14T10:00:00Z', can_enable_discovery: connected } : portal(platform))
  const request = vi.fn(async (path: string, _token: string, init?: RequestInit) => {
    const method = init?.method || 'GET'
    let value: any = {}
    if (path === '/integrations/job-portals') value = { gmail: { connected, gmail_address: null, oauth_configured: oauthConfigured, oauth_configuration_message: oauthMessage }, items }
    else if (path.includes('/audit')) value = [{ id: 'audit-1', platform: 'LINKEDIN', action: 'ALERT_SOURCE_CREATED', details: {}, occurred_at: '2026-11-14T10:00:00Z' }]
    else if (path.includes('/reviews')) value = [review]
    else if (path.includes('/history')) value = { items: [{ id: 'run-1', status: 'FAILED', started_at: '2026-11-14T10:00:00Z', jobs_found: 0, jobs_created: 0, jobs_updated: 0, error: 'Gmail unavailable' }] }
    else if (path.includes('/alerts') && method === 'PUT') value = { ok: true }
    else if (path.includes('/discovery') && method === 'PATCH') value = { ok: true }
    else if (path.includes('/reviews/') && method === 'PATCH') value = { ok: true }
    return new Response(JSON.stringify(value), { status: method === 'DELETE' ? 204 : 200, headers: { 'Content-Type': 'application/json' } })
  })
  return { request, items }
}

describe('job portal connections', () => {
  it('shows all six portal states and makes clear Gmail does not connect portal accounts', async () => {
    const { request } = setup()
    render(<JobPortalConnections token="test-token" request={request} />)
    expect(await screen.findByRole('heading', { name: 'Job Portal Connections' })).toBeInTheDocument()
    for (const platform of platformNames) expect(screen.getByRole('heading', { name: platform })).toBeInTheDocument()
    expect(screen.getAllByText('Portal account: not connected. Gmail authorization only reads this mailbox.')).toHaveLength(6)
    expect(screen.getByText('Gmail not connected')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Enable discovery' })).toHaveLength(6)
    expect(screen.getAllByRole('button', { name: 'Enable discovery' }).every(button => (button as HTMLButtonElement).disabled)).toBe(true)
  })

  it('shows malformed OAuth configuration categories and disables the Gmail connection button', async () => {
    const setupMessage = 'Gmail connection is unavailable. Configure: OAUTH_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.'
    const { request } = setup({ oauthConfigured: false, oauthMessage: setupMessage })
    render(<JobPortalConnections token="test-token" request={request} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(setupMessage)
    expect(screen.getByRole('button', { name: 'Connect Gmail' })).toBeDisabled()
  })

  it('saves sender settings, loads sync history and handles the unknown-alert review queue', async () => {
    const { request } = setup({ connected: true })
    render(<JobPortalConnections token="test-token" request={request} />)
    const sender = await screen.findByDisplayValue('jobs@linkedin.example')
    fireEvent.change(sender, { target: { value: 'alerts@linkedin.example, jobs@linkedin.example' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Save alert settings' })[0])
    await waitFor(() => expect(request).toHaveBeenCalledWith('/integrations/job-portals/LINKEDIN/alerts', 'test-token', expect.objectContaining({ method: 'PUT' })))
    const sent = JSON.parse(String(request.mock.calls.find(call => String(call[0]).includes('/alerts') && call[2]?.method === 'PUT')?.[2]?.body))
    expect(sent.allowed_senders).toEqual(['alerts@linkedin.example', 'jobs@linkedin.example'])

    fireEvent.click(screen.getByRole('button', { name: 'View sync history' }))
    await waitFor(() => expect(screen.getByLabelText('LINKEDIN sync history')).toHaveTextContent('Gmail unavailable'))
    fireEvent.click(screen.getByRole('button', { name: 'Mark reviewed' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/integrations/gmail/reviews/review-1', 'test-token', expect.objectContaining({ method: 'PATCH' })))
    expect(screen.getByText('Integration activity')).toBeInTheDocument()
  })

  it('enables discovery only when Gmail is connected and reports API errors', async () => {
    const { request } = setup({ connected: true })
    render(<JobPortalConnections token="test-token" request={request} />)
    const enable = (await screen.findAllByRole('button', { name: 'Enable discovery' }))[0]
    expect(enable).toBeEnabled()
    fireEvent.click(enable)
    await waitFor(() => expect(request).toHaveBeenCalledWith('/integrations/job-portals/LINKEDIN/discovery', 'test-token', expect.objectContaining({ method: 'PATCH' })))
  })
})
