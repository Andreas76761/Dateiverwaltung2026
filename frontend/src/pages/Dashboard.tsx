import { CalendarClock, CheckCircle2, CloudUpload, Wand2, Copy, FileSearch, FolderTree, HardDrive, Laptop, Loader2, Play, ScanLine, ShieldCheck, Sparkles, Square } from "lucide-react";
import { useState } from "react";
import { get, post } from "../api";
import CostDialog from "../components/CostDialog";
import { Empty, ExportMenu, GroupBadge, Importance, useAsync, useJobs, useToast } from "../components/ui";
import type { Job } from "../types";
import { fmtBytes, fmtDate, fmtNum, groupClass } from "../util";

type Stats = any;

const STEPS = [
  { kind: "scan", n: 1, title: "Einlesen", icon: ScanLine, text: "Alle Dateien lokal, extern & Cloud je Computer erfassen – nur lesend.", url: "/api/pipeline/scan" },
  { kind: "analyze", n: 2, title: "Analysieren", icon: Sparkles, text: "LLM liest Inhalte, OCR, Miniaturen, 60 Kategorien → Privat/Beruf (mit Kapitel oneSCM)/GenAI/Sonstiges.", url: "/api/pipeline/analyze" },
  { kind: "propose", n: 3, title: "Vorschlag", icon: FolderTree, text: "Neue Ordnerstruktur virtuell erzeugen – physisch wird nichts verändert.", url: "/api/pipeline/propose" },
  { kind: "copy", n: 4, title: "Kopieren", icon: CloudUpload, text: "Nach manueller Prüfung: Kopien in neue Cloud-Ordner inkl. Statistik.", url: "" },
] as const;

