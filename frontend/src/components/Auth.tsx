import { useCallback, useEffect, useState, type ReactNode } from "react";
import { FolderTree, KeyRound, Loader2, LogIn, LogOut, ShieldCheck, UserRound } from "lucide-react";
import { get, post } from "../api";
import { Modal, useToast } from "./ui";

export interface AuthStatus {
  mode: string; required: boolean; user: { username: string; role: string } | null; users_exist: boolean;
  can_bootstrap: boolean; local: boolean; https: boolean;
}

/** Anmeldeseite bzw. „Erstes Konto anlegen“ – nur auf dem Server-Computer möglich. */
function LoginScreen({ st, onDone }: { st: AuthStatus; onDone: () => void }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [p2, setP2] = useState("");
  const [remember, setRemember] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const boot = st.can_bootstrap;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    if (boot && p !== p2) { setErr("Die Passwörter stimmen nicht überein"); return; }
    setBusy(true);
    try {
      await post(boot ? "/api/auth/bootstrap" : "/api/auth/login", boot ? { username: u, password: p } : { username: u, password: p, remember });
      onDone();
    } catch (ex: any) { setErr(ex.message); } finally { setBusy(false); }
  };
  return (
    <div className="login-wrap">
      <form className="card card-pad login-card col" onSubmit={submit}>
        <div className="row" style={{ gap: 10 }}>
          <div className="brand-logo"><FolderTree size={19} /></div>
          <div><div style={{ fontWeight: 750, fontSize: 17 }}>Future Dateiverwaltung</div>
            <div className="faint" style={{ fontSize: 12.5 }}>{boot ? "Erstes Konto anlegen (Admin)" : "Anmelden"}</div></div>
        </div>
        {!st.users_exist && !st.local && (
          <div className="callout warn" style={{ fontSize: 12.5 }}>Es gibt noch kein Konto. Das erste Konto lässt sich nur direkt auf dem Server-Computer anlegen: dort <span className="mono">http://localhost:8800</span> öffnen.</div>
        )}
        <label className="col" style={{ gap: 4, fontSize: 12.5 }}>Benutzername
          <input className="input" autoFocus autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} />
        </label>
        <label className="col" style={{ gap: 4, fontSize: 12.5 }}>Passwort {boot && <span className="faint">(mind. 10 Zeichen)</span>}
          <input className="input" type="password" autoComplete={boot ? "new-password" : "current-password"} value={p} onChange={(e) => setP(e.target.value)} />
        </label>
        {boot && <label className="col" style={{ gap: 4, fontSize: 12.5 }}>Passwort wiederholen
          <input className="input" type="password" autoComplete="new-password" value={p2} onChange={(e) => setP2(e.target.value)} />
        </label>}
        {!boot && <label className="switch" style={{ fontSize: 12.5 }}><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Angemeldet bleiben (30 Tage)</label>}
        {err && <div className="callout warn" style={{ fontSize: 12.5 }}>{err}</div>}
        <button className="btn primary" disabled={busy || !u || !p || (!st.users_exist && !st.local)}>{busy ? <Loader2 size={14} className="spin" /> : <LogIn size={14} />} {boot ? "Konto anlegen und anmelden" : "Anmelden"}</button>
        <div className="faint row" style={{ fontSize: 11.5, gap: 6 }}><ShieldCheck size={13} /> {st.https ? "Verbindung verschlüsselt (HTTPS)" : "Unverschlüsselte Verbindung – im Netzwerk HTTPS einschalten (Einstellungen → Zugang)"}</div>
      </form>
    </div>
  );
}

/** Zeigt die App erst nach erfolgreicher Anmeldung (wenn nötig). */
export function AuthGate({ children }: { children: (st: AuthStatus, reload: () => void) => ReactNode }) {
  const [st, setSt] = useState<AuthStatus | null>(null);
  const load = useCallback(() => { get<AuthStatus>("/api/auth/status").then(setSt).catch(() => setSt(null)); }, []);
  useEffect(() => {
    load();
    const h = () => load();
    window.addEventListener("fdv-login-required", h);
    return () => window.removeEventListener("fdv-login-required", h);
  }, [load]);
  if (!st) return <div className="login-wrap"><Loader2 className="spin" /></div>;
  if (st.required && !st.user) return <LoginScreen st={st} onDone={load} />;
  return <>{children(st, load)}</>;
}

/** Benutzer oben rechts: Rolle, Passwort ändern, Abmelden – oder Hinweis, dass der Zugang offen ist. */
export function UserMenu({ st, reload }: { st: AuthStatus; reload: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState<{ old: string; neu: string } | null>(null);
  if (!st.user) {
    return st.mode === "aus" ? null : (
      <a className="badge warn" href="#/settings?zugang=1" title="Ohne Konto ist die App nur auf diesem Computer erreichbar">
        <KeyRound size={11} /> <span className="hide-sm">Kein Konto – nur lokal</span>
      </a>
    );
  }
  const logout = async () => { await post("/api/auth/logout"); reload(); };
  const change = async () => {
    try { await post("/api/auth/password", { old: pw!.old, new: pw!.neu }); toast("Passwort geändert – bitte neu anmelden"); setPw(null); reload(); }
    catch (e: any) { toast(e.message, true); }
  };
  return (
    <div className="menu-wrap">
      <button className="btn ghost sm" onClick={() => setOpen(!open)}><UserRound size={15} /> {st.user.username}{st.user.role === "leser" && <span className="badge outline" style={{ fontSize: 10 }}>nur lesen</span>}</button>
      {open && (
        <div className="menu" onMouseLeave={() => setOpen(false)}>
          <a onClick={() => { setPw({ old: "", neu: "" }); setOpen(false); }}><KeyRound size={14} /> Passwort ändern</a>
          <a onClick={logout}><LogOut size={14} /> Abmelden</a>
        </div>
      )}
      {pw && (
        <Modal title="Passwort ändern" onClose={() => setPw(null)} actions={<><button className="btn" onClick={() => setPw(null)}>Abbrechen</button><button className="btn primary" onClick={change}>Ändern</button></>}>
          <div className="col" style={{ gap: 8 }}>
            <input className="input" type="password" placeholder="Bisheriges Passwort" autoComplete="current-password" value={pw.old} onChange={(e) => setPw({ ...pw, old: e.target.value })} />
            <input className="input" type="password" placeholder="Neues Passwort (mind. 10 Zeichen)" autoComplete="new-password" value={pw.neu} onChange={(e) => setPw({ ...pw, neu: e.target.value })} />
          </div>
        </Modal>
      )}
    </div>
  );
}
