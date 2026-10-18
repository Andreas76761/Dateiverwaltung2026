export type Group = "Privat" | "Beruf" | "GenAI" | "Sonstiges";

export interface FileItem {
  id: number;
  computer_id: string;
  volume_id: string;
  path: string;
  rel_path: string;
  name: string;
  ext: string;
  file_type: string;
  size: number;
  mtime: string;
  ctime: string;
  page_count: number | null;
  summary: string | null;
  category: string | null;
  group_name: Group | null;
  confidence: number | null;
  importance: number;
  suggested_path: string | null;
  final_path: string | null;
  review_status: "offen" | "freigegeben" | "abgelehnt";
  dup_count: number;
  is_primary: number;
  status: string;
  pinned: number;
  missing: number;
  labels: string[];
  thumbs: number;
  thumbs_complete: number;  // 0 = bisher nur Deckblatt im Cache
  online_only: number;      // Cloud-Platzhalter: Inhalt liegt nur online
  web_url?: string | null;  // Cloud-Schnittstelle: Link zum Öffnen in OneDrive/Google Drive
  thumb_labels: string[]; // Video-Zeitpunkte bzw. "E-Mail · S. 1" / "Anhang: …"
  sim_group: number | null; // Ähnlichkeitsgruppe (Fotos, Versionen, Formate, Inhalt)
  sim_count: number;
  sim_kind: SimKind | null;
  sim_best: number;         // 1 = Empfehlung (neueste Version / bestes Foto), 2 = gleicher Inhalt in anderem Format
  computer_name: string;
  volume_name: string;
  volume_kind: string;
}

export interface FileDetail extends FileItem {
  text_excerpt: string | null;
  ocr_text: string | null;
  importance_reason: string | null;
  sha256: string | null;
  error: string | null;
  llm_provider: string | null;
  analyzed_at: string | null;
  scanned_at: string | null;
  mime: string;
  label_details: { label: string; source: string }[];
  thumbnails: { page: number; width: number; height: number; label: string | null }[];
  duplicates: { id: number; path: string; computer_name: string; volume_name: string; mtime: string; is_primary: number }[];
  copies: CopyOp[];
  target_root: string;
  similar: SimilarFile[];
}

export type SimKind = "Versionen" | "Formate" | "Inhalt" | "Fotos";

export interface SimilarFile {
  id: number;
  name: string;
  path: string;
  ext: string;
  file_type: string;
  size: number;
  mtime: string;
  computer_id: string;
  computer_name: string;
  volume_name: string;
  category: string | null;
  group_name: Group | null;
  importance: number;
  sim_group: number;
  sim_kind: SimKind;
  sim_best: number;
  online_only: number;
  review_status: string;
  thumbs: number;
  pair_kind?: string | null;
  pair_text?: string;
  score?: number | null;
}

export interface SimGroup {
  id: number;
  kind: SimKind;
  n: number;
  bytes: number;
  other_bytes: number;
  importance: number;
  score_min: number | null;
  score_max: number | null;
  members: SimilarFile[];
}

export interface FileList {
  total: number;
  bytes: number;
  page: number;
  limit: number;
  items: FileItem[];
}

export interface Job {
  id: number;
  kind: "scan" | "analyze" | "propose" | "copy" | "inventory" | "similar";
  status: "wartend" | "läuft" | "fertig" | "fehler" | "abgebrochen";
  progress: number;
  total: number;
  message: string | null;
  stats: Record<string, any>;
  params: Record<string, any>;
  created_at: string;
  finished_at: string | null;
}

export interface CopyOp {
  id: number;
  job_id: number;
  file_id: number;
  src: string;
  dst: string;
  status: string;
  bytes: number;
  verified: number;
  message: string;
  done_at: string | null;
  name?: string;
  group_name?: string;
  category?: string;
}

export interface TreeNode {
  name: string;
  path: string;
  count: number;
  size: number;
  approved: number;
  rejected: number;
  children: TreeNode[];
}

export interface Volume {
  id: string;
  computer_id: string;
  name: string;
  path: string;
  kind: string;
  total_bytes: number | null;
  free_bytes: number | null;
  last_scan: string | null;
  files: number;
  bytes: number;
  analyzed: number;
  reachable: boolean;
}

export interface Computer {
  id: string;
  name: string;
  os: string;
  hostname: string | null;
  mode: string;
  last_seen: string | null;
  agent_version: string | null;
  volumes: Volume[];
}
