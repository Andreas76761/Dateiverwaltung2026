import { useMemo, useState } from "react";
import { AlertTriangle, Bot, Boxes, Check, ChevronDown, ChevronRight, Cpu, EyeOff, HardDrive, Lightbulb, Loader2, MemoryStick, Play, RotateCcw, Search, ShieldCheck, Table2, Wrench } from "lucide-react";
import { get, post, qs } from "../api";
import { Empty, ExportMenu, useAsync, useJobs, useToast } from "../components/ui";
import { fmtBytes, fmtDate, fmtNum } from "../util";

const KINDS: Record<string, { label: string; icon: any; cls: string }> = {
  "llm-modell": { label: "LLM-Modelle", icon: Cpu, cls: "g-genai" },
  "llm-tool": { label: "LLM-Lösungen & KI-Tools", icon: Bot, cls: "g-beruf" },
  "dev-tool": { label: "Entwickler-Tools", icon: Wrench, cls: "g-privat" },
  programm: { label: "Programme", icon: Boxes, cls: "g-sonst" },
};
const REC_TYPE: Record<string, string> = {
  doppelt: "Doppelt gespeichert", mehrfach: "Mehrere Fassungen", zentral: "Zentral bereitstellen", veraltet: "Ältere Generation",
  ueberschneidung: "Überschneidung", version: "Versionen angleichen", hardware: "Passt nicht zur Hardware", speicher: "Speicher knapp",
};
type Tab = "empfehlungen" | "vergleich" | "speicher" | "liste";

interface Rec {
  key: string; type: string; priority: number; priority_text: string; title: string; detail: string; computers: string[];
  items: { computer_name: string; name: string; display: string; tool: string; version: string | null; quant: string | null; format: string | null; size: number | null; location: string | null }[];
  saving: number; hint: string; status: string;
}
interface Cell { versions: string[]; size: number; count: number; variants: string[]; tools: string[]; outdated: boolean }
interface Row { key: string; kind: string; display: string; names: string[]; roles: string[]; computers: number; count: number; size: number; versions: string[]; newest: string | null; drift: boolean; cells: Record<string, Cell> }
interface Comp { id: string; name: string; os: string; mode: string }

