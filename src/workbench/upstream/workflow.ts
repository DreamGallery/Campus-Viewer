import { mergeScriptText } from '../script-text'
/* eslint-disable @typescript-eslint/no-explicit-any */
// Adapted from chihya72/gakumas-viewer; MIT license in ./LICENSE.
// 汉化工作台配置：工作仓库 + 双轨认领模型（翻译 / 校对）
//
// 每篇剧情 = 一个 GitHub Issue。issue body 里嵌两条独立轨道标记：
//   <!-- tr:<用户>:<状态> -->   翻译轨
//   <!-- pr:<用户>:<状态> -->   校对轨
// 状态 ∈ 待认领 / 进行中 / 完成。两轨互不依赖：待翻译时校对也能提前认领；
// 一个人可两轨都接，也可两人分接。issue 的 assignees = 两轨认领人的并集（便于 GitHub 侧可见 + 我的任务过滤）。
// 文件路径用阶段目录标记；旧 issue 的 <!-- path: data/... --> 仍可兼容。

import { extractInfoFromCsvText, setCsvTranslator } from './csv'
import { storyKind } from './document-filter'

export const WORK_OWNER = import.meta.env.VITE_WORK_OWNER || 'chihya72'
export const WORK_REPO =
  import.meta.env.VITE_WORK_REPO || 'gakumas-translation-work'
export const WORK_BRANCH = import.meta.env.VITE_WORK_BRANCH || 'main'

export const STATES = ['待认领', '进行中', '完成'] as const
export type TrackState = (typeof STATES)[number]

export type TrackKey = 'tr' | 'pr'
export const TRACK_LABEL: Record<TrackKey, string> = { tr: '翻译', pr: '校对' }

export interface Track {
  user: string
  state: TrackState
}

let workUsers: Record<string, { github?: string; qq?: string }> = {}

let usersVersion = 0
const userListeners = new Set<() => void>()
export const subscribeWorkUsers = (listener: () => void) => { userListeners.add(listener); return () => { userListeners.delete(listener) } }
export const workUsersVersion = () => usersVersion
export function displayWorkUser(value: string): string { return findWorkUser(value)?.[0] || (value || '').trim() }

export function setAssigneeUsers(
  value: Record<string, { github?: string; qq?: string }>
) {
  workUsers = Object.fromEntries(Object.entries(value).filter(([, item]) => item && typeof item === 'object').map(([id, item]) => [id.trim(), { github: String(item.github || '').trim(), qq: String(item.qq || '').trim() }]))
  usersVersion++
  userListeners.forEach(listener => listener())
}
export interface DocTask {
  number: number
  title: string
  paths: string[]
  rawPath: string
  aiPath: string
  translatedPath: string
  proofreadPath: string
  tr: Track
  pr: Track
  createdAt?: string // issue 创建时间(ISO)
  updatedAt: string // issue 最后更新时间(ISO)
}

function markerRe(key: TrackKey) {
  return new RegExp(`<!--\\s*${key}:([^:>]*):([^>]*?)-->`)
}

export function parseTrack(
  body: string | null | undefined,
  key: TrackKey
): Track {
  const m = (body || '').match(markerRe(key))
  if (!m) return { user: '', state: '待认领' }
  const user = m[1].trim()
  const state = m[2].trim() as TrackState
  return { user, state: STATES.includes(state) ? state : '待认领' }
}

// 个人 ID / GitHub login / qq-<号> 都能查到同一个人。
// 空值必须早退：只填 QQ 的成员 github 为空，否则 '' === '' 会把无人认领认成他。
export function findWorkUser(
  value: string
): [string, { github?: string; qq?: string }] | undefined {
  const v = (value || '').trim()
  if (!v) return undefined
  const qq = /^qq-/i.test(v) ? v.slice(3) : /^\d+$/.test(v) ? v : ''
  if (Object.prototype.hasOwnProperty.call(workUsers, v)) return [v, workUsers[v]]
  const matches = Object.entries(workUsers).filter(
    ([, item]) => (!!qq && item.qq === qq) || (!!item.github && item.github.toLowerCase() === v.toLowerCase())
  )
  return matches.length === 1 ? matches[0] : undefined
}

