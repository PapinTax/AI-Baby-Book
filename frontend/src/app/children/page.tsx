"use client";
import { useEffect, useState } from "react";
import { listChildren, createChild, Child } from "@/lib/api";

export default function ChildrenPage() {
  const [children, setChildren] = useState<Child[]>([]);
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listChildren().then(setChildren).catch(() => {});
  }, []);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const child = await createChild(name.trim(), birthDate || undefined);
      setChildren((prev) => [...prev, child]);
      setName("");
      setBirthDate("");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-lg mx-auto space-y-8">
      <h1 className="text-2xl font-bold text-gray-800">Children</h1>

      {/* Existing children */}
      {children.length > 0 && (
        <div className="space-y-3">
          {children.map((c) => (
            <div
              key={c.id}
              className="bg-white rounded-2xl p-4 shadow-sm border border-brand-100 flex items-center gap-4"
            >
              <div className="w-10 h-10 rounded-full bg-brand-100 flex items-center justify-center text-brand-700 font-bold text-lg select-none">
                {c.name[0].toUpperCase()}
              </div>
              <div>
                <p className="font-medium text-gray-800">{c.name}</p>
                {c.birth_date && (
                  <p className="text-xs text-gray-400">
                    Born{" "}
                    {new Date(c.birth_date).toLocaleDateString("en-US", {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    })}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add form */}
      <div className="bg-white rounded-2xl p-6 shadow-sm border border-brand-100">
        <h2 className="font-semibold text-gray-700 mb-4">Add a child</h2>
        <form onSubmit={handleAdd} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Emma"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Birth date <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              type="date"
              value={birthDate}
              onChange={(e) => setBirthDate(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
            />
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <button
            type="submit"
            disabled={saving}
            className="w-full bg-brand-600 text-white py-2.5 rounded-xl font-medium text-sm hover:bg-brand-700 transition disabled:opacity-50"
          >
            {saving ? "Saving..." : "Add child"}
          </button>
        </form>
      </div>
    </div>
  );
}
