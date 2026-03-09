"use client";

import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import { Plus, Trash2, Shield, Loader2, Settings as SettingsIcon } from "lucide-react";

export default function SettingsPage() {
  const authenticated = useAuth();
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [cfEmail, setCfEmail] = useState("");
  const [cfApiKey, setCfApiKey] = useState("");
  const [isDefault, setIsDefault] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["cf-configs"],
    queryFn: () => api.listCFConfigs(),
  });

  const configs = data?.configs ?? [];

  const createMutation = useMutation({
    mutationFn: (data: any) => api.createCFConfig(data),
    onSuccess: () => {
      setLabel(""); setCfEmail(""); setCfApiKey(""); setIsDefault(false);
      queryClient.invalidateQueries({ queryKey: ["cf-configs"] });
    },
    onError: (e: any) => alert(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteCFConfig(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cf-configs"] }),
    onError: (e: any) => alert(e.message),
  });

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    createMutation.mutate({ label, cf_email: cfEmail, cf_api_key: cfApiKey, is_default: isDefault });
  }

  function handleDelete(id: string) {
    if (!confirm("Delete this Cloudflare config?")) return;
    deleteMutation.mutate(id);
  }

  if (authenticated === null) return null;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <div className="max-w-3xl mx-auto">
          <div className="mb-6">
            <h1 className="text-2xl font-bold flex items-center gap-2"><SettingsIcon size={24} className="text-gray-600" /> Settings</h1>
            <p className="text-sm text-gray-500 mt-0.5">Manage Cloudflare configurations and integrations</p>
          </div>

          {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl mb-4 text-sm">{(error as any).message}</div>}

          <div className="bg-white rounded-xl border p-6 shadow-sm">
            <div className="flex items-center gap-2 mb-5">
              <Shield size={18} className="text-orange-500" />
              <h2 className="font-semibold text-lg">Cloudflare Configurations</h2>
            </div>

            {isLoading ? (
              <div className="flex items-center justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-blue-600" /></div>
            ) : (
              <div className="space-y-2 mb-6">
                {configs.map((c: any) => (
                  <div key={c.id} className="flex items-center justify-between p-3.5 bg-gray-50 rounded-xl border hover:bg-gray-100/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-orange-100 rounded-lg flex items-center justify-center">
                        <Shield size={14} className="text-orange-600" />
                      </div>
                      <div>
                        <span className="font-medium text-gray-900">{c.label || "Unnamed"}</span>
                        <span className="text-gray-400 text-sm ml-2">{c.cf_email}</span>
                      </div>
                      {c.is_default && <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full text-xs font-medium">Default</span>}
                    </div>
                    <button onClick={() => handleDelete(c.id)} className="p-1.5 hover:bg-red-50 rounded-lg"><Trash2 size={16} className="text-red-500" /></button>
                  </div>
                ))}
                {configs.length === 0 && <p className="text-gray-400 text-sm py-4 text-center">No configurations yet</p>}
              </div>
            )}

            <form onSubmit={handleCreate} className="border-t pt-5 space-y-4">
              <h3 className="text-sm font-semibold text-gray-700">Add New Config</h3>
              <div className="grid grid-cols-2 gap-3">
                <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label" className="px-4 py-2.5 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500/30 focus:outline-none" />
                <input value={cfEmail} onChange={(e) => setCfEmail(e.target.value)} placeholder="Cloudflare email" className="px-4 py-2.5 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500/30 focus:outline-none" required />
                <input type="password" value={cfApiKey} onChange={(e) => setCfApiKey(e.target.value)} placeholder="API Key" className="px-4 py-2.5 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500/30 focus:outline-none" required />
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} className="rounded" /> Default config</label>
              </div>
              <button type="submit" disabled={createMutation.isPending} className="bg-blue-600 text-white px-4 py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium flex items-center gap-2">
                {createMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />} Add Config
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}
