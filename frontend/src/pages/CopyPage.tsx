import { useState } from "react";
import { CheckCircle2, CloudUpload, FileCheck2, FlaskConical, FolderUp, Loader2, ShieldCheck, XCircle } from "lucide-react";
import { exportUrl, get, post, qs } from "../api";
import { Empty, ExportMenu, GroupBadge, useAsync, useJobs, useToast } from "../components/ui";
import type { CopyOp } from "../types";
import { fmtBytes, fmtDate, fmtNum, groupClass, relTo, shortPath } from "../util";

export default function CopyPage({ go }: { go: (p: string) => void }) {
  const { jobs, running, refresh, version } = useJobs();
  const toast = useToast();
  const [inclDup, setInclDup] = useState(false);
  const [dlOnline, setDlOnline] = useState(false);
  const [skipOlder, setSkipOlder] = useState(false);
  const [jobSel, setJobSel] = useState<number | null>(null);
  const preview = useAsync<any>(() => get(`/api/copy/preview${qs({ include_duplicates: inclDup })}`), [inclDup, version]);
  const copyJobs = jobs.filter((j) => j.kind === "copy");
  const shownJob = copyJobs.find((j) => j.id === jobSel) ?? copyJobs[0];
  const ops = useAsync<CopyOp[]>(() => (shownJob ? get(`/api/copy/ops${qs({ job_id: shownJob.id })}`) : Promise.resolve([])), [shownJob?.id, version]);
  const isRunning = running.some((r) => r.kind === "copy");
  const p = preview.data;

  const start = async (dry: boolean) => {
    const n = (p?.n ?? 0) - (skipOlder ? p?.older_versions ?? 0 : 0);
    if (!dry && !window.confirm(`${n} Dateien werden nach\n${p?.target_root}\nkopiert. Originale bleiben unverändert. Fortfahren?`)) return;
    try {
      const r = await post<{ job_id: number }>("/api/pipeline/copy", { include_duplicates: inclDup, dry_run: dry, download_online_only: dlOnline, skip_older_versions: skipOlder });
      setJobSel(r.job_id);
      refresh();
      toast(dry ? "Trockenlauf gestartet" : "Kopiervorgang gestartet");
    } catch (e: any) {
      toast(e.message, true);
    }
  };

  const saveReport = async () => {
    if (!shownJob) return;
    try {
      const r = await post<{ dateien: string[] }>(`/api/export/kopie/${shownJob.id}/pruefbericht-ablegen`);
      toast(`Prüfbericht abgelegt: ${relTo(r.dateien[0], p?.target_root ?? "")}`);
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const st = shownJob?.stats ?? {};
  const groups = Object.entries((st.je_gruppe ?? {}) as Record<string, number>);
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <h1>Schritt 4 · Kopieren & Statistik</h1>
          <p>Nur manuell freigegebene Dateien werden als Kopie in die neue Cloud-Struktur übernommen.</p>
        </div>
      </div>

      <div className="grid g3">
        <div className="card card-pad col" style={{ gap: 12 }}>
          <h2>Bereit zum Kopieren</h2>
          {p && p.n > 0 ? (
            <>
              <div className="row" style={{ alignItems: "baseline", gap: 10 }}>
                <span style={{ fontSize: 30, fontWeight: 750 }}>{fmtNum(p.n)}</span><span className="muted">Dateien · {fmtBytes(p.bytes)}</span>
              </div>
              <div className="col" style={{ gap: 6 }}>
                {p.by_group.map((g: any) => (
                  <div key={g.k} className="row"><GroupBadge group={g.k} /><span className="spacer" /><b>{g.n}</b><span className="faint" style={{ fontSize: 12, width: 70, textAlign: "right" }}>{fmtBytes(g.bytes)}</span></div>
                ))}
              </div>
              <div className="faint" style={{ fontSize: 12 }}>Ziel:</div>
              <div className="pathbox new">{p.target_root}</div>
              <label className="switch"><input type="checkbox" checked={inclDup} onChange={(e) => setInclDup(e.target.checked)} /> Auch überzählige Duplikate kopieren</label>
              {p.older_versions > 0 && (
                <label className="switch" title="Erkannte ältere Versionen (z. B. Angebot_v1, wenn es Angebot_final gibt) bleiben im Original erhalten, werden aber nicht in die neue Struktur kopiert">
                  <input type="checkbox" checked={skipOlder} onChange={(e) => setSkipOlder(e.target.checked)} /> Nur neueste Versionen kopieren
                  <span className="faint">({fmtNum(p.older_versions)} ältere · {fmtBytes(p.older_bytes)})</span>
                </label>
              )}
              {p.online_only > 0 && (
                <div className="callout" style={{ fontSize: 12.5, flexDirection: "column", gap: 6 }}>
                  <span>☁ <b>{fmtNum(p.online_only)}</b> freigegebene Dateien ({fmtBytes(p.online_bytes)}) liegen nur online. Sie werden standardmäßig <b>übersprungen</b>, weil das Kopieren den Download auslöst.</span>
                  <label className="switch"><input type="checkbox" checked={dlOnline} onChange={(e) => setDlOnline(e.target.checked)} /> Diese Dateien herunterladen und kopieren</label>
                </div>
              )}
              <div className="row">
                <button className="btn primary" disabled={isRunning} onClick={() => start(false)}>{isRunning ? <Loader2 size={14} className="spin" /> : <CloudUpload size={15} />} Kopien erstellen</button>
                <button className="btn" disabled={isRunning} onClick={() => start(true)}><FlaskConical size={14} /> Trockenlauf</button>
              </div>
            </>
          ) : (
            <Empty icon={<CheckCircle2 size={32} />} title="Keine freigegebenen Dateien">
              Prüfe zuerst den <a onClick={() => go("proposal")} style={{ cursor: "pointer" }}>Vorschlag (Schritt 3)</a> und gib Dateien oder ganze Ordner frei.
            </Empty>
          )}
        </div>

        <div className="card card-pad col" style={{ gap: 10, gridColumn: "span 2" }}>
          <div className="row">
            <h2 className="grow">Statistik {shownJob ? `· Lauf #${shownJob.id}` : ""}</h2>
            {copyJobs.length > 0 && (
              <select className="input" value={shownJob?.id} onChange={(e) => setJobSel(Number(e.target.value))}>
                {copyJobs.map((j) => <option key={j.id} value={j.id}>#{j.id} · {fmtDate(j.created_at, true)} · {j.stats.trockenlauf ? "Trockenlauf" : j.status}</option>)}
              </select>
            )}
          </div>
          {shownJob ? (
            <>
              {shownJob.status === "läuft" && <div className="progress"><div style={{ width: `${shownJob.total ? (shownJob.progress / shownJob.total) * 100 : 0}%` }} /></div>}
              <div className="grid g4" style={{ gap: 10 }}>
                <div className="card kpi" style={{ boxShadow: "none" }}><div className="k-label">Kopiert</div><div className="k-val" style={{ color: "var(--ok)" }}>{fmtNum(st.kopiert)}</div><div className="k-sub">{fmtBytes(st.bytes)}</div></div>
                <div className="card kpi" style={{ boxShadow: "none" }}><div className="k-label">Übersprungen</div><div className="k-val">{fmtNum(st["übersprungen"])}</div><div className="k-sub">bereits identisch im Ziel{st["ältere_versionen_ausgelassen"] ? ` · ≈ ${fmtNum(st["ältere_versionen_ausgelassen"])} ältere Versionen ausgelassen` : ""}</div></div>
                <div className="card kpi" style={{ boxShadow: "none" }}><div className="k-label">An Agenten</div><div className="k-val">{fmtNum(st["an_agent_übergeben"])}</div><div className="k-sub">andere Computer{st.nur_online ? ` · ☁ ${fmtNum(st.nur_online)} nur online übersprungen` : ""}{st.cloud_serverseitig ? ` · ☁ ${fmtNum(st.cloud_serverseitig)} serverseitig in der Cloud kopiert` : ""}</div></div>
                <div className="card kpi" style={{ boxShadow: "none" }}><div className="k-label">Fehler</div><div className="k-val" style={{ color: st.fehler ? "var(--bad)" : undefined }}>{fmtNum(st.fehler)}</div><div className="k-sub">{st.trockenlauf ? "Trockenlauf" : `von ${fmtNum(st.geplant)} geplant`}</div></div>
              </div>
              {groups.length > 0 && (
                <div>
                  <h3 style={{ margin: "6px 0" }}>Je Bereich</h3>
                  {groups.map(([g, n]) => {
                    const max = Math.max(...groups.map(([, x]) => x));
                    return (
                      <div key={g} className="hbar-row">
                        <GroupBadge group={g} />
                        <div className="hbar"><div className={`bg-${groupClass(g).slice(2)}`} style={{ width: `${(n / max) * 100}%` }} /></div>
                        <span className="faint" style={{ textAlign: "right" }}>{n}</span>
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="callout ok"><ShieldCheck size={18} color="var(--ok)" /><span>Jede Kopie wird per SHA-256 verifiziert. Vorhandene Dateien im Ziel werden nie überschrieben – bei Namenskonflikten wird „Name (2)“ angelegt.</span></div>
              <div className="row wrap" style={{ gap: 8 }}>
                <a className="btn" href={exportUrl(`/api/export/kopie/${shownJob.id}/pruefbericht.pdf`)} target="_blank" rel="noreferrer"><FileCheck2 size={14} /> Prüfbericht (PDF)</a>
                <ExportMenu path={`/api/export/kopie/${shownJob.id}`} label="Protokoll" title="Vollständiges Kopierprotokoll als Excel/CSV" />
                {!st.trockenlauf && <button className="btn" onClick={saveReport} title="Prüfbericht (PDF + Excel) erneut im Zielordner unter „_Prüfberichte“ ablegen"><FolderUp size={14} /> Im Zielordner ablegen</button>}
                {Array.isArray(st["prüfbericht"]) && <span className="faint" style={{ fontSize: 12 }}>Automatisch abgelegt: <span className="mono">{relTo(st["prüfbericht"][0], p?.target_root ?? "")}</span></span>}
              </div>
            </>
          ) : (
            <div className="faint">Noch kein Kopiervorgang durchgeführt.</div>
          )}
        </div>
      </div>

      {shownJob && (
        <div className="card">
          <div className="card-head"><h2 className="grow">Protokoll</h2><span className="faint" style={{ fontSize: 12 }}>{fmtNum(ops.data?.length)} Einträge</span></div>
          <div style={{ maxHeight: 460, overflow: "auto" }}>
            <table className="table">
              <thead><tr><th style={{ width: 110 }}>Status</th><th>Datei</th><th>Quelle</th><th>Ziel (Kopie)</th><th style={{ width: 80 }}>Größe</th></tr></thead>
              <tbody>
                {ops.data?.map((o) => (
                  <tr key={o.id} style={{ cursor: "default" }}>
                    <td>
                      <span className={`badge ${o.status === "kopiert" ? "ok" : o.status === "fehler" ? "bad" : o.status === "übersprungen" ? "warn" : "outline"}`}>
                        {o.status === "kopiert" ? <CheckCircle2 size={11} /> : o.status === "fehler" ? <XCircle size={11} /> : null} {o.status}
                      </span>
                    </td>
                    <td><div className="ellipsis" style={{ maxWidth: 220, fontWeight: 550 }}>{o.name}</div><div className="faint" style={{ fontSize: 11 }}>{o.category}</div></td>
                    <td className="mono faint"><div className="ellipsis" style={{ maxWidth: 300 }} title={o.src}>{shortPath(o.src, 3)}</div></td>
                    <td className="mono"><div className="ellipsis" style={{ maxWidth: 360 }} title={o.dst}>{relTo(o.dst, p?.target_root ?? "")}</div>{o.message && <div className="faint" style={{ fontSize: 11, fontFamily: "inherit" }}>{o.message}</div>}</td>
                    <td className="faint">{fmtBytes(o.bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {shownJob.stats.trockenlauf && <div className="empty">Trockenlauf – es wurde nichts kopiert. Ergebnis siehe Statistik.</div>}
          </div>
        </div>
      )}
    </div>
  );
}
