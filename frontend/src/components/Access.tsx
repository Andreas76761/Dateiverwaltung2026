import { useState } from "react";
import { Copy, KeyRound, Lock, Plus, RefreshCw, ShieldCheck, UserRound } from "lucide-react";
import { get, post } from "../api";
import { useAsync, useToast } from "./ui";
import { fmtDate } from "../util";

interface AccessInfo {
  mode: string; api_key: string | null;
  tls: { aktiv: boolean; zertifikat: boolean; fingerprint: string | null; namen: string[] | null; gueltig_bis: string | null; ca_datei: string };
  users: { username: string; role: string; active: number; created_at: string; last_login: string | null }[];
}

/** Einstellungen → Zugang & Sicherheit: Anmeldung, Konten, API-Key für Agenten, HTTPS. Nur für Admins. */
export default function Access() {
  const toast = useToast();
  const [tick, setTick] = useState(0);
  const a = useAsync<AccessInfo>(() => get("/api/auth/access"), [tick]);
  const [nu, setNu] = useState({ username: "", password: "", role: "leser" });
  const [showKey, setShowKey] = useState(false);
  const run = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); toast(msg); setTick((t) => t + 1); } catch (e: any) { toast(e.message, true); }
  };
  if (a.error) return <div className="card card-pad faint" style={{ fontSize: 12.5 }}><Lock size={14} /> Zugang & Sicherheit: nur für Admins.</div>;
  const d = a.data;
  if (!d) return null;
  return (
    <div className="card card-pad col" style={{ gap: 14 }} id="zugang">
      <h2><ShieldCheck size={17} style={{ verticalAlign: -3 }} /> Zugang & Sicherheit</h2>
      <div className="grid g3" style={{ gap: 16 }}>
        <div className="col" style={{ gap: 8 }}>
          <h3 style={{ margin: 0 }}>Anmeldung</h3>
          <select className="input" value={d.mode} onChange={(e) => run(() => post("/api/auth/mode", { mode: e.target.value }), "Gespeichert")}>
            <option value="auto">Automatisch – ohne Konto nur auf diesem Computer, mit Konto immer anmelden</option>
            <option value="an">Immer anmelden</option>
            <option value="aus">Aus (nur für Testumgebungen)</option>
          </select>
          {!d.users.length && <div className="callout warn" style={{ fontSize: 12 }}>Noch kein Konto: Die App ist nur auf diesem Computer erreichbar. Für den Zugriff aus dem Netzwerk ein Konto anlegen.</div>}
          <h3 style={{ margin: "6px 0 0" }}>Konten</h3>
          {d.users.map((u) => (
            <div key={u.username} className="row" style={{ gap: 6, fontSize: 12.5, opacity: u.active ? 1 : 0.5 }}>
              <UserRound size={14} /><b className="grow">{u.username}</b>
              <select className="input" style={{ padding: "1px 4px", fontSize: 12 }} value={u.role} onChange={(e) => run(() => post(`/api/auth/users/${u.username}`, { role: e.target.value }), "Rolle geändert")}>
                <option value="admin">Admin</option><option value="leser">nur lesen</option>
              </select>
              <button className="btn sm ghost" onClick={() => run(() => post(`/api/auth/users/${u.username}`, { active: !u.active }), u.active ? "Deaktiviert" : "Aktiviert")}>{u.active ? "Deaktivieren" : "Aktivieren"}</button>
            </div>
          ))}
          <div className="faint" style={{ fontSize: 11.5 }}>Konten werden nie gelöscht, nur deaktiviert. Letzte Anmeldungen stehen im Audit-Protokoll.</div>
          <div className="row" style={{ gap: 4 }}>
            <input className="input" style={{ width: 110 }} placeholder="Name" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
            <input className="input grow" type="password" autoComplete="new-password" placeholder="Passwort (≥ 10)" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            <select className="input" value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}><option value="leser">lesen</option><option value="admin">Admin</option></select>
            <button className="btn sm" onClick={() => run(async () => { await post("/api/auth/users", nu); setNu({ username: "", password: "", role: "leser" }); }, "Konto angelegt")}><Plus size={13} /></button>
          </div>
        </div>
        <div className="col" style={{ gap: 8 }}>
          <h3 style={{ margin: 0 }}><KeyRound size={14} style={{ verticalAlign: -2 }} /> API-Key für Agenten</h3>
          <div className="faint" style={{ fontSize: 12 }}>Agenten auf den anderen Computern melden sich mit diesem Schlüssel an. Wer ihn kennt, hat vollen Zugriff – nur in die Agent-Einrichtung kopieren.</div>
          {d.api_key ? (
            <div className="row" style={{ gap: 6 }}>
              <div className="code grow" style={{ fontSize: 11, wordBreak: "break-all", whiteSpace: "pre-wrap" }}>{showKey ? d.api_key : "•".repeat(24)}</div>
              <button className="btn sm" onClick={() => setShowKey(!showKey)}>{showKey ? "Verbergen" : "Zeigen"}</button>
              <button className="btn icon sm" title="Kopieren" onClick={() => { navigator.clipboard?.writeText(d.api_key!); toast("Kopiert"); }}><Copy size={13} /></button>
            </div>
          ) : <div className="callout warn" style={{ fontSize: 12 }}>Noch kein API-Key – Agenten aus dem Netzwerk werden abgewiesen.</div>}
          <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => { if (!d.api_key || window.confirm("Neuen Schlüssel erzeugen? Der bisherige wird ungültig – alle Agenten brauchen dann den neuen.")) run(() => post("/api/auth/api-key"), "Neuer API-Key erzeugt"); }}>
            <RefreshCw size={13} /> {d.api_key ? "Neu erzeugen" : "API-Key erzeugen"}
          </button>
        </div>
        <div className="col" style={{ gap: 8 }}>
          <h3 style={{ margin: 0 }}><Lock size={14} style={{ verticalAlign: -2 }} /> HTTPS (verschlüsselt)</h3>
          <div style={{ fontSize: 12.5 }}>Status: {d.tls.aktiv ? <span className="badge ok">eingeschaltet</span> : <span className="badge warn">aus</span>}
            {location.protocol === "https:" && <span className="badge ok" style={{ marginLeft: 6 }}>diese Verbindung verschlüsselt</span>}</div>
          {d.tls.fingerprint && <>
            <div className="faint" style={{ fontSize: 12 }}>CA-Fingerabdruck – für die Agent-Einrichtung (<span className="mono">--fingerprint</span>) und zum Abgleich:</div>
            <div className="code" style={{ fontSize: 10.5, wordBreak: "break-all", whiteSpace: "pre-wrap" }}>{d.tls.fingerprint}</div>
            <div className="faint" style={{ fontSize: 11.5 }}>Gültig für: {d.tls.namen?.join(", ")} · bis {fmtDate(d.tls.gueltig_bis)}</div>
          </>}
          {!d.tls.aktiv ? (
            <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => run(() => post("/api/auth/tls"), "HTTPS vorbereitet – wirkt nach dem Neustart des Servers")}><Lock size={13} /> HTTPS einschalten</button>
          ) : !location.protocol.startsWith("https") && <div className="callout warn" style={{ fontSize: 12 }}><span>Eingeschaltet – wirkt nach dem Neustart des Servers. Danach <span className="mono">https://…:8800</span> öffnen.</span></div>}
          <div className="faint" style={{ fontSize: 11.5 }}>Eigenes Zertifikat für dieses Netzwerk: Der Browser warnt einmalig. Agenten prüfen den Server über den Fingerabdruck.</div>
        </div>
      </div>
    </div>
  );
}
