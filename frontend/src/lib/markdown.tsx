import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'
import { preprocessWikiLinks, safeImgUrl, safeUrl } from '@/lib/markdown-safety'

interface MarkdownProps {
  content: string
  onWikiLink?: (path: string) => void
  className?: string
}

/** 安全 Markdown 渲染：不启用 rehype-raw / dangerouslySetInnerHTML；
    协议过滤、外链 rel、远程图片阻止都在这里统一处理。 */
export function Markdown({ content, onWikiLink, className }: MarkdownProps) {
  const src = preprocessWikiLinks(content)
  return (
    <div className={cn('md-body', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => safeUrl(url)}
        components={{
          a: ({ href, children, node: _node, ...props }) => {
            if (href && href.startsWith('wiki:')) {
              const path = href.slice(5)
              return (
                <a
                  className="wikilink"
                  href="#"
                  onClick={(e) => {
                    e.preventDefault()
                    onWikiLink?.(path)
                  }}
                  {...props}
                >
                  {children}
                </a>
              )
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" {...props}>
                {children}
              </a>
            )
          },
          img: ({ src, alt }) => {
            const u = src ? safeImgUrl(src) : null
            if (!u) {
              return (
                <span className="img-blocked" title="远程图片已阻止加载">
                  🖼 {alt || '图片'}
                </span>
              )
            }
            return <img src={u} alt={alt ?? ''} loading="lazy" />
          },
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {src}
      </ReactMarkdown>
    </div>
  )
}
