"use client";
import { useEffect, useState } from "react";
import { getTimeline, listChildren, TimelineItem, Child } from "@/lib/api";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import Lightbox from "@/components/Lightbox";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const MILESTONE_EMOJI: Record<string, string> = {
  first_smile: "😊", first_laugh: "😂", tummy_time: "👶", first_roll: "🔄",
  sitting_up: "🧸", first_crawl: "🐣", first_pull_to_stand: "💪", first_stand: "🏋️",
  first_steps: "👟", first_walk: "🚶", first_solid_food: "🥣", first_birthday: "🎂",
  birthday: "🎉", first_bath: "🛁", first_tooth: "🦷", vacation: "✈️",
  holiday: "🎄", memorable_moment: "⭐",
};

function formatDate(iso: string | null) {
  if (!iso) return "Date unknown";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric",
  });
}

function groupByYear(items: TimelineItem[]): Record<string, TimelineItem[]> {
  return items.reduce((acc, item) => {
    const year = item.taken_at ? new Date(item.taken_at).getFullYear().toString() : "Unknown";
    if (!acc[year]) acc[year] = [];
    acc[year].push(item);
    return acc;
  }, {} as Record<string, TimelineItem[]>);
}

export default function TimelinePage() {
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [children, setChildren] = useState<Child[]>([]);
  const [selectedChild, setSelectedChild] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<{ photoId: number; label: string } | null>(null);

  useEffect(() => {
    listChildren().then(setChildren).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    getTimeline(true, selectedChild ?? undefined)
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedChild]);

  if (loading) return <div className="text-center py-20 text-gray-400">Loading timeline...</div>;
  if (error) return <div className="text-center py-20 text-red-400">Could not load timeline: {error}</div>;

  if (!loading && items.length === 0) {
    return (
      <div className="text-center py-20 space-y-3">
        <div className="text-5xl">📷</div>
        <p className="text-gray-500">No approved milestones yet.</p>
        <a href="/upload" className="inline-block bg-brand-600 text-white px-5 py-2 rounded-xl text-sm font-medium hover:bg-brand-700 transition">
          Import Photos
        </a>
      </div>
    );
  }

  const grouped = groupByYear(items);
  const years = Object.keys(grouped).sort((a, b) =>
    a === "Unknown" ? 1 : b === "Unknown" ? -1 : Number(a) - Number(b)
  );

  const exportUrl = `${API}/timeline/export/pdf?child_name=${
    selectedChild
      ? encodeURIComponent(children.find((c) => c.id === selectedChild)?.name ?? "Baby")
      : "Baby"
  }${selectedChild ? `&child_id=${selectedChild}` : ""}`;

  return (
    <>
      {lightbox && (
        <Lightbox
          photoId={lightbox.photoId}
          label={lightbox.label}
          onClose={() => setLightbox(null)}
        />
      )}

      <div className="space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <h1 className="text-2xl font-bold text-gray-800">Timeline</h1>
          <div className="flex items-center gap-3 flex-wrap">
            {children.length > 0 && (
              <select
                value={selectedChild ?? ""}
                onChange={(e) => setSelectedChild(e.target.value ? Number(e.target.value) : null)}
                className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand-400"
              >
                <option value="">All children</option>
                {children.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            )}
            <a
              href={exportUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="border border-brand-200 text-brand-700 px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-brand-50 transition"
            >
              Export PDF
            </a>
            {children.length > 1 && (
              <a
                href={`${API}/timeline/export/pdf/full`}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-brand-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-brand-700 transition"
              >
                Family Book PDF
              </a>
            )}
          </div>
        </div>

        {years.map((year) => (
          <section key={year}>
            <h2 className="text-lg font-bold text-brand-700 mb-4 flex items-center gap-2">
              <span className="w-8 h-8 bg-brand-100 rounded-full flex items-center justify-center text-sm">
                {year.slice(-2)}
              </span>
              {year}
            </h2>

            <div className="relative pl-8 border-l-2 border-brand-100 space-y-6">
              {grouped[year].map((item) => (
                <div key={item.milestone_id} className="relative">
                  <div className="absolute -left-[2.15rem] top-1 w-4 h-4 rounded-full bg-brand-500 border-2 border-white shadow" />

                  <div className="bg-white rounded-2xl shadow-sm border border-brand-100 hover:shadow-md transition overflow-hidden">
                    <div className="flex">
                      {/* Thumbnail — click to open lightbox */}
                      <button
                        onClick={() => setLightbox({ photoId: item.photo_id, label: item.label })}
                        className="w-24 sm:w-32 shrink-0 bg-gray-50 flex items-center justify-center hover:opacity-90 transition"
                        title="View full photo"
                      >
                        {item.thumbnail_url ? (
                          <img
                            src={`${API}${item.thumbnail_url}`}
                            alt={item.label}
                            className="w-full h-full object-cover"
                            style={{ maxHeight: "128px" }}
                          />
                        ) : (
                          <span className="text-4xl select-none p-3">
                            {MILESTONE_EMOJI[item.milestone_type] ?? "📸"}
                          </span>
                        )}
                      </button>

                      {/* Content */}
                      <div className="flex-1 p-4 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          {!item.thumbnail_url && (
                            <span className="text-xl">{MILESTONE_EMOJI[item.milestone_type] ?? "📸"}</span>
                          )}
                          <h3 className="font-semibold text-gray-800">{item.label}</h3>
                          <ConfidenceBadge confidence={item.confidence} />
                          {item.approximate_age && (
                            <span className="text-xs text-gray-400 bg-gray-50 border px-2 py-0.5 rounded-full">
                              {item.approximate_age}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {formatDate(item.taken_at)}
                          {item.child_name && ` · ${item.child_name}`}
                        </p>
                        {item.description && (
                          <p className="text-sm text-gray-600 mt-2 leading-relaxed line-clamp-3">
                            {item.description}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
