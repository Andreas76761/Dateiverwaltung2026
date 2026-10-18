import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Cloud, Copy, Folder, FolderOpen, GalleryHorizontal, HardDrive, Images, LayoutGrid, Laptop, List, PanelLeftClose, PanelLeftOpen, Pin, Search, Usb, X } from "lucide-react";
import { get, qs, thumbUrl } from "../api";
import FileDetail from "../components/FileDetail";
import { FileIcon, FileThumbOrIcon, GroupBadge, Importance, Labels, PageViewer, ReviewBadge, useAsync, useJobs } from "../components/ui";
import type { Computer, FileItem, FileList } from "../types";

// Dateitypen mit Seitenvorschau (Office über LibreOffice → PDF → alle Seiten)
const PREVIEW_EXTS = ".pdf,.pptx,.ppt,.ppsx,.odp,.docx,.doc,.odt,.rtf,.xlsx,.xls,.xlsm,.ods,.png,.jpg,.jpeg" +
  ",.mp4,.mov,.avi,.mkv,.m4v,.wmv,.webm,.mpg,.mpeg,.3gp,.mts,.eml,.msg";
import { fmtBytes, fmtDate, fmtNum, GROUPS, shortLabel } from "../util";

interface Facets {
  categories: { value: string; grp: string; n: number }[];
  types: { value: string; n: number }[];
  labels: { value: string; n: number }[];
}

type View = "list" | "grid" | "pages";
const PREVIEW_PAGES = 24; // so viele Seiten je Datei sofort, Rest per Klick

function PageStrip({ f, selected, onOpen, onPage }: { f: FileItem; selected: boolean; onOpen: () => void; onPage: (p: number) => void }) {
  const [all, setAll] = useState(false);
  const n = all ? f.thumbs : Math.min(f.thumbs, PREVIEW_PAGES);
  const isVideo = f.file_type === "Video";
  const wide = f.file_type === "Präsentation" || isVideo;
  const unit = isVideo ? ["Standbild", "Standbilder"] : ["Seite", "Seiten"];
  const nAtt = new Set(f.thumb_labels.filter((l) => l.startsWith("Anhang")).map((l) => l.replace(/ · S\. \d+$/, ""))).size;
  return (
    <div className={`pv-file ${selected ? "sel" : ""}`}>
      <div className="pv-head" onClick={onOpen}>
        <FileIcon type={f.file_type} ext={f.ext} />
        <div className="grow">
          <div className="ellipsis" style={{ fontWeight: 600 }}>{f.name}</div>
          <div className="faint ellipsis" style={{ fontSize: 11.5 }}>
            {f.thumbs > 1 ? `${f.thumbs} ${unit[1]} · ` : f.thumbs === 1 ? `1 ${unit[0]} · ` : ""}
            {nAtt > 0 ? `${nAtt} ${nAtt === 1 ? "Anhang" : "Anhänge"} · ` : ""}{f.computer_name} · {f.volume_name} · {fmtDate(f.mtime)} · {fmtBytes(f.size)}
          </div>
        </div>
        <GroupBadge group={f.group_name} />
        {f.category && <span className="badge outline">{f.category}</span>}
        {f.dup_count > 1 && <span className={`badge ${f.is_primary ? "warn" : "bad"}`}>{f.dup_count}×</span>}
        <div style={{ width: 110 }}><Importance value={f.importance} /></div>
      </div>
      {f.thumbs > 0 ? (
        <div className="pv-strip">
          {Array.from({ length: n }, (_, i) => i + 1).map((p) => (
            <div key={p} className={`pv-page ${wide ? "wide" : ""} ${f.thumb_labels[p - 1]?.startsWith("Anhang") ? "att" : ""}`}
              onClick={() => onPage(p)} title={f.thumb_labels[p - 1] || `Seite ${p}`}>
              <img src={thumbUrl(f.id, p)} loading="lazy" alt={f.thumb_labels[p - 1] || `Seite ${p}`} />
              {isVideo && <i className="play">▶</i>}
              {(f.thumbs > 1 || f.thumb_labels[p - 1]) && <span>{shortLabel(f.thumb_labels[p - 1], p)}</span>}
            </div>
          ))}
          {f.thumbs > n && <button className="btn sm pv-more" onClick={() => setAll(true)}>+ {f.thumbs - n} weitere Seiten</button>}
        </div>
      ) : (
        <div className="faint" style={{ padding: "10px 12px", fontSize: 12.5 }}>Keine Miniaturansicht – Datei noch nicht analysiert oder Dateityp ohne Vorschau.</div>
      )}
    </div>
  );
}

