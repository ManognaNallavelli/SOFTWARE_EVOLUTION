import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type Props = {
  open: boolean
  onClose: () => void
  children: ReactNode
}

/**
 * Right-side drawer that stays mounted while closed so the chat thread survives
 * opening, closing and switching workspace pages.
 */
export function CopilotDrawer({ open, onClose, children }: Props) {
  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  return createPortal(
    <>
      <div
        className={`copilot-backdrop${open ? ' is-open' : ''}`}
        aria-hidden
        onClick={onClose}
      />
      <aside
        id="copilot-drawer"
        className={`copilot-drawer${open ? ' is-open' : ''}`}
        role="complementary"
        aria-labelledby="copilot-title"
        aria-hidden={!open}
        inert={!open}
      >
        {children}
      </aside>
    </>,
    document.body,
  )
}
