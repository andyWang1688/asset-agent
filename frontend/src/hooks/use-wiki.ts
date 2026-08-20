import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { WikiDoc, WikiPage } from '@/lib/types'

export const WIKI_CATS = [
  { key: 'concepts', label: '概念' },
  { key: 'entities', label: '实体' },
  { key: 'projects', label: '项目' },
  { key: 'analyses', label: '分析' },
  { key: 'sources', label: '来源' },
] as const

/** 知识库：目录树 + 文档阅读（/api/wiki/pages、/api/wiki/page、/api/wiki/rebuild） */
export function useWiki(initialPath?: string | null) {
  const [pages, setPages] = useState<WikiPage[]>([])
  const [loaded, setLoaded] = useState(false)
  const [path, setPath] = useState<string | null>(initialPath ?? null)
  const [doc, setDoc] = useState<WikiDoc | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const rows = await api.wikiPages()
      setPages(rows)
      setLoaded(true)
    } catch {
      setPages([])
    }
  }, [])

  const open = useCallback(async (p: string) => {
    setPath(p)
    setLoading(true)
    setError(null)
    try {
      setDoc(await api.wikiPage(p))
    } catch (e) {
      setDoc(null)
      setError(e instanceof Error ? e.message : '页面加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const rebuild = useCallback(async () => {
    await api.wikiRebuild()
    await load()
  }, [load])

  useEffect(() => {
    void load()
  }, [load])

  return { pages, loaded, path, doc, loading, error, load, open, rebuild }
}
