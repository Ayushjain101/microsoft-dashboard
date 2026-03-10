"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TOTPEntry } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import { useToast } from "@/components/ui/Toast";
import Sidebar from "@/components/layout/Sidebar";
import { KeyRound, Copy, Check, Trash2, Plus, Search, X, Loader2 } from "lucide-react";

function CountdownRing({ remaining, period }: { remaining: number; period: number }) {
  const size = 42;
  const stroke = 3;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = remaining / period;
  const offset = circumference * (1 - progress);
  const color = remaining <= 5 ? "#ef4444" : remaining <= 10 ? "#f59e0b" : "#3b82f6";

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#f3f4f6" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeWidth={stroke} strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round" className="transition-all duration-1000 linear" />
      </svg>
      <span className="absolute text-xs font-mono font-bold" style={{ color }}>{remaining}</span>
    </div>
  );
}

export default function TOTPPage() {
  const authenticated = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [entries, setEntries] = useState<TOTPEntry[]>([]);
  const [search, setSearch] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["totp"],
    queryFn: () => api.listTOTP(),
    refetchInterval: 30000,
  });

  useEffect(() => {
    if (data) setEntries(data);
  }, [data]);

  // Local countdown timer
  useEffect(() => {
    const interval = setInterval(() => {
      setEntries((prev) => {
        const needsRefresh = prev.some((e) => e.remaining <= 1);
        if (needsRefresh) {
          queryClient.invalidateQueries({ queryKey: ["totp"] });
          return prev;
        }
        return prev.map((e) => ({ ...e, remaining: e.remaining - 1 }));
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [queryClient]);

  async function copyCode(tenantId: string, code: string) {
    await navigator.clipboard.writeText(code);
    setCopiedId(tenantId);
    setTimeout(() => setCopiedId(null), 2000);
  }

  async function handleDelete(tenantId: string) {
    try {
      await api.deleteTOTPSecret(tenantId);
      setEntries((prev) => prev.filter((e) => e.tenant_id !== tenantId));
      setDeleteConfirm(null);
      queryClient.invalidateQueries({ queryKey: ["totp"] });
    } catch (e: any) { toast.error("Failed to delete: " + e.message); }
  }

  if (authenticated === null) return null;

  const filtered = entries.filter((e) => {
    const q = search.toLowerCase();
    return e.tenant_name.toLowerCase().includes(q) || e.admin_email.toLowerCase().includes(q);
  });

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <div className="max-w-[1200px] mx-auto">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold flex items-center gap-2"><KeyRound size={24} className="text-blue-600" /> TOTP Vault</h1>
              <p className="text-sm text-gray-500 mt-0.5">Live authenticator codes for tenants with MFA secrets</p>
            </div>
            <button onClick={() => setShowAddModal(true)} className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2.5 rounded-lg hover:bg-blue-700 text-sm font-medium shadow-sm">
              <Plus size={16} /> Add Secret
            </button>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-blue-600" /></div>
          ) : error ? (
            <div className="p-8 text-center text-red-500">Failed to load TOTP data</div>
          ) : (
            <>
              {entries.length > 0 && (
                <div className="relative mb-6">
                  <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="text" placeholder="Search by tenant name or email..." value={search} onChange={(e) => setSearch(e.target.value)} className="w-full pl-10 pr-4 py-2.5 bg-white border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30" />
                </div>
              )}

              {filtered.length === 0 ? (
                <div className="text-center py-16 text-gray-400">{entries.length === 0 ? 'No tenants with MFA secrets. Use "Add Secret" to store one.' : "No matching tenants."}</div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {filtered.map((entry) => (
                    <div key={entry.tenant_id} className="bg-white rounded-xl border p-5 flex flex-col gap-3 shadow-sm hover:shadow-md transition-shadow">
                      <div className="flex items-start justify-between">
                        <div className="min-w-0">
                          <div className="font-semibold truncate text-gray-900">{entry.tenant_name}</div>
                          <div className="text-xs text-gray-500 truncate">{entry.admin_email}</div>
                        </div>
                        <CountdownRing remaining={entry.remaining} period={entry.period} />
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-3xl font-bold tracking-widest text-gray-800">{entry.code.slice(0, 3)} {entry.code.slice(3)}</span>
                        <button onClick={() => copyCode(entry.tenant_id, entry.code)} className="p-2 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors" title="Copy code">
                          {copiedId === entry.tenant_id ? <Check size={18} className="text-green-500" /> : <Copy size={18} />}
                        </button>
                      </div>
                      <div className="flex justify-end">
                        {deleteConfirm === entry.tenant_id ? (
                          <div className="flex items-center gap-2 text-xs">
                            <span className="text-red-600">Remove secret?</span>
                            <button onClick={() => handleDelete(entry.tenant_id)} className="text-red-600 font-medium hover:underline">Yes</button>
                            <button onClick={() => setDeleteConfirm(null)} className="text-gray-500 hover:underline">No</button>
                          </div>
                        ) : (
                          <button onClick={() => setDeleteConfirm(entry.tenant_id)} className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-500 transition-colors" title="Remove secret"><Trash2 size={14} /></button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {showAddModal && <AddSecretModal onClose={() => setShowAddModal(false)} onAdded={() => queryClient.invalidateQueries({ queryKey: ["totp"] })} />}
      </main>
    </div>
  );
}

function AddSecretModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [tenants, setTenants] = useState<any[]>([]);
  const [selectedTenant, setSelectedTenant] = useState("");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingTenants, setLoadingTenants] = useState(true);

  useEffect(() => {
    api.listTenants(1).then((data) => setTenants(data.tenants)).catch(() => {}).finally(() => setLoadingTenants(false));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedTenant || !secret.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.setTOTPSecret(selectedTenant, secret.trim());
      onAdded();
      onClose();
    } catch (err: any) { setError(err.message); }
    finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold">Add TOTP Secret</h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Tenant</label>
            {loadingTenants ? <div className="text-sm text-gray-400">Loading tenants...</div> : (
              <select value={selectedTenant} onChange={(e) => setSelectedTenant(e.target.value)} className="w-full border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30" required>
                <option value="">Select a tenant...</option>
                {tenants.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.admin_email})</option>)}
              </select>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">TOTP Secret (Base32)</label>
            <input type="text" value={secret} onChange={(e) => setSecret(e.target.value.toUpperCase())} placeholder="e.g. JBSWY3DPEHPK3PXP" className="w-full border rounded-lg px-3 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/30" required />
            <p className="text-xs text-gray-400 mt-1">The base32-encoded secret from the authenticator setup</p>
          </div>
          {error && <div className="text-sm text-red-600 bg-red-50 p-2.5 rounded-lg">{error}</div>}
          <div className="flex gap-3 justify-end pt-1">
            <button type="button" onClick={onClose} className="px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
            <button type="submit" disabled={saving || !selectedTenant || !secret.trim()} className="px-4 py-2.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium">
              {saving ? "Saving..." : "Save Secret"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
