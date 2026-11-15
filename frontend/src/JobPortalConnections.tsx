import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Request = (path: string, token: string, init?: RequestInit) => Promise<Response | null>
type Portal = {
  platform: string; name: string; mark: string; direct_status: string; limitation: string
  connection_method: string; portal_account_connected: boolean; alert_source_configured: boolean
  source_id: string | null; discovery_enabled: boolean; can_enable_discovery: boolean; alert_status: string
  allowed_senders: string[]; required_terms: string[]; label_ids: string[]
  last_success_at: string | null; last_failure_at: string | null; last_run: Record<string, any> | null
}
type Audit = { id: string; platform: string; action: string; details: Record<string, any>; occurred_at: string }
type Review = { id: string; sender: string; subject: string; received_at: string | null; status: string; reason: string; excerpt: string }

const names = ['LINKEDIN', 'NAUKRI', 'INDEED', 'INSTAHYRE', 'CUTSHORT', 'HIRIST']
const csv = (value: FormDataEntryValue | null) => String(value || '').split(',').map(item => item.trim()).filter(Boolean)
const prettyDate = (value?: string | null) => value ? new Date(value).toLocaleString() : 'Never'

async function body(response: Response | null) { return response ? response.json() : null }

export default function JobPortalConnections({ token, request }: { token: string; request: Request }) {
  const [items, setItems] = useState<Portal[]>([])
  const [gmail, setGmail] = useState<{ connected: boolean; gmail_address?: string | null; oauth_configured: boolean; oauth_configuration_message?: string | null }>({ connected: false, oauth_configured: false })
  const [audits, setAudits] = useState<Audit[]>([])
  const [reviews, setReviews] = useState<Review[]>([])
  const [history, setHistory] = useState<Record<string, any[]>>({})
  const [drafts, setDrafts] = useState<Record<string, { senders: string; terms: string; labels: string }>>({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const [overviewResponse, auditResponse, reviewResponse] = await Promise.all([
      request('/integrations/job-portals', token),
      request('/integrations/job-portals/audit?limit=30', token),
      request('/integrations/gmail/reviews?status=NEEDS_REVIEW&limit=100', token),
    ])
    const overview = await body(overviewResponse)
    const nextItems = (overview?.items || []) as Portal[]
    setItems(nextItems)
    setGmail(overview?.gmail || { connected: false, oauth_configured: false })
    setAudits((await body(auditResponse)) || [])
    setReviews((await body(reviewResponse)) || [])
    setDrafts(current => Object.fromEntries(nextItems.map(item => [item.platform, current[item.platform] || {
      senders: item.allowed_senders.join(', '), terms: item.required_terms.join(', '), labels: item.label_ids.join(', '),
    }])))
  }, [request, token])

  useEffect(() => { void load().catch(cause => setError(cause instanceof Error ? cause.message : 'Could not load portal connections.')) }, [load])

  async function action(run: () => Promise<void>, message?: string) {
    setBusy(true); setError(''); setNotice('')
    try { await run(); if (message) setNotice(message) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Request failed.') }
    finally { setBusy(false) }
  }

  async function connectGmail() {
    await action(async () => {
      const response = await request('/integrations/gmail/authorize', token, { method: 'POST' })
      const result = await body(response)
      const popup = window.open(result.authorization_url, 'gmail-oauth', 'popup,width=620,height=760')
      if (!popup) window.location.assign(result.authorization_url)
      else {
        const timer = window.setInterval(() => {
          if (popup.closed) { window.clearInterval(timer); void load().catch(cause => setError(cause.message)) }
        }, 1500)
      }
    }, 'Google authorization started. Return here after approval to see the updated status.')
  }

  async function disconnectGmail() {
    if (!window.confirm('Disconnect the read-only Gmail connection? Enabled alert discovery sources will be disabled.')) return
    await action(async () => { await request('/integrations/gmail/connection', token, { method: 'DELETE' }); await load() }, 'Gmail disconnected; alert discovery has been disabled.')
  }

  async function saveAlerts(event: FormEvent<HTMLFormElement>, platform: string) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const senders = csv(form.get('allowed_senders'))
    const valid = /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/
    if (!senders.length || senders.some(sender => !valid.test(sender))) { setError('Enter one or more valid sender email addresses separated by commas.'); return }
    await action(async () => {
      await request(`/integrations/job-portals/${platform}/alerts`, token, { method: 'PUT', body: JSON.stringify({
        allowed_senders: senders, required_terms: csv(form.get('required_terms')), label_ids: csv(form.get('label_ids')),
      }) })
      await load()
    }, 'Alert source settings saved. This does not connect your portal account.')
  }

  async function toggleDiscovery(item: Portal) {
    await action(async () => {
      await request(`/integrations/job-portals/${item.platform}/discovery`, token, { method: 'PATCH', body: JSON.stringify({ enabled: !item.discovery_enabled }) })
      await load()
    }, item.discovery_enabled ? 'Discovery disabled.' : 'Email alert discovery enabled.')
  }

  async function loadHistory(platform: string) {
    await action(async () => {
      const result = await body(await request(`/integrations/job-portals/${platform}/history?limit=20`, token))
      setHistory(current => ({ ...current, [platform]: result.items || [] }))
    })
  }

  async function updateReview(review: Review, status: 'REVIEWED' | 'IGNORED') {
    await action(async () => { await request(`/integrations/gmail/reviews/${review.id}`, token, { method: 'PATCH', body: JSON.stringify({ status }) }); await load() }, `Alert marked ${status.toLowerCase()}.`)
  }

  return <section className="portal-connections" aria-label="Job Portal Connections">
    <header className="portal-connections-heading">
      <div><p className="eyebrow">AUTHORIZED JOB DISCOVERY</p><h3>Job Portal Connections</h3><p>Use supported integrations and portal-provided job alerts. No portal passwords or browser sessions are used.</p></div>
      <button className="secondary" disabled={busy} onClick={() => void action(load)}>Refresh status</button>
    </header>
    {error && <p role="alert" className="phase7-error">{error}</p>}{notice && <p role="status" className="phase7-notice">{notice}</p>}

    <section className="phase7-panel portal-gmail-panel">
      <div><p className="eyebrow">MAILBOX AUTHORIZATION</p><h4>Gmail job-alert access</h4>
        <p>Read-only Gmail access is used to collect alerts you have subscribed to on each portal. It does not log in to LinkedIn, Naukri, Indeed, Instahyre, Cutshort, or Hirist.</p>
        {!gmail.oauth_configured && <p className="portal-limit" role="alert">{gmail.oauth_configuration_message || 'Gmail connection is unavailable. Configure Google OAuth credentials, an HTTPS callback URI, and a token encryption key.'}</p>}
      </div>
      <div className="portal-gmail-state"><span className={`portal-status ${gmail.connected ? 'is-ready' : ''}`}>{gmail.connected ? `Gmail connected${gmail.gmail_address ? ` · ${gmail.gmail_address}` : ''}` : 'Gmail not connected'}</span>
        {gmail.connected ? <button className="secondary" disabled={busy} onClick={() => void disconnectGmail()}>Disconnect Gmail</button> : <button disabled={busy || !gmail.oauth_configured} onClick={() => void connectGmail()}>Connect Gmail</button>}
      </div>
    </section>

    <div className="portal-card-grid">
      {names.map(platform => {
        const item = items.find(value => value.platform === platform)
        if (!item) return <article className="phase7-panel portal-card" key={platform}><p role="status">Loading {platform}…</p></article>
        const draft = drafts[platform] || { senders: '', terms: '', labels: '' }
        return <article className="phase7-panel portal-card" key={platform}>
          <header className="portal-card-header"><span className={`portal-brand portal-brand-${platform.toLowerCase()}`} aria-hidden="true">{item.mark}</span><div><h4>{item.name}</h4><span className={`portal-status ${item.discovery_enabled ? 'is-ready' : ''}`}>{item.alert_status.replaceAll('_', ' ')}</span></div></header>
          <p className="portal-method">Connection method: <strong>Portal job-alert email + read-only Gmail</strong></p>
          <p className="portal-limit">{item.limitation}</p>
          <p className="portal-not-connected">Portal account: not connected. Gmail authorization only reads this mailbox.</p>
          <form className="portal-config-form" onSubmit={event => void saveAlerts(event, platform)}>
            <label>Allowed sender email addresses<input name="allowed_senders" value={draft.senders} onChange={event => setDrafts(current => ({ ...current, [platform]: { ...draft, senders: event.target.value } }))} placeholder="alerts@example.com, jobs@example.com" required /></label>
            <label>Optional required terms<input name="required_terms" value={draft.terms} onChange={event => setDrafts(current => ({ ...current, [platform]: { ...draft, terms: event.target.value } }))} placeholder="python, backend" /></label>
            <label>Optional Gmail label IDs<input name="label_ids" value={draft.labels} onChange={event => setDrafts(current => ({ ...current, [platform]: { ...draft, labels: event.target.value } }))} placeholder="INBOX, Label_123" /></label>
            <div className="portal-actions"><button disabled={busy}>Save alert settings</button><button type="button" className="secondary" disabled={busy || !item.alert_source_configured || (!item.discovery_enabled && !item.can_enable_discovery)} onClick={() => void toggleDiscovery(item)}>{item.discovery_enabled ? 'Disable discovery' : 'Enable discovery'}</button></div>
          </form>
          <div className="portal-sync-info"><p>Last successful sync: {prettyDate(item.last_success_at)}</p><p>Last failure: {prettyDate(item.last_failure_at)}</p>
            {item.last_run && <p>Latest run: {item.last_run.status} · {item.last_run.jobs_found} found, {item.last_run.jobs_created} new{item.last_run.error ? ` · ${item.last_run.error}` : ''}</p>}
          </div>
          {item.source_id && <div className="portal-actions"><button type="button" className="text-button" disabled={busy} onClick={() => void loadHistory(platform)}>View sync history</button></div>}
          {history[platform] && <div className="portal-history" aria-label={`${item.name} sync history`}>
            <h5>Sync history</h5>{history[platform].length === 0 ? <p>No runs yet.</p> : history[platform].map(run => <p key={run.id}><strong>{run.status}</strong> · {prettyDate(run.started_at)} · {run.jobs_found} found, {run.jobs_created} new, {run.jobs_updated} updated{run.error ? ` · ${run.error}` : ''}</p>)}
          </div>}
        </article>
      })}
    </div>

    <section className="phase7-panel portal-review-panel"><header><div><h4>Unrecognized Gmail alerts</h4><p>Messages that the current parser cannot safely identify stay here for review.</p></div><span className="phase7-count">{reviews.length} pending</span></header>
      {reviews.length === 0 ? <p className="empty">No unrecognized alerts need review.</p> : <ul className="portal-review-list">{reviews.map(review => <li key={review.id}><div><strong>{review.subject || '(No subject)'}</strong><small>{review.sender} · {prettyDate(review.received_at)}</small><p>{review.reason}</p>{review.excerpt && <details><summary>Show saved excerpt</summary><p>{review.excerpt}</p></details>}</div><div className="portal-actions"><button className="secondary" disabled={busy} onClick={() => void updateReview(review, 'REVIEWED')}>Mark reviewed</button><button className="text-button" disabled={busy} onClick={() => void updateReview(review, 'IGNORED')}>Ignore</button></div></li>)}</ul>}
    </section>

    <section className="phase7-panel portal-audit-panel"><header><div><h4>Integration activity</h4><p>Account connection and discovery-setting changes for your account.</p></div></header>
      {audits.length === 0 ? <p className="empty">No integration changes recorded yet.</p> : <ul className="portal-audit-list">{audits.map(event => <li key={event.id}><strong>{event.platform} · {event.action.replaceAll('_', ' ')}</strong><time>{prettyDate(event.occurred_at)}</time></li>)}</ul>}
    </section>
  </section>
}
