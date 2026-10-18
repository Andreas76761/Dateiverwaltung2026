import { useEffect, useState } from "react";
import { FileStack, Files, Images, Layers, Loader2, RefreshCw, Search, ShieldCheck, Star } from "lucide-react";
import { get, post, qs, thumbUrl } from "../api";
import FileDetail from "../components/FileDetail";
import { Empty, FileIcon, GroupBadge, SIM_TEXT, useAsync, useJobs, useToast } from "../components/ui";
import type { SimGroup, SimilarFile, SimKind } from "../types";
import { fmtBytes, fmtDate, fmtNum, shortPath } from "../util";

interface SimList {
  total: number;
  page: number;
  limit: number;
  groups: SimGroup[];
  summary: { k: SimKind; groups: number; n: number; other_bytes: number }[];
}

const KINDS: { k: SimKind; icon: typeof Layers }[] = [
  { k: "Versionen", icon: FileStack },
  { k: "Formate", icon: Files },
  { k: "Fotos", icon: Images },
  { k: "Inhalt", icon: Layers },
];

function role(g: SimGroup, m: SimilarFile): { text: string; cls: string } {
  if (g.kind === "Versionen") {
    if (m.sim_best === 1) return { text: "Neueste Version", cls: "ok" };
    if (m.sim_best === 2) return { text: "Neueste · anderes Format", cls: "ok" };
    return { text: "Ältere Version", cls: "warn" };
  }
  if (g.kind === "Fotos") return m.sim_best === 1 ? { text: "Beste Qualität", cls: "ok" } : { text: "Ähnlich", cls: "outline" };
  return m.sim_best === 1 ? { text: "Empfohlen", cls: "ok" } : { text: g.kind === "Formate" ? "Anderes Format" : "Ähnlich", cls: "outline" };
}

function MemberCard({ g, m, onOpen }: { g: SimGroup; m: SimilarFile; onOpen: () => void }) {
  const r = role(g, m);
  return (
    <div className={`sim-card ${m.sim_best === 1 ? "best" : ""}`} onClick={onOpen} title={m.path}>
      <div className="sim-prev">
        {m.thumbs > 0 ? <img src={thumbUrl(m.id, 1)} loading="lazy" alt="" /> : <FileIcon type={m.file_type} ext={m.ext} />}
      </div>
      <div className="sim-body">
        <div className="sim-name">{m.sim_best === 1 && <Star size={12} style={{ verticalAlign: -1, color: "var(--ok)" }} />} {m.name}</div>
        <div className="faint ellipsis">{m.computer_name} · {m.volume_name}</div>
        <div className="faint ellipsis mono" style={{ fontSize: 10.5 }}>{shortPath(m.path, 2, true)}</div>
        <div className="faint">{fmtDate(m.mtime)} · {fmtBytes(m.size)}{m.online_only ? " · ☁" : ""}</div>
        <div className="row" style={{ gap: 5, marginTop: 3, flexWrap: "wrap" }}>
          <span className={`badge ${r.cls}`}>{r.text}</span>
          <span className="badge outline">{(m.ext || "").replace(".", "").toUpperCase() || m.file_type}</span>
        </div>
      </div>
    </div>
  );
}

