import { useEffect, useState, type KeyboardEvent } from 'react'

type PreferenceValues = {
  target_job_roles: string[]
  required_skills: string[]
  optional_skills: string[]
  minimum_experience_months: number | null
  maximum_experience_months: number | null
  minimum_salary: number | null
  maximum_salary: number | null
  preferred_locations: string[]
  work_modes: string[]
  excluded_companies: string[]
  excluded_roles: string[]
  employment_types: string[]
  is_active: boolean
}
type Preferences = PreferenceValues & { user_id?: string; created_at?: string; updated_at?: string }
type Requester = (path: string, token: string, init?: RequestInit) => Promise<Response | null>

const emptyPreferences: PreferenceValues = {
  target_job_roles: [], required_skills: [], optional_skills: [], minimum_experience_months: null, maximum_experience_months: null,
  minimum_salary: null, maximum_salary: null, preferred_locations: [], work_modes: [], excluded_companies: [], excluded_roles: [], employment_types: [], is_active: true,
}
const suggestions: PreferenceValues = {
  ...emptyPreferences,
  target_job_roles: ['Python Backend Developer', 'AI Engineer', 'LLM Engineer'],
  required_skills: ['Python', 'FastAPI'],
  optional_skills: ['Flask', 'Django', 'React', 'PostgreSQL', 'OpenAI', 'LangChain', 'LlamaIndex', 'RAG', 'Qdrant'],
  minimum_experience_months: 24, maximum_experience_months: 36,
  minimum_salary: 1200000, maximum_salary: 1500000,
  preferred_locations: ['Chennai', 'Remote'], work_modes: ['REMOTE', 'HYBRID'], employment_types: ['FULL_TIME'],
}
const workModeOptions = [['REMOTE', 'Remote'], ['HYBRID', 'Hybrid'], ['ONSITE', 'Onsite']] as const
const employmentOptions = [['FULL_TIME', 'Full time'], ['PART_TIME', 'Part time'], ['CONTRACT', 'Contract'], ['INTERNSHIP', 'Internship'], ['TEMPORARY', 'Temporary']] as const
const clone = (value: PreferenceValues): PreferenceValues => ({ ...value, target_job_roles: [...value.target_job_roles], required_skills: [...value.required_skills], optional_skills: [...value.optional_skills], preferred_locations: [...value.preferred_locations], work_modes: [...value.work_modes], excluded_companies: [...value.excluded_companies], excluded_roles: [...value.excluded_roles], employment_types: [...value.employment_types] })
const normalize = (value: Partial<PreferenceValues>): PreferenceValues => ({
  ...emptyPreferences,
  minimum_experience_months: value.minimum_experience_months ?? null,
  maximum_experience_months: value.maximum_experience_months ?? null,
  minimum_salary: value.minimum_salary ?? null,
  maximum_salary: value.maximum_salary ?? null,
  is_active: value.is_active ?? true,
  target_job_roles: value.target_job_roles || [], required_skills: value.required_skills || [], optional_skills: value.optional_skills || [],
  preferred_locations: value.preferred_locations || [], work_modes: value.work_modes || [], excluded_companies: value.excluded_companies || [],
  excluded_roles: value.excluded_roles || [], employment_types: value.employment_types || [],
})

function MultiValueInput({ label, values, onChange }: { label: string; values: string[]; onChange: (values: string[]) => void }) {
  const [draft, setDraft] = useState('')
  function add(value = draft) {
    const additions = value.split(',').map(item => item.trim()).filter(Boolean)
    if (additions.length) onChange([...values, ...additions.filter(item => !values.some(existing => existing.toLowerCase() === item.toLowerCase()))])
    setDraft('')
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter' || event.key === ',') { event.preventDefault(); add() }
  }
  return <div className="preferences-multi"><label htmlFor={`pref-${label}`}>{label}</label><div className="preferences-add"><input id={`pref-${label}`} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={onKeyDown} placeholder="Type a value and press Enter" /><button type="button" className="secondary" onClick={() => add()}>Add</button></div><div className="preferences-chips" aria-label={`${label} selected`}>{values.map(value => <span className="preferences-chip" key={value}>{value}<button type="button" aria-label={`Remove ${value}`} onClick={() => onChange(values.filter(item => item !== value))}>×</button></span>)}</div></div>
}

function MultiSelect({ label, values, options, onChange }: { label: string; values: string[]; options: readonly (readonly [string, string])[]; onChange: (values: string[]) => void }) {
  const known = new Set(options.map(([value]) => value))
  const additionalOptions = values.filter(value => !known.has(value)).map(value => [value, value] as const)
  return <fieldset className="preferences-options"><legend>{label}</legend>{[...options, ...additionalOptions].map(([value, title]) => <label key={value}><input type="checkbox" checked={values.includes(value)} onChange={event => onChange(event.target.checked ? [...values, value] : values.filter(item => item !== value))} />{title}</label>)}</fieldset>
}

