import { useEffect, useState } from "react";
import { ArrowRight, Check, ChevronDown, ChevronRight, Cloud, Folder, FolderInput, Pencil, RefreshCw, RotateCcw, ShieldCheck, X } from "lucide-react";
import { get, post, qs } from "../api";
import FileDetail from "../components/FileDetail";
import { Empty, FileThumbOrIcon, GroupBadge, Importance, Labels, ExportMenu, ReviewBadge, SimBadge, useAsync, useJobs, useToast } from "../components/ui";
import type { TreeNode } from "../types";
import { fmtBytes, fmtNum, shortPath } from "../util";

interface PFile {
  id: number; name: string; path: string; computer_name: string; volume_name: string; file_type: string; size: number; mtime: string;
  category: string; group_name: string; importance: number; confidence: number; target: string; review_status: string;
  dup_count: number; is_primary: number; summary: string; thumbs: number; labels: string[]; ext?: string; final_path: string | null;
  sim_kind: string | null; sim_count: number; sim_best: number;
}

function Node({ n, depth, sel, onSel }: { n: TreeNode; depth: number; sel: string; onSel: (p: string) => void }) {
  const [open, setOpen] = useState(depth < 1);
  const pct = n.count ? (n.approved / n.count) * 100 : 0;
  return (
    <>
      <div className={`ptree-item ${sel === n.path ? "on" : ""}`} style={{ paddingLeft: 6 + depth * 14 }} onClick={() => onSel(n.path)}>
        <span className="chev" style={{ width: 14, display: "flex" }} onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
          {n.children.length ? (open ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : null}
        </span>
        <Folder size={14} color={depth === 0 ? "var(--accent)" : "#eab308"} />
        <span className="ellipsis grow">{n.name}</span>
        <div className="mini-prog" title={`${n.approved}/${n.count} freigegeben`}><div style={{ width: `${pct}%` }} /></div>
        <span className="faint" style={{ fontSize: 11, minWidth: 24, textAlign: "right" }}>{n.count}</span>
      </div>
      {open && n.children.map((c) => <Node key={c.path} n={c} depth={depth + 1} sel={sel} onSel={onSel} />)}
    </>
  );
}

export default function Proposal() {
  const { version, refresh } = useJobs();
  const toast = useToast();
  const [folder, setFolder] = useState("");
  const [inclDup, setInclDup] = useState(false);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const [moveTo, setMoveTo] = useState<string | null>(null);
  const [rename, setRename] = useState<string | null>(null);
  const tree = useAsync<TreeNode>(() => get(`/api/proposal/tree${qs({ include_duplicates: inclDup })}`), [version, tick, inclDup]);
  const files = useAsync<PFile[]>(() => get(`/api/proposal/files${qs({ folder, include_duplicates: inclDup, recursive: true })}`), [folder, version, tick, inclDup]);
  useEffect(() => setChecked(new Set()), [folder]);

  const act = async (action: string, body: Record<string, unknown>) => {
    try {
      const r = await post<{ geändert: number }>("/api/review", { action, include_duplicates: inclDup, ...body });
      toast(`${r["geändert"]} Dateien: ${action === "freigeben" ? "freigegeben" : action === "ablehnen" ? "abgelehnt" : "zurückgesetzt"}`);
      setChecked(new Set());
      setTick((t) => t + 1);
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const doMove = async () => {
    if (moveTo === null) return;
    await post("/api/proposal/move", { file_ids: [...checked], folder: moveTo });
    toast(`${checked.size} Dateien im Vorschlag verschoben (virtuell)`);
    setMoveTo(null);
    setChecked(new Set());
    setTick((t) => t + 1);
  };
  const doRename = async () => {
    if (rename === null || !folder) return;
    const r = await post<{ geändert: number }>("/api/proposal/rename-folder", { old: folder, new: rename });
    toast(`Ordner im Vorschlag umbenannt (${r["geändert"]} Dateien)`);
    setFolder(rename);
    setRename(null);
    setTick((t) => t + 1);
  };
  const regenerate = async () => {
    await post("/api/pipeline/propose");
    refresh();
    toast("Vorschlag wird neu berechnet");
  };

  const root = tree.data;
  const items = files.data ?? [];
  const allChecked = items.length > 0 && items.every((f) => checked.has(f.id));
  const toggleAll = () => setChecked(allChecked ? new Set() : new Set(items.map((f) => f.id)));

  if (root && root.count === 0) {
    return (
      <div className="content">
        <div className="card"><Empty icon={<Cloud size={38} />} title="Noch kein Vorschlag vorhanden">Führe zuerst Schritt 1 (Einlesen) und Schritt 2 (Analysieren) auf der Übersicht aus.</Empty></div>
      </div>
    );
  }

  return (
    <div className="proposal" style={{ gridTemplateColumns: detail ? "330px minmax(0,1fr) 420px" : undefined }}>
      <div className="pane tree-pane">
        <div className="row" style={{ padding: "4px 8px 10px" }}>
          <Cloud size={16} color="var(--accent)" />
          <b className="grow">Neue Cloud-Struktur</b>
          <button className="btn sm ghost" title="Vorschlag neu berechnen" onClick={regenerate}><RefreshCw size={13} /></button>
        </div>
        <label className="switch" style={{ padding: "0 8px 8px" }}><input type="checkbox" checked={inclDup} onChange={(e) => setInclDup(e.target.checked)} /> Duplikate einblenden</label>
        {root && (
          <>
            <div className={`ptree-item ${folder === "" ? "on" : ""}`} onClick={() => setFolder("")}>
              <span style={{ width: 14 }} /><Cloud size={14} /><span className="grow">Zielordner (gesamt)</span>
              <span className="faint" style={{ fontSize: 11 }}>{root.count}</span>
            </div>
            {root.children.map((c) => <Node key={c.path} n={c} depth={0} sel={folder} onSel={setFolder} />)}
          </>
        )}
      </div>

      <div className="list-pane">
        <div className="toolbar">
          <div className="grow">
            <div className="row" style={{ gap: 6 }}>
              <h2 className="ellipsis">{folder || "Alle vorgeschlagenen Ordner"}</h2>
              {folder && <button className="btn sm ghost" title="Ordner im Vorschlag umbenennen" onClick={() => setRename(folder)}><Pencil size={13} /></button>}
            </div>
            <div className="faint" style={{ fontSize: 12 }}>{fmtNum(items.length)} Dateien · {fmtBytes(items.reduce((a, f) => a + f.size, 0))} · Nur Vorschlag – physisch wird nichts verändert</div>
          </div>
          <ExportMenu path="/api/export/vorschlag" params={{ include_duplicates: inclDup }} title="Gesamten Vorschlag (alle Ordner, Prüfstatus, Quelle → Ziel) als Excel/CSV" />
          <button className="btn ok" onClick={() => act("freigeben", { folder })}><Check size={14} /> Ordner freigeben</button>
          <button className="btn bad" onClick={() => act("ablehnen", { folder })}><X size={14} /> Ordner ablehnen</button>
          <button className="btn ghost" onClick={() => act("zurücksetzen", { folder })}><RotateCcw size={14} /></button>
        </div>
        {rename !== null && (
          <div className="filterbar">
            <span style={{ fontSize: 12.5 }}>Neuer Ordnerpfad:</span>
            <input className="input mono grow" value={rename} onChange={(e) => setRename(e.target.value)} />
            <button className="btn sm primary" onClick={doRename}>Umbenennen</button>
            <button className="btn sm ghost" onClick={() => setRename(null)}>Abbrechen</button>
          </div>
        )}
        {checked.size > 0 && (
          <div className="filterbar" style={{ background: "var(--accent-soft)" }}>
            <b style={{ fontSize: 12.5 }}>{checked.size} ausgewählt</b>
            <button className="btn sm ok" onClick={() => act("freigeben", { file_ids: [...checked] })}><Check size={13} /> Freigeben</button>
            <button className="btn sm bad" onClick={() => act("ablehnen", { file_ids: [...checked] })}><X size={13} /> Ablehnen</button>
            <button className="btn sm" onClick={() => setMoveTo(folder)}><FolderInput size={13} /> In anderen Ordner …</button>
            {moveTo !== null && (
              <>
                <input className="input mono grow" style={{ padding: "4px 8px" }} value={moveTo} onChange={(e) => setMoveTo(e.target.value)} placeholder="z. B. 02_Beruf/Projekte/Phoenix" />
                <button className="btn sm primary" onClick={doMove}>Übernehmen</button>
              </>
            )}
          </div>
        )}
        <div className="list-scroll">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 34 }}><input type="checkbox" checked={allChecked} onChange={toggleAll} /></th>
                <th>Datei</th>
                <th style={{ width: "34%" }}>Bisher → Neu (Vorschlag)</th>
                <th style={{ width: 160 }}>Labels</th>
                <th style={{ width: 105 }}>Wichtigkeit</th>
                <th style={{ width: 100 }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.id} className={`${detail === f.id ? "sel" : ""} ${!f.is_primary ? "dupe" : ""}`} onClick={() => setDetail(f.id)}>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={checked.has(f.id)} onChange={() => { const s = new Set(checked); s.has(f.id) ? s.delete(f.id) : s.add(f.id); setChecked(s); }} />
                  </td>
                  <td>
                    <div className="fname">
                      <FileThumbOrIcon id={f.id} thumbs={f.thumbs} type={f.file_type} ext={f.ext || ""} />
                      <div className="grow">
                        <div className="n ellipsis">{f.name}</div>
                        <div className="row" style={{ gap: 5, marginTop: 2 }}><GroupBadge group={f.group_name} /><span className="faint ellipsis" style={{ fontSize: 11.5 }}>{f.category}</span>{f.dup_count > 1 && <span className="badge warn">{f.dup_count}×</span>}<SimBadge kind={f.sim_kind} count={f.sim_count} best={f.sim_best} small /></div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="arrow-path">
                      <span className="mono ellipsis faint" title={f.path}>{f.computer_name}: {shortPath(f.path, 2, true)}</span>
                      <ArrowRight size={14} color="var(--ok)" />
                      <span className="mono ellipsis" style={{ color: "var(--ok)" }} title={f.target}>{shortPath(f.target, 3, true)}{f.final_path ? " ✎" : ""}</span>
                    </div>
                  </td>
                  <td><Labels labels={f.labels} max={2} nowrap /></td>
                  <td><Importance value={f.importance} /></td>
                  <td><ReviewBadge status={f.review_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!files.loading && !items.length && <div className="empty">Keine Dateien in diesem Ordner.</div>}
        </div>
        <div className="statusbar">
          <ShieldCheck size={14} color="var(--ok)" />
          <span>Freigegebene Dateien werden erst in Schritt 4 als <b>Kopie</b> angelegt. Originale bleiben unverändert.</span>
          <span className="spacer" />
          {root && <span><b>{fmtNum(root.approved)}</b> freigegeben · {fmtNum(root.rejected)} abgelehnt · {fmtNum(root.count - root.approved - root.rejected)} offen</span>}
        </div>
      </div>
      {detail && <FileDetail id={detail} onClose={() => setDetail(null)} onChanged={() => setTick((t) => t + 1)} onOpen={setDetail} />}
    </div>
  );
}
