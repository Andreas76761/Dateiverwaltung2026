// Kleiner API-Client für das FastAPI-Backend
const KEY_STORAGE = "fdv-api-key";

export function apiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setApiKey(k: string) {
  try {
    localStorage.setItem(KEY_STORAGE, k);
  } catch {
    /* ignore */
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const k = apiKey();
  if (k) headers["X-API-Key"] = k;
  const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return res.json();
}

export const get = <T,>(path: string) => request<T>("GET", path);
export const post = <T,>(path: string, body: unknown = {}) => request<T>("POST", path, body);

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function thumbUrl(fileId: number, page: number) {
  const k = apiKey();
  return `/api/files/${fileId}/thumb/${page}${k ? `?key=${encodeURIComponent(k)}` : ""}`;
}

export function rawUrl(fileId: number) {
  const k = apiKey();
  return `/api/files/${fileId}/raw${k ? `?key=${encodeURIComponent(k)}` : ""}`;
}
