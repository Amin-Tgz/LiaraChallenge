/**
 * Answer rendering: Markdown, highlighted code, and a copy button per block.
 *
 * The whole page is RTL, but a shell command is not Persian text and must not
 * be reordered by the bidi algorithm. Every code element is therefore forced
 * `dir="ltr"` and isolated, which is the difference between a runnable command
 * and a scrambled one.
 */

import { useCallback, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import ini from 'highlight.js/lib/languages/ini'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import nginx from 'highlight.js/lib/languages/nginx'
import php from 'highlight.js/lib/languages/php'
import plaintext from 'highlight.js/lib/languages/plaintext'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

/*
 * Registered explicitly rather than pulling `highlight.js/lib/common`, which
 * bundles roughly forty grammars. These are the languages the Liara corpus
 * actually shows — shell, config, and the runtimes the platform supports — and
 * dropping the rest takes a large bite out of what a stuck user has to download
 * before they can read an answer.
 */
for (const [name, language] of [
  ['bash', bash],
  ['dockerfile', dockerfile],
  ['ini', ini],
  ['javascript', javascript],
  ['json', json],
  ['nginx', nginx],
  ['php', php],
  ['plaintext', plaintext],
  ['python', python],
  ['sql', sql],
  ['typescript', typescript],
  ['xml', xml],
  ['yaml', yaml],
] as const) {
  hljs.registerLanguage(name, language)
}
hljs.registerAliases(['sh', 'shell', 'zsh', 'console'], { languageName: 'bash' })
hljs.registerAliases(['yml'], { languageName: 'yaml' })
hljs.registerAliases(['js'], { languageName: 'javascript' })
hljs.registerAliases(['ts'], { languageName: 'typescript' })
hljs.registerAliases(['html'], { languageName: 'xml' })
hljs.registerAliases(['text'], { languageName: 'plaintext' })

type CopyButtonProps = { text: string }

function CopyButton({ text }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)

  const copy = useCallback(() => {
    void navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 2000)
      })
      .catch(() => setCopied(false))
  }, [text])

  return (
    <button type="button" className="copy" onClick={copy} aria-label="کپی کد">
      {copied ? 'کپی شد' : 'کپی'}
    </button>
  )
}

function highlight(code: string, language: string | null): string {
  try {
    if (language && hljs.getLanguage(language)) {
      return hljs.highlight(code, { language }).value
    }
    return hljs.highlightAuto(code).value
  } catch {
    // Highlighting is decoration. If it fails the code still has to be readable,
    // so fall back to escaped plain text rather than losing the block.
    return code.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c] ?? c)
  }
}

type CodeProps = {
  className?: string
  children?: React.ReactNode
}

export function Markdown({ children }: { children: string }) {
  const components = useMemo(
    () => ({
      code({ className, children: content, ...rest }: CodeProps) {
        const text = String(content ?? '').replace(/\n$/, '')
        const match = /language-(\w+)/.exec(className ?? '')
        const isBlock = text.includes('\n') || Boolean(match)

        if (!isBlock) {
          return (
            <code dir="ltr" className="inline-code" {...rest}>
              {text}
            </code>
          )
        }

        return (
          <figure className="code-block">
            <div className="code-toolbar">
              <span className="code-language">{match?.[1] ?? 'code'}</span>
              <CopyButton text={text} />
            </div>
            <pre dir="ltr" tabIndex={0}>
              <code
                className={className}
                /*
                 * Safe despite the name: the only thing ever assigned here is
                 * highlight.js output. Both `highlight` and `highlightAuto`
                 * take a raw string and HTML-escape every character they did
                 * not themselves wrap in a <span class="hljs-*">, so markup
                 * inside an answer or a retrieved code sample renders as text
                 * rather than executing. The catch branch escapes by hand for
                 * the same reason. Nothing else reaches this attribute — in
                 * particular, model output is never passed through unescaped.
                 */
                dangerouslySetInnerHTML={{ __html: highlight(text, match?.[1] ?? null) }}
              />
            </pre>
          </figure>
        )
      },
      /*
       * react-markdown wraps a fenced block in its own <pre>, and the `code`
       * override below returns a <figure>. Left alone that nests a figure
       * inside a pre — invalid HTML, and the outer pre is the one the browser
       * hands back for `pre` selectors, so the dir="ltr" on ours would not be
       * the one that applies. Unwrapping here leaves exactly one <pre>: mine.
       */
      pre({ children: content }: { children?: React.ReactNode }) {
        return <>{content}</>
      },
      a({ href, children: content }: { href?: string; children?: React.ReactNode }) {
        return (
          <a href={href} target="_blank" rel="noreferrer noopener">
            {content}
          </a>
        )
      },
    }),
    [],
  )

  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
