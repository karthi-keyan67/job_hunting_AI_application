import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import AutomationWorkspace from './AutomationWorkspace'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Phase 8 automation workspace', () => {
  it('renders worker, collection history, notification inbox, and triggers manual collection', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      let body: any = {}
      if (url.includes('/automation/settings')) body = { id: 'settings-1', enabled: true, timezone: 'Asia/Kolkata', schedule: '0,6,12,18 every day', email_enabled: false, email_provider_configured: false, notify_job_matches: true, notify_collection: true, notify_reminders: true, minimum_match_score: 75, quiet_start: null, quiet_end: null, reminder_intervals_minutes: [1440, 60] }
      else if (url.includes('/automation/status')) body = { timezone: 'Asia/Kolkata', scheduler_status: 'RUNNING', next_scheduled_run: '2026-11-14T06:30:00Z', worker_heartbeat_at: '2026-11-14T00:30:00Z', source_metrics: { sources: [] } }
      else if (url.includes('/automation/collection-runs')) body = { items: [{ id: 'run-1', status: 'SUCCEEDED', started_at: '2026-11-14T00:00:00Z', duration_seconds: 2.4, retry_count: 0, source_id: 'source-1' }], total: 1 }
      else if (url.includes('/notifications')) body = { items: [{ id: 'notification-1', notification_type: 'HIGH_MATCH_JOB', payload: { title: 'Strong match', message: 'Platform Engineer · 88% match' }, is_read: false, delivery_status: 'SKIPPED', created_at: '2026-11-14T00:00:00Z' }], total: 1 }
      else if (url.includes('/automation/collect')) body = { status: 'SUCCEEDED', results: [] }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AutomationWorkspace token="test-token" />)
    expect(await screen.findByText(/Worker:/)).toBeInTheDocument()
    expect(await screen.findByText(/SUCCEEDED · source-1/)).toBeInTheDocument()
    expect(await screen.findByText('Strong match')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run enabled sources now' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/automation/collect'), expect.objectContaining({ method: 'POST' })))
    expect(await screen.findByRole('status')).toHaveTextContent('Manual collection finished.')
  })
})
