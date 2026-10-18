import { useEffect, useState } from "react";
import { AlertTriangle, Archive, Check, ChevronLeft, ChevronRight, Cloud, Copy, Download, FolderOpen, HardDrive, Laptop, Loader2, Plus, RotateCcw, Save, ShieldCheck, Trash2, Usb, Wand2, X } from "lucide-react";
import { exportUrl, get, post } from "../api";
import { Modal, useAsync, useJobs, useToast } from "../components/ui";
import { fmtBytes, fmtDate, fmtNum } from "../util";

interface Vol { id?: string; name: string; path: string; kind?: string }
interface Comp { id?: string; name: string; os?: string; mode: "local" | "agent"; volumes: Vol[] }
interface Detected {
  computer: { name: string; os: string; user_home: string };
  drives: (Vol & { total: number | null; free: number | null; system: boolean })[];
  folders: Vol[]; clouds: (Vol & { provider: string })[]; target_suggestions: string[]; server_url: string;
}
interface SetupStatus {
  config_file: string; demo: boolean; target_root: string; structure: string; computers: Comp[]; api_key_set: boolean;
  detected: Detected; agent_key: string | null; tools: Record<string, boolean>;
}
interface Check { path: string; exists: boolean; readable: boolean; files: number; bytes: number; complete: boolean; warnings: string[]; cloud?: boolean }

const STEPS = ["Dieser Computer", "Weitere Computer", "Zielordner", "Prüfen & speichern"];
const OS_HINT: Record<string, string> = { Windows: "C:/Users/andreas, D:/", macOS: "/Users/andreas, /Volumes/Backup", Linux: "/home/andreas, /mnt/daten" };

function FolderPicker({ onPick, onClose }: { onPick: (p: string) => void; onClose: () => void }) {
  const [path, setPath] = useState<string | null>(null);
  const [data, setData] = useState<{ path: string; parent: string | null; dirs: { name: string; path: string }[] }>();
  const [err, setErr] = useState("");
  useEffect(() => {
    post<any>("/api/setup/browse", { path }).then((d) => { setData(d); setErr(""); }).catch((e) => setErr(e.message));
  }, [path]);
  return (
    <Modal title="Ordner auswählen" onClose={onClose} actions={<>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" disabled={!data?.path} onClick={() => { onPick(data!.path); onClose(); }}><Check size={14} /> Diesen Ordner nehmen</button>
    </>}>
      <div className="pathbox mono" style={{ marginBottom: 8 }}>{data?.path || "Laufwerke & Ordner"}</div>
      {err && <div className="callout warn" style={{ fontSize: 12.5 }}>{err}</div>}
      <div className="col" style={{ gap: 2, maxHeight: 380, overflow: "auto" }}>
        {data?.path && <div className="tree-item" onClick={() => setPath(data.parent || null)}><ChevronLeft size={14} /> Übergeordneter Ordner</div>}
        {data?.dirs.map((d) => <div key={d.path} className="tree-item" onClick={() => setPath(d.path)}><FolderOpen size={14} /> {d.name}</div>)}
        {data && !data.dirs.length && <div className="faint" style={{ padding: 8, fontSize: 12.5 }}>Keine Unterordner.</div>}
      </div>
    </Modal>
  );
}

