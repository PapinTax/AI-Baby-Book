"use client";
import { useEffect, useState } from "react";
import {
  getPendingMilestones,
  listMilestones,
  reviewMilestone,
  deleteMilestone,
  listChildren,
  rescanLowConfidence,
  Milestone,
  Child,
} from "@/lib/api";
import MilestoneCard from "@/components/MilestoneCard";

export default function MilestonesPage() {
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [children, setChildren] = useState<Child[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"pending" | "approved">("pending");
  const [rescanning, setRescanning] = useState(false);
  const [rescanMsg, setRescanMsg] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [items, kids] = await Promise.all([
        tab === "pending" ? getPendingMilestones(50) : listMilestones(true),
        listChildren(),
      ]);
      setMilestones(items);
      setChildren(kids);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [tab]);

  const handleApprove = async (id: number, childId?: number) => {
    await reviewMilestone(id, true, childId);
    setMilestones((prev) => prev.filter((m) => m.id !== id));
  };

  const handleReject = async (id: number) => {
    await reviewMilestone(id, false);
    setMilestones((prev) => prev.filter((m) => m.id !== id));
  };

  const handleRemove = async (id: number) => {
    await deleteMilestone(id);
    setMilestones((prev) => prev.filter((m) => m.id !== id));
  };

  const handleRescan = async () => {
    setRescanning(true);
    setRescanMsg(null);
    try {
      const res = await rescanLowConfidence(0.75, 50);
      setRescanMsg(res.message);
      // Reload after a short delay to pick up improved results
      setTimeout(load, 3000);
    } catch (e: any) {
      setRescanMsg(`Error: ${e.message}`);
    } finally {
      setRescanning(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-gray-800">Milestone Review</h1>
        <div className="flex gap-2 flex-wrap">
          {tab === "pending" && (
            <button
              onClick={handleRescan}
              disabled={rescanning}
              className="border border-brand-200 text-brand-700 text-sm px-4 py-1.5 rounded-lg hover:bg-brand-50 transition disabled:opacity-50"
            >
              {rescanning ? "Re-scanning..." : "Re-scan with Sonnet"}
            </button>
          )}
          {(["pending", "approved"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition ${
                tab === t
                  ? "bg-brand-600 text-white"
                  : "bg-white text-gray-600 border border-gray-200 hover:bg-brand-50"
              }`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {rescanMsg && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-3 text-sm text-blue-700">
          {rescanMsg} — results will refresh in a moment.
        </div>
      )}

      {loading && (
        <div className="text-center py-16 text-gray-400">Loading...</div>
      )}

      {!loading && milestones.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          {tab === "pending"
            ? "No milestones awaiting review. Run a scan first."
            : "No approved milestones yet."}
        </div>
      )}

      <div className="grid gap-4">
        {milestones.map((m) => (
          <MilestoneCard
            key={m.id}
            milestone={m}
            children={children}
            mode={tab === "pending" ? "review" : "approved"}
            onApprove={handleApprove}
            onReject={handleReject}
            onRemove={handleRemove}
            onLabelChange={(id, label) =>
              setMilestones((prev) =>
                prev.map((x) => (x.id === id ? { ...x, label } : x))
              )
            }
          />
        ))}
      </div>
    </div>
  );
}
