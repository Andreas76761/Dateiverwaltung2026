import { useEffect, useState } from "react";
import { AlertTriangle, CalendarClock, CheckCircle2, FilePlus2, FileWarning, History, Loader2, Play, RefreshCw, ShieldCheck, Undo2, Wifi } from "lucide-react";
import { get, post, qs } from "../api";
import FileDetail from "../components/FileDetail";
import { Empty, ExportMenu, FileThumbOrIcon, GroupBadge, ReviewBadge, useAsync, useJobs, useToast } from "../components/ui";
import type { Computer } from "../types";
import { fmtBytes, fmtDate, fmtNum, shortPath } from "../util";

interface AutoSettings {
  enabled: boolean; mode: "intervall" | "täglich" | "wöchentlich"; interval_hours: number; time: string; weekday: number;
  analyze: boolean; use_llm: boolean; max_cost_usd: number; inventory: boolean;
}
interface Run { id: number; trigger: string; status: string; started_at: string; finished_at: string | null; summary: any }
interface AutoStatus {
  settings: AutoSettings; enabled: boolean; next_run: string | null; running: { schritt: string; trigger: string } | null;
  last_run: Run | null; runs: Run[];
}
interface Change {
  id: number; ts: string; kind: string; detail: string | null; file_id: number; name: string; path: string; file_type: string; ext: string;
  size: number; status: string; review_status: string; category: string | null; group_name: string | null; missing: number;
  computer_name: string; volume_name: string; thumbs: number;
}

const WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const KIND: Record<string, { label: string; cls: string; icon: typeof FilePlus2 }> = {
  neu: { label: "Neu", cls: "ok", icon: FilePlus2 },
  geändert: { label: "Geändert", cls: "warn", icon: RefreshCw },
  fehlt: { label: "Nicht mehr gefunden", cls: "bad", icon: FileWarning },
  wieder_da: { label: "Wieder da", cls: "outline", icon: Undo2 },
};

function describe(s: AutoSettings): string {
  if (s.mode === "intervall") return `alle ${String(s.interval_hours).replace(".", ",")} Stunden`;
  if (s.mode === "wöchentlich") return `jeden ${WEEKDAYS[s.weekday]} um ${s.time} Uhr`;
  return `täglich um ${s.time} Uhr`;
}

function RunSummary({ r }: { r: Run }) {
  const s = r.summary ?? {};
  const ch = s.einlesen?.änderungen;
  return (
    <span className="faint" style={{ fontSize: 12 }}>
      {s.einlesen?.dateien != null && <>{fmtNum(s.einlesen.dateien)} Dateien gelesen</>}
      {ch && <> · {fmtNum(ch.neu)} neu · {fmtNum(ch.geändert)} geändert · {fmtNum(ch.fehlt)} fehlen</>}
      {s.analyse?.analysiert != null && <> · {fmtNum(s.analyse.analysiert)} analysiert{s.analyse.nur_regeln_auto ? " (offline)" : ""}</>}
      {s.analyse?.status === "nicht nötig" && <> · Analyse nicht nötig</>}
      {s.analyse?.kosten_usd > 0 && <> · {s.analyse.kosten_usd.toLocaleString("de-DE", { maximumFractionDigits: 3 })} $</>}
      {s.analyse?.ähnliche_gruppen > 0 && <> · ≈ {fmtNum(s.analyse.ähnliche_gruppen)} ähnliche Gruppen</>}
      {s.agenten_angefordert > 0 && <> · {s.agenten_angefordert} Agenten angefordert</>}
      {s.fehler && <span style={{ color: "var(--bad)" }}> · {s.fehler}</span>}
    </span>
  );
}