// 轨道里存的是个人 ID（写回 body 时归一过），而登录态给的是 GitHub login，
// 直接相等比较会让个人 ID ≠ login 的人（如 pm / chihya72）永远判不出「是我的」。
export function sameWorkUser(a: string, b: string): boolean {
  const x = (a || '').trim()
  const y = (b || '').trim()
  if (!x || !y) return false
  if (x.toLocaleLowerCase() === y.toLocaleLowerCase()) return true
  const idA = findWorkUser(x)?.[0]
  return !!idA && idA === findWorkUser(y)?.[0]
}

// 把任意身份形式折算成该用户的规范鉴权身份：有 GitHub 账号用 login，否则 qq-<号>。
// 管理页的下拉选项按这个规则取值，加载时归一才能正确回显，而不是把 qq-xxx 裸露出来。
export function canonicalOperator(value: string): string {
  const found = findWorkUser(value)
  if (!found) return (value || '').trim()
  const [, user] = found
  return user.github || (user.qq ? `qq-${user.qq}` : '')
}

// 把某轨道写回 body（有则替换，无则追加）
// 轨道存的是「鉴权身份」，原样写入不做归一：网页写 GitHub login，QQ 端写 qq-<号>。
// 归一成个人 ID 会抹掉判定依据，让两端都认不出自己的工序；个人 ID 只在显示时折算。
export function setTrackInBody(
  body: string | null | undefined,
  key: TrackKey,
  t: Track
): string {
  const marker = `<!-- ${key}:${t.user.trim()}:${t.state} -->`
  const re = markerRe(key)
  const b = body || ''
  if (re.test(b)) return b.replace(re, marker)
  return (b.trimEnd() + '\n' + marker).trim()
}

export function pathsFromBody(body: string | null | undefined): string[] {
  const out: string[] = []
  const re = /<!--\s*path:\s*(.+?)\s*-->/g
  let m
  while ((m = re.exec(body || ''))) out.push(m[1].trim())
  return out
}

function markerPath(body: string | null | undefined, key: string): string {
  const m = (body || '').match(new RegExp(`<!--\\s*${key}:\\s*(.+?)\\s*-->`))
  return m ? m[1].trim() : ''
}

function csvPathFromTitle(title: string, dir: string): string {
  return `${dir}/${title.split('_').join('/')}.csv`
}

function stagePathFromAny(path: string, title: string, dir: string): string {
  if (!path) return csvPathFromTitle(title, dir)
  const parts = path.split('/')
  if (
    ['data', 'ai_csv', 'translated_csv', 'proofread_csv'].includes(parts[0])
  ) {
    return [dir, ...parts.slice(1)].join('/')
  }
  return csvPathFromTitle(title, dir)
}

// 成品 CSV 的署名行改写（进出都是 base64）；translator 传展示用的个人 ID
export function stampTranslator(b64: string, translator: string): string {
  if (!translator) return b64
  const text = base64ToUtf8(b64.replace(/\n/g, ''))
  return utf8ToBase64(setCsvTranslator(text, translator))
}

export function completionPath(
  sourcePath: string,
  title: string,
  role: TrackKey
) {
  return stagePathFromAny(
    sourcePath,
    title,
    role === 'tr' ? 'translated_csv' : 'proofread_csv'
  )
}

// 两轨认领人并集（去空、去重）
export function assigneesOf(tr: Track, pr: Track): string[] {
  return [
    ...new Set(
      [tr.user, pr.user]
        .map((operator) => {
          const value = operator.trim()
          if (!value) return ''
          const found = findWorkUser(value)
          return (
            found?.[1].github || (!Object.keys(workUsers).length ? value : '')
          )
        })
        .filter(Boolean)
    ),
  ]
}

// 多文件一次提交到工作仓库；内容传 base64
export async function commitWorkFiles(
  wrapper: any,
  files: { path: string; content: string | null }[],
  message: string
): Promise<string> {
  return wrapper.commitFiles(WORK_OWNER, WORK_REPO, WORK_BRANCH, message, files)
}

// ===== 网页端产物下载：成品 CSV / 纯中文 txt =====

