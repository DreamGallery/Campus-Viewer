import type { DocTask } from './workflow'

export type StoryKind =
  | 'cidol'
  | 'csprt'
  | 'dear'
  | 'event'
  | 'pstory'
  | 'pevent'
  | 'other'
export type DocStatus =
  | '待翻译'
  | '翻译中'
  | '待校对'
  | '校对中'
  | '已完成'
  | '已存档'

export const STORY_LABELS: Record<StoryKind, string> = {
  cidol: '角色卡剧情',
  csprt: '辅助卡剧情',
  dear: '亲密度剧情',
  event: '活动剧情',
  pstory: '培养故事',
  pevent: '培养事件',
  other: '其他剧情',
}

export function storyKind(title: string): StoryKind {
  return (title
    .match(/(?:^|[_-])(cidol|csprt|dear|event|pstory|pevent)(?:[_-]|$)/i)?.[1]
    .toLowerCase() || 'other') as StoryKind
}

export function docStatus(d: DocTask, archived = false): DocStatus {
  if (archived) return '已存档'
  if (d.tr.state !== '完成')
    return d.tr.state === '进行中' ? '翻译中' : '待翻译'
  if (d.pr.state !== '完成')
    return d.pr.state === '进行中' ? '校对中' : '待校对'
  return '已完成'
}

// 按原文入库日（GMT+8）分页：一天一页，新的在前，无时间的归到最后一页
export function groupDocsByDate(docs: DocTask[]): [string, DocTask[]][] {
  const groups = new Map<string, DocTask[]>()
  for (const d of docs) {
    const iso = d.sourceCommitTime || d.updatedAt || ''
    const key = iso
      ? new Date(iso).toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
      : ''
    const bucket = groups.get(key)
    if (bucket) bucket.push(d)
    else groups.set(key, [d])
  }
  return [...groups].sort(([a], [b]) => (!a ? 1 : !b ? -1 : b.localeCompare(a)))
}

export function datePageLabel(key: string, count: number): string {
  return `${key ? key.slice(5).replace('-', '/') : '未知时间'}（${count}）`
}

export function matchesDocFilters(
  d: DocTask,
  story: StoryKind | 'all',
  status: DocStatus | 'all',
  search: string,
  archived = false
) {
  return (
    (story === 'all' || storyKind(d.title) === story) &&
    (status === 'all' || docStatus(d, archived) === status) &&
    d.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())
  )
}