export default function Automation() {
  const { version, refresh } = useJobs();
  const toast = useToast();
  const [tick, setTick] = useState(0);
  const st = useAsync<AutoStatus>(() => get("/api/automation"), [version, tick]);
  const [form, setForm] = useState<AutoSettings | null>(null);
  const [kind, setKind] = useState("");
  const [detail, setDetail] = useState<number | null>(null);
  const changes = useAsync<{ items: Change[]; counts: Record<string, number>; recheck: number }>(
    () => get(`/api/changes${qs({ kind, limit: 300 })}`), [kind, version, tick]);
  const sources = useAsync<{ computers: (Computer & { scan_requested_at?: string | null })[] }>(() => get("/api/sources"), [version, tick]);
  useEffect(() => { if (st.data && !form) setForm(st.data.settings); }, [st.data, form]);
  // Während eines Durchgangs regelmäßig aktualisieren
  useEffect(() => {
    if (!st.data?.running) return;
    const t = setInterval(() => setTick((x) => x + 1), 3000);
    return () => clearInterval(t);
  }, [st.data?.running]);

  const save = async (patch: Partial<AutoSettings>) => {
    const next = { ...(form as AutoSettings), ...patch };
    setForm(next);
    try {
      await post("/api/automation", patch);
      setTick((x) => x + 1);
      toast("Automatik gespeichert");
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const runNow = async () => {
    try {
      await post("/api/automation/run");
      toast("Durchgang gestartet: Einlesen → Analyse → Inventar");
      setTimeout(() => { refresh(); setTick((x) => x + 1); }, 800);
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const requestScan = async (id: string) => {
    try {
      await post(`/api/agents/${id}/request-scan`);
      toast("Angefordert – der Agent liest beim nächsten Abruf (≤ 10 min) neu ein");
      setTick((x) => x + 1);
    } catch (e: any) {
      toast(e.message, true);
    }
  };

  const d = st.data;
  const f = form;
  const agents = (sources.data?.computers ?? []).filter((c) => c.mode === "agent");
  const counts = changes.data?.counts ?? {};
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <h1>Automatik</h1>
          <p>Regelmäßig einlesen, Änderungen erkennen und neue Dateien einordnen – auf diesem Server und über die Agenten auf allen Computern.</p>
        </div>
        <span className="spacer" />
        <button className="btn primary" disabled={!!d?.running} onClick={runNow}>
          {d?.running ? <Loader2 size={14} className="spin" /> : <Play size={14} />} {d?.running ? `Läuft: ${d.running.schritt} …` : "Jetzt ausführen"}
        </button>
      </div>

      <div className="grid g3">
        <div className="card card-pad col" style={{ gap: 12, gridColumn: "span 2" }}>
          <div className="row">
            <h2 className="grow"><CalendarClock size={17} style={{ verticalAlign: -3 }} /> Zeitplan</h2>
            {f && <label className="switch"><input type="checkbox" checked={f.enabled} onChange={(e) => save({ enabled: e.target.checked })} /> <b>{f.enabled ? "Automatik an" : "Automatik aus"}</b></label>}
          </div>
          {f && (
            <>
              <div className="row wrap" style={{ gap: 10 }}>
                <select className="input" value={f.mode} onChange={(e) => save({ mode: e.target.value as AutoSettings["mode"] })}>
                  <option value="täglich">Täglich</option>
                  <option value="wöchentlich">Wöchentlich</option>
                  <option value="intervall">Alle … Stunden</option>
                </select>
                {f.mode === "intervall" ? (
                  <select className="input" value={f.interval_hours} onChange={(e) => save({ interval_hours: Number(e.target.value) })}>
                    {[1, 2, 4, 6, 12, 24].map((h) => <option key={h} value={h}>alle {h} Stunden</option>)}
                  </select>
                ) : (
                  <>
                    {f.mode === "wöchentlich" && (
                      <select className="input" value={f.weekday} onChange={(e) => save({ weekday: Number(e.target.value) })}>
                        {WEEKDAYS.map((w, i) => <option key={w} value={i}>{w}</option>)}
                      </select>
                    )}
                    <input type="time" className="input" value={f.time} onChange={(e) => setForm({ ...f, time: e.target.value })} onBlur={(e) => save({ time: e.target.value })} />
                  </>
                )}
                <span className="faint" style={{ fontSize: 12.5 }}>{describe(f)} · verpasste Läufe (Computer aus) werden nachgeholt</span>
              </div>
              <div className="col" style={{ gap: 8 }}>
                <label className="switch"><input type="checkbox" checked disabled /> Einlesen aller Festplatten & Cloud-Konten (nur lesend), Agenten werden mit angefordert</label>
                <label className="switch"><input type="checkbox" checked={f.analyze} onChange={(e) => save({ analyze: e.target.checked })} /> Neue und geänderte Dateien gleich analysieren (inkl. Duplikate & ähnliche Dateien)</label>
                <div className="row wrap" style={{ gap: 8, paddingLeft: 24 }}>
                  <label className="switch"><input type="checkbox" checked={f.use_llm} disabled={!f.analyze} onChange={(e) => save({ use_llm: e.target.checked })} /> Dabei das LLM nutzen</label>
                  {f.use_llm ? (
                    <span className="row" style={{ gap: 6, fontSize: 12.5 }}>Kostenlimit je Lauf
                      <input className="input" type="number" min={0} step={0.5} style={{ width: 80 }} value={f.max_cost_usd}
                        onChange={(e) => setForm({ ...f, max_cost_usd: Number(e.target.value) })} onBlur={(e) => save({ max_cost_usd: Number(e.target.value) })} /> $</span>
                  ) : <span className="faint" style={{ fontSize: 12 }}>aus = nur Offline-Regeln, keine Kosten. Diese Dateien holt die nächste manuelle LLM-Analyse nach.</span>}
                </div>
                <label className="switch"><input type="checkbox" checked={f.inventory} onChange={(e) => save({ inventory: e.target.checked })} /> Programme & LLMs auffrischen</label>
                <label className="switch" style={{ opacity: .75 }}><input type="checkbox" checked={false} disabled /> <span>Kopieren – <b>nie automatisch</b>, nur nach manueller Prüfung in Schritt 4</span></label>
              </div>
            </>
          )}
        </div>

        <div className="card card-pad col" style={{ gap: 10 }}>
          <h2>Status</h2>
          {d && (
            <>
              <div className="row" style={{ gap: 8 }}>
                <span className={`badge ${d.enabled ? "ok" : "outline"}`}>{d.enabled ? "aktiv" : "aus"}</span>
                {d.running && <span className="badge warn"><Loader2 size={11} className="spin" /> {d.running.schritt}</span>}
              </div>
              <div className="faint" style={{ fontSize: 12 }}>Nächster Lauf</div>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{d.next_run ? fmtDate(d.next_run, true) : "–"}</div>
              <div className="faint" style={{ fontSize: 12 }}>Letzter Lauf</div>
              {d.last_run ? (
                <div className="col" style={{ gap: 3 }}>
                  <div className="row" style={{ gap: 6 }}>
                    <span className={`badge ${d.last_run.status === "fertig" ? "ok" : d.last_run.status === "läuft" ? "warn" : "bad"}`}>{d.last_run.status}</span>
                    <span style={{ fontSize: 13 }}>{fmtDate(d.last_run.started_at, true)} · {d.last_run.trigger}</span>
                  </div>
                  <RunSummary r={d.last_run} />
                </div>
              ) : <div className="faint" style={{ fontSize: 12.5 }}>Noch kein Lauf.</div>}
              <div className="callout ok" style={{ fontSize: 12, marginTop: 4 }}>
                <ShieldCheck size={16} color="var(--ok)" /><span>Die Automatik liest nur. Sie löscht, verschiebt und kopiert nichts.</span>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="grid g3">
        <div className="card" style={{ gridColumn: "span 2" }}>
          <div className="card-head">
            <h2 className="grow">Änderungen</h2>
            <ExportMenu path="/api/export/aenderungen" />
            <button className={`chip ${!kind ? "on" : ""}`} onClick={() => setKind("")}>Alle</button>
            {Object.entries(KIND).map(([k, v]) => (
              <button key={k} className={`chip ${kind === k ? "on" : ""}`} onClick={() => setKind(kind === k ? "" : k)}>{v.label} {counts[k] ? `(${fmtNum(counts[k])})` : ""}</button>
            ))}
          </div>
          {(changes.data?.recheck ?? 0) > 0 && (
            <div className="callout warn" style={{ margin: "10px 16px 0", fontSize: 12.5 }}>
              <AlertTriangle size={16} /><span><b>{fmtNum(changes.data!.recheck)}</b> bereits freigegebene Dateien wurden danach geändert. Ihre Freigabe wurde auf „offen“ zurückgesetzt – bitte im <a href="#/proposal">Vorschlag</a> erneut prüfen.</span>
            </div>
          )}
          <div style={{ maxHeight: 520, overflow: "auto" }}>
            {changes.data && changes.data.items.length === 0 ? (
              <Empty icon={<History size={30} />} title="Noch keine Änderungen">
                Ab dem zweiten Einlesen einer Festplatte werden hier neue, geänderte, verschwundene und wieder aufgetauchte Dateien protokolliert.
              </Empty>
            ) : (
              <table className="table">
                <thead><tr><th style={{ width: 150 }}>Änderung</th><th>Datei</th><th>Ort</th><th style={{ width: 130 }}>Zeitpunkt</th></tr></thead>
                <tbody>
                  {changes.data?.items.map((c) => {
                    const k = KIND[c.kind] ?? { label: c.kind, cls: "outline", icon: RefreshCw };
                    return (
                      <tr key={c.id} onClick={() => setDetail(c.file_id)}>
                        <td><span className={`badge ${k.cls}`}><k.icon size={11} /> {k.label}</span></td>
                        <td>
                          <div className="row" style={{ gap: 8 }}>
                            <FileThumbOrIcon id={c.file_id} thumbs={c.thumbs} type={c.file_type} ext={c.ext} />
                            <div style={{ minWidth: 0 }}>
                              <div className="ellipsis" style={{ fontWeight: 600, maxWidth: 300 }}>{c.name}</div>
                              <div className="faint ellipsis" style={{ fontSize: 11.5, maxWidth: 340 }}>{c.detail || (c.group_name ? `${c.category} · ${fmtBytes(c.size)}` : fmtBytes(c.size))}</div>
                            </div>
                            {c.group_name && <GroupBadge group={c.group_name} />}
                            {c.kind === "geändert" && <ReviewBadge status={c.review_status} />}
                          </div>
                        </td>
                        <td className="faint" style={{ fontSize: 12 }}><div>{c.computer_name} · {c.volume_name}</div><div className="mono ellipsis" style={{ fontSize: 10.5, maxWidth: 260 }}>{shortPath(c.path, 2, true)}</div></td>
                        <td className="faint" style={{ fontSize: 12 }}>{fmtDate(c.ts, true)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="col" style={{ gap: 16 }}>
          <div className="card card-pad col" style={{ gap: 10 }}>
            <h2><Wifi size={16} style={{ verticalAlign: -2 }} /> Agenten (Hintergrunddienst)</h2>
            {agents.length ? agents.map((c) => {
              const online = c.last_seen && Date.now() - new Date(c.last_seen).getTime() < 30 * 60 * 1000;
              return (
                <div key={c.id} className="row" style={{ gap: 8, fontSize: 12.5 }}>
                  <span className={`dot`} style={{ background: online ? "var(--ok)" : "var(--text-3)" }} />
                  <div className="grow" style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>{c.name}</div>
                    <div className="faint" style={{ fontSize: 11.5 }}>{online ? "online" : "zuletzt"} {fmtDate(c.last_seen, true)}{c.scan_requested_at ? ` · angefordert ${fmtDate(c.scan_requested_at, true)}` : ""}</div>
                  </div>
                  <button className="btn sm" onClick={() => requestScan(c.id)}><RefreshCw size={12} /> Einlesen anfordern</button>
                </div>
              );
            }) : <div className="faint" style={{ fontSize: 12.5 }}>Keine Agent-Computer konfiguriert.</div>}
            <div className="faint" style={{ fontSize: 12 }}>Einrichten auf dem jeweiligen Computer (startet bei jeder Anmeldung, ohne Fenster):</div>
            <div className="code" style={{ fontSize: 11, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{`.\\dienst-einrichten.ps1 agent --server http://<SERVER>:8800 --computer laptop --key <API-KEY> --target "$env:OneDrive\\Future-Dateiverwaltung"`}</div>
            <div className="faint" style={{ fontSize: 11.5 }}>macOS/Linux: <span className="mono">./dienst-einrichten.sh agent …</span> · Server selbst: <span className="mono">dienst-einrichten server</span></div>
          </div>
          <div className="card card-pad col" style={{ gap: 8 }}>
            <h2><History size={16} style={{ verticalAlign: -2 }} /> Verlauf</h2>
            {d?.runs.length ? d.runs.map((r) => (
              <div key={r.id} className="col" style={{ gap: 2, borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>
                <div className="row" style={{ gap: 6, fontSize: 12.5 }}>
                  {r.status === "fertig" ? <CheckCircle2 size={13} color="var(--ok)" /> : r.status === "läuft" ? <Loader2 size={13} className="spin" /> : <AlertTriangle size={13} color="var(--bad)" />}
                  <b>{fmtDate(r.started_at, true)}</b><span className="faint">{r.trigger}</span>
                </div>
                <RunSummary r={r} />
              </div>
            )) : <div className="faint" style={{ fontSize: 12.5 }}>Noch keine Läufe.</div>}
          </div>
        </div>
      </div>
      {detail && (
        <>
          <div className="drawer-bg" onClick={() => setDetail(null)} />
          <div className="drawer"><FileDetail id={detail} onClose={() => setDetail(null)} onChanged={() => setTick((t) => t + 1)} onOpen={setDetail} /></div>
        </>
      )}
    </div>
  );
}
