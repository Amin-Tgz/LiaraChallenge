/**
 * The sources an answer rests on.
 *
 * Citations are shown by page title and section rather than as a bare URL,
 * because "کدام صفحه؟" is the question a stuck user actually has. Each link
 * deep-links to the section anchor the evidence came from.
 */

import type { Citation, ChatImage } from '../api/types'

export function Citations({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null

  return (
    <section className="citations" aria-labelledby="citations-heading">
      <h3 id="citations-heading">منابع</h3>
      <ol>
        {citations.map((citation) => (
          <li key={citation.evidence_id}>
            <a href={citation.url} target="_blank" rel="noreferrer noopener">
              {citation.page_title ?? citation.url}
              {citation.section_title && (
                <span className="section"> › {citation.section_title}</span>
              )}
            </a>
          </li>
        ))}
      </ol>
    </section>
  )
}

/**
 * An illustration beside the step it belongs to.
 *
 * A broken image must never take the answer down with it: on error the figure
 * collapses to its alt text, which still tells the reader what they were meant
 * to see.
 */
export function Figures({ images }: { images: ChatImage[] }) {
  if (images.length === 0) return null

  return (
    <div className="figures">
      {images.map((image) => (
        <figure key={image.url}>
          <img
            src={image.url}
            alt={image.alt ?? image.caption ?? 'تصویر مستندات'}
            loading="lazy"
            onError={(event) => {
              const element = event.currentTarget
              element.classList.add('broken')
              // Replaced by its alt text rather than left as a broken icon.
              element.style.display = 'none'
              element.insertAdjacentText(
                'afterend',
                element.alt || 'تصویر در دسترس نیست',
              )
            }}
          />
          {image.caption && <figcaption>{image.caption}</figcaption>}
        </figure>
      ))}
    </div>
  )
}
