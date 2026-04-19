"use client";
import { useEffect, useState } from "react";
import { getPendingMilestones, reviewMilestone, deleteMilestone, Milestone } from "@/lib/api";
import ConfidenceBadge from "@/components/ConfidenceBadge";

function formatDate(iso: string | null) {
  if (!iso) return "Date unknown";
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}

const MILESTONE_EMOJI: Record<string, string> = {
  first_smile: "😊",
  first_laugh: "😂",
  tummy_time: "👶",
  first_roll: "🔄",
  sitting_up: "🧸",
  first_crawl: "🐣",
  first_pull_to_stand: "💪",
  first_stand: "🏋️",
  first_steps: "👟",
  first_walk: "🚶",
  first_solid_food: "🥣",
  first_birthday: "🎂",
  birthday: "🎉",
  first_bath: "🛁",
  first_tooth: "🦷",
  vacation: "✈️",
  holiday: "🎄",
  memorable_moment: "⭐",
};

export default function MilestonesPage() {
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"pending" | "approved">("pending");

  const load = async () => {
    setLoading(true);
    try {
      if (tab === "pending") {
        const data = await getPendingMilestones(50);
        setMilestones(data);
      } else {
        const { listMilestones } = await import("@/lib/api");
        const data = await listMilestones(true);
        setMilestones(data);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [tab]);

  const handleReview = async (id: number, approved: boolean) => {
    await reviewMilestone(id, approved);
    setMilestones((prev) => prev.filter((m) => m.id !== id));
  };

  const handleDelete = async (id: number) => {
    await deleteMilestone(id);
    setMilestones((prev) => prev.filter((m) => m.id !== id));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">Milestone Review</h1>
        <div className="flex gap-2">
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
          <div key={m.id} className="bg-white rounded-2xl p-5 shadow-sm border border-brand-100">
            <div className="flex items-start gap-4">
              <div className="text-4xl select-none">
                {MILESTONE_EMOJI[m.milestone_type] ?? "📸"}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-semibold text-gray-800">{m.label}</h3>
                  <ConfidenceBadge confidence={m.confidence} />
                  {m.approximate_age && (
                    <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded-full border">
                      {m.approximate_age}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 mt-0.5">{formatDate(m.photo_taken_at)}</p>
                {m.description && (
                  <p className="text-sm text-gray-600 mt-2 leading-relaxed">{m.description}</p>
                )}
                {m.evidence && m.evidence.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {m.evidence.map((e) => (
                      <span key={e} className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded-full border border-brand-100">
                        {e}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {tab === "pending" && (
                <div className="flex flex-col gap-2 shrink-0">
                  <button
                    onClick={() => handleReview(m.id, true)}
                    className="bg-green-500 hover:bg-green-600 text-white text-sm px-4 py-1.5 rounded-lg transition"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => handleReview(m.id, false)}
                    className="bg-red-100 hover:bg-red-200 text-red-600 text-sm px-4 py-1.5 rounded-lg transition"
                  >
                    Reject
                  </button>
                </div>
              )}

              {tab === "approved" && (
                <button
                  onClick={() => handleDelete(m.id)}
                  className="text-gray-300 hover:text-red-400 transition text-xs shrink-0"
                >
                  Remove
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
