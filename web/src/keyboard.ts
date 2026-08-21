import type { KeyboardEvent } from 'react'

/** Enter submits; Shift+Enter keeps the multiline escape hatch. */
export function submitTextareaOnEnter(event: KeyboardEvent<HTMLTextAreaElement>): void {
  if (
    event.key !== 'Enter' ||
    event.shiftKey ||
    event.nativeEvent.isComposing
  ) {
    return
  }
  event.preventDefault()
  event.currentTarget.form?.requestSubmit()
}
