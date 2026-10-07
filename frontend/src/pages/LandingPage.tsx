import { Link } from 'react-router-dom'
import { HealthScoreRing } from '../components/HealthScoreRing'
import { IconArchitecture, IconChat, IconHealth, IconSpark } from '../components/icons'
import { PageFade } from '../components/AnswerContent'
import { useAuth } from '../hooks/useAuth'
import { getGoogleLoginUrl } from '../services/authService'

function AuthCta({ className = 'btn btn-primary btn-lg' }: { className?: string }) {
  const { isAuthenticated, loading } = useAuth()
  if (loading) {
    return (
      <span className={`${className} is-loading`} aria-busy="true">
        Loading…
      </span>
    )
  }
  if (isAuthenticated) {
    return (
      <Link className={className} to="/dashboard">
        Open Dashboard
      </Link>
    )
  }
  return (
    <a className={className} href={getGoogleLoginUrl()}>
      Sign in with Google
    </a>
  )
}

export function LandingPage() {
  return (
    <PageFade>
      <div className="landing">
        <section className="landing-hero">
          <div className="landing-hero-copy">
            <p className="eyebrow">
              <IconSpark /> AI Software Evolution Platform
            </p>
            <h1>
              Understand your codebase.
              <span className="hero-line-accent">Evolve it with intelligence.</span>
            </h1>
            <p className="lede">
              Connect a public GitHub repository and turn real structure into health analysis,
              architecture maps, and grounded AI assistance — evidence from your code, not invented
              summaries.
            </p>
            <div className="cta-row">
              <AuthCta />
              <a className="btn btn-ghost btn-lg" href="#how-it-works">
                See how it works
              </a>
            </div>
            <ul className="hero-signals">
              <li>Repository health</li>
              <li>Architecture maps</li>
              <li>Grounded assistant</li>
            </ul>
          </div>

          <div className="landing-visual" aria-hidden>
            <div className="network-canvas">
              <div className="network-grid" />
              <div className="network-glow" />
              <div className="network-orbit network-orbit-a" />
              <div className="network-orbit network-orbit-b" />

              <div className="intel-chip intel-chip-health">
                <IconHealth />
                <span>Health</span>
              </div>
              <div className="intel-chip intel-chip-arch">
                <IconArchitecture />
                <span>Architecture</span>
              </div>
              <div className="intel-chip intel-chip-chat">
                <IconChat />
                <span>Assistant</span>
              </div>

              <svg className="network-svg" viewBox="0 0 480 420" fill="none">
                <g className="network-edges" stroke="currentColor" strokeWidth="1.2">
                  <path className="edge-draw e1" d="M110 96H220V156H330" />
                  <path className="edge-draw e2" d="M220 156V250H130" />
                  <path className="edge-draw e3" d="M330 156V214H400" />
                  <path className="edge-draw e4" d="M130 250H250V330" />
                  <path className="edge-draw e5" d="M400 214V308H290" />
                  <path className="network-pulse" d="M110 96H220V156H330V214H400" />
                </g>
                <g className="network-nodes">
                  <rect className="n n1" x="78" y="70" width="72" height="44" rx="10" />
                  <rect className="n n2" x="186" y="132" width="84" height="48" rx="10" />
                  <rect className="n n3" x="304" y="132" width="72" height="44" rx="10" />
                  <rect className="n n4" x="98" y="230" width="76" height="44" rx="10" />
                  <rect className="n n5" x="218" y="312" width="84" height="44" rx="10" />
                  <rect className="n n6" x="368" y="190" width="72" height="44" rx="10" />
                </g>
                <g
                  className="network-labels"
                  fill="currentColor"
                  fontSize="11"
                  fontFamily="IBM Plex Mono, monospace"
                >
                  <text x="90" y="96">
                    repo/
                  </text>
                  <text x="202" y="160">
                    services
                  </text>
                  <text x="318" y="158">
                    api
                  </text>
                  <text x="112" y="256">
                    auth
                  </text>
                  <text x="236" y="338">
                    data
                  </text>
                  <text x="382" y="216">
                    ext
                  </text>
                </g>
              </svg>

              <div className="network-caption">
                <span className="caption-dot" />
                Repository intelligence graph
              </div>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="landing-how">
          <div className="landing-section-head">
            <p className="eyebrow">Workflow</p>
            <h2>How it works</h2>
            <p className="muted">
              A focused path from a public repository URL to evidence-backed understanding.
            </p>
          </div>

          <ol className="how-flow">
            <li className="how-step">
              <span className="how-index">01</span>
              <strong>Connect</strong>
              <p>Add a public GitHub repository.</p>
            </li>
            <li className="how-step">
              <span className="how-index">02</span>
              <strong>Analyze</strong>
              <p>Inspect its real structure, files, symbols, and dependencies.</p>
            </li>
            <li className="how-step">
              <span className="how-index">03</span>
              <strong>Understand</strong>
              <p>Generate repository health insights and an architecture map.</p>
            </li>
            <li className="how-step">
              <span className="how-index">04</span>
              <strong>Ask</strong>
              <p>Ask grounded questions about the codebase using repository evidence.</p>
            </li>
          </ol>
        </section>

        <section id="capabilities" className="landing-showcase">
          <div className="landing-section-head">
            <p className="eyebrow">Product capabilities</p>
            <h2>What you can explore in the workspace</h2>
            <p className="muted">
              Previews of the same surfaces you use after connecting a repository.
            </p>
          </div>

          <div className="showcase-grid">
            <article className="showcase-panel showcase-health">
              <div className="showcase-copy">
                <div className="capability-icon">
                  <IconHealth />
                </div>
                <h3>Repository Health</h3>
                <p>
                  Review an overall score with category signals for quality, testing, security
                  posture, and related repository evidence.
                </p>
              </div>
              <div className="showcase-preview health-preview" aria-hidden>
                <HealthScoreRing score={78} status="Good" size={140} />
                <div className="preview-bars">
                  <div className="preview-bar">
                    <span>Code quality</span>
                    <i style={{ width: '82%' }} />
                  </div>
                  <div className="preview-bar">
                    <span>Architecture</span>
                    <i style={{ width: '74%' }} />
                  </div>
                  <div className="preview-bar">
                    <span>Testing</span>
                    <i style={{ width: '61%' }} />
                  </div>
                </div>
                <span className="preview-label">Example health view</span>
              </div>
            </article>

            <article className="showcase-panel showcase-arch">
              <div className="showcase-copy">
                <div className="capability-icon">
                  <IconArchitecture />
                </div>
                <h3>Architecture Intelligence</h3>
                <p>
                  Generate an interactive map of modules, APIs, and services grounded in structural
                  evidence from analysis.
                </p>
              </div>
              <div className="showcase-preview arch-preview" aria-hidden>
                <svg viewBox="0 0 320 180" className="arch-mini-svg">
                  <path className="arch-mini-edge" d="M60 40H160V90H250" />
                  <path className="arch-mini-edge" d="M160 90V140H90" />
                  <path className="arch-mini-pulse" d="M60 40H160V90H250" />
                  <rect className="arch-mini-node" x="28" y="22" width="70" height="36" rx="8" />
                  <rect className="arch-mini-node n-accent" x="126" y="72" width="78" height="36" rx="8" />
                  <rect className="arch-mini-node" x="226" y="72" width="70" height="36" rx="8" />
                  <rect className="arch-mini-node" x="58" y="128" width="70" height="36" rx="8" />
                  <text x="42" y="44">
                    frontend
                  </text>
                  <text x="140" y="94">
                    api
                  </text>
                  <text x="242" y="94">
                    service
                  </text>
                  <text x="74" y="150">
                    data
                  </text>
                </svg>
                <span className="preview-label">Example architecture map</span>
              </div>
            </article>

            <article className="showcase-panel showcase-chat">
              <div className="showcase-copy">
                <div className="capability-icon">
                  <IconChat />
                </div>
                <h3>Repository Assistant</h3>
                <p>
                  Ask questions about routes, auth, and design. Answers stay scoped to indexed
                  project context with source file references.
                </p>
              </div>
              <div className="showcase-preview chat-preview" aria-hidden>
                <div className="chat-preview-user">Where is authentication implemented?</div>
                <div className="chat-preview-ai">
                  <p>
                    Authentication is handled in the backend auth module, with login routes and
                    session middleware wired into the app entrypoint.
                  </p>
                  <div className="chat-preview-sources">
                    <span className="source-chip">backend/app/api/routes/auth.py</span>
                    <span className="source-chip">backend/app/services/auth_service.py</span>
                  </div>
                </div>
                <span className="preview-label">Example assistant exchange</span>
              </div>
            </article>
          </div>
        </section>

        <section className="landing-close">
          <p className="eyebrow">Get started</p>
          <h2>Understand what’s inside your repository.</h2>
          <p className="muted">
            Sign in, connect a public GitHub project, and explore health, architecture, and
            grounded chat from the same workspace.
          </p>
          <AuthCta />
        </section>

        <footer className="landing-footer">
          <strong>AI Software Evolution Platform</strong>
          <p>
            An AI developer workspace for analyzing public repositories, mapping architecture, and
            asking evidence-based questions about the code.
          </p>
        </footer>
      </div>
    </PageFade>
  )
}
