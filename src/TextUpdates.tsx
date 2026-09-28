import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, ChevronLeft, ChevronRight, Search, ChevronDown, BookOpen } from "lucide-react";
import { useCatalog, useJson } from "./catalog";

import CardPreview from "./CardPreview";
import { groupUpdates, type TextUpdate } from './text-updates';
import { api } from './workbench/github';
import { downloadFile } from './workbench/export';
interface Updates {
  items: TextUpdate[];
  source_commit: string | null;
  pending_count: number;
}
const normalize = (text: string) => text.normalize("NFKC").replace(/\s/g, "").toLocaleLowerCase();
const dateFormat = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeZone: "Asia/Shanghai" });
export default function TextUpdates() {
  const catalog = useCatalog();
  const [params, setParams] = useSearchParams();
  const pendingOnly = params.get("view") === "pending";
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [category, setCategory] = useState("all");
  const [page, setPage] = useState(1);
  const [openedAt] = useState(() => Date.now());
  const { data, error } = useJson<Updates>(`${catalog.base_path}/${catalog.updates_path || "updates.json"}`);
  const names = useMemo(() => new Map((catalog.filter_characters || catalog.characters).map(c => [c.id, c.name])), [catalog.filter_characters, catalog.characters]);
  const rows = useMemo(() => {
    const search = normalize(query);
    return (data?.items || []).filter(row => (pendingOnly ? row.pending : row.updated_at !== null && row.updated_at >= openedAt - 14 * 24 * 60 * 60 * 1000 && row.updated_at <= openedAt)
      && (category === "all" || row.category_id === category || row.category_id.startsWith(category + "."))
      && (kind === "all" || row.change_kind === kind)
      && (!search || normalize(`${row.title} ${row.group_title || ""} ${row.script_id} ${row.character_ids.map(id => names.get(id) || id).join(" ")}`).includes(search)));
  }, [data, pendingOnly, kind, category, query, names, openedAt]);
  const groups = useMemo(() => groupUpdates(rows), [rows]);
  const [exportMode, setExportMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false), [exportNotice, setExportNotice] = useState('');
  async function exportSelected(format: 'csv' | 'txt') {
    if (exporting) return;
    setExporting(true); setExportNotice('正在准备导出…');
    const files: Record<string, Uint8Array> = {}, failures: string[] = [];
    try {
      const { zipSync, strToU8 } = await import('fflate');
      const targets = (data?.items || []).filter(row => selected.has(row.script_id));
      let nextIndex = 0, completed = 0;
      setExportNotice(`正在导出 0 / ${targets.length}`);
      async function downloadNext() {
        while (nextIndex < targets.length) {
          const row = targets[nextIndex++];
          try {
            const result = await api<{ csv?: string; txt?: string }>((format === 'csv' ? 'source/' : 'script/') + encodeURIComponent(row.script_id));
            const content = format === 'csv' ? result.csv : result.txt;
            if (content === undefined) throw new Error('文件内容缺失');
            files[row.script_id + '.' + format] = strToU8(format === 'csv' ? '\uFEFF' + content.replace(/^\uFEFF/, '') : content);
          } catch (error) { failures.push(`${row.script_id}：${error instanceof Error ? error.message : String(error)}`); }
          finally { setExportNotice(`正在导出 ${++completed} / ${targets.length}`); }
        }
      }
      await Promise.all(Array.from({ length: Math.min(5, targets.length) }, () => downloadNext()));
      const count = Object.keys(files).length;
      if (count) {
        if (failures.length) files['导出失败.txt'] = strToU8(failures.join('\n'));
        if (targets.length === 1 && !failures.length) { const [name, bytes] = Object.entries(files)[0]; downloadFile(bytes, name); }
        else downloadFile(zipSync(files), `campus-text-updates-${format}.zip`, 'application/zip');
      }
      setExportNotice(`已导出 ${count} 个文件${failures.length ? '\n' + failures.join('\n') : ''}`);
    } catch (error) { setExportNotice(error instanceof Error ? error.message : String(error)); }
    finally { setExporting(false); }
  }
  function toggle(ids: string[]) {
    setSelected(previous => { const next = new Set(previous), remove = ids.every(id => next.has(id)); for (const id of ids) { if (remove) next.delete(id); else next.add(id); } return next; });
  }
  const pages = Math.max(1, Math.ceil(groups.length / 24));
  const current = Math.min(page, pages);
  const sourceRevision = data?.source_commit || "main";
  return <main className="updates-page">
    <div className="section-title"><span className="section-en" aria-hidden="true">TEXT UPDATES</span><div><h1>文本更新</h1></div></div>
    <section className="category-directory">
    <div className="updates-intro">
      <p>更新列表仅显示最近两周的 CSV 提交，修改可能包含翻译调整。待补全资料不受时间限制。</p>
      <a href={`https://github.com/DreamGallery/Campus-Story/tree/${sourceRevision}/CSV`} target="_blank" rel="noreferrer">查看文本仓库 ↗</a>
    </div>
    <div className="filter-tabs" role="group" aria-label="文本更新视图">
      <button aria-pressed={!pendingOnly} onClick={() => { setParams({}); setPage(1); }}>近两周更新</button>
      <button aria-pressed={pendingOnly} onClick={() => { setParams({ view: "pending" }); setPage(1); }}>待补全资料 {data ? `(${data.pending_count})` : ""}</button>
    </div>
    {pendingOnly && <p className="pending-explanation">这些文本尚未关联剧情资料，不一定都是未上线内容。分类、角色与预览按文件名尝试匹配；卡名、稀有度等未知信息暂不填写。</p>}
    <div className="updates-tools">
      <div className="update-search-actions"><div className="search-field"><Search size={17} /><input aria-label="搜索文本更新" placeholder="搜索角色、章节或文件名" value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} /></div><button className="update-export-toggle" disabled={exporting} aria-pressed={exportMode} onClick={() => { setExportMode(!exportMode); setSelected(new Set()); setExportNotice(''); }}>{exportMode ? '退出选择' : '选择导出'}</button></div>
      <label>剧情分类 <select aria-label="更新剧情分类" value={category} onChange={e => { setCategory(e.target.value); setPage(1); }}>
        <option value="all">全部剧情</option>
        {catalog.categories.filter(c => c.parent_id === null).map(root => <optgroup key={root.id} label={root.name}>
          <option value={root.id}>{root.name}（全部）</option>
          {catalog.categories.filter(c => c.parent_id === root.id).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </optgroup>)}
      </select></label>
      <label>变更类型 <select aria-label="文本变更类型" value={kind} onChange={e => { setKind(e.target.value); setPage(1); }}><option value="all">全部</option><option value="added">新增文件</option><option value="modified">修改文件</option></select></label>
    </div>
    {!data ? <p role="status">{error || "正在加载文本更新…"}</p> : <>
      <p className="results-label" role="status">找到 {groups.length} 个剧情分组 · {rows.length} 篇文本</p>
      {!rows.length && <div className="empty-state">暂无符合条件的文本。</div>}
      {exportMode && <div className="updates-tools update-export-tools">

        {exportMode && <><button disabled={exporting} onClick={() => setSelected(new Set(rows.map(row => row.script_id)))}>选择筛选结果</button><button disabled={exporting} onClick={() => setSelected(previous => new Set([...previous, ...groups.slice((current-1)*24,current*24).flatMap(g => g.items.map(r => r.script_id))]))}>选择本页</button><button disabled={exporting || !selected.size} onClick={() => setSelected(new Set())}>清空选择</button><span>已选 {selected.size} 个章节</span><button disabled={exporting || !selected.size} onClick={() => exportSelected('csv')}>导出 CSV</button><button disabled={exporting || !selected.size} onClick={() => exportSelected('txt')}>导出原始 TXT</button><p>导出当前发布的源文本，不包含协作译文或浏览器草稿。</p></>}
      </div>}
      {exportNotice && <p className="update-export-notice" role="status">{exportNotice}</p>}
      <div className="story-grid updates-group-grid">{groups.slice((current - 1) * 24, current * 24).map(group => <article key={group.id} className={`story-group ${group.images.length ? "has-art" : ""} ${group.items[0].category_id.startsWith("character") ? "update-character-group" : group.items[0].category_id.startsWith("support_card") ? "update-support-group" : ""}`}>
        {group.images.length ? <CardPreview images={group.images} title={group.title} /> : <div className="update-art-placeholder" aria-hidden="true"><BookOpen size={38} strokeWidth={1} /></div>}
        <details>
          <summary>
            <div className="group-copy"><p className="eyebrow">{catalog.categories.find(c => c.id === group.items[0].category_id)?.name || '待分类'}</p><h3>{group.title}</h3><span>{group.items.length} 个章节</span>{group.items.some(r => r.pending) && <span className="pending-badge">待补全资料</span>}</div><ChevronDown size={18} className="disclosure-icon" />
          </summary>
          {exportMode && <button className="update-select-group" disabled={exporting} aria-pressed={group.items.every(row => selected.has(row.script_id))} onClick={() => toggle(group.items.map(row => row.script_id))}>选择此剧情全部章节</button>}
          <ol className="chapter-list">{group.items.map(row => <li key={row.script_id} className="update-chapter">
            <div className="update-meta"><time>{row.updated_at ? dateFormat.format(row.updated_at) : '提交时间未知'}</time><span>{row.change_kind === 'added' ? '新增' : row.change_kind === 'modified' ? '修改' : '变更类型未知'}</span></div>
            {exportMode ? <button className="chapter-link update-chapter-option" disabled={exporting} aria-pressed={selected.has(row.script_id)} onClick={() => toggle([row.script_id])}><span><b>{row.pending ? row.script_id : row.title}</b><small>{row.line_count} 条文本</small></span></button> : <Link className="chapter-link" to={`/chapter/${encodeURIComponent(row.script_id)}?${new URLSearchParams({ entry: row.entry_id })}`}><span><b>{row.pending ? row.script_id : row.title}</b><small>{row.character_ids.map(id => names.get(id) || id).join('、')} · {row.line_count} 条文本</small></span><ArrowRight size={15} /></Link>}
            <div className="update-links"><a href={`https://github.com/DreamGallery/Campus-Story/blob/${sourceRevision}/${row.csv_path.split('/').map(encodeURIComponent).join('/')}`} target="_blank" rel="noreferrer">CSV ↗</a>{row.commit && <a href={`https://github.com/DreamGallery/Campus-Story/commit/${row.commit}`} target="_blank" rel="noreferrer">查看提交 ↗</a>}</div>
          </li>)}</ol>
        </details>
      </article>)}</div>
      {pages > 1 && <nav className="pagination" aria-label="文本更新分页"><button aria-label="上一页" disabled={current === 1} onClick={() => setPage(current - 1)}><ChevronLeft size={18} /></button><span>{current} / {pages}</span><button aria-label="下一页" disabled={current === pages} onClick={() => setPage(current + 1)}><ChevronRight size={18} /></button></nav>}
    </>}
    </section>
  </main>;
}
