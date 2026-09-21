import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Search,
  X,
  BookOpen,
  LibraryBig,
  Sun,
  Moon,
} from "lucide-react";
import {
  CatalogContext,
  useCatalog,
  useJson,
  type Catalog,
  type Character,
  type Chapter,
  type Entry,
} from "./catalog";

import ResourceStatus from "./ResourceStatus";
import ResourceVersions from "./ResourceVersions";
import TextUpdates from "./TextUpdates";
import { ChapterWorkbench, WorkbenchPage } from "./workbench/Workbench";

const roots = [
  { id: "character", name: "角色剧情", en: "IDOL", icon: "idol" },
  { id: "main", name: "主线剧情", en: "MAIN STORY", icon: "comm" },
  { id: "support_card", name: "辅助卡剧情", en: "SUPPORT", icon: "support" },
  { id: "event", name: "活动剧情", en: "EVENT", icon: "event" },
  { id: "other", name: "其他剧情", en: "EXTRA", icon: "comm" },
];
function CategoryIcon({ category }: { category: string }) {
  if (category.split(".")[0] === "other") return <LibraryBig className="category-icon library-icon" aria-hidden="true" />;
  const name = category.includes("dearness")
    ? "dearness_story"
    : {
        character: "idol-commu",
        main: "comm",
        support_card: "support-commu",
        event: "event-commu",
        other: "info",
      }[category.split(".")[0]] || "comm";
  return (
    <span
      className="category-icon"
      aria-hidden="true"
      style={{
        maskImage: `url(/images/icon/icon_${name}.png)`,
        WebkitMaskImage: `url(/images/icon/icon_${name}.png)`,
      }}
    />
  );
}
function CardPreview({
  images,
  title,
}: {
  images: NonNullable<Entry["group_images"]>;
  title: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState(0);
  return (
    <>
      <div
        className="card-previews"
        style={{
          gridTemplateColumns: `repeat(${images.length}, minmax(0, 1fr))`,
        }}
      >
        {images.map((image, index) => (
          <button
            key={image.url}
            className="card-preview"
            aria-label={`放大 ${title} ${image.label}`}
            onClick={() => {
              setSelected(index);
              dialog.current?.showModal();
            }}
          >
            <img
              style={{aspectRatio: image.preview_crop ? 3 : image.aspect_ratio || undefined, objectFit: image.preview_crop ? "cover" : undefined, objectPosition: image.preview_crop || undefined}} src={image.url}
              alt={`${title} ${image.label}`}
              loading="lazy"
            />
            {images.length > 1 && <span>{image.label}</span>}
          </button>
        ))}
      </div>
      <dialog
        ref={dialog}
        className="card-lightbox"
        aria-label={`${title} 卡面预览`}
        onClick={(event) => {
          if (event.target === event.currentTarget) dialog.current?.close();
        }}
      >
        <div className="lightbox-toolbar">
          <span>{title}</span>
          <button
            autoFocus
            aria-label="关闭卡面预览"
            onClick={() => dialog.current?.close()}
          >
            <X />
          </button>
        </div>
        <img
          style={{aspectRatio: images[selected].aspect_ratio || undefined, width: images[selected].aspect_ratio ? `min(100%, ${75 * images[selected].aspect_ratio!}dvh)` : undefined}} src={images[selected].url}
          alt={`${title} ${images[selected].label}`}
        />
        {images.length > 1 && (
          <div className="lightbox-stages">
            {images.map((image, index) => (
              <button
                key={image.url}
                aria-pressed={selected === index}
                onClick={() => setSelected(index)}
              >
                {image.label}
              </button>
            ))}
          </div>
        )}
      </dialog>
    </>
  );
}
const statusLabel: Record<string, string> = {
  present: "文本已收录",
  empty: "暂无台词文本",
  missing: "文本待补充",
};
function Feedback({ error }: { error?: string }) {
  return (
    <div className="feedback" role="status">
      <BookOpen size={30} />
      <p>{error || "正在加载…"}</p>
      {error && (
        <button
          className="outline-button"
          onClick={() => window.location.reload()}
        >
          重新加载
        </button>
      )}
    </div>
  );
}
function ScrollReset() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);
  return null;
}
function ThemeSwitch() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  function choose(next: "light" | "dark") {
    document.documentElement.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
    setTheme(next);
    try { localStorage.setItem("campus-theme-v1", next); } catch { /* Theme still works without storage. */ }
  }
  return <div className="theme-switch" role="group" aria-label="网页主题">
    <button type="button" aria-label="浅色主题" aria-pressed={theme === "light"} onClick={() => choose("light")}><Sun size={15} aria-hidden="true" /><span>浅色</span></button>
    <button type="button" aria-label="深色主题" aria-pressed={theme === "dark"} onClick={() => choose("dark")}><Moon size={15} aria-hidden="true" /><span>深色</span></button>
  </div>;
}
function Header({ revision }: { revision?: string | number | null }) {
  const { pathname } = useLocation();
  const characterRoute =
    pathname.startsWith("/idol") ||
    pathname.startsWith("/character-card") ||
    pathname === "/stories/character";
  return (
    <header className="header">
      <Link to="/" className="brand">
        <svg className="brand-mark" viewBox="0 0 100 100" aria-hidden="true">
          <defs><filter id="school-crest-ink" colorInterpolationFilters="sRGB"><feComponentTransfer result="ink"><feFuncA type="linear" slope="9.8077" /></feComponentTransfer><feFlood floodColor="#a77b38" /><feComposite in2="ink" operator="in" /></filter></defs>
          <image href="/images/official/crest.png" width="100" height="100" filter="url(#school-crest-ink)" />
        </svg>
        <span>
          初星学园<span className="brand-sub">CAMPUS STORY ARCHIVE</span>
        </span>
      </Link>
      <nav aria-label="剧情分类">
        {roots.map((r) => (
          <NavLink
            key={r.id}
            className={({ isActive }) =>
              isActive || (r.id === "character" && characterRoute)
                ? "active"
                : undefined
            }
            to={r.id === "character" ? "/idols" : "/stories/" + r.id}
          >
            <CategoryIcon category={r.id} />
            {r.name}
          </NavLink>
        ))}
        <NavLink to="/updates"><span className="category-icon" aria-hidden="true" style={{ maskImage: "url(/images/icon/icon_info.png)", WebkitMaskImage: "url(/images/icon/icon_info.png)" }} />文本更新</NavLink>
        <NavLink to="/workbench"><BookOpen className="category-icon library-icon" aria-hidden="true" />翻译协作</NavLink>
      </nav>
      <div className="header-tools"><ResourceVersions revision={revision} /><ThemeSwitch /></div>
    </header>
  );
}
function SectionTitle({ en, title }: { en: string; title: string }) {
  return (
    <div className="section-title">
      <span className="section-en" aria-hidden="true">
        {en}
      </span>
      <div>
        <h1>{title}</h1>
      </div>
    </div>
  );
}
function Portrait({ character }: { character: Character }) {
  return (
    <div className="portrait-stage">
      <div className="portrait-word" aria-hidden="true">
        {character.english_name.split(" ")[0]}
      </div>
      <span className="portrait-caption">初星学園 · アイドル科</span>
      {character.portrait ? (
        <img
          className="portrait"
          src={character.portrait}
          alt={character.name}
        />
      ) : (
        <div className="portrait-missing">{character.name}</div>
      )}
      <span className="portrait-index">
        IDOL FILE / {character.id.toUpperCase()}
      </span>
    </div>
  );
}
function Roster({ selected }: { selected: string }) {
  const { characters } = useCatalog();
  return (
    <nav className="roster" aria-label="选择角色">
      {characters.map((c, i) => (
        <Link
          key={c.id}
          to={"/idol-commu/" + c.id}
          className={c.id === selected ? "idol-tile selected" : "idol-tile"}
          style={{ "--idol": c.color } as CSSProperties}
          aria-current={c.id === selected ? "page" : undefined}
        >
          <span className="idol-no">{String(i + 1).padStart(2, "0")}</span>
          {c.avatar && <img src={c.avatar} alt="" loading="lazy" />}
          <span lang="ja">{c.name}</span>
        </Link>
      ))}
    </nav>
  );
}
function CharacterPage() {
  const { characterId = "hski" } = useParams();
  const catalog = useCatalog();
  const character = catalog.characters.find((c) => c.id === characterId);
  if (!character) return <NotFound />;
  const d = character.details;
  return (
    <main style={{ "--accent": character.color } as CSSProperties}>
      <SectionTitle en="IDOL" title="学园名簿" />
      <section className="character-hero">
        <Portrait character={character} />
        <div className="profile-sheet">
          <div className="binding" aria-hidden="true" />
          <p className="english-name">{character.english_name}</p>
          <h2 lang="ja">{character.name}</h2>
          <p className="cv">
            CV <span lang="ja">{d.Cv || "—"}</span>
          </p>
          <div className="profile-label">
            PROFILE <span>角色档案</span>
          </div>
          <dl className="profile-grid">
            {[
              ["年级", d.Grade],
              ["年龄", d.Age ? d.Age + " 岁" : ""],
              ["生日", d.Birthday],
              ["身高", d.Height ? d.Height + " cm" : ""],
              ["出身", d.Birthplace],
              ["血型", d.BloodType],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value || "—"}</dd>
              </div>
            ))}
          </dl>
          <p className="introduction" lang="ja">{d.Introduction}</p>
          <div className="profile-bottom">
            <a className="gold-button" href="#stories">
              浏览角色剧情 <ArrowDown size={16} />
            </a>
            {character.signature && (
              <img src={character.signature} alt={`${character.name}的签名`} />
            )}
          </div>
        </div>
      </section>
      <div className="roster-heading">
        <p>选择角色</p>
      </div>
      <Roster selected={character.id} />
      <section id="stories" className="story-section">
        <div className="section-heading">
          <div>
            <h2>{character.first_name}的剧情</h2>
          </div>
          <Link className="back-link" to="/stories/character">
            浏览全部角色剧情 <ArrowRight size={14} />
          </Link>
        </div>
        <StoryDirectory
          key={character.id}
          list={"character-" + character.id}
          root="character"
        />
      </section>
    </main>
  );
}
function CategoryPage() {
  const { categoryId = "main" } = useParams();
  const root = roots.find((r) => r.id === categoryId);
  if (!root) return <Navigate to="/idols" replace />;
  return (
    <main>
      <SectionTitle en={root.en} title={root.name} />
      <section className="category-directory">
        <StoryDirectory key={categoryId} list={categoryId} root={categoryId} />
      </section>
    </main>
  );
}
const normalize = (value: string) => value.normalize("NFKC").replace(/\s/g, "").toLocaleLowerCase();
function StoryDirectory({ list, root }: { list: string; root: string }) {
  const catalog = useCatalog();
  const path = catalog.lists[list];
  const { data: allEntries, error } = useJson<Entry[]>(
    path ? catalog.base_path + "/" + path : "/catalog/missing.json",
  );
  const entries = useMemo(
    () => allEntries?.filter((entry) => entry.text_status !== "empty"),
    [allEntries],
  );
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("all");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("default");
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>([]);
  const [characterMatch, setCharacterMatch] = useState<"any" | "all">("any");
  const [rarities, setRarities] = useState<string[]>([]);
  const [attributes, setAttributes] = useState<string[]>([]);
  const toggle = (value: string, selected: string[], setter: (values: string[]) => void) => {
    setter(selected.includes(value) ? selected.filter(x => x !== value) : [...selected, value]);
    setPage(1);
  };
  const filterCharacters = (catalog.filter_characters || catalog.characters)
    .filter(c => entries?.some(e => e.character_ids.includes(c.id)));
  const resetFilters = () => {
    setSearch(""); setTab("all"); setSelectedCharacters([]); setCharacterMatch("any"); setRarities([]); setAttributes([]); setPage(1);
  };
  const categories = catalog.categories.filter((c) => c.parent_id === root);
  const query = normalize(search);
  const groups = useMemo(() => {
    const map = new Map<
      string,
      {
        id: string;
        title: string;
        images: NonNullable<Entry["group_images"]>;
        items: Entry[];
        releaseAt: number | null;
        updatedAt: number | null;
      }
    >();
    for (const e of entries || []) {
      if (tab !== "all" && e.category_id !== tab) continue;
      if (selectedCharacters.length) {
        const matches = root === "support_card" && characterMatch === "all"
          ? selectedCharacters.every(id => e.character_ids.includes(id))
          : selectedCharacters.some(id => e.character_ids.includes(id));
        if (!matches) continue;
      }
      if (rarities.length && !rarities.includes(e.support_rarity || "")) continue;
      if (attributes.length && !attributes.includes(e.support_attribute || "")) continue;
      if (
        query &&
        !normalize(`${e.title} ${e.group_title} ${e.script_id} ${e.character_ids.map((id) => (catalog.filter_characters || catalog.characters).find((c) => c.id === id)?.name || id).join(" ")}`).includes(query)
      )
        continue;
      const key = e.category_id + "::" + e.group_id + (root === "character" ? "::" + [...e.character_ids].sort().join(",") : "");
      let group = map.get(key);
      if (!group) {
        group = {
          id: key,
          title: e.group_title,
          images:
            e.group_images ??
            (e.group_image ? [{ url: e.group_image, label: "预览" }] : []),
          items: [],
          releaseAt: null,
          updatedAt: null,
        };
        map.set(key, group);
      }
      if (e.text_updated_at) group.updatedAt = Math.max(group.updatedAt || 0, e.text_updated_at);
      if (e.release_at) group.releaseAt = Math.max(group.releaseAt || 0, e.release_at);
      if (!group.items.some((x) => x.script_id === e.script_id))
        group.items.push(e);
    }
    const result = [...map.values()];
    if (sort === "name") result.sort((a, b) => a.title.localeCompare(b.title, "ja", { numeric: true }) || a.id.localeCompare(b.id));
    if (["newest", "oldest", "updated-newest", "updated-oldest"].includes(sort)) result.sort((a, b) => {
      const left = sort.startsWith("updated") ? a.updatedAt : a.releaseAt;
      const right = sort.startsWith("updated") ? b.updatedAt : b.releaseAt;
      if (left === null) return right === null ? 0 : 1;
      if (right === null) return -1;
      return sort.endsWith("newest") ? right - left : left - right;
    });
    return result;
  }, [entries, tab, query, catalog.characters, catalog.filter_characters, root, sort, selectedCharacters, characterMatch, rarities, attributes]);
  if (!path) return <div className="empty-state">当前角色暂无收录剧情。</div>;
  if (!entries) return <Feedback error={error} />;
  const totalScripts = new Set(entries.map((e) => e.script_id)).size;
  const totalPages = Math.max(1, Math.ceil(groups.length / 12));
  const current = Math.min(page, totalPages);
  return (
    <>
      <div className="directory-toolbar">
        <p>
          <strong>{totalScripts.toLocaleString()}</strong> 篇收录剧情{" "}
          <span className="subtle">/ 选择章节，前往章节入口</span>
        </p>
        <div className="search-field">
          <Search size={17} />
          <input
            aria-label="搜索剧情"
            placeholder="搜索角色、章节或卡牌名称"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
          {search && (
            <button
              aria-label="清除搜索"
              onClick={() => {
                setSearch("");
                setPage(1);
              }}
            >
              <X size={16} />
            </button>
          )}
        </div>
      </div>
      <div className="filter-tabs" role="group" aria-label="剧情类型">
        <button
          aria-pressed={tab === "all"}
          onClick={() => {
            setTab("all");
            setPage(1);
          }}
        >
          全部
        </button>
        {categories
          .filter((c) => entries.some((e) => e.category_id === c.id))
          .map((c) => (
            <button
              key={c.id}
              aria-pressed={tab === c.id}
              onClick={() => {
                setTab(c.id);
                setPage(1);
              }}
            >

              {c.name}
            </button>
          ))}
      </div>
      {root !== "main" && <div className="directory-filters">
        <div className="sort-row">
          <label>排序 <select aria-label="剧情排序" value={sort} onChange={e => { setSort(e.target.value); setPage(1); }}>
            <option value="default">默认顺序</option>
            <option value="updated-newest">文本更新时间 · 最新优先</option>
            <option value="updated-oldest">文本更新时间 · 最早优先</option>
            <option value="newest">上线时间 · 最新优先</option>
            <option value="oldest">上线时间 · 最早优先</option>
            {(root === "support_card" || root === "event") && <option value="name">{root === "event" ? "活动名称" : "卡牌名称"} · 正序</option>}
          </select></label>
          <button className="reset-filters" onClick={resetFilters}>清除筛选</button>
        </div>
        {(list === "character" || root === "support_card") && <fieldset className="character-filters">
          <legend>角色 <small>可多选</small></legend>
          {root === "support_card" && <div className="character-match" role="group" aria-label="角色匹配方式">
            <button type="button" aria-pressed={characterMatch === "any"} onClick={() => { setCharacterMatch("any"); setPage(1); }}>或 · 任一角色</button>
            <button type="button" aria-pressed={characterMatch === "all"} onClick={() => { setCharacterMatch("all"); setPage(1); }}>且 · 全部角色</button>
          </div>}
          <div className="character-options">{filterCharacters.map(c => {
            const profile = catalog.characters.find(p => p.id === c.id);
            const stamps = catalog.filter_characters?.find(p => p.id === c.id);
            const checked = selectedCharacters.includes(c.id);
            const stamp = (checked ? stamps?.stamp_selected : stamps?.stamp_unselected) || stamps?.stamp_unselected || profile?.avatar;
            return <label key={c.id} className="character-option" style={{ "--idol": profile?.color || "#aa8955" } as CSSProperties}>
              <input type="checkbox" checked={selectedCharacters.includes(c.id)} onChange={() => toggle(c.id, selectedCharacters, setSelectedCharacters)} />
              <span className="filter-avatar" aria-hidden="true">{stamp ? <img src={stamp} alt="" loading="lazy" /> : <span>{c.name.slice(0, 1)}</span>}</span>
              <span lang="ja">{c.name}</span>
            </label>;
          })}</div>
        </fieldset>}
        {root === "support_card" && <div className="support-filters">
          <fieldset><legend>稀有度 <small>可多选</small></legend><div className="filter-options">{["SSR", "SR", "R"].map(value => <label className="filter-chip" key={value}>
            <input type="checkbox" checked={rarities.includes(value)} onChange={() => toggle(value, rarities, setRarities)} />
            <img src={`/images/filters/${value.toLowerCase()}.webp`} alt="" /><span>{value}</span>
          </label>)}</div></fieldset>
          <fieldset><legend>属性 <small>可多选</small></legend><div className="filter-options">{[["Vocal", "Vocal · 红"], ["Dance", "Dance · 蓝"], ["Visual", "Visual · 黄"], ["Assist", "Assist · 绿"]].map(([value, label]) => <label className="filter-chip" key={value}>
            <input type="checkbox" checked={attributes.includes(value)} onChange={() => toggle(value, attributes, setAttributes)} />
            <img src={`/images/filters/${value.toLowerCase()}.webp`} alt="" /><span>{label}</span>
          </label>)}</div></fieldset>
        </div>}
        {sort !== "default" && sort !== "name" && <p className="sort-note">{sort.startsWith("updated") ? "按文本最后提交时间排序，包含翻译修改。" : "按已知展示／开放时间排序。"}分组取最新章节时间，未知时间排在最后。</p>}
      </div>}
      <p className="results-label" role="status">
        找到 {groups.length} 个剧情分组
      </p>
      {groups.length === 0 ? (
        <div className="empty-state">
          <BookOpen />
          <h3>未找到匹配的剧情</h3>
          <p>试试角色名、卡牌名，或更短的关键词。</p>
          <button
            className="outline-button"
            onClick={() => {
              resetFilters();
            }}
          >
            重置筛选
          </button>
        </div>
      ) : (
        <div className={`story-grid ${root === "event" ? "event-grid" : root === "character" ? "character-grid" : ""}`}>
          {groups.slice((current - 1) * 12, current * 12).map((g, i) => (
            <article
              className={`story-group ${g.images.length ? "has-art" : ""}`}
              key={g.id}
            >
              {g.images.length > 0 && (
                <CardPreview images={g.images} title={g.title} />
              )}
              <details open={query ? true : undefined}>
                <summary>
                  {g.images.length === 0 && (
                    <div className="group-art typographic-art">
                      <span>
                        {String((current - 1) * 12 + i + 1).padStart(2, "0")}
                      </span>
                      <BookOpen size={28} />
                    </div>
                  )}
                  <div className="group-copy">
                    <p className="eyebrow">

                      {
                        catalog.categories.find(
                          (c) => c.id === g.items[0].category_id,
                        )?.name
                      }
                    </p>
                    {root === "character" && <p className="group-character" lang="ja">{g.items[0].character_ids.length ? g.items[0].character_ids.map(id => catalog.characters.find(c => c.id === id)?.name || id).join(" · ") : "共通 / 未标注角色"}</p>}
                    <h3>{g.title}</h3>
                    <span>{g.items.length} 个章节</span>
                    {root === "support_card" && <p className="card-facets">{g.items[0].support_rarity} · {g.items[0].support_attribute}</p>}
                    {sort.startsWith("updated") ? <small className="release-date">{g.updatedAt ? `文本更新 ${new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai" }).format(g.updatedAt)}` : "文本更新时间未知"}</small> : sort === "newest" || sort === "oldest" ? <small className="release-date">{g.releaseAt ? `上线 ${new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Tokyo" }).format(g.releaseAt)}` : "上线时间未知"}</small> : null}
                  </div>
                  <ChevronDown size={18} className="disclosure-icon" />
                </summary>
                <ol className="chapter-list">
                  {g.items.map((e, index) => (
                    <li key={e.script_id}>
                      <Link
                        className="chapter-link"
                        to={
                          "/chapter/" +
                          encodeURIComponent(e.script_id) +
                          "?" +
                          new URLSearchParams({ entry: e.id })
                        }
                      >
                        <span className="chapter-number">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span>
                          <b>{e.title || "未命名章节"}</b>
                          <small>
                            {statusLabel[e.text_status] || e.text_status} ·{" "}
                            {e.line_count} 条文本
                          </small>
                        </span>
                        <ArrowRight size={16} />
                      </Link>
                    </li>
                  ))}
                </ol>
              </details>
            </article>
          ))}
        </div>
      )}
      {totalPages > 1 && (
        <nav className="pagination" aria-label="目录分页">
          <button
            aria-label="上一页"
            disabled={current === 1}
            onClick={() => setPage(current - 1)}
          >
            <ChevronLeft size={18} />
          </button>
          <span>
            {current} / {totalPages}
          </span>
          <button
            aria-label="下一页"
            disabled={current === totalPages}
            onClick={() => setPage(current + 1)}
          >
            <ChevronRight size={18} />
          </button>
        </nav>
      )}
    </>
  );
}
function ChapterPage() {
  const { scriptId } = useParams();
  const [params, setParams] = useSearchParams();
  const catalog = useCatalog();
  const { data, error } = useJson<Chapter>(
    catalog.base_path +
      "/chapters/" +
      encodeURIComponent(scriptId || "") +
      ".json",
  );
  if (!data)
    return (
      <main>
        <Feedback error={error} />
      </main>
    );
  const entry =
    data.entries.find((e) => e.id === params.get("entry")) || data.entries[0];
  const root = entry.category_id.split(".")[0];
  const category = catalog.categories.find((c) => c.id === entry.category_id);
  const back =
    root === "character" && entry.character_ids[0]
      ? "/idol-commu/" + entry.character_ids[0]
      : "/stories/" + root;
  return (
    <main className="chapter-page">
      <Link className="back-link" to={back}>
        <ArrowLeft size={16} />
        返回剧情目录
      </Link>
      <section className="chapter-sheet">
        <p className="eyebrow">CHAPTER / {category?.name}</p>
        <p className="chapter-group-title">{entry.group_title}</p>
        <h1>{data.metadata_pending ? "名称待补全" : entry.title}</h1>
        {data.metadata_pending && <p className="pending-explanation">文本已收录，剧情资料尚未关联。<Link to="/updates?view=pending">查看待补全资料</Link></p>}
        {data.metadata_pending && !!data.group_images?.length && <CardPreview images={data.group_images} title="文件名匹配预览" />}
        <div className="chapter-status">
          <span>{statusLabel[data.text_status]}</span>
          <span>{data.line_count} 条文本</span>
          <span>{data.voice_event_count} 个语音事件</span>
        </div>
        {data.entries.length > 1 && (
          <label className="variant-label">
            剧情入口
            <select
              value={entry.id}
              onChange={(e) => setParams({ entry: e.target.value })}
            >
              {data.entries.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.group_title} · {e.title} ·{" "}
                  {e.character_ids
                    .map(
                      (id) =>
                        catalog.characters.find((c) => c.id === id)?.name || id,
                    )
                    .join("、")}
                </option>
              ))}
            </select>
          </label>
        )}
        <ChapterWorkbench key={data.script_id} scriptId={data.script_id} voices={data.voices} />
        <details className="chapter-source">
          <summary>查看章节资源信息</summary>
          <dl>
            <dt>剧情资源</dt>
            <dd>{data.script_id}</dd>
            <dt>文本文件</dt>
            <dd>{data.csv_path || "尚未收录"}</dd>
            <dt>入口标识</dt>
            <dd>{entry.id}</dd>
          </dl>
        </details>
      </section>
    </main>
  );
}
function NotFound() {
  return (
    <main>
      <div className="empty-state">
        <h1>页面不存在</h1>
        <Link className="gold-button" to="/">
          回到学园名簿 <ArrowRight size={16} />
        </Link>
      </div>
    </main>
  );
}
export default function App() {
  const { data, error } = useJson<Catalog>("/catalog/manifest.json");
  return (
    <>
      <a className="skip-link" href="#content">
        跳至正文
      </a>
      <Header revision={data?.resource_revision} />
      <div id="content" tabIndex={-1}>
        {!data ? (
          <ResourceStatus error={error} />
        ) : (
          <CatalogContext.Provider value={data}>
            <ScrollReset />
            <Routes>
              <Route path="/" element={<Navigate to="/idols" replace />} />
              <Route path="/idols" element={<CharacterPage />} />
              <Route
                path="/idol-commu/:characterId"
                element={<CharacterPage />}
              />
              <Route
                path="/character-card/:characterId"
                element={<CharacterPage />}
              />
              <Route path="/updates" element={<TextUpdates />} />
              <Route path="/workbench" element={<WorkbenchPage />} />
              <Route path="/stories/:categoryId" element={<CategoryPage />} />
              <Route path="/chapter/:scriptId" element={<ChapterPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </CatalogContext.Provider>
        )}
      </div>
      <footer>
        <Link className="footer-brand" to="/">
          初星学园 <span>STORY ARCHIVE</span>
        </Link>
        <small>
          非官方剧情索引 · 游戏素材 © Bandai Namco Entertainment Inc.
        </small>
      </footer>
    </>
  );
}
