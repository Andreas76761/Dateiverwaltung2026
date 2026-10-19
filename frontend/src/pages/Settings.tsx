import { useEffect, useState } from "react";
import { Bot, CheckCircle2, Loader2, Save, ShieldCheck, XCircle, Zap } from "lucide-react";
import { get, post } from "../api";
import Access from "../components/Access";
import { useAsync, useToast } from "../components/ui";
import { fmtBytes, fmtNum, GROUPS } from "../util";

export default function Settings() {
  const toast = useToast();
  const s = useAsync<any>(() => get("/api/settings"), []);
  const skills = useAsync<any[]>(() => get("/api/skills"), []);
  const cats = useAsync<any[]>(() => get("/api/categories"), []);
  const [form, setForm] = useState<any>(null);
  const [test, setTest] = useState<any>(null);
  const [testing, setTesting] = useState(false);
  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      await post("/api/settings", form); // aktuelle Auswahl zuerst speichern
      setTest(await post("/api/settings/test-llm", { provider: form.provider }));
    } catch (e: any) {
      setTest({ ok: false, error: e.message });
    } finally {
      setTesting(false);
    }
  };
  useEffect(() => {
    if (s.data) setForm({ provider: s.data.llm.provider, anthropic_model: s.data.llm.anthropic_model, ollama_url: s.data.llm.ollama_url, ollama_model: s.data.llm.ollama_model, send_content_to_cloud: s.data.llm.send_content_to_cloud, target_structure: s.data.target_structure, ocr: s.data.analysis.ocr,
      mode: s.data.llm.mode, batch: s.data.llm.batch, max_cost_usd: s.data.llm.max_cost_usd,
      thumbnails_mode: s.data.analysis.thumbnails_mode, thumbs_budget_gb: s.data.analysis.thumbs_budget_gb,
      download_online_only: s.data.cloud.download_online_only, cloud_download_content: s.data.cloud_api.download_content });
  }, [s.data]);
  if (!s.data || !form) return <div className="faint">Lädt …</div>;
  const save = async () => {
    try {
      await post("/api/settings", form);
      toast("Einstellungen gespeichert");
      s.reload();
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const Ok = ({ v }: { v: boolean }) => (v ? <CheckCircle2 size={15} color="var(--ok)" /> : <XCircle size={15} color="var(--bad)" />);

  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="page-head">
        <div><h1>Einstellungen, Skills & Kategorien</h1><p>LLM-Anbindung, Datenschutz, Zielstruktur und die Kategorien (inkl. Kapitel oneSCM).</p></div>
        <div className="spacer" />
        <button className="btn primary" onClick={save}><Save size={14} /> Speichern</button>
      </div>

      <div className="grid g2">
        <div className="card card-pad col" style={{ gap: 12 }}>
          <h2 className="row"><Bot size={17} /> LLM für die Inhaltsanalyse</h2>
          <div className="seg" style={{ alignSelf: "flex-start" }}>
            {[["anthropic", "Claude (Anthropic)"], ["ollama", "Lokal (Ollama)"], ["rules", "Offline-Regeln"]].map(([k, l]) => (
              <button key={k} className={form.provider === k ? "on" : ""} onClick={() => setForm({ ...form, provider: k })}>{l}</button>
            ))}
          </div>
          {form.provider === "anthropic" && (
            <>
              <label className="col" style={{ gap: 4 }}><span className="faint" style={{ fontSize: 12 }}>Modell</span>
                <input className="input mono" value={form.anthropic_model} onChange={(e) => setForm({ ...form, anthropic_model: e.target.value })} /></label>
              <div className="row" style={{ fontSize: 12.5 }}><Ok v={s.data.llm.anthropic_key_present} /> ANTHROPIC_API_KEY {s.data.llm.anthropic_key_present ? "gefunden" : "nicht gesetzt (Umgebungsvariable auf dem Server setzen)"}</div>
              <label className="switch"><input type="checkbox" checked={form.send_content_to_cloud} onChange={(e) => setForm({ ...form, send_content_to_cloud: e.target.checked })} /> Dateiinhalte (Textauszug) an die Cloud-API senden</label>
              {!form.send_content_to_cloud && <div className="callout warn" style={{ fontSize: 12.5 }}>Datenschutzmodus: Es werden nur Dateiname, Pfad und Metadaten übermittelt. Für bessere Ergebnisse aktivieren oder lokal mit Ollama arbeiten.</div>}
              <div className="card card-pad col" style={{ gap: 8, boxShadow: "none", background: "var(--panel-2)" }}>
                <b style={{ fontSize: 13 }}>Kosten steuern</b>
                <div className="row wrap">
                  <span style={{ fontSize: 12.5 }}>Standard für neue Läufe:</span>
                  <div className="seg">
                    <button className={form.mode === "unklare" ? "on" : ""} onClick={() => setForm({ ...form, mode: "unklare" })}>Nur unklare Dateien</button>
                    <button className={form.mode === "alle" ? "on" : ""} onClick={() => setForm({ ...form, mode: "alle" })}>Alle Dateien</button>
                  </div>
                </div>
                <label className="switch"><input type="checkbox" checked={form.batch} onChange={(e) => setForm({ ...form, batch: e.target.checked })} /> Batch-Verarbeitung (−50 %, Ergebnis meist innerhalb 1 Stunde)</label>
                <label className="row" style={{ fontSize: 12.5 }}>Kostenlimit je Lauf
                  <input className="input" type="number" min={0} style={{ width: 90 }} value={form.max_cost_usd} onChange={(e) => setForm({ ...form, max_cost_usd: Number(e.target.value) })} /> $
                  <span className="faint">(0 = ohne)</span></label>
                <span className="faint" style={{ fontSize: 12 }}>
                  Bisher ausgegeben: <b>{(s.data.llm_kosten.kosten_usd ?? 0).toLocaleString("de-DE", { maximumFractionDigits: 3 })} $</b> in {fmtNum(s.data.llm_kosten.aufrufe)} Aufrufen ·
                  Vor jedem Lauf erscheint eine Kostenschätzung zur Bestätigung.
                </span>
              </div>
            </>
          )}
          {form.provider === "ollama" && (
            <div className="grid g2" style={{ gap: 10 }}>
              <label className="col" style={{ gap: 4 }}><span className="faint" style={{ fontSize: 12 }}>Ollama-URL</span><input className="input mono" value={form.ollama_url} onChange={(e) => setForm({ ...form, ollama_url: e.target.value })} /></label>
              <label className="col" style={{ gap: 4 }}><span className="faint" style={{ fontSize: 12 }}>Modell</span><input className="input mono" value={form.ollama_model} onChange={(e) => setForm({ ...form, ollama_model: e.target.value })} /></label>
              <div className="callout ok" style={{ gridColumn: "span 2", fontSize: 12.5 }}><ShieldCheck size={16} /> Inhalte verlassen den Computer nicht.</div>
            </div>
          )}
          <div className="row">
            <button className="btn" disabled={testing} onClick={runTest}>{testing ? <Loader2 size={14} className="spin" /> : <Zap size={14} />} Verbindung testen</button>
            <span className="faint" style={{ fontSize: 12 }}>analysiert eine Beispieldatei (Mietvertrag) ohne Fallback</span>
          </div>
          {test && (
            <div className={`callout ${test.ok ? "ok" : "warn"}`} style={{ fontSize: 12.5, flexDirection: "column", gap: 4 }}>
              {test.ok ? (
                <>
                  <b>✓ {test.provider}{test.model ? ` · ${test.usage?.model ?? test.model}` : ""} antwortet ({test.ms} ms)</b>
                  <span>Kategorie: <b>{test.result.category_id}</b> · Sicherheit {Math.round(test.result.confidence * 100)} % · Wichtigkeit {test.result.importance}</span>
                  <span>Labels: {test.result.labels.join(", ")}</span>
                  <span className="muted">{test.result.summary}</span>
                  {test.usage && <span className="faint">Tokens: {test.usage.input} ein · {test.usage.output} aus{test.usage.cache_read ? ` · ${test.usage.cache_read} aus Cache` : ""}</span>}
                </>
              ) : (
                <><b>✗ Verbindung fehlgeschlagen ({test.provider ?? "LLM"})</b><span>{test.error}</span></>
              )}
            </div>
          )}
          {form.provider === "rules" && <div className="callout" style={{ fontSize: 12.5 }}>Schlüsselwort- und Endungsbasierte Klassifikation – kostenlos, offline, schnell. Dient auch als automatischer Fallback, wenn ein LLM nicht erreichbar ist.</div>}
        </div>

        <div className="card card-pad col" style={{ gap: 12 }}>
          <h2>Zielstruktur & Analyse</h2>
          <label className="col" style={{ gap: 4 }}><span className="faint" style={{ fontSize: 12 }}>Ordner-Vorlage (Platzhalter: {"{group} {category} {subcategory} {year} {month} {type}"})</span>
            <input className="input mono" value={form.target_structure} onChange={(e) => setForm({ ...form, target_structure: e.target.value })} /></label>
          <div className="pathbox new">{s.data.target_root}/{form.target_structure.replace("{group}", "02_Beruf").replace("{category}", "Projekte").replace("{year}", "2025").replace("{month}", "10").replace("{subcategory}", "Phoenix").replace("{type}", "PDF")}/Datei.pdf</div>
          <label className="switch"><input type="checkbox" checked={form.ocr} onChange={(e) => setForm({ ...form, ocr: e.target.checked })} /> OCR für Bilder & gescannte PDFs</label>
          <div className="col" style={{ gap: 6 }}>
            <span className="faint" style={{ fontSize: 12 }}>Miniaturen (alle Seiten)</span>
            <div className="seg" style={{ alignSelf: "flex-start" }}>
              {[["smart", "Wichtige sofort"], ["alle", "Alle sofort"], ["bei_bedarf", "Nur beim Öffnen"]].map(([k, l]) => (
                <button key={k} className={form.thumbnails_mode === k ? "on" : ""} onClick={() => setForm({ ...form, thumbnails_mode: k })}>{l}</button>
              ))}
            </div>
            <span className="faint" style={{ fontSize: 11.5 }}>Deckblatt immer; alle Seiten sofort nur für Dateien ab Wichtigkeit {s.data.analysis.thumbs_all_pages_min_importance} – der Rest beim ersten Öffnen.</span>
            <label className="row" style={{ fontSize: 12.5 }}>Speicher-Obergrenze
              <input className="input" type="number" min={1} style={{ width: 80 }} value={form.thumbs_budget_gb} onChange={(e) => setForm({ ...form, thumbs_budget_gb: Number(e.target.value) })} /> GB</label>
            <div className="row" style={{ fontSize: 12 }}>
              <div className="progress grow"><div style={{ width: `${Math.min(100, (s.data.cache.total_bytes / Math.max(1, s.data.cache.budget_bytes)) * 100)}%` }} /></div>
              <span className="faint nowrap">{fmtBytes(s.data.cache.total_bytes)} von {fmtBytes(s.data.cache.budget_bytes)}</span>
            </div>
            <span className="faint" style={{ fontSize: 11.5 }}>{fmtNum(s.data.cache.thumbs_pages)} Seitenbilder · {fmtNum(s.data.cache.complete_files)} Dateien vollständig · {fmtNum(s.data.cache.cover_only_files)} nur Deckblatt. Wird die Grenze erreicht, werden zuerst Folgeseiten unwichtiger Dateien aus dem Cache entfernt (nie Ihre Dateien).</span>
          </div>
          <div className="col" style={{ gap: 6 }}>
            <span className="faint" style={{ fontSize: 12 }}>Cloud-Dateien „nur online“ (OneDrive, Google Drive, iCloud, Dropbox, Nextcloud)</span>
            <label className="switch"><input type="checkbox" checked={form.download_online_only} onChange={(e) => setForm({ ...form, download_online_only: e.target.checked })} /> Inhalte lesen und kopieren (löst den Download aus)</label>
            {form.download_online_only
              ? <div className="callout warn" style={{ fontSize: 12 }}>Achtung: Analyse und Kopie laden Nur-online-Dateien herunter – bei großen Cloud-Ablagen kann die Festplatte volllaufen.</div>
              : <span className="faint" style={{ fontSize: 11.5 }}>Standard: nur Metadaten (Name, Pfad, Größe, Datum) – es wird nichts heruntergeladen.</span>}
            <label className="switch"><input type="checkbox" checked={!!form.cloud_download_content} onChange={(e) => setForm({ ...form, cloud_download_content: e.target.checked })} />
              Cloud-Konten (Schnittstelle): Inhalte für die Analyse vorübergehend laden (bis {s.data.cloud_api.download_max_mb} MB je Datei)</label>
            <span className="faint" style={{ fontSize: 11.5 }}>Aus: Einordnung nach Name/Pfad/Metadaten, Deckblatt kommt direkt von der Cloud. An: Text, OCR und alle Seiten – die Datei wird nur temporär geladen und danach verworfen.</span>
          </div>
          <div className="col" style={{ gap: 5, fontSize: 12.5 }}>
            <div className="row"><Ok v={s.data.ocr_available} /> Tesseract OCR</div>
            <div className="row"><Ok v={s.data.libreoffice_available} /> LibreOffice (Miniaturen für PPTX/DOCX/XLSX)</div>
            <div className="row"><Ok v={s.data.api_key_enabled} /> API-Key für Agenten {s.data.api_key_enabled ? "gesetzt" : "fehlt (siehe Zugang & Sicherheit)"}</div>
          </div>

        </div>
      </div>

      <Access />

      <div className="card">
        <div className="card-head"><h2 className="grow">Skills der Agenten</h2></div>
        <table className="table">
          <thead><tr><th>Skill</th><th>Beschreibung</th><th>Agent</th><th style={{ width: 90 }}>Status</th></tr></thead>
          <tbody>
            {skills.data?.map((k) => (
              <tr key={k.id} style={{ cursor: "default" }}>
                <td style={{ fontWeight: 600 }}>{k.name}</td><td className="muted">{k.beschreibung}</td><td><span className="badge outline">{k.agent}</span></td>
                <td>{k["verfügbar"] ? <span className="badge ok">aktiv</span> : <span className="badge bad">fehlt</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card card-pad">
        <h2 style={{ marginBottom: 12 }}>{cats.data?.length ?? 60} Kategorien</h2>
        <div className="grid g4" style={{ gap: 14 }}>
          {GROUPS.map((g) => {
            const inGroup = cats.data?.filter((c) => c.group === g) ?? [];
            const chapters = [...new Set(inGroup.filter((c) => c.chapter).map((c) => c.chapter as string))];
            const line = (c: any) => (
              <div key={c.id} className="row" style={{ fontSize: 12.5, padding: "3px 0", flexWrap: "nowrap" }} title={`${c.keywords.join(", ")}\nZielordner: ${c.folder}`}>
                <span className={`dot g-${g === "Sonstiges" ? "sonst" : g.toLowerCase()}`} />
                <span className="grow ellipsis">{c.short ?? c.name}</span>
                <span className="faint">{c.count ? fmtNum(c.count) : ""}</span>
              </div>
            );
            return (
              <div key={g}>
                <h3 style={{ marginBottom: 8 }}>{g}</h3>
                {inGroup.filter((c) => !c.chapter).map(line)}
                {chapters.map((ch) => (
                  <div key={ch} className="chapter-box">
                    <div className="row" style={{ marginBottom: 4 }}>
                      <b style={{ fontSize: 12.5 }}>Kapitel {ch}</b>
                      <span className="badge outline" style={{ fontSize: 10.5 }}>{inGroup.filter((c) => c.chapter === ch).length} Kategorien</span>
                    </div>
                    <div className="faint mono" style={{ fontSize: 11, marginBottom: 4 }}>Zielordner: {{ Privat: "01_Privat", Beruf: "02_Beruf", GenAI: "03_GenAI", Sonstiges: "04_Sonstiges" }[g]}/{ch}/…</div>
                    {inGroup.filter((c) => c.chapter === ch).map(line)}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
