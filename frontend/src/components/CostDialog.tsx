import { useEffect, useState } from "react";
import { AlertTriangle, Layers, Loader2, Play, Sparkles } from "lucide-react";
import { post } from "../api";
import { fmtNum } from "../util";
import { Modal, useToast } from "./ui";

interface Estimate {
  dateien: number;
  an_llm: number;
  nur_regeln: number;
  modell: string;
  modus: string;
  batch: boolean;
  inhalte_senden: boolean;
  tokens: { input: number; output: number; cache_read: number; cache_write: number };
  kosten_usd: number;
  kosten_eur: number;
  kosten_ohne_batch_usd: number;
  alternativen_usd: Record<string, number>;
  limit_usd: number;
  duplikate_ohne_kosten: number;
  in_laufenden_batches: number;
  hinweis: string;
}

const usd = (v: number) => (v < 0.01 && v > 0 ? "< 0,01 $" : `${v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`);

/** Kostenschätzung und Bestätigung vor einer Analyse mit Claude. */
export default function CostDialog({ force, onClose, onStarted }: { force: boolean; onClose: () => void; onStarted: () => void }) {
  const toast = useToast();
  const [mode, setMode] = useState<"alle" | "unklare">("unklare");
  const [batch, setBatch] = useState(false);
  const [limit, setLimit] = useState<number | null>(null);
  const [est, setEst] = useState<Estimate | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    setLoading(true);
    post<Estimate>("/api/llm/estimate", { force, mode, batch, max_cost_usd: limit ?? undefined })
      .then((e) => {
        setEst(e);
        if (limit === null) setLimit(e.limit_usd);
      })
      .catch((e) => toast(e.message, true))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, batch, force]);

  const start = async () => {
    setStarting(true);
    try {
      await post("/api/pipeline/analyze", { force, confirmed: true, mode, batch, max_cost_usd: limit ?? 0 });
      toast(batch ? "Analyse gestartet – Claude-Batch wird übermittelt" : "Analyse mit Claude gestartet");
      onStarted();
      onClose();
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setStarting(false);
    }
  };

  return (
    <Modal onClose={onClose} title={<span className="row"><Sparkles size={16} color="var(--accent)" /> Analyse mit Claude – Kosten prüfen</span>}>
      <div className="col" style={{ gap: 14, width: "min(640px, 86vw)" }}>
        <div className="grid g2" style={{ gap: 10 }}>
          <div className="col" style={{ gap: 6 }}>
            <span className="faint" style={{ fontSize: 12 }}>Welche Dateien gehen an Claude?</span>
            <div className="seg">
              <button className={mode === "unklare" ? "on" : ""} onClick={() => setMode("unklare")}>Nur unklare</button>
              <button className={mode === "alle" ? "on" : ""} onClick={() => setMode("alle")}>Alle</button>
            </div>
            <span className="faint" style={{ fontSize: 11.5 }}>„Nur unklare“: Dateien, die die Offline-Regeln sicher einordnen, kosten nichts.</span>
          </div>
          <div className="col" style={{ gap: 6 }}>
            <span className="faint" style={{ fontSize: 12 }}>Abrechnung</span>
            <div className="seg">
              <button className={!batch ? "on" : ""} onClick={() => setBatch(false)}>Sofort</button>
              <button className={batch ? "on" : ""} onClick={() => setBatch(true)}><Layers size={13} /> Batch −50 %</button>
            </div>
            <span className="faint" style={{ fontSize: 11.5 }}>Batch: halber Preis, Ergebnis meist innerhalb 1 Stunde (max. 24 h). Übersteht Neustarts.</span>
          </div>
        </div>

        {loading || !est ? (
          <div className="row faint"><Loader2 size={15} className="spin" /> Kosten werden geschätzt …</div>
        ) : (
          <>
            <div className="card card-pad" style={{ boxShadow: "none", background: "var(--panel-2)" }}>
              <div className="row" style={{ alignItems: "baseline", gap: 12 }}>
                <span style={{ fontSize: 30, fontWeight: 750 }}>{usd(est.kosten_usd)}</span>
                <span className="muted">≈ {est.kosten_eur.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} € · Obergrenze</span>
                {est.batch && <span className="badge ok">statt {usd(est.kosten_ohne_batch_usd)}</span>}
              </div>
              <div className="grid g3" style={{ gap: 8, marginTop: 10, fontSize: 12.5 }}>
                <div><div className="faint">An Claude</div><b>{fmtNum(est.an_llm)}</b> Dateien</div>
                <div><div className="faint">Offline (kostenlos)</div><b>{fmtNum(est.nur_regeln)}</b> Dateien</div>
                <div><div className="faint">Duplikate (übernommen)</div><b>{fmtNum(est.duplikate_ohne_kosten)}</b> Dateien</div>
              </div>
              <div className="faint" style={{ fontSize: 11.5, marginTop: 8 }}>
                Modell {est.modell} · ca. {fmtNum(est.tokens.input + est.tokens.cache_read + est.tokens.cache_write)} Eingabe- /{" "}
                {fmtNum(est.tokens.output)} Ausgabe-Tokens · Inhalte {est.inhalte_senden ? "werden" : "werden nicht"} gesendet
              </div>
            </div>

            <div>
              <div className="faint" style={{ fontSize: 12, marginBottom: 4 }}>Zum Vergleich (gleiche Auswahl, Modell in den Einstellungen änderbar):</div>
              <div className="row wrap" style={{ gap: 6 }}>
                {Object.entries(est.alternativen_usd).map(([m, v]) => (
                  <span key={m} className={`badge ${m === est.modell ? "g-beruf" : "outline"}`}>{m.replace("claude-", "")}: {usd(v)}</span>
                ))}
              </div>
            </div>

            <label className="row" style={{ fontSize: 13 }}>
              Kostenlimit für diesen Lauf
              <input className="input" type="number" min={0} step={1} style={{ width: 100 }} value={limit ?? 0}
                onChange={(e) => setLimit(Number(e.target.value))} /> $
              <span className="faint" style={{ fontSize: 11.5 }}>(0 = kein Limit; danach Rest offline)</span>
            </label>

            {est.in_laufenden_batches > 0 && (
              <div className="callout warn" style={{ fontSize: 12.5 }}><AlertTriangle size={16} /> {fmtNum(est.in_laufenden_batches)} Dateien warten noch auf einen laufenden Batch – sie werden nicht erneut gesendet.</div>
            )}
            <div className="faint" style={{ fontSize: 11.5 }}>{est.hinweis} Die tatsächlichen Kosten erscheinen nach dem Lauf in der Übersicht.</div>

            <div className="row">
              <span className="spacer" />
              <button className="btn ghost" onClick={onClose}>Abbrechen</button>
              <button className="btn primary" disabled={starting || est.dateien === 0} onClick={start}>
                {starting ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
                {est.dateien === 0 ? "Nichts zu analysieren" : `Analyse starten (bis ${usd(limit && limit > 0 ? Math.min(limit, est.kosten_usd) : est.kosten_usd)})`}
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
