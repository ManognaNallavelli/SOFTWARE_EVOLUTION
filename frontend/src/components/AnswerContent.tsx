import type { ReactNode } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Raw HTML in model output is never rendered (react-markdown ignores it without rehype-raw).
const MARKDOWN_COMPONENTS: Components = {
  pre: ({ children }) => <pre className="answer-code">{children}</pre>,
  ul: ({ children }) => <ul className="answer-list">{children}</ul>,
  ol: ({ children }) => <ol className="answer-list">{children}</ol>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="answer-table-wrap">
      <table>{children}</table>
    </div>
  ),
}

/** Renders assistant answers as Markdown (GFM: bold, lists, code, tables). */
export function AnswerContent({ text }: { text: string }) {
  return (
    <div className="answer-content">
      <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {text}
      </Markdown>
    </div>
  )
}

export function PageFade({ children }: { children: ReactNode }) {
  return <div className="page-fade">{children}</div>
}
