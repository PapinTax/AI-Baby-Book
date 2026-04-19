"use client";
import { useEffect, useState } from "react";
import { listPhotos, Photo } from "@/lib/api";
import Lightbox from "@/components/Lightbox";
import clsx from "clsx";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Filter = "all" | "with_milestones" | "without_milestones";

export default function PhotosPage() {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [lightbox, setLightbox] = useState<{ photoId: number; label: string } | null>(null);

  useEffect(() => {
    listPhotos()
      .then(setPhotos)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = photos.filter((p) => {
    if (filter === "with_milestones") return p.milestone_count > 0;
    if (filter === "without_milestones") return p.milestone_count === 0;
    return true;
  });

  const totalMilestones = photos.reduce((s, p) => s + p.milestone_count, 0);

  return (
    <>
      {lightbox && (
        <Lightbox
          photoId={lightbox.photoId}
          label={lightbox.label}
          onClose={() => setLightbox(null)}
        />
      )}

      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Photos</h1>
            {!loading && (
              <p className="text-sm text-gray-400 mt-0.5">
                {photos.length} photos scanned · {totalMilestones} milestones detected
              </p>
            )}
          </div>

          {/* Filter pills */}
          <div className="flex gap-1 bg-gray-100 rounded-xl p-1">
            {([
              { key: "all", label: "All" },
              { key: "with_milestones", label: "With milestones" },
              { key: "without_milestones", label: "No milestones" },
            ] as { key: Filter; label: string }[]).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={clsx(
                  "px-3 py-1.5 rounded-lg text-xs font-medium transition",
                  filter === key
                    ? "bg-white text-brand-700 shadow-sm"
                    : "text-gray-500 hover:text-gray-700"
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {loading && (
          <div className="text-center py-20 text-gray-400">Loading photos...</div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="text-center py-20 space-y-3">
            <div className="text-4xl">📷</div>
            <p className="text-gray-500">
              {photos.length === 0
                ? "No photos scanned yet."
                : "No photos match this filter."}
            </p>
            {photos.length === 0 && (
              <a
                href="/upload"
                className="inline-block bg-brand-600 text-white px-5 py-2 rounded-xl text-sm font-medium hover:bg-brand-700 transition"
              >
                Import Photos
              </a>
            )}
          </div>
        )}

        {/* Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {filtered.map((photo) => (
            <PhotoTile
              key={photo.id}
              photo={photo}
              onClick={() =>
                setLightbox({ photoId: photo.id, label: photo.filename })
              }
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
}: {
  photo: Photo;
  onClick: () => void;
}) {
  const thumbSrc = photo.thumbnail_url ? `${API}${photo.thumbnail_url}` : null;
  const hasMilestones = photo.milestone_count > 0;

  return (
    <button
      onClick={onClick}
      className="relative group aspect-square rounded-xl overflow-hidden bg-gray-100 hover:ring-2 hover:ring-brand-400 transition"
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

      {/* Milestone badge */}
      {hasMilestones && (
        <div className="absolute top-1.5 right-1.5 bg-brand-600 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center shadow">
          {photo.milestone_count > 9 ? "9+" : photo.milestone_count}
        </div>
      )}

      {/* Date overlay on hover */}
      {photo.taken_at && (
        <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/60 to-transparent p-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <p className="text-white text-xs truncate">
            {new Date(photo.taken_at).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
          </p>
        </div>
      )}
    </button>
  );
}
