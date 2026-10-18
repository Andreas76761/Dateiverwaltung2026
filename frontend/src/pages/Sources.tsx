import { Cloud, HardDrive, Laptop, Play, Server, Usb, Wifi, WifiOff } from "lucide-react";
import { get, post } from "../api";
import { useAsync, useJobs, useToast } from "../components/ui";
import CloudAccounts from "../components/CloudAccounts";
import type { Computer } from "../types";
import { fmtBytes, fmtDate, fmtNum } from "../util";

interface Src {
  computers: Computer[];
  cloud_detected: { provider: string; path: string; suggested_target: string }[];
  this_host: { hostname: string; os: string };
  target_root: string;
  target_structure: string;
  config_file: string;
}

export default function Sources() {
  const { version, refresh } = useJobs();
  const toast = useToast();
  const { data } = useAsync<Src>(() => get("/api/sources"), [version]);
  if (!data) return <div className="faint">Lädt …</div>;
  const server = typeof window !== "undefined" ? window.location.origin : "http://SERVER:8800";
  const scanVol = async (id: string) => {
    await post("/api/pipeline/scan", { volume_ids: [id] });
    refresh();
    toast("Einlesen gestartet");
  };

  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="page-head">
        <div>
          <h1>Quellen & Connectoren</h1>
          <p>Computer, Festplatten und Cloud-Ordner · Konfiguration: <span className="mono">{data.config_file}</span></p>
        </div>
      </div>

      <div className="grid g2">
        {data.computers.map((c) => (
          <div key={c.id} className="card">
            <div className="card-head">
              <Laptop size={18} color="var(--accent)" />
              <div className="grow">
                <div style={{ fontWeight: 650 }}>{c.name}</div>
                <div className="faint" style={{ fontSize: 12 }}>{c.os} · {c.mode === "agent" ? "Agent" : "lokal gescannt"} · zuletzt {fmtDate(c.last_seen, true)}</div>
              </div>
              <span className={`badge ${c.mode === "agent" ? "g-genai" : "outline"}`}>{c.mode === "agent" ? <><Wifi size={11} /> Agent</> : <><Server size={11} /> Server</>}</span>
            </div>
            <table className="table">
              <tbody>
                {c.volumes.map((v) => (
                  <tr key={v.id} style={{ cursor: "default" }}>
                    <td style={{ width: 28 }}>{v.kind === "cloud" || v.kind === "cloud-api" ? <Cloud size={16} color="var(--beruf)" /> : v.kind === "external" ? <Usb size={16} color="var(--warn)" /> : <HardDrive size={16} color="var(--text-3)" />}</td>
                    <td>
                      <div style={{ fontWeight: 550 }}>{v.name}</div>
                      <div className="mono faint ellipsis" style={{ maxWidth: 300 }} title={v.path}>{v.path}</div>
                    </td>
                    <td className="nowrap">{fmtNum(v.files)} Dateien<div className="faint" style={{ fontSize: 11.5 }}>{fmtBytes(v.bytes)} · {fmtNum(v.analyzed)} analysiert</div></td>
                    <td className="nowrap">{c.mode === "cloud-api" ? <span className="faint" style={{ fontSize: 12 }}>über Schnittstelle</span> : c.mode === "agent" ? <span className="faint" style={{ fontSize: 12 }}>via Agent</span> : v.reachable ? <button className="btn sm" onClick={() => scanVol(v.id)}><Play size={12} /> Einlesen</button> : <span className="badge bad"><WifiOff size={11} /> nicht erreichbar</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      <CloudAccounts />

      <div className="grid g2">
        <div className="card card-pad col" style={{ gap: 10 }}>
          <h2>Ziel: neue Ordner in der Cloud</h2>
          <div className="pathbox new">{data.target_root}</div>
          <div className="faint" style={{ fontSize: 12.5 }}>Struktur-Vorlage: <span className="mono">{data.target_structure}</span></div>
          <div className="faint" style={{ fontSize: 12.5 }}>
            Das Ziel ist ein Ordner innerhalb eines synchronisierten Cloud-Laufwerks (OneDrive, Google Drive, Dropbox, iCloud, Nextcloud). Der Sync-Client lädt die Kopien automatisch hoch – es werden keine Cloud-Zugangsdaten benötigt.
          </div>
          <h3 style={{ marginTop: 6 }}>Auf diesem Computer erkannt ({data.this_host.hostname})</h3>
          {data.cloud_detected.length ? data.cloud_detected.map((c) => (
            <div key={c.path} className="row"><Cloud size={14} /><b>{c.provider}</b><span className="mono faint ellipsis">{c.path}</span></div>
          )) : <div className="faint" style={{ fontSize: 12.5 }}>Kein Cloud-Sync-Ordner gefunden (Demo-Modus nutzt ./demo/cloud).</div>}
        </div>

        <div className="card card-pad col" style={{ gap: 10 }}>
          <h2>Weitere Computer anbinden (Agent)</h2>
          <div className="faint" style={{ fontSize: 12.5 }}>
            1. Projekt auf dem Computer installieren (<span className="mono">pip install -r backend/requirements.txt</span>).<br />
            2. In <span className="mono">config/fdv.yaml</span> des Servers den Computer mit <span className="mono">mode: agent</span> und seinen Festplatten-Pfaden eintragen.<br />
            3. Agent starten – er liest nur, sendet Metadaten, Textauszüge & Miniaturen und führt später freigegebene Kopien lokal in seinen Cloud-Ordner aus:
          </div>
          <div className="code">{`cd backend
python -m app.agent_client \\
  --server ${server} \\
  --computer laptop \\
  --key  <API-KEY> \\
  --target "C:/Users/andreas/OneDrive/Future-Dateiverwaltung" \\
  scan inventory copy`}</div>
          <div className="faint" style={{ fontSize: 12.5 }}>4. Dauerhaft als <b>Hintergrunddienst</b> einrichten (startet bei jeder Anmeldung, liest alle 24 h und auf Anforderung neu ein, holt alle 10 Minuten freigegebene Kopien ab):</div>
          <div className="code">{`.\\dienst-einrichten.ps1 agent --server ${server} --computer laptop --key <API-KEY> --target "$env:OneDrive\\Future-Dateiverwaltung"   # Windows
./dienst-einrichten.sh  agent --server ${server} --computer macbook --key <API-KEY> --target ~/OneDrive/Future-Dateiverwaltung  # macOS/Linux`}</div>
          <div className="faint" style={{ fontSize: 12 }}>Zeitplan und „Einlesen anfordern“ für alle Agenten: Seite <a href="#/automation">Automatik</a>.</div>
        </div>
      </div>
    </div>
  );
}
