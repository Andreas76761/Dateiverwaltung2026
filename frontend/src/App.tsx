import { useEffect, useState } from "react";
import { Boxes, CalendarClock, CloudUpload, Copy, FolderKanban, FolderTree, HardDrive, Layers, LayoutDashboard, Loader2, Moon, PanelLeftClose, PanelLeftOpen, Settings as Cog, ShieldCheck, Sun, Wand2 } from "lucide-react";
import { AuthGate, UserMenu, type AuthStatus } from "./components/Auth";
import { JobsProvider, ToastProvider, useJobs } from "./components/ui";
import Automation from "./pages/Automation";
import CopyPage from "./pages/CopyPage";
import Dashboard from "./pages/Dashboard";
import Explorer from "./pages/Explorer";
import Programs from "./pages/Programs";
import Proposal from "./pages/Proposal";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";
import Similar from "./pages/Similar";
import Sources from "./pages/Sources";
import { JOB_LABEL } from "./util";

const NAV = [
  { sec: "Dateien" },
  { id: "dashboard", label: "Übersicht", icon: LayoutDashboard },
  { id: "explorer", label: "Explorer", icon: FolderKanban },
  { id: "explorer?dup=ja", label: "Duplikate", icon: Copy },
  { id: "similar", label: "Ähnliche Dateien", icon: Layers },
  { sec: "Neuordnung" },
  { id: "proposal", label: "Vorschlag & Prüfung", icon: FolderTree, step: 3 },
  { id: "copy", label: "Kopieren & Statistik", icon: CloudUpload, step: 4 },
  { sec: "System" },
  { id: "setup", label: "Einrichtung", icon: Wand2 },
  { id: "sources", label: "Quellen & Agenten", icon: HardDrive },
  { id: "automation", label: "Automatik", icon: CalendarClock },
  { id: "programs", label: "Programme & LLMs", icon: Boxes },
  { id: "settings", label: "Einstellungen", icon: Cog },
] as const;

function parseHash() {
  const h = window.location.hash.replace(/^#\/?/, "") || "dashboard";
  const [page, query = ""] = h.split("?");
  return { page, params: new URLSearchParams(query), raw: h };
}

function JobIndicator() {
  const { running } = useJobs();
  if (!running.length) return null;
  const j = running[0];
  return (
    <div className="jobpill">
      <Loader2 size={13} className="spin" />
      {JOB_LABEL[j.kind]} · {j.total ? `${j.progress}/${j.total}` : j.message}
    </div>
  );
}

function Shell({ auth, reloadAuth }: { auth: AuthStatus; reloadAuth: () => void }) {
  const [route, setRoute] = useState(parseHash());
  const [theme, setTheme] = useState<string>(() => {
    try { return localStorage.getItem("fdv-theme") || ""; } catch { return ""; }
  });
  useEffect(() => {
    const h = () => setRoute(parseHash());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("fdv-theme", theme); } catch { /* ignore */ }
  }, [theme]);
  const go = (p: string) => { window.location.hash = `/${p}`; };
  const dark = theme === "dark" || (!theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const flush = ["explorer", "proposal"].includes(route.page);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem("fdv-nav-collapsed") === "1"; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem("fdv-nav-collapsed", collapsed ? "1" : "0"); } catch { /* ignore */ }
  }, [collapsed]);
  // Tastenkürzel: Strg/Cmd + B klappt die Navigation ein/aus
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setCollapsed((c) => !c);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  return (
    <div className={`app ${collapsed ? "collapsed" : ""}`}>
      <aside className="side">
        <div className="brand">
          <div className="brand-logo"><FolderTree size={19} /></div>
          <div className="brand-text"><div className="brand-name">Future</div><div className="brand-sub">Dateiverwaltung</div></div>
        </div>
        <nav className="nav">
          {NAV.map((n, i) =>
            "sec" in n ? <div key={i} className="nav-sec">{n.sec}</div> : (
              <a key={n.id} className={route.raw === n.id || (route.page === n.id && !(n.id === "explorer" && route.params.get("dup"))) ? "active" : ""} onClick={() => go(n.id)} title={collapsed ? n.label : undefined}>
                <n.icon size={17} className="nav-icon" /> <span className="nav-label">{n.label}</span>
                {"step" in n && <span className="step">{n.step}</span>}
              </a>
            ),
          )}
        </nav>
        <div className="side-foot">
          <div className="safe-pill" title="Löschschutz aktiv"><ShieldCheck size={15} /> <span className="nav-label">Löschschutz aktiv</span></div>
          <span className="nav-label">4 Computer · 6 Festplatten · Cloud<br />v1.0</span>
          <button className="collapse-btn" onClick={() => setCollapsed(!collapsed)} title={collapsed ? "Navigation ausklappen (Strg+B)" : "Navigation einklappen (Strg+B)"}>
            {collapsed ? <PanelLeftOpen size={17} /> : <><PanelLeftClose size={17} /> <span className="nav-label">Einklappen</span></>}
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <button className="btn ghost icon" onClick={() => setCollapsed(!collapsed)} title={collapsed ? "Navigation ausklappen (Strg+B)" : "Navigation einklappen (Strg+B)"}>
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
          <b style={{ fontSize: 15 }}>{NAV.find((n) => "id" in n && (n.id === route.raw || n.id === route.page)) && (NAV.find((n) => "id" in n && (n.id === route.raw || n.id === route.page)) as any).label}</b>
          <span className="spacer" />
          <JobIndicator />
          <UserMenu st={auth} reload={reloadAuth} />
          <button className="btn ghost icon" title="Hell/Dunkel" onClick={() => setTheme(dark ? "light" : "dark")}>{dark ? <Sun size={17} /> : <Moon size={17} />}</button>
        </header>
        <div className={`content ${flush ? "flush" : ""}`}>
          {route.page === "dashboard" && <Dashboard go={go} />}
          {route.page === "explorer" && <Explorer key={route.raw} params={route.params} />}
          {route.page === "similar" && <Similar key={route.raw} params={route.params} />}
          {route.page === "proposal" && <Proposal />}
          {route.page === "copy" && <CopyPage go={go} />}
          {route.page === "setup" && <Setup key={route.raw} params={route.params} />}
          {route.page === "sources" && <Sources />}
          {route.page === "automation" && <Automation />}
          {route.page === "programs" && <Programs />}
          {route.page === "settings" && <Settings />}
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AuthGate>
        {(st, reload) => (
          <JobsProvider>
            <Shell auth={st} reloadAuth={reload} />
          </JobsProvider>
        )}
      </AuthGate>
    </ToastProvider>
  );
}
