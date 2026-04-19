"use client";
import { useState, useEffect, useRef } from "react";
import { scanDirectory, getScanStatus } from "@/lib/api";
import clsx from "clsx";

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

export default function UploadPage() {
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

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-800">Import Photos</h1>
        <p className="text-gray-500 mt-1">
          Point to a local folder containing your photos. The app will scan for childhood milestones.
        </p>
      </div>

      <div className="bg-white rounded-2xl p-6 shadow-sm border border-brand-100 space-y-5">
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
            Minimum confidence: <span className="text-brand-600">{Math.round(minConfidence * 100)}%</span>
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
          disabled={!!sessionId && job?.status !== "complete" && job?.status !== "error"}
          className={clsx(
            "w-full py-3 rounded-xl font-medium text-sm transition",
            sessionId && job?.status !== "complete" && job?.status !== "error"
              ? "bg-gray-200 text-gray-400 cursor-not-allowed"
              : "bg-brand-600 text-white hover:bg-brand-700"
          )}
        >
          {sessionId && job?.status !== "complete" && job?.status !== "error"
            ? "Scanning..."
            : "Start Scan"}
        </button>
      </div>

      {/* Progress */}
      {job && (
        <div className="bg-white rounded-2xl p-6 shadow-sm border border-brand-100 space-y-4">
          <div className="flex items-center justify-between">
            <span className="font-medium text-gray-700">
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
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
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
            <div className="bg-green-50 border border-green-100 rounded-xl p-4 text-sm text-green-700">
              Found <strong>{job.milestone_count ?? job.detected}</strong> milestone
              {(job.milestone_count ?? job.detected) !== 1 ? "s" : ""}!{" "}
              <a href="/milestones" className="underline font-medium">
                Review them now
              </a>
            </div>
          )}

          {job.error && (
            <div className="bg-red-50 border border-red-100 rounded-xl p-4 text-sm text-red-600">
              {job.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