// 预翻译仓库(=Gakumas-Auto-Translate)的 owner/repo/branch，人名字典在其根目录
const preDirMatch = (
  (import.meta.env.VITE_PRETRANSLATION_DIR as string) || ''
).match(/^https:\/\/github\.com\/([^/]+)\/([^/]+)\/blob\/([^/]+)/)
const DICT_URL = preDirMatch
  ? `https://raw.githubusercontent.com/${preDirMatch[1]}/${preDirMatch[2]}/${preDirMatch[3]}/name_dictionary.json`
  : 'https://raw.githubusercontent.com/chihya72/Gakumas-Auto-Translate/master/name_dictionary.json'

let nameDictionary: { promise: Promise<Record<string, string>>; expires: number } | undefined

export function workRawUrl(relPath: string, version = ''): string {
  const query = version ? `?v=${encodeURIComponent(version)}` : ''
  return `https://raw.githubusercontent.com/${WORK_OWNER}/${WORK_REPO}/${WORK_BRANCH}/${relPath}${query}`
}

// 原始 txt 权威源：DreamGallery/Campus-adv-txts（游戏解包 adv 文本镜像）
export const CAMPUS_REPO =
  import.meta.env.VITE_CAMPUS_REPO || 'DreamGallery/Campus-adv-txts'
export function campusRawUrl(flatTxtName: string, version = ''): string {
  const query = version ? `?v=${encodeURIComponent(version)}` : ''
  return `https://raw.githubusercontent.com/${CAMPUS_REPO}/main/Resource/${flatTxtName}${query}`
}

// 取原始 txt：campus 权威源优先，工作仓库 raw/ 兜底
export async function fetchRawTxt(title: string): Promise<string | null> {
  const name = `${title}.txt`
  for (const url of [
    workRawUrl(`raw_txt/${name}`),
    campusRawUrl(name),
    workRawUrl(`raw/${name}`),
  ]) {
    try {
      const r = await fetch(url)
      if (r.ok) return await r.text()
    } catch {
      /* try next */
    }
  }
  return null
}



const HTML_TAG_RE = /<\/?[A-Za-z][A-Za-z0-9_:-]*(?:\\=[^>]*)?>/g

function htmlTags(text: string): string[] {
  return text.match(HTML_TAG_RE) || []
}

function htmlTagsAreBalanced(tags: string[]): boolean {
  const opens: string[] = []
  return (
    tags.every((tag) => {
      const match = /^<\/?([A-Za-z][A-Za-z0-9_:-]*)/.exec(tag)
      if (!match) return false
      if (tag.startsWith('</')) return opens.pop() === match[1]
      opens.push(match[1])
      return true
    }) && !opens.length
  )
}

function utf8ToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text)
  let binary = ''
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)))
  return btoa(binary)
}

function base64ToUtf8(value: string): string {
  const bin = atob(String(value || '').replace(/\n/g, ''))
  return new TextDecoder().decode(
    Uint8Array.from(bin, (char) => char.charCodeAt(0))
  )
}

// GitHub login → 个人 ID / QQ 号。读的是仓库里的 users.json，不依赖前端已加载的映射
export async function resolveOperator(
  wrapper: any,
  operatorGithub: string
): Promise<{ operatorQq: string; operatorId: string }> {
  try {
    const userFile = await wrapper.getContent(
      WORK_OWNER,
      WORK_REPO,
      WORK_BRANCH,
      'users.json'
    )
    const all = JSON.parse(base64ToUtf8(userFile.content))
    const matched = Object.entries(all || {}).find(
      ([key, user]: [string, any]) =>
        String(user?.github === undefined ? key : user.github)
          .trim()
          .toLocaleLowerCase() === operatorGithub.toLocaleLowerCase()
    )
    return {
      operatorId: matched?.[0] || operatorGithub,
      operatorQq: String((matched?.[1] as any)?.qq || '').trim(),
    }
  } catch {
    // 身份映射不可用时仍保留 GitHub 操作者
    return { operatorId: operatorGithub, operatorQq: '' }
  }
}

export const EMPTY_RECORD = (fileId: string) => ({
  schema_version: 1,
  file_id: fileId,
  batch: '',
  category: storyKind(fileId),
  force_complete: { translation: false, proofread: false },
  translation: { revision: 0, draft_revision: 0 },
  proofread: { revision: 0, draft_revision: 0 },
  artifacts: {} as Record<string, any>,
})

