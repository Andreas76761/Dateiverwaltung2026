import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, X } from "lucide-react";
import { get, thumbUrl } from "../api";
import type { Job } from "../types";
import { groupClass, impClass } from "../util";

const TYPE_COLORS: Record<string, [string, string]> = {
  PDF: ["#dc2626", "PDF"],
  "Präsentation": ["#ea580c", "PPT"],
  Textdokument: ["#2563eb", "DOC"],
  Tabelle: ["#16a34a", "XLS"],
  "Text & Notizen": ["#64748b", "TXT"],
  Bild: ["#db2777", "IMG"],
  Video: ["#9333ea", "VID"],
  Audio: ["#0891b2", "AUD"],
  "E-Mail": ["#0ea5e9", "MAIL"],
  Quellcode: ["#334155", "</>"],
  "Daten & Konfiguration": ["#475569", "{ }"],
  "KI-Modell": ["#7c3aed", "AI"],
  Archiv: ["#a16207", "ZIP"],
  Programm: ["#1f2937", "EXE"],
  "E-Book": ["#0f766e", "BOOK"],
};

export function FileIcon({ type, ext }: { type: string; ext?: string }) {
  const [color, label] = TYPE_COLORS[type] ?? ["#94a3b8", (ext || "?").replace(".", "").slice(0, 4).toUpperCase()];
  return (
    <div className="ficon" style={{ background: color }} title={type}>
      {label}
    </div>
  );
}

export function FileThumbOrIcon({ id, thumbs, type, ext }: { id: number; thumbs: number; type: string; ext: string }) {
  if (thumbs > 0) return <img className="mini-thumb" src={thumbUrl(id, 1)} loading="lazy" alt="" />;
  return <FileIcon type={type} ext={ext} />;
}

export function GroupBadge({ group }: { group: string | null }) {
  if (!group) return <span className="badge outline">nicht analysiert</span>;
  return (
    <span className={`badge ${groupClass(group)}`}>
      <span className={`dot ${groupClass(group)}`} />
      {group}
    </span>
  );
}

export function Importance({ value }: { value: number }) {
  return (
    <div className={`imp ${impClass(value)}`} title={`Wichtigkeit ${value}/100`}>
      <div className="imp-bar">
        <div style={{ width: `${value}%` }} />
      </div>
      <span className="imp-num">{value}</span>
    </div>
  );
}

export function Labels({ labels, max = 4, nowrap = false }: { labels: string[]; max?: number; nowrap?: boolean }) {
  const shown = labels.filter((l) => !/^\d{4}$/.test(l)).slice(0, max);
  const rest = labels.length - shown.length - labels.filter((l) => /^\d{4}$/.test(l)).length;
  return (
    <div className={`row ${nowrap ? "" : "wrap"}`} style={{ gap: 4, overflow: "hidden" }}>
      {shown.map((l) => (
        <span key={l} className="label-chip">
          {l}
        </span>
      ))}
      {rest > 0 && <span className="faint" style={{ fontSize: 11 }}>+{rest}</span>}
    </div>
  );
}

export function ReviewBadge({ status }: { status: string }) {
  if (status === "freigegeben") return <span className="badge ok">freigegeben</span>;
  if (status === "abgelehnt") return <span className="badge bad">abgelehnt</span>;
  return <span className="badge outline">offen</span>;
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon}
      <div style={{ fontWeight: 650, color: "var(--text)" }}>{title}</div>
      {children && <div style={{ maxWidth: 460 }}>{children}</div>}
    </div>
  );
}

export function Modal({ onClose, title, children, actions }: { onClose: () => void; title: ReactNode; children: ReactNode; actions?: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <div className="grow ellipsis" style={{ fontWeight: 650 }}>{title}</div>
          {actions}
          <button className="btn ghost icon" onClick={onClose} aria-label="Schließen">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function PageViewer({ fileId, name, pages, start, onClose }: { fileId: number; name: string; pages: number; start: number; onClose: () => void }) {
  const [p, setP] = useState(start);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") setP((x) => Math.min(pages, x + 1));
      if (e.key === "ArrowLeft") setP((x) => Math.max(1, x - 1));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [pages]);
  return (
    <Modal
      onClose={onClose}
      title={name}
      actions={
        <div className="row">
          <button className="btn sm" disabled={p <= 1} onClick={() => setP(p - 1)}><ChevronLeft size={15} /></button>
          <span className="muted nowrap" style={{ fontSize: 12.5 }}>Seite {p} / {pages}</span>
          <button className="btn sm" disabled={p >= pages} onClick={() => setP(p + 1)}><ChevronRight size={15} /></button>
        </div>
      }
    >
      <img className="viewer-img" src={thumbUrl(fileId, p)} alt={`Seite ${p}`} />
    </Modal>
  );
}

/* ---------- Toasts ---------- */
type ToastT = { msg: string; err?: boolean } | null;
const ToastCtx = createContext<(msg: string, err?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [t, setT] = useState<ToastT>(null);
  const timer = useRef<number>();
  const show = useCallback((msg: string, err = false) => {
    setT({ msg, err });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setT(null), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {t && (
        <div className={`toast ${t.err ? "err" : ""}`}>
          {t.err ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
          <span>{t.msg}</span>
        </div>
      )}
    </ToastCtx.Provider>
  );
}

/* ---------- Jobs ---------- */
const JobsCtx = createContext<{ jobs: Job[]; refresh: () => void; running: Job[]; version: number }>({
  jobs: [], refresh: () => {}, running: [], version: 0,
});
export const useJobs = () => useContext(JobsCtx);

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [version, setVersion] = useState(0);
  const prevRunning = useRef<number>(0);
  const refresh = useCallback(() => {
    get<Job[]>("/api/jobs?limit=40").then((j) => {
      setJobs(j);
      const n = j.filter((x) => x.status === "läuft").length;
      if (n < prevRunning.current) setVersion((v) => v + 1); // ein Job wurde fertig → Daten neu laden
      prevRunning.current = n;
    }).catch(() => {});
  }, []);
  const running = jobs.filter((j) => j.status === "läuft");
  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, running.length ? 1200 : 5000);
    return () => window.clearInterval(id);
  }, [refresh, running.length]);
  return <JobsCtx.Provider value={{ jobs, refresh, running, version }}>{children}</JobsCtx.Provider>;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | undefined; loading: boolean; error: string | null; reload: () => void } {
  const [data, setData] = useState<T>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(String(e.message || e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, loading, error, reload: () => setTick((t) => t + 1) };
}