function Wizard() {
  const toast = useToast();
  const { refresh } = useJobs();
  const st = useAsync<SetupStatus>(() => get("/api/setup"), []);
  const [step, setStep] = useState(0);
  const [me, setMe] = useState<Comp>({ name: "", mode: "local", volumes: [] });
  const [others, setOthers] = useState<Comp[]>([]);
  const [target, setTarget] = useState("");
  const [customPath, setCustomPath] = useState("");
  const [picker, setPicker] = useState<null | ((p: string) => void)>(null);
  const [checks, setChecks] = useState<Record<string, Check>>({});
  const [checking, setChecking] = useState(false);
  const [newDb, setNewDb] = useState(true);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [errors, setErrors] = useState<string[]>([]);

  useEffect(() => {
    const d = st.data;
    if (!d) return;
    if (d.demo) {
      setMe({ name: d.detected.computer.name, os: d.detected.computer.os, mode: "local", volumes: [...d.detected.folders.filter((f) => /Dokumente|Bilder|Schreibtisch/.test(f.name)), ...d.detected.clouds] });
      setOthers([]);
      setTarget(d.detected.target_suggestions[0] ?? "");
    } else {
      const local = d.computers.find((c) => c.mode === "local") ?? { name: d.detected.computer.name, mode: "local" as const, volumes: [] };
      setMe(local);
      setOthers(d.computers.filter((c) => c !== local));
      setTarget(d.target_root);
    }
  }, [st.data]);

  const d = st.data;
  const has = (p: string) => me.volumes.some((v) => v.path === p);
  const toggle = (v: Vol) => setMe({ ...me, volumes: has(v.path) ? me.volumes.filter((x) => x.path !== v.path) : [...me.volumes, { name: v.name, path: v.path, kind: v.kind }] });
  const runCheck = async () => {
    setChecking(true);
    try {
      const r = await post<Check[]>("/api/setup/check", { paths: me.volumes.map((v) => v.path) });
      setChecks(Object.fromEntries(r.map((c) => [c.path, c])));
    } finally { setChecking(false); }
  };
  const save = async () => {
    setSaving(true);
    setErrors([]);
    try {
      const r = await post<any>("/api/setup/apply", { computers: [me, ...others], target_root: target, new_database: newDb });
      if (!r.ok) setErrors(r.errors);
      else { setResult(r); toast("Einrichtung gespeichert"); refresh(); }
    } catch (e: any) { toast(e.message, true); } finally { setSaving(false); }
  };
  const scanNow = async () => {
    await post("/api/pipeline/scan", {});
    refresh();
    toast("Einlesen gestartet – Fortschritt oben rechts");
  };
  if (!d) return <div className="faint">Lädt …</div>;

  const VolRow = ({ v, onRemove }: { v: Vol; onRemove: () => void }) => {
    const c = checks[v.path];
    return (
      <div className="row" style={{ gap: 8, padding: "6px 8px", border: "1px solid var(--border)", borderRadius: 8 }}>
        {v.kind === "cloud" ? <Cloud size={15} color="var(--accent)" /> : v.kind === "external" ? <Usb size={15} /> : <HardDrive size={15} />}
        <div className="grow" style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{v.name}</div>
          <div className="mono faint ellipsis" style={{ fontSize: 11 }}>{v.path}</div>
          {c && <div style={{ fontSize: 11.5 }} className={c.warnings.length ? "" : "faint"}>
            {c.exists ? `${c.complete ? "" : "mind. "}${fmtNum(c.files)} ${c.files === 1 ? "Datei" : "Dateien"} · ${fmtBytes(c.bytes)}` : ""}
            {c.warnings.map((w) => <span key={w} style={{ color: "var(--warn)", marginLeft: 6 }}><AlertTriangle size={11} style={{ verticalAlign: -1 }} /> {w}</span>)}
          </div>}
        </div>
        <button className="btn ghost icon sm" onClick={onRemove} title="Entfernen (nur aus der Auswahl)"><X size={14} /></button>
      </div>
    );
  };

  return (
    <div className="col" style={{ gap: 14 }}>
      {d.demo && !result && (
        <div className="callout" style={{ fontSize: 13 }}>
          <Wand2 size={18} color="var(--accent)" />
          <span>Die App läuft noch mit den <b>Demo-Daten</b>. Der Assistent legt deine echten Computer, Festplatten und den Cloud-Zielordner fest – in einer <b>eigenen, neuen Datenbank</b>; die Demo bleibt unberührt.</span>
        </div>
      )}
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        {STEPS.map((s, i) => (
          <button key={s} className={`chip ${step === i ? "on" : ""}`} onClick={() => setStep(i)}>
            <b>{i + 1}</b> {s}
          </button>
        ))}
      </div>

      {step === 0 && (
        <div className="grid g3">
          <div className="card card-pad col" style={{ gap: 10, gridColumn: "span 2" }}>
            <h2>Dieser Computer</h2>
            <div className="row" style={{ gap: 8 }}>
              <label className="grow col" style={{ gap: 4, fontSize: 12.5 }}>Name
                <input className="input" value={me.name} onChange={(e) => setMe({ ...me, name: e.target.value })} />
              </label>
              <div className="faint" style={{ fontSize: 12 }}>{d.detected.computer.os}</div>
            </div>
            <h3 style={{ margin: "6px 0 0" }}>Ausgewählt zum Einlesen ({me.volumes.length})</h3>
            <div className="col" style={{ gap: 6 }}>
              {me.volumes.map((v) => <VolRow key={v.path} v={v} onRemove={() => toggle(v)} />)}
              {!me.volumes.length && <div className="faint" style={{ fontSize: 12.5 }}>Rechts Laufwerke oder Ordner anklicken.</div>}
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn" onClick={() => setPicker(() => (p: string) => setMe((m) => ({ ...m, volumes: [...m.volumes, { name: p.split(/[\\/]/).filter(Boolean).pop() || p, path: p }] })))}><FolderOpen size={14} /> Ordner auswählen …</button>
              <button className="btn" disabled={!me.volumes.length || checking} onClick={runCheck}>{checking ? <Loader2 size={14} className="spin" /> : <Check size={14} />} Ordner prüfen</button>
              <span className="faint" style={{ fontSize: 12 }}>Prüfen zählt Dateien (nur Namen/Größe, wenige Sekunden).</span>
            </div>
          </div>
          <div className="card card-pad col" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>Gefunden</h3>
            {[["Laufwerke", d.detected.drives], ["Benutzerordner", d.detected.folders], ["Cloud-Ordner", d.detected.clouds]].map(([label, list]: any) => (
              <div key={label} className="col" style={{ gap: 4 }}>
                <div className="faint" style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: ".04em" }}>{label}</div>
                {list.length ? list.map((v: any) => (
                  <label key={v.path} className="switch" style={{ fontSize: 12.5 }}>
                    <input type="checkbox" checked={has(v.path)} onChange={() => toggle(v)} />
                    <span className="grow"><b>{v.name}</b> <span className="mono faint" style={{ fontSize: 11 }}>{v.path}</span>
                      {v.total ? <span className="faint" style={{ fontSize: 11 }}> · {fmtBytes(v.total - (v.free ?? 0))} belegt</span> : null}</span>
                  </label>
                )) : <div className="faint" style={{ fontSize: 12 }}>–</div>}
              </div>
            ))}
            <div className="faint" style={{ fontSize: 11.5 }}>Tipp: Statt eines ganzen System-Laufwerks besser die Benutzerordner wählen. Systemordner (Windows, Programme, AppData) werden ohnehin ausgelassen.</div>
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="col" style={{ gap: 10 }}>
          <div className="callout" style={{ fontSize: 12.5 }}><Laptop size={16} /><span>Weitere Computer liefern ihre Dateien über den <b>Agenten</b>. Die Pfade gelten auf dem jeweiligen Computer (z. B. {OS_HINT.Windows}) und werden dort geprüft.</span></div>
          {others.map((c, i) => (
            <div key={i} className="card card-pad col" style={{ gap: 8 }}>
              <div className="row" style={{ gap: 8 }}>
                <input className="input grow" placeholder="Name, z. B. Laptop" value={c.name} onChange={(e) => setOthers(others.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
                <select className="input" value={c.os || "Windows"} onChange={(e) => setOthers(others.map((x, j) => j === i ? { ...x, os: e.target.value } : x))}>
                  {Object.keys(OS_HINT).map((o) => <option key={o}>{o}</option>)}
                </select>
                <button className="btn ghost icon" title="Computer entfernen (nur aus der Einrichtung – Daten bleiben)" onClick={() => setOthers(others.filter((_, j) => j !== i))}><Trash2 size={15} /></button>
              </div>
              {c.volumes.map((v, k) => (
                <div key={k} className="row" style={{ gap: 6 }}>
                  <input className="input" style={{ width: 180 }} placeholder="Bezeichnung" value={v.name} onChange={(e) => setOthers(others.map((x, j) => j === i ? { ...x, volumes: x.volumes.map((y, l) => l === k ? { ...y, name: e.target.value } : y) } : x))} />
                  <input className="input grow mono" placeholder={`Pfad, z. B. ${OS_HINT[c.os || "Windows"].split(", ")[0]}`} value={v.path} onChange={(e) => setOthers(others.map((x, j) => j === i ? { ...x, volumes: x.volumes.map((y, l) => l === k ? { ...y, path: e.target.value } : y) } : x))} />
                  <select className="input" value={v.kind || "internal"} onChange={(e) => setOthers(others.map((x, j) => j === i ? { ...x, volumes: x.volumes.map((y, l) => l === k ? { ...y, kind: e.target.value } : y) } : x))}>
                    <option value="internal">Festplatte</option><option value="external">USB/extern</option><option value="cloud">Cloud-Ordner</option>
                  </select>
                  <button className="btn ghost icon sm" onClick={() => setOthers(others.map((x, j) => j === i ? { ...x, volumes: x.volumes.filter((_, l) => l !== k) } : x))}><X size={14} /></button>
                </div>
              ))}
              <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setOthers(others.map((x, j) => j === i ? { ...x, volumes: [...x.volumes, { name: "", path: "" }] } : x))}><Plus size={13} /> Festplatte / Ordner</button>
            </div>
          ))}
          <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setOthers([...others, { name: "", os: "Windows", mode: "agent", volumes: [{ name: "C: Benutzer", path: "C:/Users/" }] }])}><Plus size={14} /> Computer hinzufügen</button>
        </div>
      )}

      {step === 2 && (
        <div className="card card-pad col" style={{ gap: 10 }}>
          <h2>Zielordner für die neue Struktur</h2>
          <div className="faint" style={{ fontSize: 12.5 }}>Hier landen nach deiner Prüfung die <b>Kopien</b> (Schritt 4) – am besten ein neuer Ordner in deinem Cloud-Sync-Ordner. Die Originale bleiben, wo sie sind.</div>
          {d.detected.target_suggestions.map((t) => (
            <label key={t} className="switch"><input type="radio" checked={target === t} onChange={() => setTarget(t)} /> <span className="mono">{t}</span></label>
          ))}
          <label className="switch"><input type="radio" checked={!d.detected.target_suggestions.includes(target)} onChange={() => setTarget(customPath)} /> Anderer Ordner:</label>
          <div className="row" style={{ gap: 6, paddingLeft: 24 }}>
            <input className="input grow mono" value={d.detected.target_suggestions.includes(target) ? customPath : target} onChange={(e) => { setCustomPath(e.target.value); setTarget(e.target.value); }} placeholder="z. B. D:/OneDrive/Future-Dateiverwaltung" />
            <button className="btn" onClick={() => setPicker(() => (p: string) => { const t = p.replace(/[\\/]$/, "") + "/Future-Dateiverwaltung"; setCustomPath(t); setTarget(t); })}><FolderOpen size={14} /> Auswählen …</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="grid g3">
          <div className="card card-pad col" style={{ gap: 10, gridColumn: "span 2" }}>
            <h2>Zusammenfassung</h2>
            {[me, ...others].map((c, i) => (
              <div key={i}>
                <div style={{ fontWeight: 650 }}>{i === 0 ? <HardDrive size={14} style={{ verticalAlign: -2 }} /> : <Laptop size={14} style={{ verticalAlign: -2 }} />} {c.name || "(ohne Namen)"} <span className="faint" style={{ fontWeight: 400, fontSize: 12 }}>· {c.mode === "local" ? "dieser Computer" : "über Agent"}</span></div>
                {c.volumes.map((v, k) => <div key={k} className="mono faint" style={{ fontSize: 12, paddingLeft: 20 }}>{v.name}: {v.path}</div>)}
              </div>
            ))}
            <div><b><Cloud size={14} style={{ verticalAlign: -2 }} /> Zielordner:</b> <span className="mono">{target || "–"}</span></div>
            {d.demo && <label className="switch"><input type="checkbox" checked={newDb} onChange={(e) => setNewDb(e.target.checked)} /> Neue Datenbank für die echten Daten (empfohlen – Demo-Daten bleiben getrennt erhalten)</label>}
            {errors.length > 0 && <div className="callout warn" style={{ flexDirection: "column", fontSize: 12.5 }}>{errors.map((e) => <span key={e}>• {e}</span>)}</div>}
            {!result ? (
              <button className="btn primary" style={{ alignSelf: "flex-start" }} disabled={saving} onClick={save}>{saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />} Einrichtung speichern</button>
            ) : (
              <div className="callout ok col" style={{ alignItems: "flex-start", gap: 6, fontSize: 12.5 }}>
                <span><Check size={14} /> Gespeichert in <span className="mono">{result.config_file}</span>{result.backup && <> · vorherige Fassung: <span className="mono">{result.backup.split(/[\\/]/).pop()}</span></>}</span>
                {result.new_database && <span>Neue Datenbank: <span className="mono">{result.data_dir}</span></span>}
                <div className="row" style={{ gap: 8 }}>
                  <button className="btn primary sm" onClick={scanNow}>Jetzt einlesen (Schritt 1)</button>
                  <a className="btn sm" href="#/automation">Automatik einrichten</a>
                </div>
              </div>
            )}
          </div>
          <div className="card card-pad col" style={{ gap: 8 }}>
            <h3 style={{ margin: 0 }}>Sicherheit</h3>
            <div style={{ fontSize: 12.5 }} className="col">
              <span><ShieldCheck size={13} color="var(--ok)" /> Vor dem Speichern wird die Datenbank gesichert.</span>
              <span><ShieldCheck size={13} color="var(--ok)" /> Die bisherige Konfiguration bleibt als .bak-Datei erhalten.</span>
              <span><ShieldCheck size={13} color="var(--ok)" /> Entfernte Computer/Ordner werden nur nicht mehr eingelesen – nichts wird gelöscht.</span>
            </div>
            <h3 style={{ margin: "8px 0 0" }}>Bausteine auf diesem Computer</h3>
            {Object.entries({ libreoffice: "LibreOffice (Office-Seiten)", tesseract: "Tesseract (OCR)", ffmpeg: "ffmpeg (Video/Audio)", heic: "HEIC (iPhone)", audio_tags: "Audio-Tags", sevenzip: "7-Zip (7z/RAR)" }).map(([k, label]) => (
              <div key={k} className="row" style={{ gap: 6, fontSize: 12.5 }}>{d.tools[k] ? <Check size={13} color="var(--ok)" /> : <X size={13} color="var(--warn)" />} {label}</div>
            ))}
          </div>
        </div>
      )}

      {result && others.length > 0 && step === 3 && <AgentCommands comps={others} url={d.detected.server_url} keySet={d.agent_key} />}

      <div className="row" style={{ gap: 8 }}>
        <button className="btn" disabled={step === 0} onClick={() => setStep(step - 1)}><ChevronLeft size={14} /> Zurück</button>
        <span className="spacer" />
        {step < 3 && <button className="btn primary" onClick={() => setStep(step + 1)}>Weiter <ChevronRight size={14} /></button>}
      </div>
      {picker && <FolderPicker onPick={picker} onClose={() => setPicker(null)} />}
    </div>
  );
}

