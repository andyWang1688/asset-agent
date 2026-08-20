import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useApp } from '@/store/app-context'
import { useWiki } from '@/hooks/use-wiki'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { Markdown } from '@/lib/markdown'
import { cn } from '@/lib/utils'

/** 设计稿目录顺序 */
const WIKI_CATS_ORDER = [
  { key: 'projects', label: '项目' },
  { key: 'entities', label: '实体' },
  { key: 'analyses', label: '分析' },
  { key: 'sources', label: '来源' },
  { key: 'concepts', label: '概念' },
] as const

type Wiki = ReturnType<typeof useWiki>

function catOf(path: string): string {
  for (const c of WIKI_CATS_ORDER) {
    if (path.startsWith(c.key + '/')) return c.label
  }
  return '知识库'
}

/** 取正文第一段作为摘要（dek） */
function firstParagraph(content: string): string {
  const line = content
    .split('\n')
    .map((l) => l.trim())
    .find((l) => l && !/^#{1,6}\s/.test(l) && !/^[-*]\s/.test(l) && !/^>\s/.test(l))
  if (!line) return ''
  const text = line.replace(/[*_`[\]]/g, '').trim()
  return text.length > 90 ? text.slice(0, 90) + '…' : text
}

function WikiNav({ wiki }: { wiki: Wiki }) {
  const { pages, path, open } = wiki
  const [query, setQuery] = useState('')
  const [closed, setClosed] = useState<Set<string>>(new Set())
  const [rootClosed, setRootClosed] = useState(false)

  const visible = pages.filter((p) => {
    const name = p.path.split('/').pop()
    return name !== 'index.md' && name !== 'log.md'
  })

  const q = query.trim()
  const hit = (p: { path: string; title: string }) => !q || p.path.includes(q) || (p.title || '').includes(q)

  return (
    <aside className="flex min-w-0 flex-col border-r border-border bg-bg p-3 max-[820px]:max-h-[40vh] max-[820px]:border-b max-[820px]:border-r-0">
      <input
        className="h-8 w-full rounded-pill border border-border bg-surface px-3 text-caption outline-none transition-[border-color] duration-150 focus:border-fg/45"
        placeholder="搜索知识页"
        aria-label="搜索知识页"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="flex items-center gap-2 px-2.5 pb-2 pt-5 text-caption font-semibold">
        <button
          type="button"
          aria-label="折叠全部目录"
          onClick={() => setRootClosed(!rootClosed)}
          className="text-caption text-muted transition-colors duration-150 hover:text-fg"
        >
          ⌄
        </button>
        <span>知识库</span>
      </div>
      <div className={cn('min-h-0 flex-1 overflow-y-auto', rootClosed && 'hidden')}>
        {WIKI_CATS_ORDER.map((cat) => {
          const docs = visible.filter((p) => p.path.startsWith(cat.key + '/'))
          const shown = docs.filter(hit)
          const isClosed = closed.has(cat.key)
          if (q && shown.length === 0) return null
          return (
            <div key={cat.key}>
              <button
                type="button"
                onClick={() =>
                  setClosed((prev) => {
                    const next = new Set(prev)
                    if (next.has(cat.key)) next.delete(cat.key)
                    else next.add(cat.key)
                    return next
                  })
                }
                className="flex w-full items-center gap-2 rounded-sm px-2.5 py-2 text-left text-caption font-semibold text-fg transition-colors duration-150 hover:bg-soft"
              >
                <span className={cn('inline-block transition-transform duration-200', isClosed && '-rotate-90')}>⌄</span>
                <span>{cat.label}</span>
                <span className="ml-auto font-mono text-meta text-muted">{String(docs.length).padStart(2, '0')}</span>
              </button>
              <div className={cn('pl-4', isClosed && 'hidden')}>
                {shown.length === 0 && <p className="py-1 pl-2.5 text-caption text-muted">（暂无文档）</p>}
                {shown.map((d) => (
                  <button
                    key={d.path}
                    type="button"
                    title={d.path}
                    onClick={() => void open(d.path)}
                    className={cn(
                      'tree-file block w-full truncate rounded-sm px-2.5 py-1.5 text-left font-mono text-caption transition-colors duration-150 before:mr-2 before:inline-block before:w-3 before:opacity-65 before:content-["·"]',
                      path === d.path ? 'bg-fg font-semibold text-surface' : 'text-muted hover:bg-soft hover:text-fg',
                    )}
                  >
                    {d.title || d.path.split('/').pop()}
                  </button>
                ))}
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-3 border-t border-border px-2.5 py-3">
        <Button
          variant="link"
          size="sm"
          className="h-auto p-0 text-caption"
          onClick={() => {
            void wiki.rebuild().then(() => toast.success('索引已重建'))
          }}
        >
          重建索引
        </Button>
      </div>
    </aside>
  )
}

function WikiReader({ wiki }: { wiki: Wiki }) {
  const { doc, path, loading, error, pages } = wiki
  if (!doc && !loading) {
    return (
      <article className="flex items-center justify-center px-8 py-14">
        <p className="text-caption text-muted">{error || '选择左侧的文档开始阅读'}</p>
      </article>
    )
  }
  if (loading) {
    return (
      <article className="px-8 py-14">
        <div className="flex flex-col gap-3">
          <div className="h-6 w-1/3 animate-pulse rounded-md bg-soft" />
          <div className="h-3 w-1/4 animate-pulse rounded-md bg-soft" />
          <div className="mt-4 h-3 w-full animate-pulse rounded-md bg-soft" />
          <div className="h-3 w-5/6 animate-pulse rounded-md bg-soft" />
        </div>
      </article>
    )
  }
  const meta = pages.find((p) => p.path === doc!.path)
  const title = meta?.title || doc!.path.split('/').pop()?.replace(/\.md$/, '') || doc!.path
  const dek = firstParagraph(doc!.content)
  return (
    <article
      key={path}
      className="max-h-[calc(100vh-210px)] min-w-0 overflow-y-auto px-[clamp(32px,6vw,88px)] py-[54px] max-[820px]:max-h-none max-[820px]:px-5 max-[820px]:py-9 max-[480px]:px-4"
    >
      <div className="animate-[doc-in_0.3s_ease-out]">
        <div className="mb-5 font-mono text-meta text-muted">{catOf(path || '')}</div>
        <h2 className="text-[clamp(32px,3.2vw,44px)] font-bold leading-[1.3]">{title}</h2>
        {dek && <p className="mt-3 max-w-[58ch] text-input leading-[1.7] text-muted">{dek}</p>}
        <hr className="my-6 border-t border-border" />
        <div className="min-w-0">
          <Markdown content={doc!.content} onWikiLink={(p) => void wiki.open(p)} />
        </div>
        <div className="mt-8 border-t border-border pt-4 text-caption text-muted">
          <b className="mr-1.5 font-semibold text-fg">路径</b>
          {doc!.path}
        </div>
      </div>
    </article>
  )
}

export function WikiPage() {
  const { wikiPath } = useApp()
  const wiki = useWiki()
  const isMobile = useIsMobile(820)
  const [showNav, setShowNav] = useState(false)

  // 问答引用 / Wiki 内链跳转：切换到知识库并打开对应文档
  useEffect(() => {
    if (wikiPath) {
      void wiki.open(wikiPath)
      setShowNav(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wikiPath])

  const navVisible = useMemo(() => !isMobile || showNav, [isMobile, showNav])

  return (
    <>
      <h1 className="page-heading">知识库</h1>
      <p className="page-sub">浏览模型维护的知识页。</p>
      {isMobile && (
        <Button variant="link" size="sm" className="mt-2 h-auto p-0 text-caption" onClick={() => setShowNav(!showNav)}>
          {showNav ? '收起目录' : '打开目录'}
        </Button>
      )}
      <div className="mt-7 grid min-h-[590px] grid-cols-[264px_minmax(0,1fr)] overflow-hidden rounded-lg border border-border bg-surface shadow-panel max-[820px]:grid-cols-1 max-[820px]:overflow-visible">
        {navVisible && <WikiNav wiki={wiki} />}
        <WikiReader wiki={wiki} />
      </div>
    </>
  )
}