export default function Similar({ params }: { params: URLSearchParams }) {
  const { version, running, refresh } = useJobs();
  const toast = useToast();
  const [kind, setKind] = useState<string>(params.get("kind") || "");
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [limit, setLimit] = useState(30);
  const [detail, setDetail] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setQd(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  const data = useAsync<SimList>(() => get(`/api/similar${qs({ kind, q: qd, limit })}`), [kind, qd, limit, version, tick]);
  const busy = running.some((r) => r.kind === "similar" || r.kind === "analyze");
  const d = data.data;
  const sum = (k: SimKind) => d?.summary.find((s) => s.k === k);
  const older = sum("Versionen");

  const rerun = async () => {
    try {
      await post("/api/pipeline/similar", {});
      refresh();
      toast("Suche nach ähnlichen Dateien gestartet");
    } catch (e: any) {
      toast(e.message, true);
    }
  };

  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <h1>Ähnliche Dateien</h1>
          <p>Nicht identisch, aber zusammengehörig: Versionen (Angebot_v2 / Angebot_final), dasselbe Dokument als PDF und DOCX, bearbeitete oder verkleinerte Fotos.</p>
        </div>
        <button className="btn" disabled={busy} onClick={rerun}>{busy ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Neu suchen</button>
      </div>

      <div className="grid g4">
        {KINDS.map(({ k, icon: Icon }) => {
          const s = sum(k);
          return (
            <div key={k} className={`card kpi clickable ${kind === k ? "on" : ""}`} style={{ cursor: "pointer", outline: kind === k ? "2px solid var(--accent)" : undefined }}
              onClick={() => setKind(kind === k ? "" : k)} title={SIM_TEXT[k].hint}>
              <div className="k-label"><Icon size={14} /> {SIM_TEXT[k].label}</div>
              <div className="k-val">{fmtNum(s?.groups ?? 0)} <span className="faint" style={{ fontSize: 14 }}>Gruppen</span></div>
              <div className="k-sub">{fmtNum(s?.n ?? 0)} Dateien{k === "Versionen" && s ? ` · ${fmtBytes(s.other_bytes)} in älteren Versionen` : ""}</div>
            </div>
          );
        })}
      </div>

      <div className="callout ok" style={{ fontSize: 13 }}>
        <ShieldCheck size={18} color="var(--ok)" />
        <span>Hier wird nur angezeigt und empfohlen (★ = neueste Version bzw. beste Qualität) – es wird nichts gelöscht oder zusammengeführt.
          {older && older.n > 0 ? <> Beim Kopieren (Schritt 4) können ältere Versionen auf Wunsch ausgelassen werden.</> : null}</span>
      </div>

      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <div className="search" style={{ maxWidth: 360, flex: 1 }}>
          <Search size={15} />
          <input className="input" placeholder="Gruppen durchsuchen (Name, Inhalt, Labels) …" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button className={`chip ${!kind ? "on" : ""}`} onClick={() => setKind("")}>Alle</button>
        {KINDS.map(({ k }) => <button key={k} className={`chip ${kind === k ? "on" : ""}`} onClick={() => setKind(kind === k ? "" : k)}>{SIM_TEXT[k].label}</button>)}
        <span className="spacer" />
        {d && <span className="faint" style={{ fontSize: 12.5 }}>{fmtNum(d.total)} Gruppen</span>}
      </div>

      {d && d.groups.length === 0 ? (
        <div className="card">
          <Empty icon={<Layers size={32} />} title="Keine ähnlichen Dateien gefunden">
            Die Suche läuft automatisch am Ende jeder Analyse (Schritt 2). Verglichen werden Fotos (Bild-Fingerabdruck), Versionsangaben im Dateinamen und der Textinhalt.
          </Empty>
        </div>
      ) : (
        <div className="sim-groups">
          {d?.groups.map((g) => (
            <div key={g.id} className="card sim-group">
              <div className="card-head">
                <span className="badge sim">≈ {SIM_TEXT[g.kind]?.label ?? g.kind}</span>
                <div className="grow ellipsis" style={{ fontWeight: 650, fontSize: 14 }}>{g.members.find((m) => m.sim_best === 1)?.name ?? g.members[0]?.name}</div>
                <GroupBadge group={g.members[0]?.group_name ?? null} />
                <span className="faint" style={{ fontSize: 12.5 }}>
                  {g.n} Dateien · {fmtBytes(g.bytes)}
                  {g.score_max != null && ` · Ähnlichkeit ${Math.round((g.score_min ?? g.score_max) * 100)}${g.score_min !== g.score_max ? `–${Math.round(g.score_max * 100)}` : ""} %`}
                </span>
              </div>
              <div className="sim-members">
                {g.members.map((m) => <MemberCard key={m.id} g={g} m={m} onOpen={() => setDetail(m.id)} />)}
              </div>
            </div>
          ))}
          {d && d.total > d.groups.length && (
            <button className="btn" style={{ alignSelf: "center" }} onClick={() => setLimit(limit + 30)}>Weitere Gruppen laden</button>
          )}
        </div>
      )}
      {detail && (
        <>
          <div className="drawer-bg" onClick={() => setDetail(null)} />
          <div className="drawer"><FileDetail id={detail} onClose={() => setDetail(null)} onChanged={() => setTick((t) => t + 1)} onOpen={setDetail} /></div>
        </>
      )}
    </div>
  );
}
