import { marked } from 'marked'
import { useMemo } from 'react'

marked.setOptions({ breaks: true, gfm: true })

export function MarkdownContent({ content, className }: { content: string; className?: string }) {
  const html = useMemo(() => marked.parse(content) as string, [content])
  return <div className={`markdown-content ${className ?? ''}`} dangerouslySetInnerHTML={{ __html: html }} />
}
