"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getStats } from "@/lib/api";

interface Stats {
  total_photos: number;
  total_milestones: number;
  pending_review: number;
  approved: number;
  rejected: number;
}

export default function Home() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
  }, []);

  return (
    <div className="space-y-10">
      {/* Hero */}
      <div className="text-center py-12">
        <h1 className="text-4xl font-bold text-brand-700 mb-3">
          Your Baby's Story, Discovered
        </h1>
        <p className="text-gray-500 text-lg max-w-xl mx-auto">
          Connect your photo library and AI will find the milestones — first smile, first steps,
          first birthday — organized into a beautiful timeline.
        </p>
        <div className="mt-6 flex justify-center gap-4">
          <Link
            href="/upload"
            className="bg-brand-600 text-white px-6 py-3 rounded-xl font-medium hover:bg-brand-700 transition"
          >
            Import Photos
          </Link>
          <Link
            href="/timeline"
            className="border border-brand-200 text-brand-700 px-6 py-3 rounded-xl font-medium hover:bg-brand-100 transition"
          >
            View Timeline
          </Link>
        </div>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Photos Scanned", value: stats.total_photos },
            { label: "Milestones Found", value: stats.total_milestones },
            { label: "Awaiting Review", value: stats.pending_review },
            { label: "Approved", value: stats.approved },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white rounded-2xl p-5 text-center shadow-sm border border-brand-100">
              <div className="text-3xl font-bold text-brand-600">{value}</div>
              <div className="text-sm text-gray-500 mt-1">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Feature cards */}
      <div className="grid md:grid-cols-3 gap-6">
        {[
          {
            title: "Privacy First",
            desc: "Photos are processed locally. Nothing is uploaded to any cloud without your consent.",
            icon: "🔒",
          },
          {
            title: "AI-Powered Detection",
            desc: "Claude Vision analyzes each photo and identifies developmental milestones with confidence scores.",
            icon: "🧠",
          },
          {
            title: "You're in Control",
            desc: "Review every detection. Approve, reject, or edit before anything goes into your baby book.",
            icon: "✅",
          },
        ].map(({ title, desc, icon }) => (
          <div key={title} className="bg-white rounded-2xl p-6 shadow-sm border border-brand-100">
            <div className="text-3xl mb-3">{icon}</div>
            <h3 className="font-semibold text-gray-800 mb-2">{title}</h3>
            <p className="text-sm text-gray-500">{desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
