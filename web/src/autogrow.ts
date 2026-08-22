import { useLayoutEffect, useRef } from 'react'

/**
 * Grow a textarea with its content, up to a hard ceiling of `maxRows` lines.
 *
 * Past the ceiling the box stops growing and the earlier lines scroll up out of
 * it, so the composer can never push the conversation off the screen. The
 * ceiling is measured from the element's own computed line height rather than
 * assumed, so it stays right when the font or the zoom level changes.
 */
export function useAutoGrowingTextarea(
  value: string,
  maxRows = 3,
): React.RefObject<HTMLTextAreaElement> {
  const ref = useRef<HTMLTextAreaElement>(null)

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return

    const styles = getComputedStyle(element)
    const lineHeight = Number.parseFloat(styles.lineHeight)
    if (!Number.isFinite(lineHeight)) return

    // `box-sizing: border-box` is global here, and `scrollHeight` counts
    // padding but not borders — so the borders are added back by hand.
    const padding =
      Number.parseFloat(styles.paddingBlockStart) +
      Number.parseFloat(styles.paddingBlockEnd)
    const borders =
      Number.parseFloat(styles.borderBlockStartWidth) +
      Number.parseFloat(styles.borderBlockEndWidth)
    const ceiling = lineHeight * maxRows + padding + borders

    // Collapse first: `scrollHeight` never reports less than the set height.
    element.style.height = 'auto'
    const wanted = element.scrollHeight + borders
    element.style.height = `${Math.min(wanted, ceiling)}px`
    element.style.overflowY = wanted > ceiling ? 'auto' : 'hidden'
  }, [value, maxRows])

  return ref
}
