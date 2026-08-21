/**
 * The sources an answer rests on.
 *
 * Citations are shown by page title and section rather than as a bare URL,
 * because "کدام صفحه؟" is the question a stuck user actually has. Each link
 * deep-links to the section anchor the evidence came from.
 */

import { useState } from 'react'
import type { Citation, ChatImage } from '../api/types'

type CitationsProps = {
  citations: Citation[]
  images?: ChatImage[]
}

export function Citations({ citations, images = [] }: CitationsProps) {
  if (citations.length === 0 && images.length === 0) return null

  const associated = new Set(
    images.map((image) => image.evidence_id).filter((value): value is string => Boolean(value)),
  )
  const unassociated = images.filter(
    (image) => !image.evidence_id || !citations.some((item) => item.evidence_id === image.evidence_id),
  )

  return (
    <section className="citations" aria-labelledby="citations-heading">
      <h3 id="citations-heading">منابع</h3>
      {citations.length > 0 && (
        <ol>
          {citations.map((citation) => (
            <li key={citation.evidence_id}>
              <a href={citation.url} target="_blank" rel="noreferrer noopener">
                {citation.page_title ?? citation.url}
                {citation.section_title && (
                  <span className="section"> › {citation.section_title}</span>
                )}
              </a>
              {associated.has(citation.evidence_id) && (
                <Figures
                  images={images.filter((image) => image.evidence_id === citation.evidence_id)}
                />
              )}
            </li>
          ))}
        </ol>
      )}
      <Figures images={unassociated} />
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
        <DocumentationFigure key={`${image.evidence_id ?? 'unassociated'}:${image.url}`} image={image} />
      ))}
    </div>
  )
}

function DocumentationFigure({ image }: { image: ChatImage }) {
  const [failed, setFailed] = useState(false)
  const alternative = image.alt?.trim() || image.caption?.trim() || 'تصویر مستندات'

  return (
    <figure>
      {failed ? (
        <p className="image-fallback" role="img" aria-label={alternative}>
          <span>تصویر در دسترس نیست:</span> {alternative}
        </p>
      ) : (
        <img
          src={image.url}
          alt={alternative}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
      {image.caption && image.caption.trim() !== alternative && (
        <figcaption>{image.caption}</figcaption>
      )}
    </figure>
  )
}
