import { useEffect, useState } from 'react'
import { ChevronRight, FileText, Menu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { useWiki } from '@/hooks/use-wiki'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { Markdown } from '@/lib/markdown'
import { useApp } from '@/store/app-state'
import { cn } from '@/lib/utils'

const WIKI_CATS = [
  { key: 'projects', label: '项目' },
  { key: 'entities', label: '实体' },
  { key: 'analyses', label: '分析' },
  { key: 'sources', label: '来源' },
  { key: 'concepts', label: '概念' },
] as const

type Wiki = ReturnType<typeof useWiki>

function fileName(path: string): string {
  return path.split('/').pop() || path
}

function catLabelOf(path: string): string {
  for (const c of WIKI_CATS) {
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

function WikiTree({ wiki, onNavigate }: { wiki: Wiki; onNavigate?: () => void }) {
  const { pages, path, open } = wiki
  const [query, setQuery] = useState('')
  const [closed, setClosed] = useState<Set<string>>(new Set())
  const q = query.trim().toLowerCase()

  const visible = pages.filter((p) => {
    const name = fileName(p.path)
    return name !== 'index.md' && name !== 'log.md'
  })

  return (
    <div className="flex h-full flex-col">
      <div className="p-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索知识页"
          aria-label="搜索知识页"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {WIKI_CATS.map((cat) => {
          const docs = visible.filter(
            (p) =>
              p.path.startsWith(cat.key + '/') &&
              (!q || p.path.toLowerCase().includes(q) || (p.title || '').toLowerCase().includes(q)),
          )
          if (q && docs.length === 0) return null
          const isClosed = closed.has(cat.key)
          return (
            <div key={cat.key} className="mb-1">
              <Collapsible
                open={q ? true : !isClosed}
                onOpenChange={(o) =>
                  setClosed((prev) => {
                    const next = new Set(prev)
                    if (o) next.delete(cat.key)
                    else next.add(cat.key)
                    return next
                  })
                }
              >
                <CollapsibleTrigger className="flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
                  <ChevronRight className={cn('size-3 shrink-0 transition-transform', !isClosed && 'rotate-90')} />
                  <span>{cat.label}</span>
                  <span className="ml-auto font-mono">{String(docs.length).padStart(2, '0')}</span>
                </CollapsibleTrigger>
                <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
                  {docs.map((p) => (
                    <button
                      key={p.path}
                      type="button"
                      title={p.path}
                      onClick={() => {
                        void open(p.path)
                        onNavigate?.()
                      }}
                      className={cn(
                        'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent',
                        path === p.path && 'bg-accent font-medium',
                      )}
                    >
                      <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate">{p.title || fileName(p.path)}</span>
                    </button>
                  ))}
                </CollapsibleContent>
              </Collapsible>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function WikiReaderSkeleton() {
  return (
    <article className="mx-auto w-full max-w-3xl px-6 py-8">
      <Skeleton className="h-3 w-10 rounded-sm" />
      <Skeleton className="mt-3 h-8 w-2/3 max-w-64 rounded-sm" />
      <Skeleton className="mt-3 h-4 w-full max-w-xl rounded-sm" />
      <Separator className="my-6" />
      <div className="flex flex-col gap-3">
        <Skeleton className="h-4 w-full rounded-sm" />
        <Skeleton className="h-4 w-11/12 rounded-sm" />
        <Skeleton className="h-4 w-4/5 rounded-sm" />
        <Skeleton className="mt-3 h-5 w-40 rounded-sm" />
        <Skeleton className="h-4 w-full rounded-sm" />
        <Skeleton className="h-4 w-2/3 rounded-sm" />
      </div>
    </article>
  )
}

function WikiReader({ wiki }: { wiki: Wiki }) {
  const { doc, pages, loading, error } = wiki
  const { openPrivateRef } = useApp()

  if (loading) return <WikiReaderSkeleton />

  if (!doc) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileText />
          </EmptyMedia>
          <EmptyTitle>暂无文档</EmptyTitle>
          <EmptyDescription>{error || '选择左侧的知识页开始阅读。'}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const meta = pages.find((p) => p.path === doc.path)
  const title = meta?.title || fileName(doc.path).replace(/\.md$/, '')
  const dek = firstParagraph(doc.content)

  return (
    <article className="mx-auto w-full max-w-3xl px-6 py-8">
      <p className="font-mono text-xs text-muted-foreground">{catLabelOf(doc.path)}</p>
      <h1 className="mt-2 text-2xl font-semibold">{title}</h1>
      {dek && <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{dek}</p>}
      <Separator className="my-6" />
      <Markdown content={doc.content} onWikiLink={(p) => void wiki.open(p)} onPrivateRef={openPrivateRef} />
      <div className="mt-8 border-t pt-4 text-xs text-muted-foreground">
        <span className="mr-1.5 font-semibold text-foreground">路径</span>
        <span>{doc.path}</span>
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

  return (
    <div className={cn('flex min-h-0 w-full flex-1', isMobile ? 'flex-col' : 'flex-row')}>
      {isMobile && (
        <div className="flex shrink-0 items-center border-b px-2 py-1.5">
          <Button variant="ghost" size="sm" aria-expanded={showNav} onClick={() => setShowNav((v) => !v)}>
            <Menu data-icon="inline-start" />
            {showNav ? '收起目录' : '目录'}
          </Button>
        </div>
      )}
      {(!isMobile || showNav) && (
        <aside className={cn('shrink-0 border-r', isMobile ? 'h-[40vh] w-full border-b border-r-0' : 'w-60')}>
          <WikiTree wiki={wiki} onNavigate={isMobile ? () => setShowNav(false) : undefined} />
        </aside>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <WikiReader wiki={wiki} />
      </div>
    </div>
  )
}
