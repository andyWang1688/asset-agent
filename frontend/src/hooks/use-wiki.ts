import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { WikiDoc, WikiPage } from '@/lib/types'

/** 知识库：目录树 + 文档阅读（/api/wiki/pages、/api/wiki/page、/api/wiki/rebuild） */
export function useWiki(initialPath?: string | null) {
  const [pages, setPages] = useState<WikiPage[]>([])
  const [loaded, setLoaded] = useState(false)
  const [path, setPath] = useState<string | null>(initialPath ?? null)
  const [doc, setDoc] = useState<WikiDoc | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRef(0)

  const load = useCallback(async () => {
    setLoaded(false)
    setError(null)
    try {
      const rows = await api.wikiPages()
      setPages(rows)
    } catch (e) {
      setPages([])
      setError(e instanceof Error ? e.message : '知识库加载失败')
    } finally {
      setLoaded(true)
    }
  }, [])

  const open = useCallback(async (p: string) => {
    const id = ++requestId.current
    setPath(p)
    setDoc(null)
    setLoading(true)
    setError(null)
    try {
      const page = await api.wikiPage(p)
      if (id === requestId.current) setDoc(page)
    } catch (e) {
      if (id !== requestId.current) return
      setDoc(null)
      setError(e instanceof Error ? e.message : '页面加载失败')
    } finally {
      if (id === requestId.current) setLoading(false)
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
