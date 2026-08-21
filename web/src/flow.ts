/**
 * The one thing the rescue flow must never lose: the original question.
 *
 * A user moving between related questions, rescue tools, and chat should never
 * be asked to retype what they already wrote — including across a reload, which
 * discards router state. `sessionStorage` is the right scope: it survives a
 * refresh and dies with the tab.
 */

const QUESTION_KEY = 'rescue.question'
const DRAFT_KEY = 'rescue.next-question'

export function rememberQuestion(question: string): void {
  try {
    sessionStorage.setItem(QUESTION_KEY, question)
  } catch {
    // Private-browsing modes can refuse storage. The in-memory router state
    // still carries the question; only reload-resilience is lost.
  }
}

export function recallQuestion(): string {
  try {
    return sessionStorage.getItem(QUESTION_KEY) ?? ''
  } catch {
    return ''
  }
}

export function forgetQuestion(): void {
  try {
    sessionStorage.removeItem(QUESTION_KEY)
  } catch {
    /* nothing to clean up */
  }
}

export function rememberNextQuestion(question: string): void {
  try {
    sessionStorage.setItem(DRAFT_KEY, question)
  } catch {
    /* navigation still works; only the draft handoff is unavailable */
  }
}

export function recallNextQuestion(): string {
  try {
    return sessionStorage.getItem(DRAFT_KEY) ?? ''
  } catch {
    return ''
  }
}

export function forgetNextQuestion(): void {
  try {
    sessionStorage.removeItem(DRAFT_KEY)
  } catch {
    /* nothing to clean up */
  }
}
