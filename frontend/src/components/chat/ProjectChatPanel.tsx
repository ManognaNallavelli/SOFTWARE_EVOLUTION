import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { AnswerContent } from '../AnswerContent'
import { StatusBanner } from '../common/StatusBanner'
import { IconSpark } from '../icons'
import { formatUserError } from '../../lib/errors'
import { ApiError } from '../../services/api'
import { chatWithProject, getRagStatus } from '../../services/ragService'
import type {
  AnalysisFileRef,
  ChatContext,
  ChatMessage,
  RagIndexStatus,
  RagStatus,
  WorkspacePage,
} from '../../types/rag'

type Props = {
  projectId: string
  /**
   * Bumped after analysis completes or the code index is rebuilt; re-reads and follows index
   * status until it settles, without discarding the thread.
   */
  indexEpoch?: number
  /** Stored analysis results exist, so analysis questions work without the code index. */
  analysisAvailable: boolean
  /** Repository analysis is running; the code index is built automatically afterwards. */
  analyzing?: boolean
  context?: ChatContext
  contextLabel?: string | null
  onClearContext?: () => void
  onClose?: () => void
  /** Changing this value focuses the question input. */
  focusSignal?: number
}

const PAGE_SUGGESTIONS: Record<WorkspacePage, string[]> = {
  overview: [
    'Summarize this page',
    'What are the biggest problems in this repository?',
    'Which technologies does this repository use?',
    'Which API routes exist?',
  ],
  health: [
    'Why is the health score what it is?',
    'What should we fix first?',
    'Explain the security findings.',
    'Which categories have insufficient data?',
  ],
  architecture: [
    'Explain the architecture.',
    'How do the components connect?',
    'Where are the API routes defined?',
    'Which files handle database access?',
  ],
}

const HEALTH_SELECTION_PROMPTS = ['Explain this.', 'Why was this flagged?', 'How do I fix this?']
const CODE_SELECTION_PROMPTS = ['Explain this.', 'What depends on this?', 'Show me the relevant code.']

const MAX_INPUT_HEIGHT = 160

const INDEX_STAGES = ['Cloning', 'Chunking', 'Embedding', 'Ready'] as const
const INDEX_POLL_MS = 2000
// Auto-indexing starts in the background just after analysis responds, so keep polling
// briefly even if the previous status is still "ready"/"failed"/"not_indexed".
const INDEX_WATCH_GRACE_MS = 8000
const INDEX_WATCH_MAX_MS = 180_000

function indexStageIndex(status: RagIndexStatus | undefined, message?: string | null): number {
  if (status === 'ready') return 3
  if (status !== 'indexing') return 0
  const text = (message || '').toLowerCase()
  if (text.startsWith('embedding')) return 2
  if (text.startsWith('chunking')) return 1
  return 0
}

function statusLabel(status: RagIndexStatus, analysisAvailable: boolean): string {
  switch (status) {
    case 'ready':
      return 'Code search ready'
    case 'indexing':
      return 'Indexing code'
    case 'failed':
      return analysisAvailable ? 'Analysis only' : 'Unavailable'
    default:
      return analysisAvailable ? 'Analysis only' : 'Not ready'
  }
}

function indexReason(status: RagIndexStatus | undefined): string {
  switch (status) {
    case 'indexing':
      return 'still being built'
    case 'failed':
      return 'unavailable because indexing failed'
    default:
      return 'not built yet'
  }
}

function uniqueSourceFiles(sources: NonNullable<ChatMessage['sources']>): string[] {
  const seen = new Set<string>()
  const files: string[] = []
  for (const src of sources) {
    const path = src.file_path.trim()
    if (!path || seen.has(path)) continue
    seen.add(path)
    files.push(path)
  }
  return files
}

function formatFileRef(ref: AnalysisFileRef): string {
  if (ref.line == null) return ref.file_path
  if (ref.end_line != null && ref.end_line !== ref.line) {
    return `${ref.file_path}:${ref.line}-${ref.end_line}`
  }
  return `${ref.file_path}:${ref.line}`
}

function formatLines(start?: number | null, end?: number | null): string {
  if (start == null) return ''
  return end != null && end !== start ? `:${start}-${end}` : `:${start}`
}

