import { useCallback, useEffect, useState } from 'react'

type Version = { id: string; version_number: number; original_filename: string; parsing_status: string }
type Resume = { id: string; title: string; is_default: boolean; versions: Version[] }
type Match = { id: string; job_id: string; overall_score: number; confidence: number; eligibility_status: string; criteria_scores: Record<string, number | null>; available_criteria: string[]; missing_criteria: string[]; matched_skills: string[]; missing_required_skills: string[]; missing_preferred_skills: string[]; strengths: string[]; concerns: string[]; explanation: string; ai_analysis: Record<string, any>; recommendation: string; model_name: string | null; created_at: string; job: { title: string; company_name: string; location: string | null; work_mode: string | null; employment_type: string | null; salary_min: number | null; salary_max: number | null; salary_currency: string | null; salary_period: string | null; experience_min: number | null; experience_max: number | null; description: string; job_url: string | null; apply_url: string | null; source_name: string; required_skills: string[]; preferred_skills: string[] } }
type Source = { id: string; name: string }
type Tokens = { access_token: string }
const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

async function request(path: string, token: string, init: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } })
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Request failed (${response.status})`) }
  return response.status === 204 ? null : response
}

export default function JobMatches() {
  const [tokens, setTokens] = useState<Tokens | null>(() => { const saved = sessionStorage.getItem('job-hunt-tokens'); return saved ? JSON.parse(saved) as Tokens : null })
  const [resumes, setResumes] = useState<Resume[]>([]); const [sources, setSources] = useState<Source[]>([])
  const [versionId, setVersionId] = useState(''); const [matches, setMatches] = useState<Match[]>([])
  const [minScore, setMinScore] = useState(''); const [location, setLocation] = useState(''); const [workMode, setWorkMode] = useState(''); const [skill, setSkill] = useState(''); const [sourceId, setSourceId] = useState(''); const [eligibility, setEligibility] = useState(''); const [recommendation, setRecommendation] = useState(''); const [reviewStatus, setReviewStatus] = useState('')
  const [sortBy, setSortBy] = useState<'score' | 'confidence' | 'newest'>('score')
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([])
  const [includeAi, setIncludeAi] = useState(false); const [selected, setSelected] = useState<Match | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('')

  useEffect(() => {
    const sync = () => { const saved = sessionStorage.getItem('job-hunt-tokens'); setTokens(saved ? JSON.parse(saved) as Tokens : null) }
    window.addEventListener('job-hunt-auth', sync)
    return () => window.removeEventListener('job-hunt-auth', sync)
  }, [])

  const loadResults = useCallback(async (active = tokens) => {
    if (!active) return
    const params = new URLSearchParams()
    if (minScore) params.set('min_score', minScore)
    if (location) params.set('location', location)
    if (workMode) params.set('work_mode', workMode)
    if (skill) params.set('skill', skill)
    if (sourceId) params.set('source_id', sourceId)
    if (eligibility) params.set('eligibility', eligibility)
    if (recommendation) params.set('recommendation', recommendation)
    if (reviewStatus) params.set('review_status', reviewStatus)
    const response = await request(`/matching/results?${params.toString()}`, active.access_token)
    setMatches((await response!.json() as { items: Match[] }).items)
  }, [tokens, minScore, location, workMode, skill, sourceId, eligibility, recommendation, reviewStatus])

  useEffect(() => {
    if (!tokens) return
    void Promise.all([
      request('/resumes', tokens.access_token).then(async response => {
        const items = await response!.json() as Resume[]; setResumes(items)
        const defaultResume = items.find(item => item.is_default) || items[0]
        const defaultVersion = defaultResume?.versions.find(version => version.parsing_status === 'COMPLETED') || defaultResume?.versions[0]
        if (defaultVersion) setVersionId(old => old || defaultVersion.id)
      }),
      request('/sources', tokens.access_token).then(async response => setSources(await response!.json() as Source[])),
    ]).catch(e => setError(e.message))
  }, [tokens])

  useEffect(() => {
    if (!tokens) return
    void loadResults(tokens).catch(e => setError(e instanceof Error ? e.message : 'Could not load matching results'))
  }, [tokens, loadResults])

  async function run(path: string, jobIds?: string[]) {
    if (!tokens || !versionId) { setError('Upload a parsed resume version before matching.'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      const response = await request(path, tokens.access_token, { method: 'POST', body: JSON.stringify({ resume_version_id: versionId, include_ai: includeAi, ...(jobIds ? { job_ids: jobIds } : {}) }) })
      const result = await response!.json() as { items?: Match[]; total?: number }
      setNotice(`Matching finished. ${result.total ?? 1} result${(result.total ?? 1) === 1 ? '' : 's'} processed.`)
      await loadResults()
    } catch (e) { setError(e instanceof Error ? e.message : 'Matching failed') }
    finally { setBusy(false) }
  }

  async function matchOne(jobId: string) {
    if (!tokens || !versionId) return
    setBusy(true); setError('')
    try {
      const response = await request(`/matching/jobs/${jobId}`, tokens.access_token, { method: 'POST', body: JSON.stringify({ resume_version_id: versionId, include_ai: includeAi }) })
      setSelected(await response!.json() as Match); await loadResults()
    } catch (e) { setError(e instanceof Error ? e.message : 'Matching failed') }
    finally { setBusy(false) }
  }

  if (!tokens) return null
  const versions = resumes.flatMap(resume => resume.versions.map(version => ({ ...version, resumeTitle: resume.title })))
  const sortedMatches = [...matches].sort((a, b) => sortBy === 'confidence' ? b.confidence - a.confidence : sortBy === 'newest' ? b.created_at.localeCompare(a.created_at) : b.overall_score - a.overall_score)
  return <section className="matches-workspace" aria-label="Job matches">
    <div className="matches-heading"><div><p className="eyebrow">PHASE 5 · EXPLAINABLE MATCHING</p><h2>Job matches</h2><p>Deterministic eligibility and weighted fit scores, with optional evidence-based AI analysis.</p></div><div className="matching-actions"><button className="secondary" disabled={busy || !versionId || selectedJobIds.length === 0} onClick={() => void run('/matching/rematch', selectedJobIds)}>Rematch selected ({selectedJobIds.length})</button><button disabled={busy || !versionId} onClick={() => void run('/matching/run')}>Match jobs now</button></div></div>
    {error && <p role="alert" className="notice error">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    <div className="matching-controls"><label>Resume version<select aria-label="Resume version" value={versionId} onChange={e => setVersionId(e.target.value)}><option value="">Choose a resume version</option>{versions.map(version => <option key={version.id} value={version.id}>{version.resumeTitle} · v{version.version_number} · {version.parsing_status}</option>)}</select></label><label className="ai-toggle"><input type="checkbox" checked={includeAi} onChange={e => setIncludeAi(e.target.checked)} /> Request optional AI analysis</label><button className="secondary" disabled={busy || !versionId} onClick={() => void run('/matching/rematch')}>Rematch</button><small>Incomplete parsing lowers confidence and leaves unsupported criteria unknown.</small></div>
    <form className="matching-filters" onSubmit={event => { event.preventDefault(); void loadResults().catch(e => setError(e.message)) }}><label>Minimum score<input type="number" min="0" max="100" value={minScore} onChange={e => setMinScore(e.target.value)} /></label><label>Location<input value={location} onChange={e => setLocation(e.target.value)} /></label><label>Work mode<select value={workMode} onChange={e => setWorkMode(e.target.value)}><option value="">Any</option><option>REMOTE</option><option>HYBRID</option><option>ONSITE</option></select></label><label>Skill<input value={skill} onChange={e => setSkill(e.target.value)} /></label><label>Source<select value={sourceId} onChange={e => setSourceId(e.target.value)}><option value="">Any source</option>{sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label><label>Review status<select value={reviewStatus} onChange={e => setReviewStatus(e.target.value)}><option value="">Any</option>{['PENDING_REVIEW', 'APPROVED_FOR_PREPARATION', 'SAVED', 'REJECTED'].map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></label><label>Eligibility<select value={eligibility} onChange={e => setEligibility(e.target.value)}><option value="">Any</option>{['MATCH', 'PARTIAL_MATCH', 'MISMATCH', 'UNKNOWN'].map(value => <option key={value}>{value}</option>)}</select></label><label>Recommendation<select value={recommendation} onChange={e => setRecommendation(e.target.value)}><option value="">Any</option>{['STRONG_MATCH', 'REVIEW', 'LOW_MATCH', 'NOT_RECOMMENDED'].map(value => <option key={value}>{value}</option>)}</select></label><label>Sort by<select aria-label="Sort matches" value={sortBy} onChange={e => setSortBy(e.target.value as typeof sortBy)}><option value="score">Highest score</option><option value="confidence">Highest confidence</option><option value="newest">Newest</option></select></label><button className="secondary">Filter</button></form>
    <div className="match-results" aria-live="polite">{matches.length === 0 ? <p className="empty">No matching results yet. Run matching to compare your resume with collected jobs.</p> : sortedMatches.map(match => <article className="match-card" key={match.id}>
      <div className="match-card-head"><div><label className="match-select"><input type="checkbox" aria-label={`Select ${match.job.title}`} checked={selectedJobIds.includes(match.job_id)} onChange={event => setSelectedJobIds(current => event.target.checked ? [...new Set([...current, match.job_id])] : current.filter(id => id !== match.job_id))} /> Select</label><p className="eyebrow">{match.job.source_name} · {match.job.company_name}</p><h3>{match.job.title}</h3><p>{match.job.location || 'Location not provided'}{match.job.work_mode ? ` · ${match.job.work_mode}` : ''}</p></div><div className="score-pill"><strong>{Math.round(match.overall_score)}%</strong><span>fit · {Math.round(match.confidence)}% confidence</span></div></div>
      <div className="match-badges"><span>{match.eligibility_status.replaceAll('_', ' ')}</span><span>{match.recommendation.replaceAll('_', ' ')}</span><span>Criteria: {match.available_criteria.join(', ') || 'none'}{match.missing_criteria.length ? ` · Missing: ${match.missing_criteria.join(', ')}` : ''}</span></div>
      <div className="match-score-grid">{Object.entries(match.criteria_scores).map(([name, value]) => <div key={name}><span>{name}</span><strong>{value === null ? 'Unknown' : `${Math.round(value)}%`}</strong></div>)}</div>
      <div className="job-facts"><span>Experience: {match.job.experience_min === null ? 'Unknown' : `${match.job.experience_min} months`}{match.job.experience_max !== null ? `–${match.job.experience_max} months` : ''}</span><span>Salary: {match.job.salary_min === null ? 'Unknown' : `${match.job.salary_currency} ${match.job.salary_min.toLocaleString()}${match.job.salary_max ? `–${match.job.salary_max.toLocaleString()}` : ''} ${match.job.salary_period || ''}`}</span><span>{match.job.employment_type?.replaceAll('_', ' ') || 'Employment type unknown'}</span></div>
      <div className="skill-tags">{match.matched_skills.map(item => <span key={`matched-${item}`}>Matched · {item}</span>)}{match.missing_required_skills.map(item => <span key={`required-${item}`} className="missing-skill">Required · {item}</span>)}{match.missing_preferred_skills.map(item => <span key={`preferred-${item}`} className="missing-skill">Preferred · {item}</span>)}</div>
      {match.ai_analysis.status === 'complete' && (match.ai_analysis.skill_analysis?.transferable || []).map((item: { candidate_skill: string; job_skill: string }, index: number) => <span className="equivalent-skill" key={`${item.candidate_skill}-${item.job_skill}-${index}`}>Equivalent · {item.candidate_skill} → {item.job_skill}</span>)}
      <p className="match-explanation">{match.explanation}</p><div className="match-actions"><button className="secondary" onClick={() => void matchOne(match.job_id)} disabled={busy}>Match this job</button><button className="text-button" onClick={() => setSelected(selected?.id === match.id ? null : match)} aria-expanded={selected?.id === match.id}>Job details</button>{match.job.job_url && <a href={match.job.job_url} target="_blank" rel="noreferrer">Listing ↗</a>}</div>
      {selected?.id === match.id && <div className="match-detail"><h4>Responsibilities and requirements</h4><p>{match.job.description || 'No description provided.'}</p><p>Experience: {match.job.experience_min === null ? 'Unknown' : `${match.job.experience_min} months`}{match.job.experience_max !== null ? `–${match.job.experience_max} months` : ''} · Salary: {match.job.salary_min === null ? 'Unknown' : `${match.job.salary_currency} ${match.job.salary_min.toLocaleString()}${match.job.salary_max ? `–${match.job.salary_max.toLocaleString()}` : ''} ${match.job.salary_period || ''}`}</p>{match.strengths.length > 0 && <><h4>Strengths</h4><ul>{match.strengths.map(item => <li key={item}>{item}</li>)}</ul></>}{match.concerns.length > 0 && <><h4>Concerns / unknowns</h4><ul>{match.concerns.map(item => <li key={item}>{item}</li>)}</ul></>}{match.ai_analysis.status === 'complete' && <><h4>AI semantic analysis · {match.model_name || 'configured model'}</h4><p>{match.ai_analysis.explanation as string}</p><ul>{(match.ai_analysis.evidence || []).map((item: { source: string; quote: string }, index: number) => <li key={`${item.source}-${index}`}>{item.source}: “{item.quote}”</li>)}</ul></>}{match.job.apply_url && <a href={match.job.apply_url} target="_blank" rel="noreferrer">Open application page ↗</a>}</div>}
    </article>)}</div>
  </section>
}
