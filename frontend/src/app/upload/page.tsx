"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { scanDirectory, getScanStatus, uploadPhoto, UploadResult } from "@/lib/api";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import clsx from "clsx";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Directory scan tab ────────────────────────────────────────────────────

type ScanPhase = "idle" | "scanning" | "detecting" | "saving" | "complete" | "error";

interface JobStatus {
  status: ScanPhase;
  scanned: number;
  total: number;
  detected: number;
  current_file?: string;
  milestone_count?: number;
  error?: string;
}

function DirectoryScanTab() {
  const [directory, setDirectory] = useState("");
  const [minConfidence, setMinConfidence] = useState(0.6);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const startScan = async () => {
    if (!directory.trim()) return;
    try {
      const res = await scanDirectory(directory.trim(), minConfidence);
      setSessionId(res.session_id);
      setJob({ status: "scanning", scanned: 0, total: 0, detected: 0 });
    } catch (e: any) {
      alert(`Failed to start scan: ${e.message}`);
    }
  };

  useEffect(() => {
    if (!sessionId) return;
    pollRef.current = setInterval(async () => {
      try {
        const status = await getScanStatus(sessionId);
        setJob(status as JobStatus);
        if (status.status === "complete" || status.status === "error") {
          clearInterval(pollRef.current!);
        }
      } catch {}
    }, 1500);
    return () => clearInterval(pollRef.current!);
  }, [sessionId]);

  const phaseLabel: Record<ScanPhase, string> = {
    idle: "",
    scanning: "Reading photos and extracting EXIF data...",
    detecting: "Detecting milestones with Claude Vision...",
    saving: "Saving results...",
    complete: "Scan complete!",
    error: "Scan failed",
  };

  const progress = job && job.total > 0 ? Math.round((job.scanned / job.total) * 100) : 0;
  const scanning = !!sessionId && job?.status !== "complete" && job?.status !== "error";

  return (
    <div className="space-y-5">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Photo directory path
        </label>
        <input
          type="text"
          value={directory}
          onChange={(e) => setDirectory(e.target.value)}
          placeholder="/Users/yourname/Pictures/Baby Photos"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
        />
        <p className="text-xs text-gray-400 mt-1">
          The backend reads this path directly from the server's filesystem.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Minimum confidence:{" "}
          <span className="text-brand-600">{Math.round(minConfidence * 100)}%</span>
        </label>
        <input
          type="range"
          min={0.3}
          max={0.95}
          step={0.05}
          value={minConfidence}
          onChange={(e) => setMinConfidence(Number(e.target.value))}
          className="w-full accent-brand-600"
        />
        <div className="flex justify-between text-xs text-gray-400 mt-0.5">
          <span>More results (30%)</span>
          <span>Higher accuracy (95%)</span>
        </div>
      </div>

      <button
        onClick={startScan}
        disabled={scanning}
        className={clsx(
          "w-full py-3 rounded-xl font-medium text-sm transition",
          scanning
            ? "bg-gray-200 text-gray-400 cursor-not-allowed"
            : "bg-brand-600 text-white hover:bg-brand-700"
        )}
      >
        {scanning ? "Scanning..." : "Start Scan"}
      </button>

      {job && (
        <div className="bg-gray-50 rounded-xl p-4 space-y-3 border border-gray-100">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-700">
              {phaseLabel[job.status] || job.status}
            </span>
            {job.status === "complete" && (
              <span className="text-green-600 font-semibold text-sm">Done</span>
            )}
            {job.status === "error" && (
              <span className="text-red-500 font-semibold text-sm">Error</span>
            )}
          </div>

          {job.total > 0 && (
            <>
              <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-brand-500 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-xs text-gray-400">
                {job.scanned} / {job.total} photos
                {job.current_file && ` · ${job.current_file}`}
              </p>
            </>
          )}

          {job.status === "complete" && (
            <div className="bg-green-50 border border-green-100 rounded-xl p-3 text-sm text-green-700">
              Found <strong>{job.milestone_count ?? job.detected}</strong> milestone
              {(job.milestone_count ?? job.detected) !== 1 ? "s" : ""}!{" "}
              <a href="/milestones" className="underline font-medium">Review them now →</a>
            </div>
          )}
          {job.error && (
            <div className="bg-red-50 border border-red-100 rounded-xl p-3 text-sm text-red-600">
              {job.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Single-photo upload tab ───────────────────────────────────────────────

function SingleUploadTab() {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const processFile = useCallback(async (file: File) => {
    setUploading(true);
    setResult(null);
    setError(null);
    try {
      const res = await uploadPhoto(file, 0.5);
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  }, []);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
  };

  return (
    <div className="space-y-5">
      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={clsx(
          "border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition select-none",
          dragging
            ? "border-brand-500 bg-brand-50"
            : "border-gray-200 hover:border-brand-300 hover:bg-brand-50/50"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={onFileChange}
        />
        <div className="text-4xl mb-3">{uploading ? "⏳" : "📷"}</div>
        <p className="font-medium text-gray-700">
          {uploading ? "Analyzing photo..." : "Drop a photo here, or click to select"}
        </p>
        <p className="text-xs text-gray-400 mt-1">
          JPEG, PNG, HEIC, WebP — Claude Vision will detect milestones instantly
        </p>
      </div>

      {/* Result */}
      {result && (
        <div className="bg-white rounded-2xl border border-brand-100 shadow-sm overflow-hidden">
          <div className="flex">
            {result.thumbnail_url && (
              <div className="w-32 shrink-0">
                <img
                  src={`${API}${result.thumbnail_url}`}
                  alt={result.filename}
                  className="w-full h-full object-cover"
                  style={{ maxHeight: "128px" }}
                />
              </div>
            )}
            <div className="p-4 flex-1 min-w-0">
              <p className="text-xs text-gray-400 truncate mb-2">{result.filename}</p>

              {result.detection ? (
                <>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-gray-800">{result.detection.label}</span>
                    <ConfidenceBadge confidence={result.detection.confidence} />
                  </div>
                  {result.detection.approximate_age && (
                    <p className="text-xs text-gray-400 mt-0.5">{result.detection.approximate_age}</p>
                  )}
                  {result.detection.description && (
                    <p className="text-sm text-gray-600 mt-2 leading-relaxed">
                      {result.detection.description}
                    </p>
                  )}
                  {result.detection.evidence.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {result.detection.evidence.map((e) => (
                        <span key={e} className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded-full border border-brand-100">
                          {e}
                        </span>
                      ))}
                    </div>
                  )}
                  <a
                    href="/milestones"
                    className="inline-block mt-3 text-xs text-brand-600 underline font-medium"
                  >
                    Review in queue →
                  </a>
                </>
              ) : (
                <p className="text-sm text-gray-500">
                  No milestone detected in this photo.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-xl p-3 text-sm text-red-600">
          {error}
        </div>
      )}
    </div>
  );
}

// ─── Page ──────────────────────────────────────────────────────────────────

export default function UploadPage() {
  const [tab, setTab] = useState<"directory" | "single">("directory");

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-800">Import Photos</h1>
        <p className="text-gray-500 mt-1">
          Scan a whole folder or test with a single photo.
        </p>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
        {([
          { key: "directory", label: "📁 Folder scan" },
          { key: "single", label: "📷 Single photo" },
        ] as const).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={clsx(
              "px-4 py-2 rounded-lg text-sm font-medium transition",
              tab === key
                ? "bg-white text-brand-700 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-2xl p-6 shadow-sm border border-brand-100">
        {tab === "directory" ? <DirectoryScanTab /> : <SingleUploadTab />}
      </div>
    </div>
  );
}