function Recommendations() {
  const { version } = useJobs();
  const toast = useToast();
  const [tick, setTick] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const recs = useAsync<{ items: Rec[]; offen: number; einsparung: number }>(() => get("/api/programs/recommendations"), [version, tick]);
  const st = useAsync<any>(() => get("/api/programs/storage"), [version]);
  const setStatus = async (r: Rec, status: string) => {
    await post(`/api/programs/recommendations/${r.key}`, { status });
    toast(status === "offen" ? "Wieder geöffnet" : status === "erledigt" ? "Als erledigt markiert" : "Ignoriert");
    setTick((t) => t + 1);
  };
  const items = (recs.data?.items ?? []).filter((r) => showAll || r.status === "offen");
  const hasInventory = (st.data?.computers ?? []).some((c: any) => c.models_n > 0 || c.programs_known > 0);
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="grid g4">
        <div className="card kpi"><div className="k-label"><Lightbulb size={14} /> Offene Empfehlungen</div><div className="k-val">{fmtNum(recs.data?.offen)}</div><div className="k-sub">Zusammenführen, angleichen, auslagern</div></div>
        <div className="card kpi"><div className="k-label"><HardDrive size={14} /> Einsparpotenzial</div><div className="k-val">{fmtBytes(recs.data?.einsparung)}</div><div className="k-sub">wenn die Empfehlungen umgesetzt werden</div></div>
        <div className="card kpi"><div className="k-label"><Cpu size={14} /> Lokale Modelle gesamt</div><div className="k-val">{fmtBytes(st.data?.models_total)}</div><div className="k-sub">über alle Computer</div></div>
        <div className="card kpi"><div className="k-label"><Boxes size={14} /> Computer mit Inventar</div><div className="k-val">{fmtNum((st.data?.computers ?? []).filter((c: any) => c.models_n || c.programs_known).length)}</div><div className="k-sub">von {fmtNum(st.data?.computers?.length)}</div></div>
      </div>
      <div className="callout ok" style={{ fontSize: 12.5 }}>
        <ShieldCheck size={17} color="var(--ok)" />
        <span>Nur Vorschläge: Die App installiert, entfernt oder verschiebt keine Programme und Modelle. Jede Empfehlung beschreibt, was du selbst im jeweiligen Tool tun kannst – und hakt sie danach ab.</span>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <span className="spacer" />
        <label className="switch"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Erledigte und ignorierte anzeigen</label>
      </div>
      {!hasInventory ? (
        <div className="card"><Empty icon={<Boxes size={32} />} title="Noch kein Inventar">„Inventar erfassen“ auf diesem Server starten – weitere Computer melden ihr Inventar über den Agenten (Befehl <span className="mono">inventory</span> bzw. als Dienst automatisch).</Empty></div>
      ) : items.length === 0 ? (
        <div className="card"><Empty icon={<Check size={32} />} title="Keine offenen Empfehlungen">Alles aufgeräumt – oder alle Empfehlungen sind abgehakt.</Empty></div>
      ) : (
        <div className="col" style={{ gap: 10 }}>
          {items.map((r) => (
            <div key={r.key} className="card" style={{ opacity: r.status === "offen" ? 1 : 0.6 }}>
              <div className="card-pad col" style={{ gap: 6 }}>
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <span className={`badge ${r.priority === 1 ? "bad" : r.priority === 2 ? "warn" : "outline"}`}>{r.priority_text}</span>
                  <span className="badge sim">{REC_TYPE[r.type] ?? r.type}</span>
                  <b className="grow" style={{ fontSize: 14 }}>{r.title}</b>
                  {r.saving > 0 && <span className="badge ok" title="Speicher, der frei würde">− {fmtBytes(r.saving)}</span>}
                  {r.status !== "offen" && <span className="badge outline">{r.status}</span>}
                </div>
                <div style={{ fontSize: 13 }}>{r.detail}</div>
                <div className="faint" style={{ fontSize: 12.5 }}><b>Vorgehen:</b> {r.hint}</div>
                <div className="row" style={{ gap: 8, marginTop: 4 }}>
                  <button className="btn sm ghost" onClick={() => setOpen({ ...open, [r.key]: !open[r.key] })}>
                    {open[r.key] ? <ChevronDown size={13} /> : <ChevronRight size={13} />} {r.items.length} betroffene Einträge · {r.computers.join(", ")}
                  </button>
                  <span className="spacer" />
                  {r.status === "offen" ? (
                    <>
                      <button className="btn sm ok" onClick={() => setStatus(r, "erledigt")}><Check size={13} /> Erledigt</button>
                      <button className="btn sm ghost" onClick={() => setStatus(r, "ignoriert")}><EyeOff size={13} /> Ignorieren</button>
                    </>
                  ) : <button className="btn sm ghost" onClick={() => setStatus(r, "offen")}><RotateCcw size={13} /> Wieder öffnen</button>}
                </div>
                {open[r.key] && (
                  <table className="table" style={{ marginTop: 4 }}>
                    <thead><tr><th>Computer</th><th>Eintrag</th><th>Tool</th><th>Format / Version</th><th>Größe</th><th>Ort</th></tr></thead>
                    <tbody>
                      {r.items.map((i, n) => (
                        <tr key={n} style={{ cursor: "default" }}>
                          <td>{i.computer_name}</td>
                          <td style={{ fontWeight: 550 }}>{i.name}</td>
                          <td className="faint">{i.tool}</td>
                          <td className="faint">{[i.format, i.quant].filter(Boolean).join(" ") || i.version || "–"}</td>
                          <td className="faint">{i.size ? fmtBytes(i.size) : "–"}</td>
                          <td className="mono faint"><div className="ellipsis" style={{ maxWidth: 320 }} title={i.location ?? ""}>{i.location || "–"}</div></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Compare() {
  const { version } = useJobs();
  const [kind, setKind] = useState("llm-modell");
  const [q, setQ] = useState("");
  const [multi, setMulti] = useState(false);
  const [drift, setDrift] = useState(false);
  const data = useAsync<{ computers: Comp[]; rows: Row[] }>(() => get(`/api/programs/compare${qs({ kind, q })}`), [kind, q, version]);
  const comps = data.data?.computers ?? [];
  const rows = (data.data?.rows ?? []).filter((r) => (!multi || r.computers > 1) && (!drift || r.drift));
  return (
    <div className="card">
      <div className="toolbar" style={{ borderRadius: "10px 10px 0 0", flexWrap: "wrap" }}>
        {Object.entries(KINDS).map(([k, v]) => <button key={k} className={`chip ${kind === k ? "on" : ""}`} onClick={() => setKind(k)}>{v.label}</button>)}
        <div className="search" style={{ maxWidth: 260, flex: 1 }}><Search size={15} /><input className="input" placeholder="Suchen …" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <label className="switch"><input type="checkbox" checked={multi} onChange={(e) => setMulti(e.target.checked)} /> nur auf mehreren Computern</label>
        {kind !== "llm-modell" && <label className="switch"><input type="checkbox" checked={drift} onChange={(e) => setDrift(e.target.checked)} /> nur Versionsunterschiede</label>}
        <span className="spacer" /><span className="faint" style={{ fontSize: 12 }}>{fmtNum(rows.length)} Einträge</span>
      </div>
      {rows.length ? (
        <div style={{ maxHeight: "64vh", overflow: "auto" }}>
          <table className="table matrix">
            <thead><tr>
              <th style={{ minWidth: 220 }}>{kind === "llm-modell" ? "Modell (Familie · Größe · Variante)" : "Programm"}</th>
              {comps.map((c) => <th key={c.id} style={{ minWidth: 130 }}>{c.name}</th>)}
              <th style={{ width: 90 }}>Gesamt</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} style={{ cursor: "default" }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{r.display}</div>
                    <div className="faint ellipsis" style={{ fontSize: 11, maxWidth: 300 }} title={r.names.join(", ")}>
                      {r.roles.length ? r.roles.join(" · ") : r.names.join(", ")}
                    </div>
                  </td>
                  {comps.map((c) => {
                    const cell = r.cells[c.id];
                    if (!cell) return <td key={c.id} className="faint" style={{ textAlign: "center" }}>–</td>;
                    return (
                      <td key={c.id} className={cell.outdated ? "cell-old" : "cell-ok"} title={cell.tools.join(", ")}>
                        {kind === "llm-modell" ? (
                          <>
                            <div style={{ fontWeight: 600 }}>{fmtBytes(cell.size)}{cell.count > 1 && <span className="badge warn" style={{ marginLeft: 5, fontSize: 10, padding: "0 5px" }}>{cell.count}×</span>}</div>
                            <div className="faint" style={{ fontSize: 11 }}>{cell.variants.join(", ") || cell.tools.join(", ")}</div>
                          </>
                        ) : (
                          <>
                            <div style={{ fontWeight: 600 }}>{cell.outdated && <AlertTriangle size={11} style={{ verticalAlign: -1, marginRight: 3 }} />}{cell.versions.join(", ") || "✓"}</div>
                            {cell.size > 0 && <div className="faint" style={{ fontSize: 11 }}>{fmtBytes(cell.size)}</div>}
                          </>
                        )}
                      </td>
                    );
                  })}
                  <td className="faint">{r.size ? fmtBytes(r.size) : "–"}<div style={{ fontSize: 11 }}>{r.computers} Computer</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty icon={<Table2 size={30} />} title="Keine Einträge">Für diese Auswahl ist noch nichts inventarisiert.</Empty>}
    </div>
  );
}

function Storage() {
  const { version } = useJobs();
  const st = useAsync<any>(() => get("/api/programs/storage"), [version]);
  const comps = (st.data?.computers ?? []) as any[];
  const max = Math.max(1, ...comps.map((c) => c.models));
  const toolColors = ["var(--genai)", "var(--beruf)", "var(--privat)", "var(--warn)", "var(--sonst)", "var(--bad)"];
  const allTools = useMemo(() => Array.from(new Set(comps.flatMap((c) => Object.keys(c.by_tool)))), [comps]);
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="card card-pad col" style={{ gap: 12 }}>
        <div className="row"><h2 className="grow">Speicherbedarf lokaler Modelle je Computer</h2>
          <div className="row" style={{ gap: 10, fontSize: 12 }}>{allTools.map((t, i) => <span key={t} className="row" style={{ gap: 4 }}><span className="dot" style={{ background: toolColors[i % toolColors.length] }} />{t}</span>)}</div>
        </div>
        {comps.map((c) => (
          <div key={c.id} className="row" style={{ gap: 12, alignItems: "center" }}>
            <div style={{ width: 170 }}>
              <div style={{ fontWeight: 600 }}>{c.name}</div>
              <div className="faint" style={{ fontSize: 11 }}>
                {c.gpu ? <><Cpu size={10} /> {c.gpu} {c.vram ? `· ${fmtBytes(c.vram)}` : ""}</> : c.ram ? <><MemoryStick size={10} /> RAM {fmtBytes(c.ram)} · keine GPU</> : "keine Hardware-Angaben"}
              </div>
            </div>
            <div className="grow" style={{ height: 18, background: "var(--panel-2)", borderRadius: 6, overflow: "hidden", display: "flex", border: "1px solid var(--border)" }}>
              {Object.entries(c.by_tool as Record<string, number>).map(([t, b]) => (
                <div key={t} title={`${t}: ${fmtBytes(b)}`} style={{ width: `${(b / max) * 100}%`, background: toolColors[allTools.indexOf(t) % toolColors.length] }} />
              ))}
            </div>
            <div style={{ width: 170, textAlign: "right" }}>
              <b>{fmtBytes(c.models)}</b> <span className="faint" style={{ fontSize: 12 }}>· {c.models_n} {c.models_n === 1 ? "Modell" : "Modelle"}</span>
              {c.disk_free != null && <div className="faint" style={{ fontSize: 11 }}>Festplatten frei: {fmtBytes(c.disk_free)}</div>}
            </div>
          </div>
        ))}
      </div>
      <div className="card">
        <div className="card-head"><h2 className="grow">Größte Modelle</h2></div>
        <table className="table">
          <thead><tr><th>Modell</th><th>Computer</th><th>Tool</th><th>Format</th><th style={{ width: 90 }}>Größe</th><th>Ort</th></tr></thead>
          <tbody>
            {(st.data?.largest ?? []).map((m: any, i: number) => (
              <tr key={i} style={{ cursor: "default" }}>
                <td><div style={{ fontWeight: 600 }}>{m.display || m.name}</div><div className="faint" style={{ fontSize: 11 }}>{m.name}</div></td>
                <td>{m.computer_name}</td><td className="faint">{m.tool}</td><td className="faint">{[m.format, m.quant].filter(Boolean).join(" ")}</td>
                <td><b>{fmtBytes(m.size)}</b></td>
                <td className="mono faint"><div className="ellipsis" style={{ maxWidth: 360 }} title={m.location}>{m.location}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ListView() {
  const { version } = useJobs();
  const [kind, setKind] = useState("");
  const [computer, setComputer] = useState("");
  const [q, setQ] = useState("");
  const { data } = useAsync<any>(() => get(`/api/programs${qs({ kind, computer, q })}`), [kind, computer, q, version]);
  const comps = useAsync<any>(() => get("/api/sources"), []);
  return (
    <div className="card">
      <div className="toolbar" style={{ borderRadius: "10px 10px 0 0" }}>
        <div className="search grow" style={{ maxWidth: 380 }}><Search size={15} /><input className="input" placeholder="Programm, Hersteller, Modell …" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <select className="input" value={computer} onChange={(e) => setComputer(e.target.value)}>
          <option value="">Alle Computer</option>
          {comps.data?.computers.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Alle Arten</option>
          {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          <option value="hardware">Hardware</option>
        </select>
      </div>
      {data?.items.length ? (
        <div style={{ maxHeight: "60vh", overflow: "auto" }}>
          <table className="table">
            <thead><tr><th>Name</th><th style={{ width: 170 }}>Art</th><th>Version</th><th>Computer</th><th>Ort / Quelle</th><th style={{ width: 80 }}>Größe</th><th style={{ width: 120 }}>Erfasst</th></tr></thead>
            <tbody>
              {data.items.map((p: any) => (
                <tr key={p.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 550 }}>{p.name}{(p.publisher || (p.display && p.display !== p.name)) && <div className="faint ellipsis" style={{ fontSize: 11, maxWidth: 260, fontWeight: 400 }}>{p.display !== p.name ? p.display : p.publisher}</div>}</td>
                  <td><span className={`badge ${KINDS[p.kind]?.cls ?? "outline"}`}>{KINDS[p.kind]?.label ?? (p.kind === "hardware" ? "Hardware" : p.kind)}</span>{p.category && <div className="faint" style={{ fontSize: 11 }}>{p.category}</div>}</td>
                  <td className="mono faint"><div className="ellipsis" style={{ maxWidth: 180 }}>{p.version || p.quant || "–"}</div></td>
                  <td>{p.computer_name || p.computer_id}</td>
                  <td className="mono faint"><div className="ellipsis" style={{ maxWidth: 300 }} title={p.location}>{p.location || p.source}</div></td>
                  <td className="faint">{p.size ? fmtBytes(p.size) : "–"}</td>
                  <td className="faint">{fmtDate(p.seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty icon={<Boxes size={34} />} title="Noch kein Inventar">„Inventar erfassen“ liest installierte Programme (Registry / Applications / dpkg), KI-Tools im PATH, Python-KI-Bibliotheken, lokale Modelle (Ollama, LM Studio, Hugging Face, GGUF) sowie GPU und Arbeitsspeicher. Andere Computer melden ihr Inventar per Agent.</Empty>
      )}
    </div>
  );
}

export default function Programs() {
  const { running, refresh } = useJobs();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("empfehlungen");
  const isRunning = running.some((r) => r.kind === "inventory");
  const start = async () => {
    await post("/api/pipeline/inventory");
    refresh();
    toast("Inventar wird erfasst");
  };
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <h1>Programme & LLM-Lösungen</h1>
          <p>Organisation über alle Computer: welches Programm und Modell liegt wo, wie viel Platz es belegt und was sich zusammenführen lässt.</p>
        </div>
        <div className="spacer" />
        <ExportMenu path="/api/export/programme" title="Excel: Empfehlungen, Vergleich, Speicher, Inventar · CSV: Inventar" />
        <button className="btn primary" disabled={isRunning} onClick={start}>{isRunning ? <Loader2 size={14} className="spin" /> : <Play size={14} />} Inventar erfassen</button>
      </div>
      <div className="tabs" style={{ marginTop: -6 }}>
        <button className={tab === "empfehlungen" ? "on" : ""} onClick={() => setTab("empfehlungen")}><Lightbulb size={13} style={{ verticalAlign: -2 }} /> Empfehlungen</button>
        <button className={tab === "vergleich" ? "on" : ""} onClick={() => setTab("vergleich")}><Table2 size={13} style={{ verticalAlign: -2 }} /> Vergleich über alle Computer</button>
        <button className={tab === "speicher" ? "on" : ""} onClick={() => setTab("speicher")}><HardDrive size={13} style={{ verticalAlign: -2 }} /> Speicherbedarf</button>
        <button className={tab === "liste" ? "on" : ""} onClick={() => setTab("liste")}><Boxes size={13} style={{ verticalAlign: -2 }} /> Inventar (Liste)</button>
      </div>
      {tab === "empfehlungen" && <Recommendations />}
      {tab === "vergleich" && <Compare />}
      {tab === "speicher" && <Storage />}
      {tab === "liste" && <ListView />}
    </div>
  );
}
