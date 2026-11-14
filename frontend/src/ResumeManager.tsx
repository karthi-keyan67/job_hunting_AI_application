import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Version = { id: string; version_number: number; original_filename: string; file_type: string; file_size: number; parsing_status: string; parsing_error: string | null; parsed_text: string | null; created_at: string }
type Resume = { id: string; title: string; is_default: boolean; versions: Version[] }
type Tokens = { access_token: string }
const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
const MAX_FILE = 5 * 1024 * 1024

async function request(path: string, token: string, init: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...init.headers } })
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Request failed (${response.status})`) }
  return response.status === 204 ? null : response
}

export default function ResumeManager() {
  const [tokens, setTokens] = useState<Tokens | null>(() => { const saved = sessionStorage.getItem('job-hunt-tokens'); return saved ? JSON.parse(saved) as Tokens : null })
  const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [register, setRegister] = useState(false)
  const [resumes, setResumes] = useState<Resume[]>([]); const [selected, setSelected] = useState<string | null>(null)
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const reload = useCallback(async (active = tokens) => {
    if (!active) return
    const response = await request('/resumes', active.access_token)
    const items = await response!.json() as Resume[]; setResumes(items)
    setSelected(old => old && items.some(item => item.id === old) ? old : items[0]?.id ?? null)
  }, [tokens])
  useEffect(() => { if (tokens) void reload().catch(e => setError(e.message)) }, [tokens, reload])
  async function authenticate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const response = await fetch(`${API}/auth/${register ? 'register' : 'login'}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) })
      const body = await response.json(); if (!response.ok) throw new Error(body.detail || 'Authentication failed')
      const sessionTokens = { access_token: body.access_token }
      sessionStorage.setItem('job-hunt-tokens', JSON.stringify(sessionTokens)); setTokens(sessionTokens); window.dispatchEvent(new Event('job-hunt-auth'))
    } catch (e) { setError(e instanceof Error ? e.message : 'Authentication failed') } finally { setBusy(false) }
  }
  async function upload(file: File, resumeId?: string) {
    setError(''); setNotice(''); const extension = file.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'docx'].includes(extension || '')) { setError('Choose a PDF or DOCX file.'); return }
    if (file.size > MAX_FILE) { setError('File exceeds the 5 MB upload limit.'); return }
    if (!tokens) return
    setBusy(true)
    try {
      const form = new FormData(); form.append('file', file)
      if (!resumeId) form.append('title', file.name.replace(/\.[^.]+$/, '').slice(0, 200))
      const path = `/resumes${resumeId ? `/${resumeId}/versions` : ''}`
      const send = (body: FormData) => fetch(`${API}${path}`, { method: 'POST', headers: { Authorization: `Bearer ${tokens.access_token}` }, body })
      let response = await send(form)
      if (response.status === 409 && resumeId && confirm('This file already exists. Add it as another version anyway?')) { form.append('force_new_version', 'true'); response = await send(form) }
      if (!response.ok) { const body = await response.json(); throw new Error(body.detail || 'Upload failed') }
      setNotice('Resume uploaded.'); await reload()
    } catch (e) { setError(e instanceof Error ? e.message : 'Upload failed') } finally { setBusy(false) }
  }
  async function action(path: string, method: string, message: string) {
    if (!tokens) return
    setBusy(true); setError('')
    try { await request(path, tokens.access_token, { method }); await reload(); setNotice(message) }
    catch (e) { setError(e instanceof Error ? e.message : 'Request failed') } finally { setBusy(false) }
  }
  async function download(resume: Resume, version: Version) {
    try {
      const response = await request(`/resumes/${resume.id}/versions/${version.id}/download`, tokens!.access_token)
      const url = URL.createObjectURL(await response!.blob()); const link = document.createElement('a'); link.href = url; link.download = version.original_filename; link.click(); URL.revokeObjectURL(url)
    } catch (e) { setError(e instanceof Error ? e.message : 'Download failed') }
  }
  if (!tokens) return <section className="auth-card"><p className="eyebrow">PRIVATE RESUME WORKSPACE</p><h1>{register ? 'Create your account' : 'Welcome back'}</h1><form onSubmit={authenticate}><label>Email<input type="email" required value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" /></label><label>Password<input type="password" required minLength={12} value={password} onChange={e => setPassword(e.target.value)} autoComplete={register ? 'new-password' : 'current-password'} /></label><button disabled={busy}>{register ? 'Create account' : 'Sign in'}</button></form><button className="text-button" onClick={() => setRegister(!register)}>{register ? 'Already registered? Sign in' : 'Create an account'}</button>{error && <p role="alert" className="error">{error}</p>}</section>

  const active = resumes.find(item => item.id === selected) || null
  return <><header className="workspace-head"><div><p className="eyebrow">YOUR DOCUMENTS STAY PRIVATE</p><h1>Resume library</h1><p className="intro">Upload and review versions of your resume. Files are only accessible from your account.</p></div><label className="upload-button">{busy ? 'Working…' : '+ Upload resume'}<input aria-label="Upload a resume" type="file" accept=".pdf,.docx" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file); e.currentTarget.value = '' }} /></label><button className="text-button" onClick={() => { sessionStorage.removeItem('job-hunt-tokens'); setTokens(null); window.dispatchEvent(new Event('job-hunt-auth')) }}>Sign out</button></header>
    {error && <p role="alert" className="notice error">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    <section className="resume-layout"><aside className="resume-list"><div className="section-heading"><h2>My resumes</h2><span>{resumes.length}</span></div>{resumes.length ? resumes.map(item => <button className={`resume-row ${selected === item.id ? 'selected' : ''}`} key={item.id} onClick={() => setSelected(item.id)}><strong>{item.title}</strong><small>{item.versions.length} versions{item.is_default ? ' · Default' : ''}</small></button>) : <div className="empty">No resumes yet. Upload a PDF or DOCX.</div>}</aside>
      <section className="resume-detail">{active ? <><div className="section-heading"><div><h2>{active.title}</h2><p>{active.is_default ? 'Default resume' : 'Resume versions'}</p></div><div className="detail-actions">{!active.is_default && <button className="secondary" disabled={busy} onClick={() => void action(`/resumes/${active.id}/default`, 'POST', 'Default resume updated.')}>Make default</button>}<button className="secondary danger-button" disabled={busy} onClick={() => confirm('Delete this resume and all its versions?') && void action(`/resumes/${active.id}`, 'DELETE', 'Resume deleted.')}>Delete</button></div></div>
        <label className="version-upload">＋ Add a new version<input aria-label="Add a resume version" type="file" accept=".pdf,.docx" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file, active.id); e.currentTarget.value = '' }} /></label>
        <div className="version-list">{active.versions.map(version => <article className="version-card" key={version.id}><div className="version-top"><span className="version-badge">V{version.version_number}</span><div className="version-name"><strong>{version.original_filename}</strong><small>{version.file_type} · {(version.file_size / 1024).toFixed(0)} KB · {new Date(version.created_at).toLocaleDateString()}</small></div><span className={`status status-${version.parsing_status.toLowerCase()}`}>{version.parsing_status.replace('_', ' ')}</span></div>{version.parsing_error && <p className="parse-note">{version.parsing_error}</p>}<div className="version-actions"><button className="text-button" onClick={() => void download(active, version)}>Download</button>{version.parsed_text && <details><summary>Preview extracted text</summary><pre>{version.parsed_text}</pre></details>}{active.versions.length > 1 && <button className="text-button danger-text" onClick={() => confirm(`Delete version ${version.version_number}?`) && void action(`/resumes/${active.id}/versions/${version.id}`, 'DELETE', 'Resume version deleted.')}>Delete version</button>}</div></article>)}</div></> : <div className="empty large-empty">Select a resume or upload your first file.</div>}</section></section></>
}
