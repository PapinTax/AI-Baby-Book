import type { Metadata, Viewport } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "AI Baby Book",
  description: "Discover your child's milestones with AI",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Baby Book",
  },
};

export const viewport: Viewport = {
  themeColor: "#7c3aed",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,   // prevents double-tap zoom on iOS, intentional for app feel
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-brand-50">
        <Nav />
        <main className="max-w-5xl mx-auto px-4 py-6 pb-12">{children}</main>
      </body>
    </html>
  );
}
