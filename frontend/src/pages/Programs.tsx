import { useState } from "react";
import { Bot, Boxes, Cpu, Loader2, Play, Search, Wrench } from "lucide-react";
import { get, post, qs } from "../api";
import { Empty, ExportMenu, useAsync, useJobs, useToast } from "../components/ui";
import { fmtBytes, fmtDate, fmtNum } from "../util";

const KINDS: Record<string, { label: string; icon: any; cls: string }> = {
  "llm-modell": { label: "LLM-Modelle", icon: Cpu, cls: "g-genai" },
  "llm-tool": { label: "LLM-Lösungen & KI-Tools", icon: Bot, cls: "g-beruf" },
  "dev-tool": { label: "Entwickler-Tools", icon: Wrench, cls: "g-privat" },
  programm: { label: "Programme", icon: Boxes, cls: "g-sonst" },
};

export default function Programs() {
  const { version, running, refresh } = useJobs();
  const toast = useToast();
  const [kind, setKind] = useState("");
  const [computer, setComputer] = useState("");
  const [q, setQ] = useState("");
  const { data } = useAsync<any>(() => get(`/api/programs${qs({ kind, computer, q })}`), [kind, computer, q, version]);
  const comps = useAsync<any>(() => get("/api/sources"), []);
  const isRunning = running.some((r) => r.kind === "inventory");

  const count = (k: string) => (data?.summary ?? []).filter((s: any) => s.kind === k && (!computer || s.computer_id === computer)).reduce((a: number, s: any) => a + s.n, 0);
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
          <p>Erweiterung: Organisation aller Programme, KI-Tools und lokalen Modelle je Computer – nur Bestandsaufnahme, keine Änderungen.</p>
        </div>
        <div className="spacer" />
        <ExportMenu path="/api/export/programme" />
        <button className="btn primary" disabled={isRunning} onClick={start}>{isRunning ? <Loader2 size={14} className="spin" /> : <Play size={14} />} Inventar erfassen</button>
      </div>

      <div className="grid g4">
        {Object.entries(KINDS).map(([k, v]) => {
          const Icon = v.icon;
          return (
            <div key={k} className={`card kpi`} style={{ cursor: "pointer", outline: kind === k ? "2px solid var(--accent)" : undefined }} onClick={() => setKind(kind === k ? "" : k)}>
              <div className="k-label"><Icon size={14} /> {v.label}</div>
              <div className="k-val">{fmtNum(count(k))}</div>
            </div>
          );
        })}
      </div>

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
          </select>
        </div>
        {data?.items.length ? (
          <div style={{ maxHeight: "60vh", overflow: "auto" }}>
            <table className="table">
              <thead><tr><th>Name</th><th style={{ width: 170 }}>Art</th><th>Version</th><th>Computer</th><th>Ort / Quelle</th><th style={{ width: 80 }}>Größe</th><th style={{ width: 120 }}>Erfasst</th></tr></thead>
              <tbody>
                {data.items.map((p: any) => (
                  <tr key={p.id} style={{ cursor: "default" }}>
                    <td style={{ fontWeight: 550 }}>{p.name}{p.publisher && <div className="faint ellipsis" style={{ fontSize: 11, maxWidth: 260, fontWeight: 400 }}>{p.publisher}</div>}</td>
                    <td><span className={`badge ${KINDS[p.kind]?.cls}`}>{KINDS[p.kind]?.label ?? p.kind}</span>{p.category && <div className="faint" style={{ fontSize: 11 }}>{p.category}</div>}</td>
                    <td className="mono faint"><div className="ellipsis" style={{ maxWidth: 180 }}>{p.version || "–"}</div></td>
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
          <Empty icon={<Boxes size={34} />} title="Noch kein Inventar">„Inventar erfassen“ liest installierte Programme (Registry / Applications / dpkg), KI-Tools im PATH, Python-KI-Bibliotheken und lokale Modelle (Ollama, LM Studio, Hugging Face, GGUF). Andere Computer melden ihr Inventar per Agent.</Empty>
        )}
      </div>
    </div>
  );
}
