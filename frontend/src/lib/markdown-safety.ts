/** 链接仅允许 http(s)、协议相对、相对路径与锚点。 */
export function safeUrl(u: string): string {
  const s = String(u ?? '').trim()
  if (/^(https?:)?\/\//i.test(s)) return s
  if (/^[a-z][a-z0-9+.-]*:/i.test(s)) return '#'
  return s
}

/** 图片仅允许相对本地路径，阻止任何协议 URL。 */
export function safeImgUrl(u: string): string | null {
  const s = String(u ?? '').trim()
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(s)) return null
  return s
}

/** 将 Wiki 双链语法转换为内部 wiki: 链接。 */
export function preprocessWikiLinks(md: string): string {
  return String(md ?? '')
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '[$2](wiki:$1)')
    .replace(/\[\[([^\]]+)\]\]/g, '[$1](wiki:$1)')
}
