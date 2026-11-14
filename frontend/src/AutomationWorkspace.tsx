import { useCallback, useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
type Props = { token: string }
type Payload = Record<string, any>

async function request(path: string, token: string, init: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } })
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Request failed (${response.status})`) }
  return response.status === 204 ? null : response.json()
}

export default function AutomationWorkspace({ token }: Props) {
  const [settings, setSettings] = useState<Payload | null>(null)
  const [status, setStatus] = useState<Payload | null>(null)
  const [history, setHistory] = useState<Payload[]>([])
  const [notifications, setNotifications] = useState<Payload[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const [preferences, health, runs, inbox] = await Promise.all([
      request('/automation/settings', token), request('/automation/status', token),
      request('/automation/collection-runs?limit=30', token), request('/notifications?limit=30', token),
    ])
    setSettings(preferences); setStatus(health); setHistory(runs.items || []); setNotifications(inbox.items || [])
  }, [token])
  useEffect(() => { void load().catch(cause => setError(cause.message)) }, [load])

  async function runAction(action: () => Promise<void>, message: string) {
    setBusy(true); setError(''); setNotice('')
    try { await action(); await load(); setNotice(message) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Request failed') } finally { setBusy(false) }
  }
  function setField(key: string, value: unknown) { setSettings(current => current ? { ...current, [key]: value } : current) }
  const number = (value: unknown) => Number(value || 0).toLocaleString()

  return <section className="automation-workspace" aria-label="Automation and notifications">
    <header className="automation-heading"><div><p className="eyebrow">AUTOMATION &amp; OPERATIONS</p><h2>Collection, notifications &amp; worker health</h2><p>Recurring collection runs at midnight, 6 AM, noon, and 6 PM in the selected schedule timezone.</p></div></header>
    {error && <p role="alert" className="automation-message error">{error}</p>}{notice && <p role="status" className="automation-message">{notice}</p>}
    <div className="automation-grid">
      <article className="phase7-panel"><h3>Scheduler status</h3><div className="automation-kpis"><p><b>Worker:</b> {status?.scheduler_status || 'Loading'}</p><p><b>Timezone:</b> {status?.timezone || 'Asia/Kolkata'}</p><p><b>Next run:</b> {status?.next_scheduled_run ? new Date(status.next_scheduled_run).toLocaleString(undefined, { timeZone: status.timezone }) : '—'}</p><p><b>Heartbeat:</b> {status?.worker_heartbeat_at ? new Date(status.worker_heartbeat_at).toLocaleString() : 'Not reported'}</p></div><button disabled={busy} onClick={() => void runAction(async () => { await request('/automation/collect', token, { method: 'POST', body: JSON.stringify({ source_ids: [] }) }) }, 'Manual collection finished.')}>Run enabled sources now</button></article>
      <article className="phase7-panel"><h3>Notification preferences</h3>{settings && <form className="automation-form" onSubmit={event => { event.preventDefault(); void runAction(async () => { await request('/automation/settings', token, { method: 'PUT', body: JSON.stringify({ ...settings, reminder_intervals_minutes: String(settings.reminder_intervals_minutes).split(',').map(Number) }) }) }, 'Preferences saved.') }}>
        <label>Timezone for quiet hours and reminders<input value={settings.timezone} onChange={event => setField('timezone', event.target.value)} /></label>
        <label>Minimum job match score<input type="number" min="0" max="100" value={settings.minimum_match_score} onChange={event => setField('minimum_match_score', Number(event.target.value))} /></label>
        <label>Reminder lead times (minutes, comma separated)<input value={Array.isArray(settings.reminder_intervals_minutes) ? settings.reminder_intervals_minutes.join(',') : settings.reminder_intervals_minutes} onChange={event => setField('reminder_intervals_minutes', event.target.value)} /></label>
        <label>Quiet hours start<input type="time" value={settings.quiet_start || ''} onChange={event => setField('quiet_start', event.target.value || null)} /></label><label>Quiet hours end<input type="time" value={settings.quiet_end || ''} onChange={event => setField('quiet_end', event.target.value || null)} /></label>
        <label className="automation-check"><input type="checkbox" checked={settings.enabled} onChange={event => setField('enabled', event.target.checked)} />Enable scheduled automation</label>
        <label className="automation-check"><input type="checkbox" checked={settings.notify_job_matches} onChange={event => setField('notify_job_matches', event.target.checked)} />Strong job match alerts</label>
        <label className="automation-check"><input type="checkbox" checked={settings.notify_collection} onChange={event => setField('notify_collection', event.target.checked)} />Collection result alerts</label>
        <label className="automation-check"><input type="checkbox" checked={settings.notify_reminders} onChange={event => setField('notify_reminders', event.target.checked)} />Interview and follow-up reminders</label>
        <label className="automation-check"><input type="checkbox" checked={settings.email_enabled} onChange={event => setField('email_enabled', event.target.checked)} />Email notifications {settings.email_provider_configured ? '' : '(provider not configured)'}</label>
        <button disabled={busy}>Save preferences</button>
      </form>}</article>
      <article className="phase7-panel"><h3>Configured source health</h3>{status?.source_metrics?.sources?.length ? <ul className="automation-list">{status.source_metrics.sources.map((source: Payload) => <li key={source.id}><strong>{source.name} · {source.status}</strong><span>30 days: {number(source.success)} successful · {number(source.failure)} failed · {number(source.retry_count)} retries</span><span>Collection average: {source.collection_duration_average_seconds == null ? '—' : `${source.collection_duration_average_seconds}s`} · matching average: {source.matching_duration_average_seconds == null ? '—' : `${source.matching_duration_average_seconds}s`} · matching failures: {number(source.matching_failures)}</span><span>Last success: {source.last_success_at ? new Date(source.last_success_at).toLocaleString() : 'Never'}</span></li>)}</ul> : <p className="empty">No configured sources.</p>}</article>
      <article className="phase7-panel"><h3>Collection run history</h3>{history.length ? <ul className="automation-list">{history.map(run => <li key={run.id}><strong>{run.status} · {run.source_name || run.source_id}</strong><span>{new Date(run.started_at).toLocaleString()} · {run.duration_seconds == null ? '—' : `${run.duration_seconds.toFixed(1)}s`} · {run.retry_count || 0} retries</span>{run.error_summary && <span>{run.error_summary}</span>}</li>)}</ul> : <p className="empty">No collection runs yet.</p>}</article>
      <article className="phase7-panel"><h3>Notification inbox</h3>{notifications.length ? <ul className="automation-list">{notifications.map(item => <li key={item.id} className={item.is_read ? 'read' : ''}><strong>{item.payload.title || item.notification_type}</strong><span>{item.payload.message || ''}</span><span>{new Date(item.created_at).toLocaleString()} · Email: {item.delivery_status}</span>{!item.is_read && <button className="secondary" disabled={busy} onClick={() => void runAction(async () => { await request(`/notifications/${item.id}/read`, token, { method: 'PATCH' }) }, 'Notification marked as read.')}>Mark read</button>}</li>)}</ul> : <p className="empty">No notifications yet.</p>}</article>
      <article className="phase7-panel"><h3>Worker executions</h3>{status?.last_success_at && <p>Last successful collection: {new Date(status.last_success_at).toLocaleString()}</p>}<p>Collection failures are isolated per source. Matching uses the existing deterministic-first scorer and cached input fingerprints.</p></article>
    </div>
  </section>
}
