"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Plus, Trash2 } from "lucide-react";

export default function SettingsPage() {
  const [configs, setConfigs] = useState<any[]>([]);
  const [label, setLabel] = useState("");
  const [cfEmail, setCfEmail] = useState("");
  const [cfApiKey, setCfApiKey] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [loading, setLoading] = useState(false);

  const [error, setError] = useState("");

  async function loadConfigs() {
    try {
      setError("");
      const data = await api.listCFConfigs();
      setConfigs(data.configs);
    } catch (err: any) {
      setError(err.message || "Failed to load configs");
    }
  }

  useEffect(() => { loadConfigs(); }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await api.createCFConfig({ label, cf_email: cfEmail, cf_api_key: cfApiKey, is_default: isDefault });
      setLabel(""); setCfEmail(""); setCfApiKey(""); setIsDefault(false);
      loadConfigs();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this Cloudflare config?")) return;
    try {
      await api.deleteCFConfig(id);
      loadConfigs();
    } catch (err: any) {
      alert(err.message);
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4 text-sm">{error}</div>
      )}

      {/* Cloudflare configs */}
      <div className="bg-white rounded-lg border p-6 mb-6">
        <h2 className="font-semibold mb-4">Cloudflare Configurations</h2>
        <div className="space-y-2 mb-4">
          {configs.map((c) => (
            <div key={c.id} className="flex items-center justify-between p-3 bg-gray-50 rounded">
              <div>
                <span className="font-medium">{c.label || "Unnamed"}</span>
                <span className="text-gray-500 text-sm ml-2">{c.cf_email}</span>
                {c.is_default && (
                  <span className="ml-2 px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full text-xs">Default</span>
                )}
              </div>
              <button onClick={() => handleDelete(c.id)} className="p-1 hover:bg-red-50 rounded">
                <Trash2 size={16} className="text-red-500" />
              </button>
            </div>
          ))}
          {configs.length === 0 && <p className="text-gray-400 text-sm">No configurations yet</p>}
        </div>

        <form onSubmit={handleCreate} className="border-t pt-4 space-y-3">
          <h3 className="text-sm font-medium">Add New Config</h3>
          <div className="grid grid-cols-2 gap-3">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Label"
              className="px-3 py-2 border rounded-lg text-sm"
            />
            <input
              value={cfEmail}
              onChange={(e) => setCfEmail(e.target.value)}
              placeholder="Cloudflare email"
              className="px-3 py-2 border rounded-lg text-sm"
              required
            />
            <input
              type="password"
              value={cfApiKey}
              onChange={(e) => setCfApiKey(e.target.value)}
              placeholder="API Key"
              className="px-3 py-2 border rounded-lg text-sm"
              required
            />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
              Default config
            </label>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm flex items-center gap-2"
          >
            <Plus size={16} /> Add Config
          </button>
        </form>
      </div>
    </div>
  );
}
