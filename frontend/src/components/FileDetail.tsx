import { useEffect, useState } from "react";
import { ArrowDown, Copy, ExternalLink, Pin, PinOff, Plus, ScanText, Sparkles, X } from "lucide-react";
import { get, post, rawUrl, thumbUrl } from "../api";
import type { FileDetail as FD } from "../types";
import { fmtBytes, fmtDate, shortLabel } from "../util";
import { FileIcon, GroupBadge, Importance, PageViewer, ReviewBadge, useToast } from "./ui";

interface Cat { id: string; name: string; group: string }

export default function FileDetail({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged?: () => void }) {
  const [f, setF] = useState<FD>();
  const [tab, setTab] = useState<"seiten" | "inhalt" | "ocr" | "duplikate">("seiten");
  const [viewer, setViewer] = useState<number | null>(null);
  const [newLabel, setNewLabel] = useState("");
  const [cats, setCats] = useState<Cat[]>([]);
  const [editPath, setEditPath] = useState<string | null>(null);
  const [videoErr, setVideoErr] = useState(false);
  const toast = useToast();

  const load = () => get<FD>(`/api/files/${id}`).then(setF).catch((e) => toast(e.message, true));
  useEffect(() => {
    setF(undefined);
    setEditPath(null);
    setVideoErr(false);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => {
    get<Cat[]>("/api/categories").then(setCats).catch(() => {});
  }, []);
  useEffect(() => {
    if (f && !f.thumbnails.length && tab === "seiten") setTab("inhalt");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f?.id]);

  if (!f) return <div className="detail"><div className="detail-body faint">Lädt …</div></div>;

  const update = async (body: Record<string, unknown>, msg: string) => {
    try {
      const r = await post<FD>(`/api/files/${f.id}/update`, body);
      setF(r);
      toast(msg);
      onChanged?.();
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const addLabel = async () => {
    if (!newLabel.trim()) return;
    await post(`/api/files/${f.id}/labels`, { label: newLabel.trim() });
    setNewLabel("");
    load();
    onChanged?.();
  };
  const removeLabel = async (label: string) => {
    await post(`/api/files/${f.id}/labels/remove`, { label });
    load();
    onChanged?.();
  };
  const target = f.final_path || f.suggested_path;
  const isVideo = f.file_type === "Video";

  return (
    <div className="detail">
      <div className="detail-head">
        <FileIcon type={f.file_type} ext={f.ext} />
        <div className="grow">
          <div style={{ fontWeight: 650, wordBreak: "break-word" }}>{f.name}</div>
          <div className="row wrap" style={{ gap: 6, marginTop: 5 }}>
            <GroupBadge group={f.group_name} />
            {f.category && <span className="badge outline">{f.category}</span>}
            <ReviewBadge status={f.review_status} />
            {f.dup_count > 1 && <span className={`badge ${f.is_primary ? "warn" : "bad"}`}><Copy size={11} /> {f.is_primary ? "Original" : "Duplikat"} · {f.dup_count}×</span>}
          </div>
        </div>
        <button className="btn ghost icon" title={f.pinned ? "Lösen" : "Anheften (wichtig)"} onClick={() => update({ pinned: !f.pinned }, f.pinned ? "Gelöst" : "Angeheftet")}>
          {f.pinned ? <PinOff size={16} /> : <Pin size={16} />}
        </button>
        <button className="btn ghost icon" onClick={onClose} aria-label="Schließen"><X size={18} /></button>
      </div>

      <div className="detail-body">
        <div>
          <div className="row" style={{ marginBottom: 6 }}>
            <h3>Wichtigkeit</h3>
          </div>
          <Importance value={f.importance} />
          {f.importance_reason && <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>{f.importance_reason}</div>}
        </div>

        {f.summary && (
          <div className="callout" style={{ padding: "10px 12px" }}>
            <Sparkles size={16} style={{ flexShrink: 0, color: "var(--accent)", marginTop: 2 }} />
            <div>
              <div style={{ fontSize: 12.5 }}>{f.summary}</div>
              <div className="faint" style={{ fontSize: 11, marginTop: 3 }}>
                {f.llm_provider} · Sicherheit {Math.round((f.confidence ?? 0) * 100)} %
              </div>
            </div>
          </div>
        )}

        <div>
          <h3 style={{ marginBottom: 8 }}>Labels</h3>
          <div className="row wrap" style={{ gap: 5 }}>
            {f.label_details.map((l) => (
              <span key={l.label} className={`label-chip ${l.source === "nutzer" ? "user" : ""}`} title={`Quelle: ${l.source}`}>
                {l.label}
                <button onClick={() => removeLabel(l.label)} aria-label="Label entfernen"><X size={11} /></button>
              </span>
            ))}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <input className="input grow" placeholder="Label hinzufügen …" value={newLabel} onChange={(e) => setNewLabel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addLabel()} style={{ padding: "5px 9px" }} />
            <button className="btn sm" onClick={addLabel}><Plus size={14} /></button>
          </div>
        </div>

        <div>
          <h3 style={{ marginBottom: 8 }}>Neue Eingruppierung (Vorschlag)</h3>
          <div className="pathbox">{f.computer_name} · {f.volume_name}<br />{f.rel_path}</div>
          <div style={{ textAlign: "center", color: "var(--text-3)", margin: "3px 0" }}><ArrowDown size={15} /></div>
          {editPath === null ? (
            <div className="pathbox new" onDoubleClick={() => setEditPath(target || "")} title="Doppelklick zum Bearbeiten">
              {target || "– noch kein Vorschlag –"}
            </div>
          ) : (
            <div className="col">
              <input className="input mono" value={editPath} onChange={(e) => setEditPath(e.target.value)} autoFocus />
              <div className="row">
                <button className="btn sm primary" onClick={() => { update({ final_path: editPath }, "Zielpfad gespeichert"); setEditPath(null); }}>Speichern</button>
                <button className="btn sm" onClick={() => { update({ final_path: "" }, "Vorschlag wiederhergestellt"); setEditPath(null); }}>Vorschlag verwenden</button>
                <button className="btn sm ghost" onClick={() => setEditPath(null)}>Abbrechen</button>
              </div>
            </div>
          )}
          <div className="row wrap" style={{ marginTop: 8 }}>
            <select className="input" style={{ flex: 1, minWidth: 0, padding: "5px 8px" }} value=""
              onChange={(e) => e.target.value && update({ category: e.target.value }, "Kategorie geändert")}>
              <option value="">Kategorie ändern …</option>
              {["Privat", "Beruf", "GenAI", "Sonstiges"].map((g) => (
                <optgroup key={g} label={g}>
                  {cats.filter((c) => c.group === g).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </optgroup>
              ))}
            </select>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn sm ok" onClick={() => update({ review_status: "freigegeben" }, "Freigegeben – wird in Schritt 4 kopiert")}>Freigeben</button>
            <button className="btn sm bad" onClick={() => update({ review_status: "abgelehnt" }, "Abgelehnt")}>Ablehnen</button>
            <button className="btn sm ghost" onClick={() => update({ review_status: "offen" }, "Zurückgesetzt")}>Zurücksetzen</button>
          </div>
        </div>

        <div>
          <div className="tabs">
            <button className={tab === "seiten" ? "on" : ""} onClick={() => setTab("seiten")}>{isVideo ? "Standbilder" : "Seiten"} ({f.thumbnails.length})</button>
            <button className={tab === "inhalt" ? "on" : ""} onClick={() => setTab("inhalt")}>Inhalt</button>
            <button className={tab === "ocr" ? "on" : ""} onClick={() => setTab("ocr")}><ScanText size={13} style={{ verticalAlign: -2 }} /> OCR</button>
            <button className={tab === "duplikate" ? "on" : ""} onClick={() => setTab("duplikate")}>Duplikate ({f.duplicates.length})</button>
          </div>
          <div style={{ paddingTop: 10 }}>
            {tab === "seiten" && isVideo && f.missing === 0 && (
              videoErr ? (
                <div className="callout warn" style={{ fontSize: 12.5, marginBottom: 10 }}>
                  Dieses Videoformat kann der Browser nicht direkt abspielen. Die Standbilder unten zeigen den Inhalt; zum Abspielen „Original ansehen“ nutzen.
                </div>
              ) : (
                <video className="video-player" src={rawUrl(f.id)} controls preload="metadata" onError={() => setVideoErr(true)}
                  poster={f.thumbnails.length ? thumbUrl(f.id, 1) : undefined} />
              )
            )}
            {tab === "seiten" && (f.thumbnails.length ? (
              <div className={`pages-grid ${isVideo ? "frames" : ""}`}>
                {f.thumbnails.map((t) => (
                  <div key={t.page} className="page-thumb" onClick={() => setViewer(t.page)} title={t.label ?? `Seite ${t.page}`}>
                    <img src={thumbUrl(f.id, t.page)} loading="lazy" alt={t.label ?? `Seite ${t.page}`} />
                    <span>{t.label ? shortLabel(t.label) : t.page}</span>
                  </div>
                ))}
              </div>
            ) : <div className="faint" style={{ fontSize: 12.5 }}>Keine Miniaturansicht für diesen Dateityp.</div>)}
            {tab === "inhalt" && <div className="textbox">{f.text_excerpt || "Kein Text extrahiert."}</div>}
            {tab === "ocr" && <div className="textbox">{f.ocr_text || "Keine OCR durchgeführt (nur für Bilder und gescannte PDFs ohne Textebene)."}</div>}
            {tab === "duplikate" && (f.duplicates.length ? (
              <div className="col">
                {f.duplicates.map((d) => (
                  <div key={d.id} className="pathbox">
                    {d.is_primary ? "★ Original · " : ""}{d.computer_name} · {d.volume_name}<br />{d.path}
                  </div>
                ))}
              </div>
            ) : <div className="faint" style={{ fontSize: 12.5 }}>Keine identischen Kopien gefunden.</div>)}
          </div>
        </div>

        <dl className="kv">
          <dt>Computer</dt><dd>{f.computer_name}</dd>
          <dt>Festplatte</dt><dd>{f.volume_name} <span className="faint">({f.volume_kind})</span></dd>
          <dt>Pfad</dt><dd className="mono">{f.path}</dd>
          <dt>Typ</dt><dd>{f.file_type} · {f.ext}{f.page_count ? ` · ${f.page_count} Seiten` : ""}</dd>
          <dt>Größe</dt><dd>{fmtBytes(f.size)}</dd>
          <dt>Geändert</dt><dd>{fmtDate(f.mtime, true)}</dd>
          <dt>Erstellt</dt><dd>{fmtDate(f.ctime, true)}</dd>
          <dt>Analysiert</dt><dd>{fmtDate(f.analyzed_at, true)}</dd>
          <dt>SHA-256</dt><dd className="mono" style={{ fontSize: 10.5 }}>{f.sha256 || "–"}</dd>
          {f.error && (<><dt>Hinweis</dt><dd style={{ color: "var(--warn)" }}>{f.error}</dd></>)}
        </dl>

        {f.copies.length > 0 && (
          <div>
            <h3 style={{ marginBottom: 6 }}>Kopien</h3>
            {f.copies.map((c) => (
              <div key={c.id} className="pathbox" style={{ marginBottom: 5 }}>
                <span className={`badge ${c.status === "kopiert" ? "ok" : c.status === "fehler" ? "bad" : "outline"}`}>{c.status}</span> {c.dst}
              </div>
            ))}
          </div>
        )}

        <a className="btn sm" href={rawUrl(f.id)} target="_blank" rel="noreferrer" style={{ alignSelf: "flex-start" }}>
          <ExternalLink size={14} /> Original ansehen (nur lesen)
        </a>
      </div>
      {viewer && <PageViewer fileId={f.id} name={f.name} pages={f.thumbnails.length} start={viewer} onClose={() => setViewer(null)}
        labels={f.thumbnails.map((t) => t.label)} video={isVideo} />}
    </div>
  );
}
