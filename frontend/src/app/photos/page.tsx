"use client";
import { useEffect, useState, useCallback } from "react";
import { listPhotos, deletePhoto, updatePhotoDate, Photo } from "@/lib/api";
import Lightbox from "@/components/Lightbox";
import clsx from "clsx";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type MilestoneFilter = "all" | "with_milestones" | "without_milestones" | "no_date";

export default function PhotosPage() {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [loading, setLoading] = useState(true);
  const [milestoneFilter, setMilestoneFilter] = useState<MilestoneFilter>("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [appliedStart, setAppliedStart] = useState("");
  const [appliedEnd, setAppliedEnd] = useState("");
  const [lightbox, setLightbox] = useState<{ photoId: number; label: string } | null>(null);
  const [editingDate, setEditingDate] = useState<Photo | null>(null);
  const [dateInput, setDateInput] = useState("");
  const [savingDate, setSavingDate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Parameters<typeof listPhotos>[0] = { limit: 2000 };
      if (milestoneFilter === "with_milestones") params.hasMilestones = true;
      if (milestoneFilter === "without_milestones") params.hasMilestones = false;
      if (milestoneFilter === "no_date") params.noDate = true;
      if (appliedStart) params.startDate = appliedStart;
      if (appliedEnd) params.endDate = appliedEnd;
      setPhotos(await listPhotos(params));
    } finally {
      setLoading(false);
    }
  }, [milestoneFilter, appliedStart, appliedEnd]);

  useEffect(() => { load(); }, [load]);

  const applyDates = () => {
    setAppliedStart(startDate);
    setAppliedEnd(endDate);
  };

  const clearDates = () => {
    setStartDate("");
    setEndDate("");
    setAppliedStart("");
    setAppliedEnd("");
  };

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Remove this photo from the app? (The file on disk is not deleted.)")) return;
    await deletePhoto(id);
    setPhotos((prev) => prev.filter((p) => p.id !== id));
  };

  const openDateEdit = (photo: Photo, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingDate(photo);
    setDateInput(
      photo.taken_at
        ? new Date(photo.taken_at).toISOString().slice(0, 10)
        : ""
    );
  };

  const saveDate = async () => {
    if (!editingDate) return;
    setSavingDate(true);
    try {
      const iso = dateInput ? `${dateInput}T12:00:00` : null;
      const updated = await updatePhotoDate(editingDate.id, iso);
      setPhotos((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      setEditingDate(null);
    } finally {
      setSavingDate(false);
    }
  };

  const totalMilestones = photos.reduce((s, p) => s + p.milestone_count, 0);
  const hasDateFilter = appliedStart || appliedEnd;

  return (
    <>
      {lightbox && (
        <Lightbox
          photoId={lightbox.photoId}
          label={lightbox.label}
          onClose={() => setLightbox(null)}
        />
      )}

      {/* Date edit modal */}
      {editingDate && (
        <div
          className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
          onClick={() => setEditingDate(null)}
        >
          <div
            className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="font-semibold text-gray-800">Edit photo date</h2>
            <p className="text-xs text-gray-400 truncate">{editingDate.filename}</p>
            <input
              type="date"
              value={dateInput}
              onChange={(e) => setDateInput(e.target.value)}
              className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setEditingDate(null)}
                className="px-4 py-1.5 text-sm text-gray-500 hover:text-gray-700 transition"
              >
                Cancel
              </button>
              <button
                onClick={saveDate}
                disabled={savingDate || !dateInput}
                className="px-4 py-1.5 bg-brand-600 text-white text-sm rounded-xl hover:bg-brand-700 transition disabled:opacity-50"
              >
                {savingDate ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Photos</h1>
            {!loading && (
              <p className="text-sm text-gray-400 mt-0.5">
                {photos.length} photos · {totalMilestones} milestones
                {hasDateFilter && (
                  <span className="ml-2 text-brand-600">
                    ({appliedStart || "…"} → {appliedEnd || "…"})
                  </span>
                )}
              </p>
            )}
          </div>
        </div>

        {/* Date range filter */}
        <div className="flex flex-wrap items-center gap-2 bg-gray-50 border border-gray-200 rounded-2xl px-4 py-3">
          <span className="text-xs font-medium text-gray-500 mr-1">Date range</span>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-brand-400"
          />
          <span className="text-gray-400 text-xs">to</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-brand-400"
          />
          <button
            onClick={applyDates}
            className="bg-brand-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-brand-700 transition"
          >
            Apply
          </button>
          {hasDateFilter && (
            <button
              onClick={clearDates}
              className="text-xs text-gray-400 hover:text-gray-600 transition px-2"
            >
              Clear
            </button>
          )}
        </div>

        {/* Milestone + date pills */}
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit flex-wrap">
          {(
            [
              { key: "all", label: "All" },
              { key: "with_milestones", label: "With milestones" },
              { key: "without_milestones", label: "No milestones" },
              { key: "no_date", label: "Unknown date" },
            ] as { key: MilestoneFilter; label: string }[]
          ).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setMilestoneFilter(key)}
              className={clsx(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition",
                milestoneFilter === key
                  ? "bg-white text-brand-700 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {loading && (
          <div className="text-center py-20 text-gray-400">Loading photos…</div>
        )}

        {!loading && photos.length === 0 && (
          <div className="text-center py-20 space-y-3">
            <div className="text-4xl">📷</div>
            <p className="text-gray-500">No photos match these filters.</p>
          </div>
        )}

        {/* Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {photos.map((photo) => (
            <PhotoTile
              key={photo.id}
              photo={photo}
              onClick={() => setLightbox({ photoId: photo.id, label: photo.filename })}
              onDelete={(e) => handleDelete(photo.id, e)}
              onEditDate={(e) => openDateEdit(photo, e)}
            />
          ))}
        </div>
      </div>
    </>
  );
}

function PhotoTile({
  photo,
  onClick,
  onDelete,
  onEditDate,
}: {
  photo: Photo;
  onClick: () => void;
  onDelete: (e: React.MouseEvent) => void;
  onEditDate: (e: React.MouseEvent) => void;
}) {
  const thumbSrc = photo.thumbnail_url ? `${API}${photo.thumbnail_url}` : null;
  const hasMilestones = photo.milestone_count > 0;
  const hasDate = !!photo.taken_at;

  const dateLabel = hasDate
    ? new Date(photo.taken_at!).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : null;

  return (
    <div className="relative group aspect-square rounded-xl overflow-hidden bg-gray-100">
      <button
        onClick={onClick}
        className="w-full h-full hover:ring-2 hover:ring-brand-400 transition rounded-xl"
        title={photo.filename}
      >
        {thumbSrc ? (
          <img
            src={thumbSrc}
            alt={photo.filename}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-3xl text-gray-300">
            📷
          </div>
        )}
      </button>

      {/* Milestone badge */}
      {hasMilestones && (
        <div className="absolute top-1.5 right-1.5 bg-brand-600 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center shadow pointer-events-none">
          {photo.milestone_count > 9 ? "9+" : photo.milestone_count}
        </div>
      )}

      {/* Bottom overlay: date or "edit date" */}
      <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent p-2 opacity-0 group-hover:opacity-100 transition-opacity">
        {hasDate ? (
          <p className="text-white text-xs truncate">{dateLabel}</p>
        ) : (
          <button
            onClick={onEditDate}
            className="text-amber-300 text-xs hover:text-amber-100 transition underline underline-offset-2"
          >
            Set date
          </button>
        )}
      </div>

      {/* Delete button */}
      <button
        onClick={onDelete}
        title="Remove from app"
        className="absolute top-1.5 left-1.5 bg-black/50 hover:bg-red-600 text-white rounded-full w-6 h-6 flex items-center justify-center opacity-0 group-hover:opacity-100 transition text-xs"
      >
        ✕
      </button>
    </div>
  );
}
