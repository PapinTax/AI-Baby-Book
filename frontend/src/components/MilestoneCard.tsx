"use client";
import { useState, useRef, forwardRef } from "react";
import { Milestone, Child, updateMilestoneLabel, reassignChild } from "@/lib/api";
import ConfidenceBadge from "./ConfidenceBadge";
import Lightbox from "./Lightbox";

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

interface Props {
  milestone: Milestone;
  children?: Child[];
  mode: "review" | "approved";
  focused?: boolean;
  onApprove?: (id: number, childId?: number) => void;
  onReject?: (id: number) => void;
  onRemove?: (id: number) => void;
  onLabelChange?: (id: number, label: string) => void;
  onChildChange?: (id: number, childId: number | null, approximateAge: string | null) => void;
}

const MilestoneCard = forwardRef<HTMLDivElement, Props>(function MilestoneCard({
  milestone: m,
  children = [],
  mode,
  focused = false,
  onApprove,
  onReject,
  onRemove,
  onLabelChange,
  onChildChange,
}, ref) {
  const thumbSrc = m.thumbnail_url ? `${API}${m.thumbnail_url}` : null;
  const [editing, setEditing] = useState(false);
  const [labelDraft, setLabelDraft] = useState(m.label);
  const [saving, setSaving] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  // For review mode: hold child selection without immediately approving
  const [selectedChildId, setSelectedChildId] = useState<number | "">(m.child_id ?? "");
  const [reassigning, setReassigning] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const commitLabel = async () => {
    const trimmed = labelDraft.trim();
    if (!trimmed || trimmed === m.label) {
      setEditing(false);
      setLabelDraft(m.label);
      return;
    }
    setSaving(true);
    try {
      await updateMilestoneLabel(m.id, trimmed);
      onLabelChange?.(m.id, trimmed);
    } catch {
      setLabelDraft(m.label);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  };

  const handleReassign = async (newChildId: number | "") => {
    setReassigning(true);
    try {
      const updated = await reassignChild(m.id, newChildId === "" ? null : newChildId);
      onChildChange?.(m.id, updated.child_id, updated.approximate_age ?? null);
      setSelectedChildId(updated.child_id ?? "");
    } catch {
      // revert local state on failure
      setSelectedChildId(m.child_id ?? "");
    } finally {
      setReassigning(false);
    }
  };

  const currentChild = children.find((c) => c.id === (m.child_id ?? selectedChildId));

  return (
    <>
      {lightboxOpen && (
        <Lightbox photoId={m.photo_id} label={m.label} onClose={() => setLightboxOpen(false)} />
      )}

      <div
        ref={ref}
        className={`bg-white rounded-2xl shadow-sm border overflow-hidden transition-shadow ${
          focused ? "border-brand-400 shadow-md ring-2 ring-brand-200" : "border-brand-100"
        }`}
      >
        <div className="flex">
          {/* Thumbnail */}
          <button
            onClick={() => setLightboxOpen(true)}
            className="w-28 sm:w-36 shrink-0 bg-gray-50 flex items-center justify-center hover:opacity-90 transition"
            title="View full photo"
          >
            {thumbSrc ? (
              <img src={thumbSrc} alt={m.label} className="w-full h-full object-cover" style={{ maxHeight: "144px" }} />
            ) : (
              <span className="text-5xl select-none p-4">{MILESTONE_EMOJI[m.milestone_type] ?? "📸"}</span>
            )}
          </button>

          {/* Content */}
          <div className="flex-1 p-4 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                {/* Editable label */}
                {editing ? (
                  <input
                    ref={inputRef}
                    value={labelDraft}
                    onChange={(e) => setLabelDraft(e.target.value)}
                    onBlur={commitLabel}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitLabel();
                      if (e.key === "Escape") { setEditing(false); setLabelDraft(m.label); }
                    }}
                    autoFocus
                    className="font-semibold text-gray-800 border-b border-brand-400 bg-transparent outline-none w-full text-base"
                  />
                ) : (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {!thumbSrc && <span className="text-lg">{MILESTONE_EMOJI[m.milestone_type] ?? "📸"}</span>}
                    <h3
                      className="font-semibold text-gray-800 cursor-text hover:text-brand-600 transition"
                      title="Click to edit label"
                      onClick={() => { setEditing(true); setTimeout(() => inputRef.current?.select(), 0); }}
                    >
                      {saving ? labelDraft : m.label}
                    </h3>
                    <ConfidenceBadge confidence={m.confidence} />
                  </div>
                )}

                <p className="text-xs text-gray-400 mt-0.5">
                  {formatDate(m.photo_taken_at)}
                  {m.approximate_age && (
                    <span className="ml-2 bg-gray-50 border px-1.5 py-0.5 rounded-full">{m.approximate_age}</span>
                  )}
                </p>
              </div>

              {/* Actions */}
              {mode === "review" && (
                <div className="flex flex-col gap-1.5 shrink-0">
                  <button
                    onClick={() => onApprove?.(m.id, selectedChildId !== "" ? selectedChildId : undefined)}
                    className="bg-green-500 hover:bg-green-600 text-white text-xs px-3 py-1.5 rounded-lg transition whitespace-nowrap"
                  >
                    Approve{selectedChildId !== "" && currentChild ? ` for ${currentChild.name}` : ""}
                  </button>
                  <button
                    onClick={() => onReject?.(m.id)}
                    className="bg-red-50 hover:bg-red-100 text-red-600 text-xs px-3 py-1.5 rounded-lg transition"
                  >
                    Reject
                  </button>
                </div>
              )}
              {mode === "approved" && (
                <button
                  onClick={() => onRemove?.(m.id)}
                  className="text-gray-300 hover:text-red-400 transition text-xs shrink-0 mt-1"
                >
                  Remove
                </button>
              )}
            </div>

            {/* Child assignment row — review: select before approving; approved: reassign */}
            {children.length > 0 && (
              <div className="mt-2 flex items-center gap-2">
                {mode === "review" ? (
                  <select
                    value={selectedChildId}
                    onChange={(e) => setSelectedChildId(e.target.value === "" ? "" : Number(e.target.value))}
                    className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 focus:outline-none focus:ring-1 focus:ring-brand-400"
                  >
                    <option value="">No child assigned</option>
                    {children.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                ) : (
                  <>
                    <select
                      value={m.child_id ?? ""}
                      onChange={(e) => handleReassign(e.target.value === "" ? "" : Number(e.target.value))}
                      disabled={reassigning}
                      className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 focus:outline-none focus:ring-1 focus:ring-brand-400 disabled:opacity-50"
                    >
                      <option value="">Unassigned</option>
                      {children.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                    {reassigning && <span className="text-xs text-gray-400">Saving…</span>}
                  </>
                )}
              </div>
            )}

            {m.description && (
              <p className="text-sm text-gray-600 mt-2 leading-relaxed line-clamp-2">{m.description}</p>
            )}

            {/* Evidence chips */}
            {m.evidence && m.evidence.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {m.evidence.map((e) => (
                  <span key={e} className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded-full border border-brand-100">{e}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
});

export default MilestoneCard;