export async function fetchRecordForWrite(
  wrapper: any,
  fileId: string
): Promise<any> {
  try {
    const current = await wrapper.getContent(
      WORK_OWNER,
      WORK_REPO,
      WORK_BRANCH,
      `records/${fileId}.json`,
      true
    )
    return JSON.parse(base64ToUtf8(current.content))
  } catch (error: any) {
    if (error?.response?.status !== 404) throw error
    return EMPTY_RECORD(fileId)
  }
}

// 就地更新记录的一条轨道与对应产物；返回是否触发「直接校对」（翻译轨归给校对者）。
// 事务提交与旧的单文件写入共用它，避免两处各写一套语义。
export function applyRecordTrack(
  record: any,
  opts: {
    role: TrackKey
    state: TrackState
    /** 内容未变的幂等提交：照写记录，但不推进版本 */
    keepRevision?: boolean
    artifactPath: string
    directMachine: boolean
    operatorQq: string
    operatorGithub: string
    operatorId: string
  }
): boolean {
  const { role, state, artifactPath, directMachine } = opts
  const directProofread =
    role === 'pr' && record.direct_machine_proofread === true
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
  const key = role === 'tr' ? 'translation' : 'proofread'
  const artifactKey = role === 'tr' ? 'translation_csv' : 'proofread_csv'
  const who = {
    operator_qq: opts.operatorQq,
    operator_github: opts.operatorGithub,
    display_id: opts.operatorId,
    display_source: 'github',
  }
  const track = record[key] || {}
  record[key] = {
    ...track,
    revision:
      state === '完成' && !opts.keepRevision
        ? Number(track.revision || 0) + 1
        : Number(track.revision || 0),
    draft_revision: Number(track.draft_revision || 0),
    state,
    ...who,
    timestamp: now,
  }
  if (artifactPath) {
    record.artifacts = record.artifacts || {}
    record.artifacts[artifactKey] = {
      ...(record.artifacts[artifactKey] || {}),
      path: artifactPath,
      ...who,
      timestamp: now,
    }
  }
  if (directMachine) record.direct_machine_proofread = true
  if (directProofread) {
    record.translation = {
      ...record.proofread,
      revision: Math.max(1, Number(record.translation?.revision || 0)),
      state: '完成',
    }
    if (record.artifacts?.translation_csv) {
      record.artifacts.translation_csv = {
        ...record.artifacts.translation_csv,
        operator_qq: record.translation.operator_qq,
        operator_github: record.translation.operator_github,
        display_id: record.translation.display_id,
        display_source: record.translation.display_source,
        timestamp: record.translation.timestamp,
      }
    }
    delete record.direct_machine_proofread
  }
  record.github = { ...(record.github || {}), updated_at: now }
  return directProofread
}

// 把两轨状态投影进记录 JSON。
// Bot 的同步游标是 git HEAD，而编辑 Issue 不产生 commit，所以只改 Issue 的操作
// （管理页保存）对 Bot 完全不可见；写记录才是那个可见信号。
// 不改 revision，也不在无变化时写入，避免空提交和时间戳漂移。
export async function syncRecordTracks(
  wrapper: any,
  fileId: string,
  tr: Track,
  pr: Track
): Promise<boolean> {
  const recordPath = `records/${fileId}.json`
  let record: any
  try {
    const current = await wrapper.getContent(
      WORK_OWNER,
      WORK_REPO,
      WORK_BRANCH,
      recordPath,
      true
    )
    record = JSON.parse(base64ToUtf8(current.content))
  } catch (error: any) {
    if (error?.response?.status === 404) return false
    throw error
  }
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
  let changed = false
  for (const [key, track] of [
    ['translation', tr],
    ['proofread', pr],
  ] as [string, Track][]) {
    const found = findWorkUser(track.user)
    const next = {
      state: track.state,
      operator_qq: found?.[1].qq || '',
      operator_github: found?.[1].github || (/^[a-z\d](?:[a-z\d-]*[a-z\d])?$/i.test(track.user) ? track.user : ''),
      display_id: found?.[0] || track.user,
    }
    const old = record[key] || {}
    if (
      old.state === next.state &&
      (old.display_id || '') === next.display_id &&
      (old.operator_qq || '') === next.operator_qq &&
      (old.operator_github || '') === next.operator_github
    )
      continue
    record[key] = { ...old, ...next, timestamp: now }
    changed = true
  }
  if (!changed) return false
  record.github = { ...(record.github || {}), updated_at: now }
  await wrapper.updateContent(
    WORK_OWNER,
    WORK_REPO,
    WORK_BRANCH,
    recordPath,
    `同步工序状态 ${fileId}`,
    utf8ToBase64(JSON.stringify(record, null, 2) + '\n')
  )
  return true
}

