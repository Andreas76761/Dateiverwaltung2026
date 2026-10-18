import { useEffect, useState } from "react";
import { CheckCircle2, CloudCog, Link2, Loader2, Play, Unlink, Zap } from "lucide-react";
import { get, post } from "../api";
import { fmtBytes, fmtDate, fmtNum } from "../util";
import { useAsync, useJobs, useToast } from "./ui";

interface Acc {
  id: string;
  provider: "onedrive" | "gdrive";
  name: string;
  root: string;
  target_folder: string;
  configured: boolean;
  connected: boolean;
  write: boolean;
  connected_at: string | null;
  volume_id: string;
  files: number;
  bytes: number;
  analyzed: number;
  last_scan: string | null;
}

const PROVIDER = { onedrive: "OneDrive / SharePoint (Microsoft Graph)", gdrive: "Google Drive" };

/** Cloud-Konten über Schnittstelle: verbinden (OAuth), testen, einlesen. */
export default function CloudAccounts() {
  const toast = useToast();
  const { refresh } = useJobs();
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [test, setTest] = useState<Record<string, any>>({});
  const { data } = useAsync<{ accounts: Acc[]; redirect_uri: string; download_content: boolean }>(() => get("/api/cloud/accounts"), [tick]);

  useEffect(() => {
    const h = (e: MessageEvent) => e.data === "fdv-cloud-connected" && (setTick((t) => t + 1), toast("Cloud-Konto verbunden"));
    window.addEventListener("message", h);
    return () => window.removeEventListener("message", h);
  }, [toast]);

  const connect = async (a: Acc, write: boolean) => {
    try {
      const r = await post<{ url: string }>(`/api/cloud/${a.id}/connect`, { write });
      window.open(r.url, "fdv-cloud-login", "width=520,height=720");
      toast("Anmeldefenster geöffnet – nach der Anmeldung hier weiter");
      setTimeout(() => setTick((t) => t + 1), 8000);
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const disconnect = async (a: Acc) => {
    await post(`/api/cloud/${a.id}/disconnect`);
    toast(`${a.name} getrennt (nur lokal gespeicherte Anmeldung entfernt)`);
    setTick((t) => t + 1);
  };
  const runTest = async (a: Acc) => {
    setBusy(a.id);
    try {
      setTest({ ...test, [a.id]: await post(`/api/cloud/${a.id}/test`) });
    } finally {
      setBusy(null);
    }
  };
  const scan = async (a: Acc) => {
    await post("/api/pipeline/scan", { volume_ids: [a.volume_id] });
    refresh();
    toast(`${a.name} wird über die Schnittstelle eingelesen`);
  };

  if (!data) return null;
  return (
    <div className="card">
      <div className="card-head">
        <CloudCog size={18} color="var(--accent)" />
        <div className="grow">
          <div style={{ fontWeight: 650 }}>Cloud-Konten über Schnittstelle</div>
          <div className="faint" style={{ fontSize: 12 }}>
            Liest alle Cloud-Dateien direkt (auch nicht synchronisierte) · Kopien in Schritt 4 serverseitig in der Cloud · nie löschen/verschieben
          </div>
        </div>
      </div>
      {data.accounts.length === 0 ? (
        <div className="card-pad faint" style={{ fontSize: 13 }}>
          Noch kein Konto eingerichtet. In <span className="mono">config/fdv.yaml</span> unter <span className="mono">cloud_api.accounts</span> eintragen –
          Anleitung inkl. App-Registrierung bei Microsoft/Google: <span className="mono">docs/CLOUD-API.md</span>.
        </div>
      ) : (
        <table className="table">
          <tbody>
            {data.accounts.map((a) => (
              <tr key={a.id} style={{ cursor: "default" }}>
                <td>
                  <div style={{ fontWeight: 600 }}>{a.name}</div>
                  <div className="faint" style={{ fontSize: 11.5 }}>{PROVIDER[a.provider]} · Ordner {a.root || "/"} · Ziel „{a.target_folder}“</div>
                  {test[a.id] && (
                    <div style={{ fontSize: 11.5, marginTop: 4 }} className={test[a.id].ok ? "" : "faint"}>
                      {test[a.id].ok
                        ? <>✓ Verbindung ok: {test[a.id].items.slice(0, 4).map((i: any) => i.name).join(", ")}{test[a.id].items.length > 4 ? " …" : ""}</>
                        : <span style={{ color: "var(--bad)" }}>✗ {test[a.id].error}</span>}
                    </div>
                  )}
                </td>
                <td className="nowrap">
                  {!a.configured ? <span className="badge bad">client_id fehlt</span>
                    : !a.connected ? <span className="badge outline">nicht verbunden</span>
                    : a.write ? <span className="badge ok"><CheckCircle2 size={11} /> lesen + kopieren</span>
                    : <span className="badge g-beruf"><CheckCircle2 size={11} /> nur lesen</span>}
                  {a.connected_at && <div className="faint" style={{ fontSize: 11 }}>seit {fmtDate(a.connected_at)}</div>}
                </td>
                <td className="nowrap">{fmtNum(a.files)} Dateien<div className="faint" style={{ fontSize: 11.5 }}>{fmtBytes(a.bytes)} · {fmtDate(a.last_scan, true)}</div></td>
                <td>
                  <div className="row wrap" style={{ gap: 5, justifyContent: "flex-end" }}>
                    {a.configured && !a.connected && <button className="btn sm primary" onClick={() => connect(a, false)}><Link2 size={12} /> Verbinden (lesen)</button>}
                    {a.connected && !a.write && <button className="btn sm" onClick={() => connect(a, true)} title="Zusätzlich Ordner anlegen und Dateien kopieren – für Schritt 4">Kopieren erlauben</button>}
                    {a.connected && <button className="btn sm" disabled={busy === a.id} onClick={() => runTest(a)}>{busy === a.id ? <Loader2 size={12} className="spin" /> : <Zap size={12} />} Testen</button>}
                    {a.connected && <button className="btn sm" onClick={() => scan(a)}><Play size={12} /> Einlesen</button>}
                    {a.connected && <button className="btn sm ghost" onClick={() => disconnect(a)} title="Lokal gespeicherte Anmeldung entfernen"><Unlink size={12} /></button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="card-pad faint" style={{ fontSize: 11.5, borderTop: "1px solid var(--border)" }}>
        Rückleitungs-Adresse für die App-Registrierung: <span className="mono">{data.redirect_uri}</span> ·
        Inhalte werden {data.download_content ? "für die Analyse vorübergehend geladen" : "nicht geladen (nur Metadaten + Deckblatt)"} – umstellbar in den Einstellungen.
      </div>
    </div>
  );
}
