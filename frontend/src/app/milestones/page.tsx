"use client";
import { useEffect, useState, useRef, useCallback } from "react";
import {
  getPendingMilestones,
  listMilestones,
  reviewMilestone,
  deleteMilestone,
  deduplicateMilestones,
  listChildren,
  rescanLowConfidence,
  Milestone,
  Child,
} from "@/lib/api";
import MilestoneCard from "@/components/MilestoneCard";
import { useReviewKeyboard } from "@/hooks/useReviewKeyboard";

export default function MilestonesPage() {
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [children, setChildren] = useState<Child[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"pending" | "approved">("pending");
  const [rescanning, setRescanning] = useState(false);
  const [rescanMsg, setRescanMsg] = useState<string | null>(null);
  const [deduping, setDeduping] = useState(false);
  const [focusedIdx, setFocusedIdx] = useState(0);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);

  const load = async () => {
    setLoading(true);
    setFocusedIdx(0);
    try {
      const [items, kids] = await Promise.all([
        tab === "pending" ? getPendingMilestones(500) : listMilestones(true),
        listChildren(),
      ]);
      setMilestones(items);
      setChildren(kids);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [tab]);

  useEffect(() => {
    cardRefs.current[focusedIdx]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [focusedIdx]);

  const removeFromList = (id: number) => {
    setMilestones((prev) => {
      const next = prev.filter((m) => m.id !== id);
      setFocusedIdx((i) => Math.min(i, Math.max(0, next.length - 1)));
      return next;
    });
  };

  const handleApprove = useCallback(async (id: number, childId?: number) => {
    await reviewMilestone(id, true, childId);
    removeFromList(id);
  }, []);

  const handleReject = useCallback(async (id: number) => {
    await reviewMilestone(id, false);
    removeFromList(id);
  }, []);

  const handleRemove = async (id: number) => {
    await deleteMilestone(id);
    removeFromList(id);
  };

  const handleChildChange = useCallback(
    (id: number, childId: number | null, approximateAge: string | null) => {
      setMilestones((prev) =>
        prev.map((m) =>
          m.id === id
            ? {
                ...m,
                child_id: childId,
                child_name: children.find((c) => c.id === childId)?.name ?? null,
                approximate_age: approximateAge ?? m.approximate_age,
              }
            : m
        )
      );
    },
    [children]
  );

  const handleRescan = async () => {
    setRescanning(true);
    setRescanMsg(null);
    try {
      const res = await rescanLowConfidence(0.75, 50);
      setRescanMsg(res.message);
      setTimeout(load, 3000);
    } catch (e: any) {
      setRescanMsg(`Error: ${e.message}`);
    } finally {
      setRescanning(false);
    }
  };

  const handleDeduplicate = async () => {
    setDeduping(true);
    setRescanMsg(null);
    try {
      const res = await deduplicateMilestones();
      setRescanMsg(res.message);
      await load();
    } catch (e: any) {
      setRescanMsg(`Error: ${e.message}`);
    } finally {
      setDeduping(false);
    }
  };

  useReviewKeyboard({
    total: milestones.length,
    focusedIdx,
    setFocusedIdx,
    onApprove: useCallback(() => {
      if (milestones[focusedIdx]) handleApprove(milestones[focusedIdx].id);
    }, [milestones, focusedIdx, handleApprove]),
    onReject: useCallback(() => {
      if (milestones[focusedIdx]) handleReject(milestones[focusedIdx].id);
    }, [milestones, focusedIdx, handleReject]),
    enabled: tab === "pending" && !loading,
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Milestone Review</h1>
          {tab === "pending" && milestones.length > 0 && (
            <p className="text-xs text-gray-400 mt-0.5">
              j/k to navigate · a to approve · r to reject
            </p>
          )}
        </div>
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
          {tab === "approved" && (
            <button
              onClick={handleDeduplicate}
              disabled={deduping}
              className="border border-amber-200 text-amber-700 text-sm px-4 py-1.5 rounded-lg hover:bg-amber-50 transition disabled:opacity-50"
              title="Keep only the earliest photo per milestone type per child"
            >
              {deduping ? "Deduplicating..." : "Remove duplicates"}
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
          {rescanMsg}
        </div>
      )}

      {loading && <div className="text-center py-16 text-gray-400">Loading...</div>}

      {!loading && milestones.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          {tab === "pending"
            ? "No milestones awaiting review. Run a scan first."
            : "No approved milestones yet."}
        </div>
      )}

      <div className="grid gap-4">
        {milestones.map((m, idx) => (
          <MilestoneCard
            key={m.id}
            ref={(el) => { cardRefs.current[idx] = el; }}
            milestone={m}
            children={children}
            mode={tab === "pending" ? "review" : "approved"}
            focused={tab === "pending" && idx === focusedIdx}
            onApprove={handleApprove}
            onReject={handleReject}
            onRemove={handleRemove}
            onChildChange={handleChildChange}
            onLabelChange={(id, label) =>
              setMilestones((prev) => prev.map((x) => (x.id === id ? { ...x, label } : x)))
            }
          />
        ))}
      </div>
    </div>
  );
}