export default function Dashboard({ go }: { go: (page: string) => void }) {
  const { jobs, running, refresh, version } = useJobs();
  const { data: s } = useAsync<Stats>(() => get("/api/stats"), [version]);
  const { data: auto } = useAsync<any>(() => get("/api/automation"), [version]);
  const { data: setup } = useAsync<any>(() => get("/api/setup"), []);
  const toast = useToast();

  const start = async (url: string, body = {}) => {
    try {
      await post(url, body);
      toast("Job gestartet");
      refresh();
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const last = (kind: string) => jobs.find((j) => j.kind === kind);
  const [costDialog, setCostDialog] = useState<null | { force: boolean }>(null);
  const startAnalyze = (force: boolean) =>
    s?.llm_provider === "anthropic" ? setCostDialog({ force }) : start("/api/pipeline/analyze", { force });
  if (!s) return <div className="faint">Lädt …</div>;
  const t = s.totals;
  const groupTotal = s.by_group.reduce((a: number, g: any) => a + g.n, 0) || 1;

  return (
    <div className="col" style={{ gap: 18 }}>
      {costDialog && <CostDialog force={costDialog.force} onClose={() => setCostDialog(null)} onStarted={refresh} />}
      <div className="page-head">
        <div>
          <h1>Übersicht</h1>
          <p>{s.by_computer.length} Computer · {s.by_volume.length} Datenträger & Cloud-Ordner · LLM: <b>{s.llm_provider}</b></p>
        </div>
        <div className="spacer" />
        <ExportMenu path="/api/export/statistik" label="Statistik" csv={false} title="Statistik als Excel: Übersicht, je Bereich, Kategorie, Dateityp, Jahr, Computer, Festplatte" />
        <div className={`callout ${auto?.enabled ? "ok" : ""}`} style={{ padding: "8px 12px", cursor: "pointer" }} onClick={() => go("automation")} title="Automatik einstellen">
          <CalendarClock size={18} color={auto?.enabled ? "var(--ok)" : undefined} />
          <span>{auto?.running ? <>Automatik läuft: <b>{auto.running.schritt}</b></> : auto?.enabled
            ? <>Automatik an · nächster Lauf <b>{fmtDate(auto.next_run, true)}</b></> : <>Automatik aus – <u>einrichten</u></>}</span>
        </div>
        <div className="callout ok" style={{ padding: "8px 12px" }}>
          <ShieldCheck size={18} color="var(--ok)" />
          <span>Read-only: Es werden <b>keine</b> Dateien oder Ordner gelöscht oder verschoben.</span>
        </div>
      </div>

      {setup?.demo && (
        <div className="callout" style={{ fontSize: 13, cursor: "pointer" }} onClick={() => go("setup")}>
          <Wand2 size={18} color="var(--accent)" />
          <span><b>Demo-Daten.</b> Mit dem Einrichtungs-Assistenten legst du deine echten Computer, Festplatten und den Cloud-Zielordner fest – <u>Einrichtung starten</u></span>
        </div>
      )}
      <div className="grid g4">
        <div className="card kpi"><div className="k-label"><FileSearch size={14} /> Dateien erfasst</div><div className="k-val">{fmtNum(t.files)}</div><div className="k-sub">{fmtBytes(t.bytes)}{t.online_only ? ` · ☁ ${fmtNum(t.online_only)} nur online` : ""}</div></div>
        <div className="card kpi"><div className="k-label"><Sparkles size={14} /> Analysiert</div><div className="k-val">{fmtNum(t.analyzed)}</div><div className="k-sub">{t.files ? Math.round((t.analyzed / t.files) * 100) : 0} % · {fmtNum(s.thumbnails)} Miniaturen · {fmtNum(t.ocr)} OCR</div></div>
        <div className="card kpi"><div className="k-label"><Copy size={14} /> Duplikate</div><div className="k-val">{fmtNum(t.dup_files)}</div><div className="k-sub">{fmtNum(t.dup_groups)} Gruppen · {fmtBytes(t.dup_bytes)} doppelt</div>
          {t.sim_groups > 0 && <div className="k-sub"><a style={{ cursor: "pointer" }} onClick={() => go("similar")}>≈ {fmtNum(t.sim_groups)} Gruppen ähnlicher Dateien{t.older_versions ? ` · ${fmtNum(t.older_versions)} ältere Versionen` : ""}</a></div>}</div>
        <div className="card kpi"><div className="k-label"><CheckCircle2 size={14} /> Freigegeben / kopiert</div><div className="k-val">{fmtNum(t.approved)} <span className="faint" style={{ fontSize: 16 }}>/ {fmtNum(s.copies?.copied)}</span></div><div className="k-sub">{fmtNum(t.rejected)} abgelehnt · {fmtBytes(s.copies?.bytes)} kopiert</div></div>
      </div>

      <div className="pipeline">
        {STEPS.map((st) => {
          const j: Job | undefined = last(st.kind);
          const isRunning = running.some((r) => r.kind === st.kind);
          const Icon = st.icon;
          return (
            <div key={st.kind} className="card step-card">
              <div className="row">
                <div className="step-num">{st.n}</div>
                <div className="grow">
                  <div style={{ fontWeight: 700 }}>{st.title}</div>
                  <div className="faint" style={{ fontSize: 11.5 }}>{j ? `${j.status} · ${fmtDate(j.finished_at || j.created_at, true)}` : "noch nicht ausgeführt"}</div>
                </div>
                <Icon size={20} color="var(--text-3)" />
              </div>
              <p>{st.text}</p>
              {isRunning && j ? (
                <div className="col" style={{ gap: 5 }}>
                  <div className={`progress ${j.total ? "" : "indet"}`}><div style={{ width: `${j.total ? (j.progress / j.total) * 100 : 30}%` }} /></div>
                  <div className="row faint" style={{ fontSize: 11.5 }}>
                    <span className="grow ellipsis">{j.message}</span>
                    <button className="btn sm ghost" onClick={() => post(`/api/jobs/${j.id}/cancel`).then(refresh)}><Square size={12} /> Stopp</button>
                  </div>
                </div>
              ) : (
                <div className="stats">
                  {j?.kind === "scan" && <><span>{fmtNum(j.stats.dateien)} Dateien</span><span>{fmtNum(j.stats.duplikatgruppen)} Duplikatgruppen</span></>}
                  {j?.kind === "analyze" && <><span>{fmtNum(j.stats.analysiert)} analysiert</span><span>{fmtNum(j.stats.miniaturen)} Seiten</span><span>{fmtNum(j.stats.ocr)} OCR</span><span>LLM: {j.stats.provider}</span>
                    {j.stats.llm > 0 && <span>{fmtNum(j.stats.llm)}× Claude</span>}
                    {j.stats["ähnlich"]?.ähnlich_gruppen > 0 && <span>≈ {fmtNum(j.stats["ähnlich"].ähnlich_gruppen)} ähnliche Gruppen</span>}
                    {j.stats.nur_regeln > 0 && <span>{fmtNum(j.stats.nur_regeln)}× offline sicher</span>}
                    {j.stats.kosten_usd > 0 && <span><b>{j.stats.kosten_usd.toLocaleString("de-DE", { maximumFractionDigits: 3 })} $</b></span>}
                    {j.stats.kostenlimit_erreicht && <span style={{ color: "var(--warn)" }}>Kostenlimit erreicht</span>}</>}
                  {j?.kind === "analyze" && j.stats.llm_fallback > 0 && (
                    <span style={{ color: "var(--warn)" }} title={j.stats.llm_fehler}>⚠ {fmtNum(j.stats.llm_fallback)}× Offline-Regeln statt LLM: {j.stats.llm_fehler}</span>
                  )}
                  {j?.kind === "propose" && <><span>{fmtNum(j.stats.zielordner)} Zielordner</span><span>{fmtNum(j.stats.dateien_im_vorschlag)} Dateien</span></>}
                  {j?.kind === "copy" && <><span>{fmtNum(j.stats.kopiert)} kopiert</span><span>{fmtNum(j.stats["übersprungen"])} übersprungen</span><span>{fmtBytes(j.stats.bytes)}</span></>}
                </div>
              )}
              <div className="row" style={{ marginTop: "auto" }}>
                {st.kind === "copy" ? (
                  <button className="btn primary" onClick={() => go("copy")}><Play size={14} /> Zur Kopie</button>
                ) : (
                  <button className="btn primary" disabled={isRunning} onClick={() => (st.kind === "analyze" ? startAnalyze(false) : start(st.url))}>
                    {isRunning ? <Loader2 size={14} className="spin" /> : <Play size={14} />} Starten
                  </button>
                )}
                {st.kind === "analyze" && <button className="btn" disabled={isRunning} onClick={() => startAnalyze(true)}>Alle neu</button>}
                {st.kind === "propose" && <button className="btn" onClick={() => go("proposal")}>Prüfen</button>}
                {st.kind === "scan" && <button className="btn" onClick={() => go("explorer")}>Explorer</button>}
              </div>
            </div>
          );
        })}
      </div>

      {t.files === 0 ? (
        <div className="card"><Empty icon={<HardDrive size={36} />} title="Noch keine Dateien eingelesen">Starte Schritt 1 „Einlesen“. Die Computer und Festplatten werden in <span className="mono">config/fdv.yaml</span> konfiguriert.</Empty></div>
      ) : (
        <>
          <div className="grid g2">
            <div className="card card-pad">
              <div className="row" style={{ marginBottom: 12 }}><h2>Kategorie-Vorschlag nach Bereich</h2></div>
              <div className="stack-bar" style={{ marginBottom: 14 }}>
                {s.by_group.filter((g: any) => g.k !== "(nicht analysiert)").map((g: any) => (
                  <div key={g.k} className={`bg-${groupClass(g.k).slice(2)}`} style={{ width: `${(g.n / groupTotal) * 100}%` }} title={`${g.k}: ${g.n}`} />
                ))}
              </div>
              <div className="grid g2" style={{ gap: 10 }}>
                {s.by_group.map((g: any) => (
                  <div key={g.k} className="row" style={{ cursor: "pointer" }} onClick={() => go(`explorer?group=${encodeURIComponent(g.k)}`)}>
                    <GroupBadge group={g.k === "(nicht analysiert)" ? null : g.k} />
                    <span className="spacer" />
                    <b>{fmtNum(g.n)}</b><span className="faint" style={{ fontSize: 12 }}>{fmtBytes(g.bytes)}</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 16 }}>
                <h3 style={{ marginBottom: 6 }}>Top-Kategorien</h3>
                {s.by_category.slice(0, 9).map((c: any) => {
                  const max = s.by_category[0].n;
                  return (
                    <div key={c.k} className="hbar-row">
                      <span className="ellipsis row" style={{ gap: 6 }}><span className={`dot ${groupClass(c.grp)}`} />{c.k}</span>
                      <div className="hbar"><div className={`bg-${groupClass(c.grp).slice(2)}`} style={{ width: `${(c.n / max) * 100}%` }} /></div>
                      <span className="faint" style={{ textAlign: "right" }}>{c.n}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="card">
              <div className="card-head"><h2 className="grow">Wichtigste Dateien</h2><button className="btn sm" onClick={() => go("explorer")}>Alle</button></div>
              <table className="table">
                <tbody>
                  {s.top_important.map((f: any) => (
                    <tr key={f.id} onClick={() => go(`explorer?file=${f.id}`)}>
                      <td><div className="ellipsis" style={{ maxWidth: 260, fontWeight: 550 }}>{f.name}</div><div className="faint" style={{ fontSize: 11.5 }}>{f.category}</div></td>
                      <td><GroupBadge group={f.group_name} /></td>
                      <td style={{ width: 120 }}><Importance value={f.importance} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h2 className="grow">Computer & Festplatten</h2><button className="btn sm" onClick={() => go("sources")}>Quellen verwalten</button></div>
            <table className="table">
              <thead><tr><th>Computer / Datenträger</th><th>Art</th><th>Dateien</th><th>Volumen</th><th>Belegung</th><th>Letzter Scan</th></tr></thead>
              <tbody>
                {s.by_volume.map((v: any) => {
                  const comp = s.by_computer.find((c: any) => c.id === v.computer_id);
                  const used = v.total_bytes ? 1 - v.free_bytes / v.total_bytes : 0;
                  return (
                    <tr key={v.id} onClick={() => go(`explorer?volume=${v.id}`)}>
                      <td><div className="row"><Laptop size={15} color="var(--text-3)" /><b>{comp?.name}</b><span className="faint">›</span>{v.name}</div></td>
                      <td><span className={`badge ${v.kind === "cloud" ? "g-beruf" : v.kind === "external" ? "warn" : "outline"}`}>{v.kind === "cloud" ? "Cloud" : v.kind === "external" ? "Extern" : "Intern"}</span></td>
                      <td>{fmtNum(v.n)}</td>
                      <td>{fmtBytes(v.bytes)}</td>
                      <td style={{ width: 160 }}>{v.total_bytes ? <div className="row"><div className="progress grow"><div style={{ width: `${used * 100}%` }} /></div><span className="faint" style={{ fontSize: 11 }}>{Math.round(used * 100)}%</span></div> : "–"}</td>
                      <td className="faint">{fmtDate(v.last_scan, true)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