export class StaleRevisionError extends Error {}

export function draftPath(
  sourcePath: string,
  fileId: string,
  role: TrackKey
): string {
  return stagePathFromAny(
    sourcePath,
    fileId,
    role === 'tr' ? 'translated_draft' : 'proofread_draft'
  )
}

const DRAFT_KEY = { tr: 'translation_draft', pr: 'proofread_draft' } as const

// 中途保存：只写草稿和记录，正式稿与完成状态一律不动。
// 草稿记下它基于哪一版正式稿，恢复时据此判断是否已过期。
export async function saveDraft(
  wrapper: any,
  opts: {
    fileId: string
    role: TrackKey
    sourcePath: string
    contentB64: string
    operatorGithub: string
  }
): Promise<{ draftRevision: number; baseRevision: number }> {
  const { fileId, role, sourcePath, operatorGithub } = opts
  const key = role === 'tr' ? 'translation' : 'proofread'
  const record = await fetchRecordForWrite(wrapper, fileId)
  const { operatorQq, operatorId } = await resolveOperator(
    wrapper,
    operatorGithub
  )
  const path = draftPath(sourcePath, fileId, role)
  const baseRevision = Number(record[key]?.revision || 0)
  const draftRevision = Number(record[key]?.draft_revision || 0) + 1
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
  record[key] = { ...(record[key] || {}), draft_revision: draftRevision }
  record.artifacts = record.artifacts || {}
  record.artifacts[DRAFT_KEY[role]] = {
    path,
    operator_qq: operatorQq,
    operator_github: operatorGithub,
    display_id: operatorId,
    display_source: 'github',
    based_on_revision: baseRevision,
    timestamp: now,
  }
  record.github = { ...(record.github || {}), updated_at: now }
  await commitWorkFiles(
    wrapper,
    [
      { path, content: opts.contentB64 },
      {
        path: `records/${fileId}.json`,
        content: utf8ToBase64(JSON.stringify(record, null, 2) + '\n'),
      },
    ],
    `${TRACK_LABEL[role]}中途保存 ${fileId}`
  )
  return { draftRevision, baseRevision }
}

export interface DraftInfo {
  path: string
  operatorGithub: string
  displayId: string
  basedOnRevision: number
  timestamp: string
  /** 基准版本已被推进，草稿内容落后于正式稿 */
  stale: boolean
  /** 草稿是别人存的 */
  mine: boolean
}

// 只读草稿元信息；内容另行取，避免打开只读页时也白下一份
export function draftInfoOf(
  record: any,
  role: TrackKey,
  meGithub: string
): DraftInfo | null {
  const meta = record?.artifacts?.[DRAFT_KEY[role]]
  if (!meta?.path) return null
  const key = role === 'tr' ? 'translation' : 'proofread'
  return {
    path: meta.path,
    operatorGithub: meta.operator_github || '',
    displayId: meta.display_id || meta.operator_github || '',
    basedOnRevision: Number(meta.based_on_revision || 0),
    timestamp: meta.timestamp || '',
    stale:
      Number(meta.based_on_revision || 0) !==
      Number(record[key]?.revision || 0),
    mine:
      !!meGithub &&
      (meta.operator_github || '').toLocaleLowerCase() ===
        meGithub.toLocaleLowerCase(),
  }
}

// 兼容旧的纯姓名署名，重复校对时只取译者部分，避免累积校对署名。
export function originalTranslator(credit: string): string {
  const match = /^翻译：(.*?)(?:；校对：.*)?$/s.exec(credit)
  return match ? match[1] : credit
}
export function completionCredit(translator: string, proofreader?: string): string {
  return `翻译：${translator}${proofreader === undefined ? '' : `；校对：${proofreader}`}`
}