export default function JobPreferencesWorkspace({ token, request }: { token: string; request: Requester }) {
  const [saved, setSaved] = useState<PreferenceValues>(clone(emptyPreferences))
  const [form, setForm] = useState<PreferenceValues>(clone(emptyPreferences))
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [fieldError, setFieldError] = useState('')
  const [suggested, setSuggested] = useState(false)

  useEffect(() => {
    let active = true
    async function load() {
      setLoading(true); setError('')
      try {
        const response = await request('/preferences', token)
        const record = response ? await response.json() as Preferences : null
        if (!active) return
        const value = normalize(record || {})
        const untouchedDefault = !!record && record.created_at && record.updated_at && new Date(record.created_at).getTime() === new Date(record.updated_at).getTime() && JSON.stringify(value) === JSON.stringify(emptyPreferences)
        const next = record && !untouchedDefault ? value : clone(suggestions)
        setSaved(clone(value)); setForm(clone(next)); setSuggested(!record || !!untouchedDefault)
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : 'Could not load preferences.') }
      finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false }
  }, [token, request])

  function update<K extends keyof PreferenceValues>(key: K, value: PreferenceValues[K]) { setForm(current => ({ ...current, [key]: value })) }
  function cancel() { setForm(clone(suggested ? suggestions : saved)); setFieldError(''); setNotice(''); setError('') }
  async function save() {
    setFieldError(''); setError(''); setNotice('')
    const experienceValues = [form.minimum_experience_months, form.maximum_experience_months].filter((value): value is number => value !== null)
    if (experienceValues.some(value => !Number.isInteger(value) || value < 0 || value > 720)) { setFieldError('Experience must be a whole number of months between 0 and 720.'); return }
    const salaryValues = [form.minimum_salary, form.maximum_salary].filter((value): value is number => value !== null)
    if (salaryValues.some(value => !Number.isFinite(value) || value < 0)) { setFieldError('Annual salary values must be valid non-negative numbers.'); return }
    if (form.minimum_experience_months !== null && form.maximum_experience_months !== null && form.minimum_experience_months > form.maximum_experience_months) { setFieldError('Minimum experience cannot exceed maximum experience.'); return }
    if (form.minimum_salary !== null && form.maximum_salary !== null && form.minimum_salary > form.maximum_salary) { setFieldError('Minimum annual salary cannot exceed maximum annual salary.'); return }
    setBusy(true)
    try {
      const response = await request('/preferences', token, { method: 'PUT', body: JSON.stringify(form) })
      const result = response ? await response.json() as Preferences : form
      const next = normalize(result)
      setForm(clone(next)); setSaved(clone(next)); setSuggested(false); setNotice('Job preferences saved.')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save preferences.') }
    finally { setBusy(false) }
  }

  return <section className="preferences-workspace" aria-label="Job Preferences">
    <header className="preferences-heading"><div><p className="eyebrow">PERSONALIZE YOUR SEARCH</p><h3>Job Preferences</h3><p>Set the roles and conditions used to filter and match jobs.</p></div><span className={`preferences-status ${form.is_active ? 'is-active' : ''}`}>{form.is_active ? 'Active' : 'Inactive'}</span></header>
    {loading ? <p role="status" className="empty">Loading saved preferences…</p> : <>
      {suggested && <p className="preferences-hint">Starter suggestions are shown as an unsaved draft. Save them to apply; your saved preferences have not been changed.</p>}
      {error && <p className="phase7-error" role="alert">{error}</p>}{fieldError && <p className="phase7-error" role="alert">{fieldError}</p>}{notice && <p className="phase7-notice" role="status">{notice}</p>}
      <div className="preferences-form">
        <article className="phase7-panel"><h4>Roles and skills</h4><MultiValueInput label="Target roles" values={form.target_job_roles} onChange={value => update('target_job_roles', value)} /><MultiValueInput label="Required skills" values={form.required_skills} onChange={value => update('required_skills', value)} /><MultiValueInput label="Optional skills" values={form.optional_skills} onChange={value => update('optional_skills', value)} /><MultiValueInput label="Excluded roles" values={form.excluded_roles} onChange={value => update('excluded_roles', value)} /></article>
        <article className="phase7-panel"><h4>Experience and annual salary</h4><div className="preferences-range"><label>Minimum experience (months)<input type="number" min="0" max="720" step="1" value={form.minimum_experience_months ?? ''} onChange={event => update('minimum_experience_months', event.target.value === '' ? null : Number(event.target.value))} /></label><label>Maximum experience (months)<input type="number" min="0" max="720" step="1" value={form.maximum_experience_months ?? ''} onChange={event => update('maximum_experience_months', event.target.value === '' ? null : Number(event.target.value))} /></label><label>Minimum expected annual salary<input type="number" min="0" step="any" value={form.minimum_salary ?? ''} onChange={event => update('minimum_salary', event.target.value === '' ? null : Number(event.target.value))} /></label><label>Maximum expected annual salary<input type="number" min="0" step="any" value={form.maximum_salary ?? ''} onChange={event => update('maximum_salary', event.target.value === '' ? null : Number(event.target.value))} /></label></div><p className="preferences-hint">Salary amounts are annual and use the currency set on your profile.</p></article>
        <article className="phase7-panel"><h4>Location and work</h4><MultiValueInput label="Preferred locations" values={form.preferred_locations} onChange={value => update('preferred_locations', value)} /><MultiSelect label="Work modes" values={form.work_modes} options={workModeOptions} onChange={value => update('work_modes', value)} /><MultiSelect label="Employment types" values={form.employment_types} options={employmentOptions} onChange={value => update('employment_types', value)} /></article>
        <article className="phase7-panel"><h4>Exclusions and status</h4><MultiValueInput label="Excluded companies" values={form.excluded_companies} onChange={value => update('excluded_companies', value)} /><label className="preferences-active"><input type="checkbox" checked={form.is_active} onChange={event => update('is_active', event.target.checked)} />Use these preferences for matching</label></article>
      </div>
      <div className="preferences-actions"><button disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save preferences'}</button><button className="secondary" disabled={busy} onClick={cancel}>Cancel</button></div>
    </>}
  </section>
}