type Sel = { computer?: string; volume?: string; folder?: string };

function VolumeIcon({ kind }: { kind: string }) {
  if (kind === "cloud") return <Cloud size={14} color="var(--beruf)" />;
  if (kind === "external") return <Usb size={14} color="var(--warn)" />;
  return <HardDrive size={14} color="var(--text-3)" />;
}

function FolderNode({ volume, path, name, count, depth, sel, onSel }: { volume: string; path: string; name: string; count: number; depth: number; sel: Sel; onSel: (s: Sel) => void }) {
  const [open, setOpen] = useState(false);
  const [kids, setKids] = useState<{ name: string; path: string; count: number }[] | null>(null);
  const on = sel.volume === volume && sel.folder === path;
  const toggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!open && kids === null) {
      const r = await get<{ folders: any[] }>(`/api/tree${qs({ volume, prefix: path })}`);
      setKids(r.folders);
    }
    setOpen(!open);
  };
  return (
    <>
      <div className={`tree-item ${on ? "on" : ""}`} style={{ paddingLeft: 8 + depth * 14 }} onClick={() => onSel({ volume, folder: path })}>
        <span className="chev" onClick={toggle}>{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
        {open ? <FolderOpen size={14} color="#eab308" /> : <Folder size={14} color="#eab308" />}
        <span className="ellipsis">{name}</span>
        <span className="cnt">{count}</span>
      </div>
      {open && kids?.map((k) => <FolderNode key={k.path} volume={volume} path={k.path} name={k.name} count={k.count} depth={depth + 1} sel={sel} onSel={onSel} />)}
    </>
  );
}

function VolumeNode({ v, sel, onSel }: { v: Computer["volumes"][number]; sel: Sel; onSel: (s: Sel) => void }) {
  const [open, setOpen] = useState(false);
  const [kids, setKids] = useState<{ name: string; path: string; count: number }[] | null>(null);
  const toggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!open && kids === null) setKids((await get<{ folders: any[] }>(`/api/tree${qs({ volume: v.id })}`)).folders);
    setOpen(!open);
  };
  return (
    <>
      <div className={`tree-item ${sel.volume === v.id && !sel.folder ? "on" : ""}`} style={{ paddingLeft: 22 }} onClick={() => onSel({ volume: v.id })}>
        <span className="chev" onClick={toggle}>{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
        <VolumeIcon kind={v.kind} />
        <span className="ellipsis">{v.name}</span>
        <span className="cnt">{fmtNum(v.files)}</span>
      </div>
      {open && kids?.map((k) => <FolderNode key={k.path} volume={v.id} path={k.path} name={k.name} count={k.count} depth={2} sel={sel} onSel={onSel} />)}
    </>
  );
}