// 校对稿沿用翻译正式稿的署名，不能被校对提交者或导入文件覆盖。
export async function completionTranslator(
  wrapper: any,
  opts: { role: TrackKey; sourcePath: string; fileId: string; contentB64: string },
  record: any,
  operatorId: string
): Promise<string> {
  if (opts.role === 'tr' || record.direct_machine_proofread === true) return operatorId
  try {
    const translated = await wrapper.getContent(
      WORK_OWNER, WORK_REPO, WORK_BRANCH,
      completionPath(opts.sourcePath, opts.fileId, 'tr'), true
    )
    const name = extractInfoFromCsvText(base64ToUtf8(translated.content)).translator
    if (name.trim()) return originalTranslator(name)
  } catch (error: any) {
    if (error?.response?.status !== 404) throw error
  }
  // 兼容正式稿缺失或未署名的旧任务，优先使用原翻译工序的记录。
  return record.translation?.display_id || record.translation?.operator_github ||
    originalTranslator(extractInfoFromCsvText(base64ToUtf8(opts.contentB64)).translator)
}

// 阶段完成事务：正式稿、备份、记录、校对 TXT 一次提交完成。
// baseRevision 是打开编辑器时看到的版本；提交前比对，旧稿不能覆盖新稿。
// 传 -1 表示放弃校验（无法确定基准版本的入口，如批量上传）。
export async function completeStage(
  wrapper: any,
  opts: {
    fileId: string
    role: TrackKey
    sourcePath: string
    contentB64: string
    operatorGithub: string
    baseRevision: number
  }
): Promise<{ directProofread: boolean; commitSha: string }> {
  const { fileId, role, sourcePath, operatorGithub, baseRevision } = opts
  const key = role === 'tr' ? 'translation' : 'proofread'
  const record = await fetchRecordForWrite(wrapper, fileId)
  const current = Number(record[key]?.revision || 0)
  if (baseRevision >= 0 && current !== baseRevision)
    throw new StaleRevisionError(
      `该文件的${TRACK_LABEL[role]}已被他人更新（你打开时是第 ${baseRevision} 版，` +
        `现在是第 ${current} 版）。请重新打开加载最新内容，避免覆盖对方的成果。`
    )

  const { operatorQq, operatorId } = await resolveOperator(wrapper, operatorGithub)
  const translator = await completionTranslator(wrapper, opts, record, operatorId)
  const outputPath = completionPath(sourcePath, fileId, role)
  const stamped = stampTranslator(opts.contentB64, completionCredit(translator, role === 'pr' ? operatorId : undefined))
  const files: { path: string; content: string | null }[] = []

  // 草稿已晋升为正式稿，同一提交里删掉，避免下次打开又恢复出旧内容
  const draft =
    record.artifacts?.[role === 'tr' ? 'translation_draft' : 'proofread_draft']
  if (draft?.path) {
    files.push({ path: draft.path, content: null })
    delete record.artifacts[
      role === 'tr' ? 'translation_draft' : 'proofread_draft'
    ]
    record[key] = { ...(record[key] || {}), draft_revision: 0 }
  }

  // 旧正式稿轮换为唯一显式备份；内容没变就不必留
  const backupDir = role === 'tr' ? 'translated_backup' : 'proofread_backup'
  let unchanged = false
  try {
    const old = await wrapper.getContent(
      WORK_OWNER,
      WORK_REPO,
      WORK_BRANCH,
      outputPath,
      true
    )
    const oldB64 = (old.content as string).replace(/\n/g, '')
    if (oldB64 === stamped) unchanged = true
    else
      files.push({
        path: stagePathFromAny(sourcePath, fileId, backupDir),
        content: oldB64,
      })
  } catch (error: any) {
    if (error?.response?.status !== 404) throw error
  }
  files.push({ path: outputPath, content: stamped })

  // 协议第 7 节：内容与现有正式稿完全相同且已完成 → 幂等成功，不增加版本。
  // 仍然写记录（操作者可能变了，例如重做），只是 revision 保持不动。
  const idempotent = unchanged && record[key]?.state === '完成'

  const directProofread = applyRecordTrack(record, {
    role,
    state: '完成',
    keepRevision: idempotent,
    artifactPath: outputPath,
    directMachine: false,
    operatorQq,
    operatorGithub,
    operatorId,
  })
  // 直接校对：翻译轨归给校对者，成品同步一份到翻译路径
  if (directProofread)
    files.push({
      path: completionPath(sourcePath, fileId, 'tr'),
      content: stampTranslator(opts.contentB64, completionCredit(operatorId)),
    })

  // 校对完成时生成纯中文 TXT；原文缺失就跳过，不阻断提交
  if (role === 'pr') {
    try {
      const [rawTxt, dict] = await Promise.all([
        fetchRawTxt(fileId),
        fetchNameDict(),
      ])
      if (rawTxt !== null) {
        const { data } = extractInfoFromCsvText(base64ToUtf8(stamped))
        files.push({
          path: `proofread_txt/${fileId}.txt`,
          content: utf8ToBase64(buildChineseTxt(rawTxt, data, dict)),
        })
      }
    } catch {
      // 生成失败不影响正式稿落地，后续可单独补
    }
  }

  files.push({
    path: `records/${fileId}.json`,
    content: utf8ToBase64(JSON.stringify(record, null, 2) + '\n'),
  })

  const commitSha = await commitWorkFiles(
    wrapper,
    files,
    `${TRACK_LABEL[role]}完成 ${fileId}`
  )
  return { directProofread, commitSha }
}

