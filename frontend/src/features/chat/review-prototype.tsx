/** 独立双栏审查原型：虚构数据，仅内存状态，不调用业务 API。 */
import { useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowLeft, Check, ChevronLeft, ChevronRight, FileSpreadsheet, LockKeyhole, LockKeyholeOpen, MessageSquare, RotateCcw, Search, ShieldCheck, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription, EmptyMedia } from '@/components/ui/empty'
import { Field, FieldLabel } from '@/components/ui/field'
import { SegmentedTabs } from '@/components/segmented-tabs'
import { cn } from '@/lib/utils'
import '@/index.css'

type SaveMeta = { name: string; description: string }
type Mode = 'source' | 'ai'
type Stage = 'review' | 'paused' | 'done' | 'rejected'
type Cell = { id: string; value: string; name: string; sheet: string; row: number; col: number }
const headings = ['服务', '地址', '账号', '密码', '说明']
const rows = [
 ['资料库', 'https://docs.example.test', 'demo_reader', 'DEMO-pass-A', '团队共享文档'],
 ['测试数据库', '192.0.2.20', 'demo_db', 'DEMO-pass-B', '仅用于测试'],
 ['备份服务', 'https://backup.example.test', 'demo_backup', 'DEMO-pass-C', '每周自动备份'],
 ['设计素材', 'https://design.example.test', 'demo_design', 'DEMO-pass-A', '与资料库共用密码'],
 ['家庭相册', 'https://photos.example.test', 'demo_family', 'DEMO-pass-E', '家庭记录'],
]
const personal = [['示例联系人', 'person@example.test', 'TEST-ID-0001', 'DEMO-CODE-01', '演示用资料']]
const all: Cell[] = [...rows.flatMap((r,i)=>r.map((value,col)=>({id:`main-${i}-${col}`,value,name: col===3?`${r[0]}密码`:headings[col],sheet:'服务账号',row:i+2,col}))), ...personal.flatMap((r,i)=>r.map((value,col)=>({id:`person-${i}-${col}`,value,name:['姓名','邮箱','证件编号','恢复码','备注'][col],sheet:'个人资料',row:i+2,col})))]
const initial = Object.fromEntries(all.filter(c=>['main-0-3','main-1-3','main-3-3','person-0-1','person-0-2'].includes(c.id)).map(c=>[c.id,c.name]))
function Demo(){
 const [stage,setStage]=useState<Stage>('review')
 const [format,setFormat]=useState('excel')
 const [sheet,setSheet]=useState('服务账号')
 const [selected,setSelected]=useState<string[]>([])
 const [protectedCells,setProtected]=useState<Record<string,string>>({...initial})
 const [metadata,setMetadata]=useState<Record<string,SaveMeta>>({})
 const [undoStack,setUndo]=useState<{protectedCells:Record<string,string>;metadata:Record<string,SaveMeta>}[]>([])
 const paneRefs=useRef<Partial<Record<Mode,HTMLDivElement>>>({})
 const [query,setQuery]=useState('')
 const [notice,setNotice]=useState('')
 const [reject,setReject]=useState(false)
 const cells=all.filter(c=>c.sheet===sheet)
 const chosen=all.filter(c=>selected.includes(c.id))
 const count=Object.keys(protectedCells).length
 const suffix=format==='excel'?'xlsx':format==='word'?'docx':'pdf'
 function remember(){setUndo(h=>[...h.slice(-29),{protectedCells:{...protectedCells},metadata:{...metadata}}])}
 function meta(c:Cell):SaveMeta {return metadata[c.id] || {name:protectedCells[c.id]||c.name,description:''}}
 function updateMeta(c:Cell,key:keyof SaveMeta,value:string){remember();setMetadata(p=>({...p,[c.id]:{...meta(c),[key]:value}}));setNotice('设置已更新')}
 function undo(){const last=undoStack.at(-1);if(!last)return;setProtected(last.protectedCells);setMetadata(last.metadata);setUndo(h=>h.slice(0,-1));setNotice('已撤销')}
 function mark(ids:string[], remove=false){remember();setProtected(p=>{const n={...p};ids.forEach(id=>{if(remove)delete n[id];else n[id]=p[id]||all.find(c=>c.id===id)!.name});return n});setNotice(remove?'已取消保护，所选内容将明文发送给 AI':`已保护 ${ids.length} 处。`)}
 function syncScroll(m:Mode,target:HTMLElement){
  const other=paneRefs.current[m==='source'?'ai':'source'];if(!other)return;
  const destination=target.dataset.slot==='table-container'?other.querySelector<HTMLElement>('[data-slot="table-container"]'):other;
  if(destination){if(destination.scrollTop!==target.scrollTop)destination.scrollTop=target.scrollTop;if(destination.scrollLeft!==target.scrollLeft)destination.scrollLeft=target.scrollLeft}
 }
 const invalidNames=all.filter(c=>protectedCells[c.id]&&!meta(c).name.trim())
 function reset(){setMetadata({});setUndo([]);setProtected({...initial});setSelected([]);setStage('review');setQuery('');setReject(false);setNotice('')}
 function pick(c:Cell,shift:boolean){setSelected(old=>shift ? old.includes(c.id)?old.filter(id=>id!==c.id):[...old,c.id]:[c.id])}
 function next(delta:number){const ids=all.filter(c=>protectedCells[c.id]);const idx=ids.findIndex(c=>c.id===selected[0]);const c=ids[(idx+delta+ids.length)%ids.length];if(c){setSheet(c.sheet);setSelected([c.id]);requestAnimationFrame(()=>{document.getElementById('cell-source-'+c.id)?.scrollIntoView({block:'nearest',inline:'center'});document.getElementById('cell-ai-'+c.id)?.scrollIntoView({block:'nearest',inline:'center'})})}}
 const display=(c:Cell,m:Mode)=>m==='ai'&&protectedCells[c.id]?`🔒 ${meta(c).name.trim()||'未命名引用'}`:c.value
 function documentView(m:Mode){return <div ref={el=>{paneRefs.current[m]=el || undefined}} onScrollCapture={e=>syncScroll(m,e.target as HTMLElement)} className="min-w-0 flex-1 overflow-auto bg-background">
  {format==='excel'?<Table className="w-full min-w-[800px] table-fixed"><TableHeader><TableRow><TableHead className="w-10 bg-muted/50">行</TableHead>{(sheet==='服务账号'?headings:['姓名','邮箱','证件编号','恢复码','备注']).map((h,i)=><TableHead key={h} className="bg-muted/50"><button className="flex w-full items-center justify-between gap-4 py-3 text-left" onClick={()=>{setSelected(cells.filter(c=>c.col===i).map(c=>c.id));setNotice(`已选中「${h}」列`)}} title="点击选择整列">{h}<span className="font-mono text-xs text-muted-foreground">{String.fromCharCode(65+i)}</span></button></TableHead>)}</TableRow></TableHeader><TableBody>{Array.from(new Set(cells.map(c=>c.row))).map(row=><TableRow key={row}><TableCell className="bg-muted/30 text-center font-mono text-xs text-muted-foreground">{row}</TableCell>{cells.filter(c=>c.row===row).map(c=><TableCell key={c.id} className="border-l p-0"><button id={'cell-'+m+'-'+c.id} title={display(c,m)} onClick={e=>pick(c,e.shiftKey)} className={cn('flex h-14 w-full items-center gap-2 px-4 py-3 text-left text-sm transition-colors hover:bg-accent',protectedCells[c.id]&&(m==='ai'?'bg-emerald-200/70 hover:bg-emerald-200':'bg-emerald-100/60 hover:bg-emerald-100'),selected.includes(c.id)&&'ring-2 ring-inset ring-ring',query&&c.value.toLowerCase().includes(query.toLowerCase())&&'bg-amber-100')}>
  {protectedCells[c.id]&&m==='source'&&<LockKeyhole className="size-3.5 shrink-0 text-emerald-600"/>}<span className={cn('truncate',c.col===3&&'font-mono text-xs',protectedCells[c.id]&&m==='ai'&&'rounded-md border border-emerald-600/25 bg-emerald-100 px-2.5 py-1.5 font-semibold text-emerald-950')}>{display(c,m)}</span></button></TableCell>)}</TableRow>)}</TableBody></Table>:<article className="mx-auto my-8 max-w-2xl border bg-background p-8 shadow-sm"><p className="text-xs text-muted-foreground">{format==='pdf'?'PDF · 第 1 页 / 共 1 页':'Word · 正文'}</p><h2 className="mt-8 text-2xl font-semibold">家庭数字资料备忘</h2><p className="my-6 leading-8">这份备忘记录家庭使用的服务及其登录信息。</p>{[0,1,2,4].map((r)=><div key={r} className="my-6"><h3 className="mb-2 font-medium">{r+1}. {rows[r][0]}</h3><p className="leading-9">登录地址：{rows[r][1]}<br/>账号：{rows[r][2]}<br/>密码：{(()=>{const c=all.find(c=>c.id===`main-${r}-3`)!;return <button className={cn('rounded px-2',protectedCells[c.id]?'border border-emerald-600/25 bg-emerald-200/70 font-semibold text-emerald-950':'bg-muted',selected.includes(c.id)&&'ring-2 ring-ring')} onClick={e=>pick(c,e.shiftKey)}>{display(c,m)}</button>})()}</p></div>)}</article>}
  </div>}
 return <div className="flex h-svh flex-col overflow-hidden bg-background text-foreground">
 <header className="flex shrink-0 items-center justify-between gap-3 border-b px-6 py-3"><div className="flex items-center gap-3"><Button variant="ghost" size="icon-sm" aria-label="返回对话" onClick={()=>setStage('paused')}><ArrowLeft/></Button><span className="font-semibold">资料审查</span><Badge variant="outline" title="虚构资料，仅本机内存交互，不发送或保存真实数据">交互原型</Badge></div><span className="text-xs text-muted-foreground">知守</span></header>
 <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
 {stage!=='review'?<div className="mx-auto max-w-2xl py-24"><Empty><EmptyHeader><EmptyMedia variant="icon">{stage==='done'?<Check/>:<MessageSquare/>}</EmptyMedia><EmptyTitle>{stage==='done'?'已确认':stage==='rejected'?'已拒绝导入':'待确认资料'}</EmptyTitle><EmptyDescription>{stage==='done'?`已确认 ${count} 处保护。本原型未执行实际保存。`:stage==='rejected'?'本次暂存已清除。':'审查进度已保留。'}</EmptyDescription></EmptyHeader><Button variant="outline" onClick={()=>stage==='paused'?setStage('review'):reset()}>{stage==='paused'?'继续审查':'返回审查'}</Button></Empty></div>
 :<><section className="flex shrink-0 flex-wrap items-center justify-between gap-3 px-6 py-4"><div className="flex items-center gap-3"><FileSpreadsheet className="size-5 text-muted-foreground"/><h1 className="text-lg font-semibold">家庭数字资料.{suffix}</h1><span className="flex items-center gap-1 text-xs text-muted-foreground"><Check className="size-3.5 text-emerald-600"/>校验通过</span></div><SegmentedTabs size="sm" value={format} onChange={v=>{setFormat(v);setSelected([]);setSheet('服务账号')}} options={[{value:'excel',label:'Excel'},{value:'word',label:'Word'},{value:'pdf',label:'PDF'}]}/></section>
 <div className="flex flex-wrap items-center justify-between gap-3 border-y bg-background px-7 py-3"><div className="flex items-center gap-3">{format==='excel'&&<><span className="text-sm text-muted-foreground">工作表</span><SegmentedTabs size="sm" value={sheet} onChange={v=>{setSheet(v);setSelected([])}} options={[{value:'服务账号',label:'服务账号'},{value:'个人资料',label:'个人资料'}]}/></>}<span className="text-xs text-muted-foreground">已保护 {count} 处</span><Button size="icon-sm" variant="ghost" aria-label="上一处标记" disabled={!count} onClick={()=>next(-1)}><ChevronLeft/></Button><Button size="icon-sm" variant="ghost" aria-label="下一处标记" disabled={!count} onClick={()=>next(1)}><ChevronRight/></Button></div><div className="flex items-center gap-2"><Search className="size-4 text-muted-foreground"/><Input className="h-8 w-44" placeholder="查找内容（高亮）" value={query} onChange={e=>setQuery(e.target.value)}/></div></div>
 <div className="flex shrink-0 items-center gap-2 border-b border-destructive/20 bg-destructive/5 px-6 py-3 text-sm font-medium text-destructive"><ShieldCheck className="size-4 shrink-0"/>请核对右侧内容，未保护的信息将明文发送给 AI。</div>
 <div className="grid min-h-[280px] flex-1 grid-cols-2 divide-x">{(['source','ai'] as Mode[]).map(m=><div key={m} className="flex min-h-0 min-w-0 flex-col"><h3 className={cn("flex items-center justify-between border-b px-5 py-3 text-sm font-semibold",m==='ai'?'bg-emerald-50':'bg-muted/30')}><span>{m==='source'?'本机原文':'发送给 AI'}</span><Badge variant="outline">{m==='source'?'只读原文':'实时预览'}</Badge></h3>{documentView(m)}</div>)}</div>
 {chosen.length>0&&<section className="shrink-0 border-t bg-background px-6 py-3" aria-label="所选内容与保存设置">
 <div className="mb-3 flex items-center justify-between gap-3"><h3 className="text-sm font-semibold">{chosen[0].sheet}{chosen.length>1?` · 已选 ${chosen.length} 处`:''}</h3><div className="flex items-center gap-2">{chosen.length>1&&<><Button size="sm" variant="outline" disabled={!chosen.some(c=>!protectedCells[c.id])} onClick={()=>mark(selected)}>保护所选</Button><Button size="sm" variant="outline" className="border-destructive/40 text-destructive hover:bg-destructive/5 hover:text-destructive" disabled={!chosen.some(c=>protectedCells[c.id])} onClick={()=>mark(selected,true)}>取消所选保护</Button></>}<Button variant="ghost" size="icon-sm" aria-label="清除选择" onClick={()=>setSelected([])}><X/></Button></div></div>
 <div className="max-h-48 space-y-3 overflow-y-auto">{chosen.map(c=><div key={c.id} className="flex flex-wrap items-end gap-3"><Badge variant="outline" className="mb-2">{String.fromCharCode(c.col+65)}{c.row}</Badge>{protectedCells[c.id]?<>
 {([['name','名称'],['description','备注（可选）']] as const).map(([key,label])=><Field key={key} className="min-w-40 flex-1 gap-2"><FieldLabel htmlFor={`${c.id}-${key}`}>{label}</FieldLabel><Input id={`${c.id}-${key}`} maxLength={80} value={meta(c)[key]} aria-invalid={key==='name'&&!meta(c).name.trim()} onChange={e=>updateMeta(c,key,e.target.value)}/></Field>)}
 <Button variant="outline" className="border-destructive/40 text-destructive hover:bg-destructive/5 hover:text-destructive" title="取消后，此内容将明文发送给 AI" onClick={()=>mark([c.id],true)}><LockKeyholeOpen data-icon="inline-start"/>取消保护</Button>
 </>:<><p className="mb-2 flex-1 text-sm text-muted-foreground">未保护 · 将明文发送</p><Button variant="outline" onClick={()=>mark([c.id])}><LockKeyhole data-icon="inline-start"/>保护内容</Button></>}</div>)}</div>
 </section>}
 {invalidNames.length>0&&<p role="alert" className="px-6 py-2 text-sm text-destructive">名称不能为空，请补全后继续。</p>}
 <footer className="flex shrink-0 items-center justify-between gap-4 border-t bg-background px-6 py-3"><div className="flex items-center gap-3">{undoStack.length>0&&<Button variant="outline" size="sm" onClick={undo}><RotateCcw data-icon="inline-start"/>撤销</Button>}<p role="status" className="text-xs text-muted-foreground">{notice}</p></div><div className="flex gap-2"><Button variant="ghost" className="text-destructive" onClick={()=>setReject(true)}>拒绝导入</Button><Button disabled={invalidNames.length>0} className="bg-emerald-600 text-white hover:bg-emerald-700" onClick={()=>setStage('done')}>确认并继续</Button></div></footer>{reject&&<div className="flex flex-wrap items-center justify-between gap-3 border-t bg-background px-7 py-4"><p className="text-sm">拒绝并清除本次暂存资料？</p><div className="flex gap-2"><Button variant="outline" onClick={()=>setReject(false)}>继续检查</Button><Button variant="destructive" onClick={()=>{setProtected({});setStage('rejected');setReject(false)}}>确定拒绝</Button></div></div>}</>}
 </main></div>
}
createRoot(document.getElementById('root')!).render(<Demo/> )
