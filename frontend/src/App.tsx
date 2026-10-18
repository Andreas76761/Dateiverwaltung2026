import { useEffect, useState } from "react";
import { Boxes, CloudUpload, Copy, FolderKanban, FolderTree, HardDrive, LayoutDashboard, Loader2, Moon, Settings as Cog, ShieldCheck, Sun } from "lucide-react";
import { JobsProvider, ToastProvider, useJobs } from "./components/ui";
import CopyPage from "./pages/CopyPage";
import Dashboard from "./pages/Dashboard";
import Explorer from "./pages/Explorer";
import Programs from "./pages/Programs";
import Proposal from "./pages/Proposal";
import Settings from "./pages/Settings";
import Sources from "./pages/Sources";
import { JOB_LABEL } from "./util";

const NAV = [
  { sec: "Dateien" },
  { id: "dashboard", label: "Übersicht", icon: LayoutDashboard },
  { id: "explorer", label: "Explorer", icon: FolderKanban },
  { id: "explorer?dup=ja", label: "Duplikate", icon: Copy },
  { sec: "Neuordnung" },
  { id: "proposal", label: "Vorschlag & Prüfung", icon: FolderTree, step: 3 },
  { id: "copy", label: "Kopieren & Statistik", icon: CloudUpload, step: 4 },
  { sec: "System" },
  { id: "sources", label: "Quellen & Agenten", icon: HardDrive },
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

function Shell() {
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

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <div className="brand-logo"><FolderTree size={19} /></div>
          <div><div className="brand-name">Future</div><div className="brand-sub">Dateiverwaltung</div></div>
        </div>
        <nav className="nav">
          {NAV.map((n, i) =>
            "sec" in n ? <div key={i} className="nav-sec">{n.sec}</div> : (
              <a key={n.id} className={route.raw === n.id || (route.page === n.id && !(n.id === "explorer" && route.params.get("dup"))) ? "active" : ""} onClick={() => go(n.id)}>
                <n.icon size={17} /> {n.label}
                {"step" in n && <span className="step">{n.step}</span>}
              </a>
            ),
          )}
        </nav>
        <div className="side-foot">
          <div className="safe-pill"><ShieldCheck size={15} /> Löschschutz aktiv</div>
          4 Computer · 6 Festplatten · Cloud<br />v1.0
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <b style={{ fontSize: 15 }}>{NAV.find((n) => "id" in n && (n.id === route.raw || n.id === route.page)) && (NAV.find((n) => "id" in n && (n.id === route.raw || n.id === route.page)) as any).label}</b>
          <span className="spacer" />
          <JobIndicator />
          <button className="btn ghost icon" title="Hell/Dunkel" onClick={() => setTheme(dark ? "light" : "dark")}>{dark ? <Sun size={17} /> : <Moon size={17} />}</button>
        </header>
        <div className={`content ${flush ? "flush" : ""}`}>
          {route.page === "dashboard" && <Dashboard go={go} />}
          {route.page === "explorer" && <Explorer key={route.raw} params={route.params} />}
          {route.page === "proposal" && <Proposal />}
          {route.page === "copy" && <CopyPage go={go} />}
          {route.page === "sources" && <Sources />}
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
      <JobsProvider>
        <Shell />
      </JobsProvider>
    </ToastProvider>
  );
}
