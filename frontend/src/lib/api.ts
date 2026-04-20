const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

// --- Photos ---
export interface Photo {
  id: number;
  filename: string;
  file_path: string;
  taken_at: string | null;
  width: number | null;
  height: number | null;
  processed: boolean;
  milestone_count: number;
  thumbnail_url: string | null;
}

export function scanDirectory(
  directory: string,
  minConfidence = 0.5,
  startDate?: string,
  endDate?: string,
  usePrefilter = true,
) {
  return request<{ session_id: string; message: string }>("/photos/scan", {
    method: "POST",
    body: JSON.stringify({
      directory,
      min_confidence: minConfidence,
      start_date: startDate || null,
      end_date: endDate || null,
      use_prefilter: usePrefilter,
    }),
  });
}

export function getScanStatus(sessionId: string) {
  return request<{
    status: string;
    scanned: number;
    total: number;
    detected: number;
    current_file?: string;
    milestone_count?: number;
    error?: string;
  }>(`/photos/scan/${sessionId}`);
}

export type ScanJobState = {
  status: string;
  scanned: number;
  total: number;
  detected: number;
  current_file?: string;
  milestone_count?: number;
  date_filtered?: number;
  prefilter_total?: number;
  prefilter_checked?: number;
  prefilter_passed?: number;
  cloud_skipped?: number;
  error?: string;
};

/**
 * Open an SSE stream for real-time scan progress.
 * Returns a cleanup function — call it to close the connection.
 */
export function openScanStream(
  sessionId: string,
  onUpdate: (state: ScanJobState) => void,
  onDone: () => void,
): () => void {
  const es = new EventSource(`${BASE}/photos/scan/${sessionId}/stream`);

  es.onmessage = (e) => {
    try {
      const data: ScanJobState = JSON.parse(e.data);
      onUpdate(data);
      if (data.status === "complete" || data.status === "error") {
        es.close();
        onDone();
      }
    } catch {}
  };

  es.onerror = () => {
    es.close();
    onDone();
  };

  return () => es.close();
}

export function listPhotos() {
  return request<Photo[]>("/photos");
}

// --- Milestones ---
export interface Milestone {
  id: number;
  photo_id: number;
  child_id: number | null;
  milestone_type: string;
  label: string;
  description: string | null;
  confidence: number;
  approximate_age: string | null;
  approved: boolean | null;
  photo_filename: string | null;
  photo_taken_at: string | null;
  thumbnail_url: string | null;
  evidence: string[] | null;
}

export function getPendingMilestones(limit = 50) {
  return request<Milestone[]>(`/milestones/pending?limit=${limit}`);
}

export function listMilestones(approvedOnly = false) {
  return request<Milestone[]>(`/milestones?approved_only=${approvedOnly}`);
}

export function reviewMilestone(id: number, approved: boolean, childId?: number) {
  return request<Milestone>(`/milestones/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ approved, child_id: childId ?? null }),
  });
}

export function deleteMilestone(id: number) {
  return fetch(`${BASE}/milestones/${id}`, { method: "DELETE" });
}

// --- Timeline ---
export interface TimelineItem {
  milestone_id: number;
  photo_id: number;
  milestone_type: string;
  label: string;
  description: string | null;
  confidence: number;
  approximate_age: string | null;
  taken_at: string | null;
  child_name: string | null;
  thumbnail_url: string | null;
}

export function rescanLowConfidence(maxConfidence = 0.75, limit = 50) {
  return request<{ message: string }>("/milestones/rescan", {
    method: "POST",
    body: JSON.stringify({ max_confidence: maxConfidence, limit }),
  });
}

export interface UploadResult {
  photo_id: number;
  filename: string;
  taken_at: string | null;
  thumbnail_url: string | null;
  milestone_id: number | null;
  detection: {
    has_milestone: boolean;
    milestone_type: string | null;
    label: string;
    description: string | null;
    confidence: number;
    approximate_age: string | null;
    evidence: string[];
  } | null;
}

export function uploadPhoto(file: File, minConfidence = 0.5): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("min_confidence", String(minConfidence));
  return fetch(`${BASE}/photos/upload`, { method: "POST", body: form }).then(
    async (res) => {
      if (!res.ok) throw new Error(`Upload failed: ${await res.text()}`);
      return res.json();
    }
  );
}

export function updateMilestoneLabel(id: number, label: string) {
  return request<Milestone>(`/milestones/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ approved: true, label }),
  });
}

export function getTimeline(approvedOnly = true, childId?: number) {
  const params = new URLSearchParams({ approved_only: String(approvedOnly) });
  if (childId != null) params.set("child_id", String(childId));
  return request<TimelineItem[]>(`/timeline?${params}`);
}

export function getStats() {
  return request<{
    total_photos: number;
    total_milestones: number;
    pending_review: number;
    approved: number;
    rejected: number;
  }>("/timeline/stats");
}

// --- Children ---
export interface Child {
  id: number;
  name: string;
  birth_date: string | null;
}

export function listChildren() {
  return request<Child[]>("/children");
}

export function createChild(name: string, birthDate?: string) {
  return request<Child>("/children", {
    method: "POST",
    body: JSON.stringify({ name, birth_date: birthDate ?? null }),
  });
}
