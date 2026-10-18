import { useEffect, useState } from "react";
import { Bot, CheckCircle2, KeyRound, Save, ShieldCheck, XCircle } from "lucide-react";
import { apiKey, get, post, setApiKey } from "../api";
import { useAsync, useToast } from "../components/ui";
import { fmtNum, GROUPS } from "../util";

export default function Settings() {
  const toast = useToast();
  const s = useAsync<any>(() => get("/api/settings"), []);
  const skills = useAsync<any[]>(() => get("/api/skills"), []);
  const cats = useAsync<any[]>(() => get("/api/categories"), []);
  const [form, setForm] = useState<any>(null);
  const [key, setKey] = useState(apiKey());
  useEffect(() => {
    if (s.data) setForm({ provider: s.data.llm.provider, anthropic_model: s.data.llm.anthropic_model, ollama_url: s.data.llm.ollama_url, ollama_model: s.data.llm.ollama_model, send_content_to_cloud: s.data.llm.send_content_to_cloud, target_structure: s.data.target_structure, ocr: s.data.analysis.ocr });
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
        <div><h1>Einstellungen, Skills & Kategorien</h1><p>LLM-Anbindung, Datenschutz, Zielstruktur und die 50 Kategorien.</p></div>
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
            </>
          )}
          {form.provider === "ollama" && (
            <div className="grid g2" style={{ gap: 10 }}>
              <label className="col" style={{ gap: 4 }}><span className="faint" style={{ fontSize: 12 }}>Ollama-URL</span><input className="input mono" value={form.ollama_url} onChange={(e) => setForm({ ...form, ollama_url: e.target.value })} /></label>
              <label className="col" style={{ gap: 4 }}><span className="faint" style={{ fontSize: 12 }}>Modell</span><input className="input mono" value={form.ollama_model} onChange={(e) => setForm({ ...form, ollama_model: e.target.value })} /></label>
              <div className="callout ok" style={{ gridColumn: "span 2", fontSize: 12.5 }}><ShieldCheck size={16} /> Inhalte verlassen den Computer nicht.</div>
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
          <div className="col" style={{ gap: 5, fontSize: 12.5 }}>
            <div className="row"><Ok v={s.data.ocr_available} /> Tesseract OCR</div>
            <div className="row"><Ok v={s.data.libreoffice_available} /> LibreOffice (Miniaturen für PPTX/DOCX/XLSX)</div>
            <div className="row"><Ok v={s.data.api_key_enabled} /> API-Key-Schutz {s.data.api_key_enabled ? "aktiv" : "aus (nur im lokalen Netz verwenden)"}</div>
          </div>
          <div className="row">
            <KeyRound size={15} />
            <input className="input grow" type="password" placeholder="API-Key für dieses Frontend" value={key} onChange={(e) => setKey(e.target.value)} />
            <button className="btn sm" onClick={() => { setApiKey(key); toast("API-Key gespeichert"); }}>Übernehmen</button>
          </div>
        </div>
      </div>

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
        <h2 style={{ marginBottom: 12 }}>50 Kategorien</h2>
        <div className="grid g4" style={{ gap: 14 }}>
          {GROUPS.map((g) => (
            <div key={g}>
              <h3 style={{ marginBottom: 8 }}>{g}</h3>
              {cats.data?.filter((c) => c.group === g).map((c) => (
                <div key={c.id} className="row" style={{ fontSize: 12.5, padding: "3px 0" }} title={c.keywords.join(", ")}>
                  <span className={`dot g-${g === "Sonstiges" ? "sonst" : g.toLowerCase()}`} />
                  <span className="grow ellipsis">{c.name}</span>
                  <span className="faint">{c.count ? fmtNum(c.count) : ""}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
