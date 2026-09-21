import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useCatalog, useJson, type Entry } from "./catalog";

interface TextUpdate {
  script_id: string;
  entry_id: string;
  title: string;
  group_title: string | null;
  category_id: string;
  character_ids: string[];
  pending: boolean;
  images: NonNullable<Entry["group_images"]>;
  csv_path: string;
  line_count: number;
  updated_at: number | null;
  change_kind: "added" | "modified" | null;
  commit: string | null;
}
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
  const pages = Math.max(1, Math.ceil(rows.length / 24));
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
      <div className="search-field"><Search size={17} /><input aria-label="搜索文本更新" placeholder="搜索角色、章节或文件名" value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} /></div>
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
      <p className="results-label" role="status">找到 {rows.length} 篇文本</p>
      {!rows.length && <div className="empty-state">暂无符合条件的文本。</div>}
      <div className="updates-list">{rows.slice((current - 1) * 24, current * 24).map(row => <article key={row.script_id} className="update-row">
        {row.images[0] && <img className="update-art" src={row.images[0].url} style={{ aspectRatio: row.images[0].aspect_ratio || undefined }} alt="" loading="lazy" />}
        <div className="update-body">
          <div className="update-meta"><time dateTime={row.updated_at ? new Date(row.updated_at).toISOString() : undefined}>{row.updated_at ? dateFormat.format(row.updated_at) : "提交时间未知"}</time><span>{row.change_kind === "added" ? "新增" : row.change_kind === "modified" ? "修改" : "变更类型未知"}</span>{row.pending && <span className="pending-badge">待补全资料</span>}</div>
          <Link className="update-title" to={`/chapter/${encodeURIComponent(row.script_id)}?${new URLSearchParams({ entry: row.entry_id })}`}>{row.title}<ArrowRight size={15} /></Link>
          {row.group_title && row.group_title !== row.title && <p lang="ja">{row.group_title}</p>}
          <p>{catalog.categories.find(c => c.id === row.category_id)?.name || "待分类"}{row.pending ? "（文件名推测）" : ""}{row.character_ids.length > 0 ? ` · ${row.character_ids.map(id => names.get(id) || id).join("、")}` : ""} · {row.line_count} 条文本</p>
          <code>{row.script_id}</code>
          <div className="update-links"><a href={`https://github.com/DreamGallery/Campus-Story/blob/${sourceRevision}/${row.csv_path.split("/").map(encodeURIComponent).join("/")}`} target="_blank" rel="noreferrer">CSV ↗</a>{row.commit && <a href={`https://github.com/DreamGallery/Campus-Story/commit/${row.commit}`} target="_blank" rel="noreferrer">查看提交 ↗</a>}</div>
        </div>
      </article>)}</div>
      {pages > 1 && <nav className="pagination" aria-label="文本更新分页"><button aria-label="上一页" disabled={current === 1} onClick={() => setPage(current - 1)}><ChevronLeft size={18} /></button><span>{current} / {pages}</span><button aria-label="下一页" disabled={current === pages} onClick={() => setPage(current + 1)}><ChevronRight size={18} /></button></nav>}
    </>}
    </section>
  </main>;
}
