import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

/**
 * 链接 URL 白名单：仅 http(s)、协议相对与相对路径/锚点。
 * javascript:、data:、vbscript: 等其余协议一律替换为 #。
 * 链接允许 http(s) 是因为跳转由用户主动点击触发，不产生自动请求。
 */
export function safeUrl(u: string): string {
  const s = String(u ?? '').trim()
  if (/^(https?:)?\/\//i.test(s)) return s
  if (/^[a-z][a-z0-9+.-]*:/i.test(s)) return '#'
  return s
}

/** 图片 URL 白名单：仅允许相对本地路径；任何协议一律阻止（渲染时会产生自动请求）。 */
export function safeImgUrl(u: string): string | null {
  const s = String(u ?? '').trim()
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(s)) return null
  return s
}

/** [[path|标题]] / [[path]] → 内部 wiki: 链接，交给 react-markdown 的 a 渲染器处理 */
export function preprocessWikiLinks(md: string): string {
  return String(md ?? '')
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '[$2](wiki:$1)')
    .replace(/\[\[([^\]]+)\]\]/g, '[$1](wiki:$1)')
}

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
