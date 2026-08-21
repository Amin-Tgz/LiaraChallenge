/**
 * Conversations and rescue tools, in one persistent rail.
 *
 * History used to live in a grid at the bottom of the landing page, which meant
 * it was only reachable by going home first and scrolling. Putting it beside the
 * conversation makes "the thing I asked yesterday" one click away from the
 * thing being asked now — and it is the only place history is shown, so there is
 * no second copy to keep in sync.
 *
 * On a phone the same markup becomes a drawer. Not a separate component: two
 * implementations of one list is how the two drift apart.
 */

import { useEffect, useRef, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import type { ConversationSummary } from '../api/types'

type Props = {
  conversations: ConversationSummary[]
  /** Drawer state. Ignored on desktop, where the rail is always laid out. */
  open: boolean
  onClose: () => void
  onDeleteConversation: (id: string) => Promise<void>
}

export function Sidebar({ conversations, open, onClose, onDeleteConversation }: Props) {
  const navigate = useNavigate()
  const panel = useRef<HTMLDivElement | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  // Moving focus into the drawer is what makes it usable without a mouse; the
  // caller returns focus to the toggle when it closes.
  useEffect(() => {
    if (open) panel.current?.focus()
  }, [open])

  function startFresh() {
    onClose()
    navigate('/')
  }

  async function removeConversation(id: string, title: string) {
    if (!window.confirm(`گفت‌وگوی «${title}» حذف شود؟ این کار قابل بازگشت نیست.`)) return
    setDeleting(id)
    setDeleteError(null)
    try {
      await onDeleteConversation(id)
    } catch (cause) {
      setDeleteError(cause instanceof Error ? cause.message : 'حذف گفت‌وگو انجام نشد.')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <>
      {open && <div className="sidebar-scrim" onClick={onClose} aria-hidden="true" />}
      <div
        className={'sidebar' + (open ? ' sidebar-open' : '')}
        ref={panel}
        tabIndex={-1}
      >
        <nav aria-label="گفت‌وگوها و ابزارها">
          <button type="button" className="new-chat" onClick={startFresh}>
            <PlusIcon />
            گفت‌وگوی جدید
          </button>

          <div className="sidebar-section">
            <h2 className="sidebar-heading" id="history-heading">
              <HistoryIcon />
              گفت‌وگوهای پیشین
            </h2>
            {conversations.length === 0 ? (
              <p className="sidebar-empty">هنوز گفت‌وگویی شروع نکرده‌اید.</p>
            ) : (
              <ul className="sidebar-list" aria-labelledby="history-heading">
                {conversations.map((conversation) => (
                  <li key={conversation.id} className="conversation-item">
                    <button
                      type="button"
                      className="delete-conversation"
                      disabled={deleting === conversation.id}
                      aria-label={`حذف گفت‌وگوی ${conversation.title ?? conversation.initial_question}`}
                      title="حذف گفت‌وگو"
                      onClick={() =>
                        void removeConversation(
                          conversation.id,
                          conversation.title ?? conversation.initial_question,
                        )
                      }
                    >
                      <TrashIcon />
                    </button>
                    <NavLink
                      to={'/chat/' + conversation.id}
                      onClick={onClose}
                      className={({ isActive }) => (isActive ? 'active' : undefined)}
                    >
                      <span className="sidebar-item-title">
                        {conversation.title ?? conversation.initial_question}
                      </span>
                      <small>{conversation.message_count} پیام</small>
                    </NavLink>
                  </li>
                ))}
              </ul>
            )}
            {deleteError && (
              <p className="sidebar-delete-error" role="alert">
                {deleteError}
              </p>
            )}
          </div>

          <div className="sidebar-section sidebar-tools">
            <h2 className="sidebar-heading" id="tools-heading">
              <ToolsIcon />
              ابزارهای دستیار
            </h2>
            <ul className="sidebar-list" aria-labelledby="tools-heading">
              <li>
                <NavLink
                  to="/tools/skill"
                  onClick={onClose}
                  className={({ isActive }) => (isActive ? 'active' : undefined)}
                >
                  <span className="sidebar-item-title">
                    <SkillIcon />
                    Skill لیارا
                  </span>
                  <small>برای دستیار کدنویسی</small>
                </NavLink>
              </li>
              <li>
                <NavLink
                  to="/tools/mcp"
                  onClick={onClose}
                  className={({ isActive }) => (isActive ? 'active' : undefined)}
                >
                  <span className="sidebar-item-title">
                    <McpIcon />
                    سرور MCP
                  </span>
                  <small>جست‌وجو به‌عنوان ابزار</small>
                </NavLink>
              </li>
            </ul>
          </div>
        </nav>
      </div>
    </>
  )
}

function HistoryIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 12a8 8 0 1 0 2.34-5.66L4 8.68M4 4v4.68h4.68M12 8v4l2.75 1.75" />
    </svg>
  )
}

function ToolsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m12 3 1.15 3.1L16 7.5l-2.85 1.4L12 12l-1.15-3.1L8 7.5l2.85-1.4L12 3ZM5.5 13l.8 2.2 2.2.8-2.2.8L5.5 19l-.8-2.2-2.2-.8 2.2-.8.8-2.2ZM18 13l.65 1.85L20.5 15.5l-1.85.65L18 18l-.65-1.85-1.85-.65 1.85-.65L18 13Z" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
    </svg>
  )
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function SkillIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 6h16M4 12h10M4 18h7" />
    </svg>
  )
}

function McpIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="6" cy="12" r="2.5" />
      <circle cx="18" cy="6" r="2.5" />
      <circle cx="18" cy="18" r="2.5" />
      <path d="M8.2 10.8 15.8 7.2M8.2 13.2l7.6 3.6" />
    </svg>
  )
}
