import { describe, expect, it } from 'vitest'
import { safeUrl, safeImgUrl, preprocessWikiLinks } from './markdown'

describe('safeUrl', () => {
  it('允许 http/https 与协议相对', () => {
    expect(safeUrl('https://example.com/a?b=1&c=2')).toBe('https://example.com/a?b=1&c=2')
    expect(safeUrl('http://example.com')).toBe('http://example.com')
    expect(safeUrl('//example.com/p')).toBe('//example.com/p')
  })
  it('允许相对路径与锚点', () => {
    expect(safeUrl('/wiki/foo.md')).toBe('/wiki/foo.md')
    expect(safeUrl('./foo.md')).toBe('./foo.md')
    expect(safeUrl('#anchor')).toBe('#anchor')
  })
  it('阻止危险协议', () => {
    expect(safeUrl('javascript:alert(1)')).toBe('#')
    expect(safeUrl('JavaScript:alert(1)')).toBe('#')
    expect(safeUrl('data:text/html,<script>')).toBe('#')
    expect(safeUrl('vbscript:msgbox')).toBe('#')
    expect(safeUrl('file:///etc/passwd')).toBe('#')
  })
})

describe('safeImgUrl', () => {
  it('仅允许相对本地路径', () => {
    expect(safeImgUrl('assets/logo.png')).toBe('assets/logo.png')
    expect(safeImgUrl('./x.png')).toBe('./x.png')
  })
  it('阻止一切协议（含 https 远程与 data）', () => {
    expect(safeImgUrl('https://example.com/x.png')).toBeNull()
    expect(safeImgUrl('//example.com/x.png')).toBeNull()
    expect(safeImgUrl('data:image/png;base64,AAAA')).toBeNull()
    expect(safeImgUrl('javascript:alert(1)')).toBeNull()
  })
})

describe('preprocessWikiLinks', () => {
  it('转换 [[path|标题]] 与 [[path]]', () => {
    expect(preprocessWikiLinks('见 [[concepts/a.md|概念 A]] 与 [[projects/b.md]]')).toBe(
      '见 [概念 A](wiki:concepts/a.md) 与 [projects/b.md](wiki:projects/b.md)',
    )
  })
})
