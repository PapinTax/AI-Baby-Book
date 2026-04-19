"use client";
import { useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Props {
  photoId: number;
  label: string;
  onClose: () => void;
}

export default function Lightbox({ photoId, label, onClose }: Props) {
  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        className="relative max-w-4xl w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute -top-10 right-0 text-white/80 hover:text-white text-sm font-medium"
        >
          Close ✕
        </button>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`${API}/photos/${photoId}/image`}
          alt={label}
          className="w-full max-h-[80vh] object-contain rounded-xl shadow-2xl"
        />
        <p className="text-white/70 text-sm text-center mt-3">{label}</p>
      </div>
    </div>
  );
}
