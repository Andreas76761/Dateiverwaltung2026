import type { Group } from "./types";

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toLocaleString("de-DE", { maximumFractionDigits: v < 10 && i ? 1 : 0 })} ${u[i]}`;
}

export function fmtNum(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("de-DE");
}

export function fmtDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return withTime
    ? d.toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" })
    : d.toLocaleDateString("de-DE", { year: "numeric", month: "2-digit", day: "2-digit" });
}

export const GROUPS: Group[] = ["Privat", "Beruf", "GenAI", "Sonstiges"];

export const groupClass = (g: string | null | undefined) =>
  g === "Privat" ? "g-privat" : g === "Beruf" ? "g-beruf" : g === "GenAI" ? "g-genai" : "g-sonst";

export function impClass(v: number) {
  return v >= 60 ? "imp-high" : v >= 35 ? "imp-mid" : "imp-low";
}

export const JOB_LABEL: Record<string, string> = {
  scan: "1 · Einlesen",
  analyze: "2 · Analyse",
  propose: "3 · Vorschlag",
  copy: "4 · Kopieren",
  inventory: "Inventar",
};

/** Langen Pfad auf die letzten Segmente kürzen: "…/Ordner/Unterordner/Datei.pdf" */
export function shortPath(p: string | null | undefined, keep = 3, dropFile = false): string {
  if (!p) return "";
  const parts = p.split(/[\\/]/).filter(Boolean);
  if (dropFile) parts.pop();
  return (parts.length > keep ? "…/" : "") + parts.slice(-keep).join("/");
}

/** Pfad relativ zu einem Wurzelordner anzeigen */
export function relTo(p: string, root: string): string {
  return p.startsWith(root) ? p.slice(root.length).replace(/^[\\/]/, "") : p;
}

/** Kurzes Seiten-Label für Miniaturen: "Anhang: rechnung.pdf · S. 2" → "📎 2", "E-Mail · S. 1" → "✉ 1", Video "1:23" bleibt */
export function shortLabel(label: string | null | undefined, page?: number): string {
  if (!label) return page ? String(page) : "";
  const pg = label.match(/S\. (\d+)$/)?.[1];
  if (label.startsWith("Anhang")) return `📎${pg ? " " + pg : ""}`;
  if (label.startsWith("E-Mail")) return `✉${pg ? " " + pg : ""}`;
  return label;
}