export function validateRowsHtmlTags(
  rows: { id: string; text: string; trans: string }[]
): string[] {
  const errors: string[] = []
  rows.forEach((row, i) => {
    if (row.id === 'info' || row.id === '译者' || !row.trans) return
    const dst = htmlTags(row.trans)
    if (!htmlTagsAreBalanced(dst)) {
      errors.push(`第 ${i + 2} 行译文标签无效：[${dst.join(' ')}]`)
    }
  })
  return errors
}

export function validateTextHtmlTags(
  _rawTxt: string,
  outputTxt: string
): string[] {
  const dst = htmlTags(outputTxt)
  return htmlTagsAreBalanced(dst) ? [] : ['输出TXT标签无效']
}

// 移植自本地 merger.process_chinese_only：把 CSV 译文回填进原始 txt，生成纯中文 txt。
export function buildChineseTxt(
  rawTxt: string,
  rows: { id: string; name: string; text: string; trans: string }[],
  nameDict: Record<string, string>
): string {
  const rowErrors = validateRowsHtmlTags(rows)
  if (rowErrors.length) throw new Error(rowErrors.slice(0, 5).join('\n'))
  const content = mergeScriptText(rawTxt, rows, nameDict)
  const textErrors = validateTextHtmlTags(rawTxt, content)
  if (textErrors.length) throw new Error(textErrors.join('\n'))
  return content
}

export async function fetchNameDict(): Promise<Record<string, string>> {
  if (!nameDictionary || nameDictionary.expires <= Date.now()) {
    const promise = (async () => {
      try {
        const r = await fetch(DICT_URL, { signal: AbortSignal.timeout(15000), credentials: 'omit' })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const data: unknown = await r.json()
        if (!data || typeof data !== 'object' || Array.isArray(data) ||
            Object.values(data).some(value => typeof value !== 'string')) throw new Error('字典格式无效')
        return data as Record<string, string>
      } catch {
        throw new Error('人名字典加载失败，请稍后重试 TXT 导出')
      }
    })()
    nameDictionary = { promise, expires: Date.now() + 5 * 60 * 1000 }
    // Concurrent/batch exports share one request; a failed download can be retried.
    void promise.catch(() => { if (nameDictionary?.promise === promise) nameDictionary = undefined })
  }
  return nameDictionary.promise
}