export default function Explorer({ params }: { params: URLSearchParams }) {
  const { version } = useJobs();
  const [sel, setSel] = useState<Sel>({ volume: params.get("volume") || undefined });
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [group, setGroup] = useState(params.get("group") || "");
  const [category, setCategory] = useState("");
  const [fileType, setFileType] = useState("");
  const [label, setLabel] = useState("");
  const [dup, setDup] = useState(params.get("dup") || "");
  const [review, setReview] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sort, setSort] = useState("importance");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [view, setView] = useState<View>(() => {
    try { return (localStorage.getItem("fdv-view") as View) || "list"; } catch { return "list"; }
  });
  const [previewOnly, setPreviewOnly] = useState(false);
  const [showTree, setShowTree] = useState<boolean>(() => {
    try { return localStorage.getItem("fdv-tree") !== "0"; } catch { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem("fdv-tree", showTree ? "1" : "0"); } catch { /* ignore */ }
  }, [showTree]);
  const [viewer, setViewer] = useState<{ id: number; name: string; pages: number; page: number; labels: string[]; video: boolean } | null>(null);
  const [limit, setLimit] = useState(150);
  const [detail, setDetail] = useState<number | null>(params.get("file") ? Number(params.get("file")) : null);
  const [openComp, setOpenComp] = useState<Record<string, boolean>>({});
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    try { localStorage.setItem("fdv-view", view); } catch { /* ignore */ }
  }, [view]);

  const sources = useAsync<{ computers: Computer[] }>(() => get("/api/sources"), [version]);
  const facets = useAsync<Facets>(() => get("/api/facets"), [version, tick]);
  const query = useMemo(() => qs({
    q: qDebounced, computer: sel.computer, volume: sel.volume, folder: sel.folder, group: group === "(nicht analysiert)" ? undefined : group,
    category, file_type: fileType, label, dup, review, date_from: dateFrom, date_to: dateTo, sort, order,
    status: group === "(nicht analysiert)" ? "eingelesen" : undefined,
    ext: previewOnly ? PREVIEW_EXTS : undefined,
    limit,
  }), [qDebounced, sel, group, category, fileType, label, dup, review, dateFrom, dateTo, sort, order, limit, previewOnly, view]);
  const list = useAsync<FileList>(() => get(`/api/files${query}`), [query, version, tick]);

  const setSortCol = (c: string) => {
    if (sort === c) setOrder(order === "asc" ? "desc" : "asc");
    else { setSort(c); setOrder(c === "name" || c === "type" ? "asc" : "desc"); }
  };
  const SortTh = ({ c, children, w }: { c: string; children: React.ReactNode; w?: number }) => (
    <th className="sort" style={{ width: w }} onClick={() => setSortCol(c)}>
      <span className="row" style={{ gap: 3 }}>{children}{sort === c && (order === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}</span>
    </th>
  );
  const anyFilter = previewOnly || group || category || fileType || label || dup || review || dateFrom || dateTo || qDebounced;
  const reset = () => { setGroup(""); setCategory(""); setFileType(""); setLabel(""); setDup(""); setReview(""); setDateFrom(""); setDateTo(""); setQ(""); setPreviewOnly(false); };
  const items = list.data?.items ?? [];
  const compact = detail !== null;
  const selName = (() => {
    const comps = sources.data?.computers ?? [];
    if (sel.computer) return comps.find((c) => c.id === sel.computer)?.name;
    if (sel.volume) {
      for (const c of comps) {
        const v = c.volumes.find((x) => x.id === sel.volume);
        if (v) return `${c.name} › ${v.name}${sel.folder ? ` › ${sel.folder}` : ""}`;
      }
    }
    return "Alle Computer & Festplatten";
  })();

  return (
    <div className={`explorer ${detail ? "with-detail" : ""} ${showTree ? "" : "no-tree"}`}>
      {showTree && <div className="pane tree-pane">
        <div className={`tree-item ${!sel.computer && !sel.volume ? "on" : ""}`} onClick={() => setSel({})}>
          <span className="chev" /><LayoutGrid size={14} /> <span>Alle Dateien</span>
        </div>
        <div className="nav-sec" style={{ color: "var(--text-3)" }}>Computer</div>
        {sources.data?.computers.map((c) => (
          <div key={c.id}>
            <div className={`tree-item ${sel.computer === c.id ? "on" : ""}`} onClick={() => setSel({ computer: c.id })}>
              <span className="chev" onClick={(e) => { e.stopPropagation(); setOpenComp({ ...openComp, [c.id]: !(openComp[c.id] ?? true) }); }}>
                {(openComp[c.id] ?? true) ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              </span>
              <Laptop size={14} /><span className="ellipsis" style={{ fontWeight: 600 }}>{c.name}</span>
              <span className="cnt">{fmtNum(c.volumes.reduce((a, v) => a + v.files, 0))}</span>
            </div>
            {(openComp[c.id] ?? true) && c.volumes.map((v) => <VolumeNode key={v.id} v={v} sel={sel} onSel={setSel} />)}
          </div>
        ))}
        <div className="nav-sec" style={{ color: "var(--text-3)" }}>Bereiche</div>
        {GROUPS.map((g) => (
          <div key={g} className={`tree-item ${group === g ? "on" : ""}`} onClick={() => setGroup(group === g ? "" : g)}>
            <span className="chev" /><span className={`dot g-${g === "Sonstiges" ? "sonst" : g.toLowerCase()}`} /> {g}
          </div>
        ))}
        <div className={`tree-item ${dup === "ja" ? "on" : ""}`} onClick={() => setDup(dup === "ja" ? "" : "ja")}>
          <span className="chev" /><Copy size={14} /> Duplikate
        </div>
      </div>}

      <div className="list-pane">
        <div className="toolbar">
          <button className="btn icon" onClick={() => setShowTree(!showTree)} title={showTree ? "Ordnerbaum ausblenden" : "Ordnerbaum einblenden"}>
            {showTree ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
          </button>
          <div className="search grow" style={{ maxWidth: 520 }}>
            <Search size={15} />
            <input className="input" placeholder="Suche in Name, Pfad, Inhalt, OCR-Text und Labels …" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <select className="input" value={sort} onChange={(e) => setSort(e.target.value)} title="Sortierung">
            <option value="importance">Nach Wichtigkeit</option>
            <option value="mtime">Nach Speicherdatum</option>
            <option value="type">Nach Dateityp</option>
            <option value="category">Nach Kategorie</option>
            <option value="name">Nach Name</option>
            <option value="size">Nach Größe</option>
            <option value="computer">Nach Computer</option>
          </select>
          <button className="btn icon" onClick={() => setOrder(order === "asc" ? "desc" : "asc")} title="Reihenfolge">{order === "asc" ? <ArrowUp size={15} /> : <ArrowDown size={15} />}</button>
          <div className="seg">
            <button className={view === "list" ? "on" : ""} onClick={() => setView("list")}><List size={14} /> Liste</button>
            <button className={view === "grid" ? "on" : ""} onClick={() => setView("grid")}><LayoutGrid size={14} /> Galerie</button>
            <button className={view === "pages" ? "on" : ""} onClick={() => { setView("pages"); setPreviewOnly(true); }} title="Alle Seiten/Standbilder von PDF, Office, Bildern, Videos und E-Mails als Miniaturen"><GalleryHorizontal size={14} /> Seiten</button>
          </div>
        </div>
        <div className="filterbar">
          <button className={`chip ${previewOnly ? "on" : ""}`} onClick={() => setPreviewOnly(!previewOnly)} title="Nur Dateien mit Vorschau: PDF, PPTX, DOCX, XLSX, PNG, JPEG, Videos (Standbilder), E-Mails (inkl. Anhänge)">
            <Images size={12} /> PDF · Office · Bilder · Videos · E-Mails
          </button>
          {GROUPS.map((g) => (
            <button key={g} className={`chip ${group === g ? "on" : ""}`} onClick={() => setGroup(group === g ? "" : g)}>
              <span className={`dot g-${g === "Sonstiges" ? "sonst" : g.toLowerCase()}`} />{g}
            </button>
          ))}
          <select className="input" style={{ padding: "3px 8px", fontSize: 12 }} value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Kategorie (50)</option>
            {facets.data?.categories.filter((c) => !group || c.grp === group).map((c) => <option key={c.value} value={c.value}>{c.value} ({c.n})</option>)}
          </select>
          <select className="input" style={{ padding: "3px 8px", fontSize: 12 }} value={fileType} onChange={(e) => setFileType(e.target.value)}>
            <option value="">Dateityp</option>
            {facets.data?.types.map((c) => <option key={c.value} value={c.value}>{c.value} ({c.n})</option>)}
          </select>
          <select className="input" style={{ padding: "3px 8px", fontSize: 12 }} value={label} onChange={(e) => setLabel(e.target.value)}>
            <option value="">Label</option>
            {facets.data?.labels.map((c) => <option key={c.value} value={c.value}>{c.value} ({c.n})</option>)}
          </select>
          <select className="input" style={{ padding: "3px 8px", fontSize: 12 }} value={dup} onChange={(e) => setDup(e.target.value)}>
            <option value="">Duplikate: alle</option>
            <option value="ja">nur mit Duplikaten</option>
            <option value="nur_kopien">nur überzählige Kopien</option>
            <option value="nein">ohne Duplikate</option>
          </select>
          <select className="input" style={{ padding: "3px 8px", fontSize: 12 }} value={review} onChange={(e) => setReview(e.target.value)}>
            <option value="">Prüfstatus</option>
            <option value="offen">offen</option>
            <option value="freigegeben">freigegeben</option>
            <option value="abgelehnt">abgelehnt</option>
          </select>
          <span className="faint" style={{ fontSize: 12, marginLeft: 4 }}>Gespeichert</span>
          <input type="date" className="input" style={{ padding: "2px 6px", fontSize: 12 }} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <span className="faint">–</span>
          <input type="date" className="input" style={{ padding: "2px 6px", fontSize: 12 }} value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          {anyFilter && <button className="chip" onClick={reset}><X size={12} /> Filter zurücksetzen</button>}
        </div>

        <div className="list-scroll">
          {view === "pages" ? (
            <div className="pages-view">
              {items.map((f) => (
                <PageStrip key={f.id} f={f} selected={detail === f.id} onOpen={() => setDetail(f.id)}
                  onPage={(p) => setViewer({ id: f.id, name: f.name, pages: f.thumbs, page: p, labels: f.thumb_labels, video: f.file_type === "Video" })} />
              ))}
            </div>
          ) : view === "list" ? (
            <table className="table" style={{ tableLayout: "fixed" }}>
              <thead>
                <tr>
                  <SortTh c="name">Name</SortTh>
                  <SortTh c="category" w={compact ? 150 : 190}>Kategorie</SortTh>
                  {!compact && <th style={{ width: 170 }}>Labels</th>}
                  <SortTh c="importance" w={110}>Wichtigkeit</SortTh>
                  <SortTh c="mtime" w={95}>Gespeichert</SortTh>
                  {!compact && <SortTh c="size" w={80}>Größe</SortTh>}
                  {!compact && <SortTh c="computer" w={150}>Ort</SortTh>}
                </tr>
              </thead>
              <tbody>
                {items.map((f) => (
                  <tr key={f.id} className={`${detail === f.id ? "sel" : ""} ${f.dup_count > 1 && !f.is_primary ? "dupe" : ""}`} onClick={() => setDetail(f.id)}>
                    <td>
                      <div className="fname">
                        <FileThumbOrIcon id={f.id} thumbs={f.thumbs} type={f.file_type} ext={f.ext} />
                        <div className="grow">
                          <div className="n ellipsis row" style={{ gap: 5 }}>
                            {f.pinned ? <Pin size={12} color="var(--accent)" /> : null}
                            <span className="ellipsis">{f.name}</span>
                            {f.dup_count > 1 && <span className={`badge ${f.is_primary ? "warn" : "bad"}`} style={{ fontSize: 10, padding: "0 6px" }}>{f.dup_count}×</span>}
                          </div>
                          <div className="p ellipsis">{f.file_type}{f.page_count ? ` · ${f.page_count} S.` : ""} · {f.rel_path}</div>
                        </div>
                      </div>
                    </td>
                    <td><div className="col" style={{ gap: 3, alignItems: "flex-start" }}><GroupBadge group={f.group_name} />{f.category && <span className="faint ellipsis" style={{ fontSize: 11.5, maxWidth: 180 }}>{f.category}</span>}</div></td>
                    {!compact && <td><Labels labels={f.labels} max={2} nowrap /></td>}
                    <td><Importance value={f.importance} /></td>
                    <td className="faint nowrap">{fmtDate(f.mtime)}</td>
                    {!compact && <td className="faint nowrap">{fmtBytes(f.size)}</td>}
                    {!compact && <td><div className="ellipsis" style={{ fontSize: 12, maxWidth: 150 }}>{f.computer_name}</div><div className="faint ellipsis" style={{ fontSize: 11, maxWidth: 150 }}>{f.volume_name}</div></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="gallery">
              {items.map((f) => (
                <div key={f.id} className={`tile ${detail === f.id ? "sel" : ""}`} onClick={() => setDetail(f.id)}>
                  <div className="tile-img">
                    {f.thumbs ? <img src={thumbUrl(f.id, 1)} loading="lazy" alt="" /> : <div style={{ transform: "scale(1.6)" }}><FileIcon type={f.file_type} ext={f.ext} /></div>}
                    {f.thumbs > 1 && <span className="pages">{f.thumbs} {f.file_type === "Video" ? "Standbilder" : "Seiten"}</span>}
                    {f.file_type === "Video" && f.thumbs > 0 && <i className="play big">▶</i>}
                    <span className="imp-pill"><span className="badge" style={{ background: "rgba(15,23,42,.75)", color: "white" }}>★ {f.importance}</span></span>
                  </div>
                  <div className="tile-body">
                    <div className="n ellipsis" title={f.name}>{f.name}</div>
                    <div className="row" style={{ gap: 5 }}><GroupBadge group={f.group_name} />{f.dup_count > 1 && <span className="badge warn">{f.dup_count}×</span>}<ReviewBadge status={f.review_status} /></div>
                    <div className="faint ellipsis" style={{ fontSize: 11 }}>{f.category} · {fmtDate(f.mtime)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {!list.loading && items.length === 0 && <div className="empty">Keine Dateien für diese Auswahl.</div>}
          {list.data && items.length < list.data.total && (
            <div style={{ padding: 16, textAlign: "center" }}><button className="btn" onClick={() => setLimit(limit + 150)}>Weitere laden ({fmtNum(list.data.total - items.length)})</button></div>
          )}
        </div>
        <div className="statusbar">
          <span><b>{fmtNum(list.data?.total)}</b> Dateien · {fmtBytes(list.data?.bytes)}</span>
          <span className="ellipsis grow">{selName}</span>
          {list.loading && <span>lädt …</span>}
        </div>
      </div>

      {viewer && <PageViewer fileId={viewer.id} name={viewer.name} pages={viewer.pages} start={viewer.page} onClose={() => setViewer(null)} labels={viewer.labels} video={viewer.video} />}
      {detail && <FileDetail id={detail} onClose={() => setDetail(null)} onChanged={() => setTick((t) => t + 1)} />}
    </div>
  );
}
