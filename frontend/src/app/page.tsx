"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getStats, listChildren } from "@/lib/api";

interface Stats {
  total_photos: number;
  total_milestones: number;
  pending_review: number;
  approved: number;
  rejected: number;
}

const STEPS = [
  {
    num: 1,
    icon: "👶",
    title: "Add your child",
    desc: "Create a profile so milestones can be linked to the right child.",
    href: "/children",
    cta: "Add Child",
  },
  {
    num: 2,
    icon: "📷",
    title: "Import photos",
    desc: "Scan a folder on your device or upload individual photos.",
    href: "/upload",
    cta: "Import Photos",
  },
  {
    num: 3,
    icon: "✅",
    title: "Review detections",
    desc: "AI will find milestones — approve the ones that matter.",
    href: "/milestones",
    cta: "Review",
  },
  {
    num: 4,
    icon: "📖",
    title: "View your timeline",
    desc: "See every milestone in order and export a beautiful PDF keepsake.",
    href: "/timeline",
    cta: "Open Timeline",
  },
];

export default function Home() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [hasChildren, setHasChildren] = useState<boolean | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
    listChildren()
      .then((kids) => setHasChildren(kids.length > 0))
      .catch(() => setHasChildren(false));
  }, []);

  const isFirstRun = stats && stats.total_photos === 0;

  return (
    <div className="space-y-10">
      {/* Hero */}
      <div className="text-center py-10">
        <h1 className="text-4xl font-bold text-brand-700 mb-3">
          Your Baby's Story, Discovered
        </h1>
        <p className="text-gray-500 text-lg max-w-xl mx-auto">
          AI scans your photo library and finds the milestones — first smile, first steps,
          first birthday — organized into a beautiful timeline.
        </p>
      </div>

      {/* Onboarding stepper — shown only on first run */}
      {isFirstRun && (
        <div className="bg-white rounded-2xl border border-brand-100 shadow-sm p-6 sm:p-8">
          <p className="text-xs uppercase tracking-widest text-brand-400 font-semibold mb-6">
            Get started in 4 steps
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {STEPS.map((step, i) => {
              const done =
                (step.num === 1 && hasChildren) ||
                (step.num === 2 && stats && stats.total_photos > 0) ||
                (step.num === 3 && stats && stats.approved > 0) ||
                false;
              return (
                <Link
                  key={step.num}
                  href={step.href}
                  className="group flex flex-col gap-3 p-5 rounded-xl border-2 transition
                    border-brand-100 hover:border-brand-400 hover:shadow-md"
                >
                  <div className="flex items-center gap-2">
                    <span className="w-7 h-7 rounded-full bg-brand-100 text-brand-700 text-xs font-bold flex items-center justify-center">
                      {done ? "✓" : step.num}
                    </span>
                    <span className="text-2xl">{step.icon}</span>
                  </div>
                  <div>
                    <p className="font-semibold text-gray-800">{step.title}</p>
                    <p className="text-xs text-gray-500 mt-1 leading-snug">{step.desc}</p>
                  </div>
                  <span className="mt-auto text-xs font-medium text-brand-600 group-hover:underline">
                    {step.cta} →
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {/* Stats — shown once user has photos */}
      {stats && stats.total_photos > 0 && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: "Photos Scanned", value: stats.total_photos, href: "/photos" },
              { label: "Milestones Found", value: stats.total_milestones, href: "/milestones" },
              { label: "Awaiting Review", value: stats.pending_review, href: "/milestones" },
              { label: "Approved", value: stats.approved, href: "/timeline" },
            ].map(({ label, value, href }) => (
              <Link
                key={label}
                href={href}
                className="bg-white rounded-2xl p-5 text-center shadow-sm border border-brand-100 hover:shadow-md hover:border-brand-200 transition"
              >
                <div className="text-3xl font-bold text-brand-600">{value}</div>
                <div className="text-sm text-gray-500 mt-1">{label}</div>
              </Link>
            ))}
          </div>

          <div className="flex justify-center gap-4 flex-wrap">
            <Link
              href="/upload"
              className="bg-brand-600 text-white px-6 py-3 rounded-xl font-medium hover:bg-brand-700 transition"
            >
              Import More Photos
            </Link>
            {stats.pending_review > 0 && (
              <Link
                href="/milestones"
                className="border border-brand-200 text-brand-700 px-6 py-3 rounded-xl font-medium hover:bg-brand-100 transition"
              >
                Review {stats.pending_review} Pending
              </Link>
            )}
            <Link
              href="/timeline"
              className="border border-brand-200 text-brand-700 px-6 py-3 rounded-xl font-medium hover:bg-brand-100 transition"
            >
              View Timeline
            </Link>
          </div>
        </>
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
