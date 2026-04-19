import Link from "next/link";

export default function Nav() {
  return (
    <nav className="bg-white border-b border-brand-100 shadow-sm">
      <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-6">
        <Link href="/" className="text-xl font-bold text-brand-700">
          Baby Book
        </Link>
        <Link href="/upload" className="text-sm text-gray-600 hover:text-brand-600">
          Import
        </Link>
        <Link href="/photos" className="text-sm text-gray-600 hover:text-brand-600">
          Photos
        </Link>
        <Link href="/milestones" className="text-sm text-gray-600 hover:text-brand-600">
          Review
        </Link>
        <Link href="/timeline" className="text-sm text-gray-600 hover:text-brand-600">
          Timeline
        </Link>
        <Link href="/children" className="text-sm text-gray-600 hover:text-brand-600">
          Children
        </Link>
      </div>
    </nav>
  );
}
