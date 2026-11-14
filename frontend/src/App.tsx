import ResumeManager from './ResumeManager'
import JobWorkspace from './JobWorkspace'

const stages = [
  ['Discover', 'Collect jobs from authorized sources'],
  ['Review', 'Approve each opportunity yourself'],
  ['Prepare', 'Review every application draft'],
  ['Apply', 'Submit manually when you are ready'],
]

export default function App() {
  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#home"><span className="brand-mark">J</span> Job Hunting Agent</a>
        <span className="phase">Job search workspace · Phase 4</span>
      </header>
      <JobWorkspace />
      <ResumeManager />
      <section className="hero" id="home">
        <p className="eyebrow">YOUR SEARCH, WITH YOU IN CONTROL</p>
        <h1>A more thoughtful way<br />to find your next role.</h1>
        <p className="intro">Discover relevant opportunities, understand your fit, and prepare stronger applications. You review every job and submit every application yourself.</p>
        <div className="actions"><button type="button" disabled>Search and review jobs above</button><span>Nothing is submitted automatically.</span></div>
      </section>
      <section className="steps" aria-label="Application workflow">
        {stages.map(([title, description], index) => <article className="step" key={title}>
          <span className="step-number">0{index + 1}</span><h2>{title}</h2><p>{description}</p>
        </article>)}
      </section>
      <footer><span>Built around your decisions.</span><span>API status: available at <code>/api/v1/health</code></span></footer>
    </main>
  )
}