export function ProjectChatPanel({
  projectId,
  indexEpoch = 0,
  analysisAvailable,
  analyzing = false,
  context,
  contextLabel,
  onClearContext,
  onClose,
  focusSignal,
}: Props) {
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null)
  const [sending, setSending] = useState(false)
  const [waitSeconds, setWaitSeconds] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({})
  const [settledEpoch, setSettledEpoch] = useState(0)
  const scrollerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const watchStartRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    watchStartRef.current = Date.now()
    async function refresh() {
      try {
        const status = await getRagStatus(projectId)
        if (!cancelled) setRagStatus(status)
      } catch (err) {
        if (!cancelled) {
          setError(formatUserError(err, 'Failed to load assistant status'))
        }
      }
    }
    void refresh()
    return () => {
      cancelled = true
    }
  }, [projectId, indexEpoch])

  useEffect(() => {
    if (!sending) {
      setWaitSeconds(0)
      return
    }
    setWaitSeconds(0)
    const timer = window.setInterval(() => {
      setWaitSeconds((s) => s + 1)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [sending])

  const indexStatus = ragStatus?.status
  const watching = indexEpoch > settledEpoch

  useEffect(() => {
    if (indexStatus !== 'indexing' && !watching) return
    const timer = window.setInterval(() => {
      void (async () => {
        let latest: RagStatus
        try {
          latest = await getRagStatus(projectId)
        } catch {
          return // ignore transient poll errors
        }
        setRagStatus(latest)
        if (!watching) return
        const elapsed = Date.now() - watchStartRef.current
        const settled = latest.status === 'ready' || latest.status === 'failed'
        if (
          (settled && elapsed >= INDEX_WATCH_GRACE_MS) ||
          (latest.status !== 'indexing' && elapsed >= INDEX_WATCH_MAX_MS)
        ) {
          setSettledEpoch(indexEpoch)
        }
      })()
    }, INDEX_POLL_MS)
    return () => window.clearInterval(timer)
  }, [projectId, indexStatus, watching, indexEpoch])

  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages, sending])

  useEffect(() => {
    if (focusSignal == null) return
    inputRef.current?.focus()
  }, [focusSignal])

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_HEIGHT)}px`
  }, [draft])

  const ready = indexStatus === 'ready'
  const preparing = indexStatus === 'indexing' || (watching && !ready)
  const stageIdx = indexStageIndex(indexStatus, ragStatus?.message)
  const canAsk = !sending && (ready || analysisAvailable)
  const hasSelection = Boolean(context?.health_item || context?.file_path || context?.architecture_node_id)

  async function sendQuestion(text: string) {
    const cleaned = text.trim()
    if (!cleaned || !canAsk) return
    setSending(true)
    setError(null)
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: 'user',
        content: cleaned,
        context_label: hasSelection ? (contextLabel ?? null) : null,
      },
    ])
    setDraft('')
    try {
      const result = await chatWithProject(projectId, cleaned, context)
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: result.answer,
          sources: result.sources,
          context_insufficient: result.context_insufficient,
          analysis_findings: result.analysis_findings ?? [],
          analysis_notes: result.analysis_notes ?? [],
          context_applied: result.context_applied ?? null,
        },
      ])
    } catch (err) {
      if (err instanceof ApiError && (err.code === 'rag_not_ready' || err.code === 'rag_empty_index')) {
        setMessages((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: 'assistant',
            content:
              `This question needs code search, and the code index is ${indexReason(indexStatus)}. ` +
              (analysisAvailable
                ? 'I can still answer from the stored analysis: health, issues, recommendations, architecture, routes and the detected stack.'
                : 'Use Refresh Repository in the workspace header to prepare it.'),
            context_insufficient: true,
          },
        ])
        try {
          setRagStatus(await getRagStatus(projectId))
        } catch {
          // keep the previous status
        }
      } else {
        const message = formatUserError(err, 'Chat failed')
        setError(message)
        setMessages((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: 'assistant',
            content: `I could not complete that request: ${message}`,
          },
        ])
      }
    } finally {
      setSending(false)
    }
  }

  async function handleSend(event: FormEvent) {
    event.preventDefault()
    await sendQuestion(draft)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void sendQuestion(draft)
    }
  }

  function startNewChat() {
    setMessages([])
    setExpandedSources({})
    setError(null)
  }

  const selectionPrompts = context?.health_item ? HEALTH_SELECTION_PROMPTS : CODE_SELECTION_PROMPTS
  const emptySuggestions = hasSelection
    ? selectionPrompts
    : PAGE_SUGGESTIONS[context?.page ?? 'overview']

  return (
    <div className="copilot-panel">
      <header className="copilot-head">
        <div className="copilot-title">
          <IconSpark className="copilot-title-icon" />
          <h2 id="copilot-title">AI Copilot</h2>
          <span
            className={`status-chip status-${preparing || analyzing ? 'indexing' : indexStatus || 'not_indexed'}`}
          >
            {analyzing
              ? 'Analyzing'
              : preparing
                ? 'Indexing code'
                : ragStatus
                  ? statusLabel(indexStatus ?? 'not_indexed', analysisAvailable)
                  : 'Checking…'}
          </span>
        </div>
        <div className="copilot-head-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={messages.length === 0 || sending}
            onClick={startNewChat}
          >
            New chat
          </button>
          {onClose ? (
            <button
              type="button"
              className="btn btn-ghost btn-icon copilot-close"
              aria-label="Close AI Copilot"
              onClick={onClose}
            >
              <span aria-hidden>×</span>
            </button>
          ) : null}
        </div>
      </header>

      <div className="copilot-banners">
        {error && <StatusBanner onDismiss={() => setError(null)}>{error}</StatusBanner>}
        {analyzing && !preparing && (
          <StatusBanner tone="info">
            Analyzing the repository… Code search will be built automatically when analysis
            finishes.
          </StatusBanner>
        )}
        {preparing && (
          <StatusBanner tone="info">
            <div className="index-progress">
              <span>
                <strong>Building code search</strong>
                {' · '}
                {indexStatus === 'indexing' && ragStatus?.message ? ragStatus.message : 'Starting…'}
              </span>
              <div className="arch-pipeline index-pipeline" aria-live="polite">
                {INDEX_STAGES.map((stage, idx) => (
                  <span
                    key={stage}
                    className={`arch-stage${idx <= stageIdx ? ' is-done' : ''}${idx === stageIdx ? ' is-current' : ''}`}
                  >
                    {stage}
                  </span>
                ))}
              </div>
              {analysisAvailable ? (
                <span>You can already ask about health, issues, architecture, routes and the stack.</span>
              ) : null}
            </div>
          </StatusBanner>
        )}
        {ragStatus && !ready && !preparing && !analyzing && analysisAvailable && (
          <StatusBanner tone="info">
            Code search is {indexReason(indexStatus)}. You can still ask about health, issues,
            architecture, routes and the detected stack; questions that need source code will say so.
          </StatusBanner>
        )}
        {ragStatus && !ready && !preparing && !analyzing && !analysisAvailable && (
          <StatusBanner tone="info">
            No analysis or code index is available yet. Use Refresh Repository in the workspace
            header to prepare them.
          </StatusBanner>
        )}
        {indexStatus === 'failed' && ragStatus?.error && !analysisAvailable && (
          <StatusBanner>{ragStatus.error}</StatusBanner>
        )}
      </div>

      <div className="copilot-messages" ref={scrollerRef} aria-live="polite">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <h3>Ask about this repository</h3>
            <div className="suggestion-row" aria-label="Suggested questions">
              {emptySuggestions.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="suggestion-chip"
                  disabled={!canAsk}
                  onClick={() => void sendQuestion(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg) => {
            if (msg.role === 'user') {
              return (
                <article key={msg.id} className="chat-bubble chat-user">
                  {msg.context_label ? (
                    <span className="chat-context-tag">About: {msg.context_label}</span>
                  ) : null}
                  <p>{msg.content}</p>
                </article>
              )
            }
            const sources = msg.sources ?? []
            const sourceFiles = uniqueSourceFiles(sources)
            const findings = msg.analysis_findings ?? []
            const notes = msg.analysis_notes ?? []
            const grounded = sourceFiles.length > 0 || findings.length > 0
            const expanded = Boolean(expandedSources[msg.id])
            return (
              <article key={msg.id} className="chat-bubble chat-assistant">
                {grounded || msg.context_applied ? (
                  <div className="chat-grounded-row">
                    {grounded ? <span className="grounded-badge">Repository grounded</span> : null}
                    {msg.context_applied ? (
                      <span className="chat-context-used">Used context: {msg.context_applied}</span>
                    ) : null}
                  </div>
                ) : null}
                <div className="chat-answer">
                  <AnswerContent text={msg.content} />
                </div>
                {notes.length > 0 ? (
                  <ul className="chat-notes">
                    {notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                ) : null}
                {msg.context_insufficient && notes.length === 0 ? (
                  <p className="muted small chat-insufficient">
                    Context may be insufficient for a precise answer.
                  </p>
                ) : null}
                {grounded ? (
                  <div className="chat-sources">
                    <button
                      type="button"
                      className="sources-toggle"
                      aria-expanded={expanded}
                      onClick={() =>
                        setExpandedSources((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                      }
                    >
                      <span className="sources-toggle-label">Sources</span>
                      <span className="sources-toggle-meta muted">
                        {findings.length > 0
                          ? `${findings.length} ${findings.length === 1 ? 'finding' : 'findings'}`
                          : ''}
                        {findings.length > 0 && sourceFiles.length > 0 ? ' · ' : ''}
                        {sourceFiles.length > 0
                          ? `${sourceFiles.length} ${sourceFiles.length === 1 ? 'file' : 'files'}`
                          : ''}
                      </span>
                      <span
                        className={`sources-toggle-chevron${expanded ? ' is-open' : ''}`}
                        aria-hidden
                      />
                    </button>
                    {expanded ? (
                      <div className="source-groups">
                        {findings.length > 0 ? (
                          <section>
                            <span className="sources-label">Analysis findings</span>
                            <ul className="source-file-list">
                              {findings.map((finding) => (
                                <li key={finding.id} className="source-file-item">
                                  <span className="source-finding-title">
                                    <span className="source-id">{finding.id}</span>
                                    {finding.title}
                                  </span>
                                  <span className="source-file-excerpt muted small">
                                    {finding.detail}
                                  </span>
                                  {finding.file_refs.length > 0 ? (
                                    <span className="source-refs">
                                      {finding.file_refs.map((ref) => (
                                        <code key={formatFileRef(ref)}>{formatFileRef(ref)}</code>
                                      ))}
                                    </span>
                                  ) : null}
                                </li>
                              ))}
                            </ul>
                          </section>
                        ) : null}
                        {sources.length > 0 ? (
                          <section>
                            <span className="sources-label">Code</span>
                            <ul className="source-file-list">
                              {sources.map((src, idx) => (
                                <li key={`${src.file_path}-${idx}`} className="source-file-item">
                                  <span className="source-file-path">
                                    {src.file_path}
                                    {formatLines(src.start_line, src.end_line)}
                                    {src.supports?.length ? (
                                      <span className="source-supports">
                                        supports {src.supports.join(', ')}
                                      </span>
                                    ) : null}
                                  </span>
                                  {src.excerpt ? (
                                    <span className="source-file-excerpt muted small">
                                      {src.excerpt}
                                    </span>
                                  ) : null}
                                </li>
                              ))}
                            </ul>
                          </section>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </article>
            )
          })
        )}
        {sending && (
          <div className="chat-thinking">
            <span className="thinking-dots" aria-hidden>
              <i />
              <i />
              <i />
            </span>
            <span>
              Looking through repository evidence
              {waitSeconds > 0 ? `… ${waitSeconds}s` : '…'}
              {waitSeconds >= 20 ? ' Longer answers can take up to a minute.' : ''}
            </span>
          </div>
        )}
      </div>

      {contextLabel ? (
        <div className="copilot-context">
          <div className="copilot-context-row">
            <span className="copilot-context-label">Context</span>
            <span className="copilot-context-value" title={contextLabel}>
              {contextLabel}
            </span>
            {onClearContext && hasSelection ? (
              <button
                type="button"
                className="copilot-context-clear"
                aria-label="Clear selection"
                onClick={onClearContext}
              >
                ×
              </button>
            ) : null}
          </div>
          {hasSelection && messages.length > 0 ? (
            <div className="copilot-quick-row">
              {selectionPrompts.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="suggestion-chip"
                  disabled={!canAsk}
                  onClick={() => void sendQuestion(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <form className="copilot-compose" onSubmit={(e) => void handleSend(e)}>
        <textarea
          ref={inputRef}
          className="chat-input copilot-input"
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          aria-label="Ask the AI Copilot"
          placeholder={
            ready
              ? 'Ask anything about this repository…'
              : analysisAvailable
                ? 'Ask about health, architecture, routes or the stack…'
                : 'Refresh Repository to prepare the assistant…'
          }
          disabled={!ready && !analysisAvailable}
        />
        <button type="submit" className="btn btn-primary" disabled={!canAsk || !draft.trim()}>
          {sending ? 'Sending…' : 'Send'}
        </button>
      </form>
      <p className="copilot-hint muted">Enter to send · Shift+Enter for a new line</p>
    </div>
  )
}
