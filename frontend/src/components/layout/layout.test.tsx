import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { EmptyState, FormRow, LoadingState, NavHighlight, PageShell, PageTransition, SectionCard, SegmentedControl } from '.'

describe('layout components', () => {
  it('renders page and section structure with token classes', () => {
    const markup = renderToStaticMarkup(
      <PageShell title="页面" description="说明">
        <SectionCard title="区域">内容</SectionCard>
      </PageShell>,
    )
    expect(markup).toContain('<h1')
    expect(markup).toContain('页面')
    expect(markup).toContain('<h2')
    expect(markup).toContain('var(--spacing-page)')
    expect(markup).toContain('rounded-lg')
  })

  it('connects form errors to the control area', () => {
    const markup = renderToStaticMarkup(<FormRow label="名称" htmlFor="name" error="请输入名称" control={<input id="name" />} />)
    expect(markup).toContain('aria-describedby="name-error"')
    expect(markup).toContain('id="name-error" role="alert"')
  })

  it('exposes segmented selection and active navigation', () => {
    const markup = renderToStaticMarkup(
      <>
        <SegmentedControl value="a" options={[{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }]} onChange={() => undefined} label="模式" />
        <NavHighlight active>设置</NavHighlight>
      </>,
    )
    expect(markup).toContain('aria-pressed="true"')
    expect(markup).toContain('aria-current="page"')
  })

  it('provides empty, loading, and transition states', () => {
    const markup = renderToStaticMarkup(
      <>
        <EmptyState title="暂无内容" description="稍后再试" />
        <LoadingState label="正在加载" />
        <PageTransition pageKey="test">内容区</PageTransition>
      </>,
    )
    expect(markup).toContain('暂无内容')
    expect(markup).toContain('role="status"')
    expect(markup).toContain('正在加载')
    expect(markup).toContain('内容区')
  })
})