// 我在本篇的当前状态：担任哪一轨、是否被"翻译未完成"挡住校对编辑
export interface MyStatus {
  activeRole: TrackKey | null // 当前可编辑/可完成的轨
  blocked: boolean // 认领了校对但翻译未完成 → 暂不能编辑
  blockMsg: string
  finished?: boolean // 指定的轨已完成 → 只读展示
}
// role 显式指定"从哪一列打开"（工作台点翻译列/校对列）；不传则翻译优先推断。
export function myStatusOf(
  tr: Track,
  pr: Track,
  me: string,
  role?: TrackKey
): MyStatus {
  const none: MyStatus = { activeRole: null, blocked: false, blockMsg: '' }
  const done: MyStatus = {
    activeRole: null,
    blocked: false,
    blockMsg: '',
    finished: true,
  }
  if (!me) return none
  const asTr = (): MyStatus => {
    // 重新翻译常开：翻译轨已完成时，任何登录用户显式带 role=tr 进来都可重做
    // （再次完成会覆盖 translated_csv，译者更新为重做者）
    if (tr.state === '完成') {
      if (role === 'tr')
        return { activeRole: 'tr', blocked: false, blockMsg: '' }
      return sameWorkUser(tr.user, me) ? done : none
    }
    if (!sameWorkUser(tr.user, me)) return none
    return { activeRole: 'tr', blocked: false, blockMsg: '' }
  }
  const asPr = (): MyStatus => {
    // 重新校对常开：校对轨已完成时，任何登录用户显式带 role=pr 进来都可重做。
    // （再次完成会覆盖 proofread_csv，校对者更新为重做者）
    if (pr.state === '完成' && role === 'pr' && tr.state === '完成')
      return { activeRole: 'pr', blocked: false, blockMsg: '' }
    if (!sameWorkUser(pr.user, me)) return none
    if (pr.state === '完成' && role !== 'pr') return done
    if (tr.state === '完成')
      return { activeRole: 'pr', blocked: false, blockMsg: '' }
    // 认领了校对但翻译未完成 → 只读
    return {
      activeRole: null,
      blocked: true,
      blockMsg: '翻译尚未完成，暂不能校对',
    }
  }
  if (role === 'tr') return asTr()
  if (role === 'pr') return asPr()
  // 未指定：翻译优先，其次校对，最后已完成态
  const t = asTr()
  if (t.activeRole) return t
  const p = asPr()
  if (p.activeRole || p.blocked) return p
  return t.finished ? t : p
}

export function docFromIssue(i: any): DocTask {
  const paths = pathsFromBody(i.body)
  const legacy = paths[0] || ''
  return {
    number: i.number,
    title: i.title,
    paths,
    rawPath: markerPath(i.body, 'raw_path') || `raw_txt/${i.title}.txt`,
    aiPath:
      markerPath(i.body, 'ai_path') ||
      stagePathFromAny(legacy, i.title, 'ai_csv'),
    translatedPath:
      markerPath(i.body, 'translated_path') ||
      stagePathFromAny(legacy, i.title, 'translated_csv'),
    proofreadPath:
      markerPath(i.body, 'proofread_path') ||
      stagePathFromAny(legacy, i.title, 'proofread_csv'),
    tr: parseTrack(i.body, 'tr'),
    pr: parseTrack(i.body, 'pr'),
    createdAt: i.created_at || '',
    updatedAt: i.updated_at || '',
  }
}

// 统一的轨道更新：拉最新 body → 改指定轨 → 回写 body + 同步 assignees（两轨全完成则关 issue）
// wrapper 用 any 以免和 auth.ts 形成类型耦合
export async function applyTrack(
  wrapper: any,
  issueNumber: number,
  key: TrackKey,
  track: Track,
  onlyUnclaimed = false
): Promise<void> {
  const issue = await wrapper.getIssue(WORK_OWNER, WORK_REPO, issueNumber)
  const previous = parseTrack(issue.body, key)
  if (onlyUnclaimed && previous.state !== '待认领')
    throw new Error('该工序已不再待认领，请刷新')
  if (previous.state === '进行中' && !sameWorkUser(previous.user, track.user))
    throw new Error('任务已被其他协作者认领，请刷新')
  const body = setTrackInBody(issue.body, key, track)
  const tr = key === 'tr' ? track : parseTrack(body, 'tr')
  const pr = key === 'pr' ? track : parseTrack(body, 'pr')
  const done = tr.state === '完成' && pr.state === '完成'
  await wrapper.updateIssue(WORK_OWNER, WORK_REPO, issueNumber, {
    body,
    assignees: assigneesOf(tr, pr),
    state: done ? 'closed' : 'open',
  })
}