function AgentCommands({ comps, url, keySet }: { comps: Comp[]; url: string; keySet: string | null }) {
  const toast = useToast();
  return (
    <div className="card card-pad col" style={{ gap: 10 }}>
      <h2>Agent auf den weiteren Computern einrichten</h2>
      <div className="faint" style={{ fontSize: 12.5 }}>Auf jedem Computer das Projekt entpacken und im Projektordner ausführen. Der Agent läuft danach im Hintergrund, liest täglich ein und führt nur freigegebene Kopien aus.</div>
      {comps.map((c, i) => {
        const id = c.id || c.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
        const win = (c.os || "Windows") === "Windows";
        const cmd = `${win ? ".\\dienst-einrichten.ps1" : "./dienst-einrichten.sh"} agent --server ${url} --computer ${id} --key ${keySet || "<API-KEY>"} --target "${win ? "$env:OneDrive\\Future-Dateiverwaltung" : "~/OneDrive/Future-Dateiverwaltung"}"`;
        return (
          <div key={i} className="col" style={{ gap: 4 }}>
            <b style={{ fontSize: 13 }}>{c.name} <span className="faint" style={{ fontWeight: 400 }}>({c.os || "Windows"})</span></b>
            <div className="row" style={{ gap: 6 }}>
              <div className="code grow" style={{ fontSize: 11, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{cmd}</div>
              <button className="btn icon" title="Kopieren" onClick={() => { navigator.clipboard?.writeText(cmd); toast("Befehl kopiert"); }}><Copy size={14} /></button>
            </div>
          </div>
        );
      })}
      {!keySet && <div className="callout warn" style={{ fontSize: 12.5 }}><AlertTriangle size={15} /><span>Noch kein API-Key gesetzt: Für Agenten über das Netzwerk unter „Einstellungen → Zugang“ einen Schlüssel erzeugen.</span></div>}
    </div>
  );
}

function Backups() {
  const toast = useToast();
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<any>(null);
  const data = useAsync<any>(() => get("/api/backup"), [tick]);
  const s = data.data?.settings;
  const setS = async (patch: any) => {
    try { await post("/api/backup/settings", patch); setTick((t) => t + 1); toast("Gespeichert"); } catch (e: any) { toast(e.message, true); }
  };
  const now = async () => {
    setBusy(true);
    try {
      const m = await post<any>("/api/backup");
      toast(m.cloud_datei ? "Gesichert – lokal und im Zielordner" : "Gesichert (lokal)");
      setTick((t) => t + 1);
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };
  const restore = async (b: any) => {
    setBusy(true);
    try {
      const r = await post<any>("/api/backup/restore", { name: b.name, ort: b.ort === "lokal" ? "lokal" : "ziel" });
      toast(`Wiederhergestellt: Stand ${fmtDate(r.stand, true)}`);
      setConfirm(null);
      setTick((t) => t + 1);
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="grid g3">
        <div className="card card-pad col" style={{ gap: 10, gridColumn: "span 2" }}>
          <div className="row"><h2 className="grow"><Archive size={17} style={{ verticalAlign: -3 }} /> Datensicherung</h2>
            <button className="btn primary" disabled={busy} onClick={now}>{busy ? <Loader2 size={14} className="spin" /> : <Save size={14} />} Jetzt sichern</button></div>
          <div className="faint" style={{ fontSize: 12.5 }}>Gesichert werden die Datenbank (Freigaben, eigene Labels und Zielpfade, Kopierprotokolle, Analyse) sowie Einstellungen und Konfiguration – konsistent auch während Jobs laufen und mit Integritätsprüfung. Miniaturen werden nicht gesichert (lassen sich neu erzeugen), Cloud-Anmeldungen bewusst nicht.</div>
          {s && (
            <div className="col" style={{ gap: 8 }}>
              <label className="switch"><input type="checkbox" checked={s.enabled} onChange={(e) => setS({ enabled: e.target.checked })} /> Automatisch sichern – alle
                <select className="input" style={{ padding: "2px 6px" }} value={s.interval_hours} onChange={(e) => setS({ interval_hours: Number(e.target.value) })}>
                  {[6, 12, 24, 48, 168].map((h) => <option key={h} value={h}>{h === 168 ? "7 Tage" : `${h} Stunden`}</option>)}
                </select>
              </label>
              <label className="switch">Lokal aufbewahren:
                <select className="input" style={{ padding: "2px 6px" }} value={s.keep} onChange={(e) => setS({ keep: Number(e.target.value) })}>
                  {[7, 14, 30, 60, 90].map((n) => <option key={n} value={n}>die letzten {n} automatischen</option>)}
                </select>
              </label>
              <label className="switch">Kopie in den Zielordner (Cloud) unter <span className="mono">_Sicherung</span>:
                <select className="input" style={{ padding: "2px 6px" }} value={s.to_target} onChange={(e) => setS({ to_target: e.target.value })}>
                  <option value="täglich">täglich</option><option value="wöchentlich">wöchentlich</option><option value="nie">nie</option>
                </select>
              </label>
            </div>
          )}
        </div>
        <div className="card card-pad col" style={{ gap: 6, fontSize: 12.5 }}>
          <h3 style={{ margin: 0 }}>Wo liegen die Sicherungen?</h3>
          <div>Lokal: <span className="mono" style={{ fontSize: 11 }}>{data.data?.local_dir}</span></div>
          <div>Cloud: <span className="mono" style={{ fontSize: 11 }}>{data.data?.target_dir}</span></div>
          <div className="faint">Letzte automatische: {fmtDate(data.data?.last, true)}</div>
          <div className="callout ok" style={{ fontSize: 12 }}><ShieldCheck size={15} color="var(--ok)" /><span>Im Zielordner wird nie etwas überschrieben oder gelöscht. Aufgeräumt werden nur ältere automatische Sicherungen im lokalen Datenordner.</span></div>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h2 className="grow">Vorhandene Sicherungen</h2><span className="faint" style={{ fontSize: 12 }}>{fmtNum(data.data?.items.length)}</span></div>
        <table className="table">
          <thead><tr><th>Erstellt</th><th>Anlass</th><th>Ort</th><th>Inhalt</th><th style={{ width: 80 }}>Größe</th><th style={{ width: 230 }} /></tr></thead>
          <tbody>
            {data.data?.items.map((b: any) => (
              <tr key={b.ort + b.name} style={{ cursor: "default" }}>
                <td>{fmtDate(b.erstellt, true)}{b.geprüft && <span className="badge ok" style={{ marginLeft: 6, fontSize: 10 }}>geprüft</span>}</td>
                <td>{b.grund}</td>
                <td>{b.ort}</td>
                <td className="faint" style={{ fontSize: 12 }}>{b.inhalt ? `${fmtNum(b.inhalt.dateien)} Dateien · ${fmtNum(b.inhalt.freigegeben)} freigegeben · ${fmtNum(b.inhalt.kopien)} Kopien` : b.defekt ? "beschädigt" : "–"}</td>
                <td className="faint">{fmtBytes(b.bytes)}</td>
                <td>
                  <div className="row" style={{ gap: 6 }}>
                    <a className="btn sm" href={exportUrl(`/api/backup/download/${encodeURIComponent(b.name)}`, { ort: b.ort === "lokal" ? "lokal" : "ziel" })}><Download size={13} /> Laden</a>
                    {!b.defekt && <button className="btn sm" onClick={() => setConfirm(b)}><RotateCcw size={13} /> Wiederherstellen</button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.data && !data.data.items.length && <div className="empty">Noch keine Sicherung – „Jetzt sichern“ oder bis zur ersten automatischen Sicherung warten.</div>}
      </div>
      {confirm && (
        <Modal title="Sicherung wiederherstellen?" onClose={() => setConfirm(null)} actions={<>
          <button className="btn" onClick={() => setConfirm(null)}>Abbrechen</button>
          <button className="btn primary" disabled={busy} onClick={() => restore(confirm)}>{busy ? <Loader2 size={14} className="spin" /> : <RotateCcw size={14} />} Wiederherstellen</button>
        </>}>
          <div className="col" style={{ gap: 8, fontSize: 13 }}>
            <span>Die App-Datenbank wird auf den Stand vom <b>{fmtDate(confirm.erstellt, true)}</b> zurückgesetzt (Freigaben, Labels, Zielpfade, Kopierprotokolle).</span>
            <span>Der aktuelle Stand wird vorher automatisch gesichert. Deine Dateien auf den Festplatten und im Zielordner bleiben unberührt.</span>
          </div>
        </Modal>
      )}
    </div>
  );
}

export default function Setup({ params }: { params: URLSearchParams }) {
  const [tab, setTab] = useState(params.get("tab") === "backup" ? "backup" : "wizard");
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <h1>Einrichtung</h1>
          <p>Computer, Festplatten, Cloud-Ordner und Zielordner festlegen – und die Daten der App sichern.</p>
        </div>
      </div>
      <div className="tabs" style={{ marginTop: -6 }}>
        <button className={tab === "wizard" ? "on" : ""} onClick={() => setTab("wizard")}><Wand2 size={13} style={{ verticalAlign: -2 }} /> Assistent</button>
        <button className={tab === "backup" ? "on" : ""} onClick={() => setTab("backup")}><Archive size={13} style={{ verticalAlign: -2 }} /> Datensicherung</button>
      </div>
      {tab === "wizard" ? <Wizard /> : <Backups />}
    </div>
  );
}
