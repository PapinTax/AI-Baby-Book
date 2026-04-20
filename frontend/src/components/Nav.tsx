"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const links = [
  { href: "/upload", label: "Import" },
  { href: "/photos", label: "Photos" },
  { href: "/milestones", label: "Review" },
  { href: "/timeline", label: "Timeline" },
  { href: "/children", label: "Children" },
];

export default function Nav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  return (
    <nav className="bg-white border-b border-brand-100 shadow-sm relative z-40">
      <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
        {/* Logo */}
        <Link href="/" className="text-xl font-bold text-brand-700" onClick={() => setOpen(false)}>
          Baby Book
        </Link>

        {/* Desktop links */}
        <div className="hidden sm:flex items-center gap-5">
          {links.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={clsx(
                "text-sm font-medium transition",
                pathname.startsWith(href)
                  ? "text-brand-600"
                  : "text-gray-500 hover:text-brand-600"
              )}
            >
              {label}
            </Link>
          ))}
        </div>

        {/* Mobile hamburger */}
        <button
          className="sm:hidden p-2 rounded-lg hover:bg-brand-50 transition"
          onClick={() => setOpen((o) => !o)}
          aria-label="Toggle menu"
        >
          <div className="space-y-1.5">
            <span className={clsx("block h-0.5 w-5 bg-gray-600 transition-transform origin-center", open && "translate-y-2 rotate-45")} />
            <span className={clsx("block h-0.5 w-5 bg-gray-600 transition-opacity", open && "opacity-0")} />
            <span className={clsx("block h-0.5 w-5 bg-gray-600 transition-transform origin-center", open && "-translate-y-2 -rotate-45")} />
          </div>
        </button>
      </div>

      {/* Mobile dropdown */}
      {open && (
        <div className="sm:hidden absolute top-full inset-x-0 bg-white border-b border-brand-100 shadow-md">
          {links.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              className={clsx(
                "block px-5 py-3.5 text-sm font-medium border-b border-gray-50 transition",
                pathname.startsWith(href)
                  ? "text-brand-600 bg-brand-50"
                  : "text-gray-600 hover:bg-gray-50"
              )}
            >
              {label}
            </Link>
          ))}
        </div>
      )}
    </nav>
  );
}
