"use client";

import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import { RefreshCw, Loader2, ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

const STATUS_COLORS: Record<string, string> = {
  healthy: "bg-emerald-50 text-emerald-700 border border-emerald-200",
  blocked: "bg-red-50 text-red-700 border border-red-200",
  auth_failed: "bg-red-50 text-red-700 border border-red-200",
  timeout: "bg-amber-50 text-amber-700 border border-amber-200",
  error: "bg-red-50 text-red-700 border border-red-200",
  warning: "bg-amber-50 text-amber-700 border border-amber-200",
};

export default function TenantHealthPage() {
  const authenticated = useAuth();
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const tenantId = params.tenantId as string;
  const [checking, setChecking] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["tenant-health", tenantId],
    queryFn: () => api.tenantHealth(tenantId),
  });

  const checks = data?.checks ?? [];

  async function handleCheckNow() {
    setChecking(true);
    try {
      await api.triggerCheck(tenantId);
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["tenant-health", tenantId] });
        setChecking(false);
      }, 3000);
    } catch { setChecking(false); }
  }

  if (authenticated === null) return null;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <button onClick={() => router.back()} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6">
          <ArrowLeft size={16} /> Back
        </button>

        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold">Health History</h1>
            <p className="text-sm text-gray-500 mt-0.5">Tenant {tenantId.slice(0, 8)}...</p>
          </div>
          <button onClick={handleCheckNow} disabled={checking} className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2.5 rounded-lg hover:bg-blue-700 text-sm font-medium disabled:opacity-50">
            {checking ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />} Check Now
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-blue-600" /></div>
        ) : (
          <div className="bg-white rounded-xl border overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50/80 border-b">
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Type</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Status</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Detail</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Response</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Time</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c: any) => (
                  <tr key={c.id} className="border-b last:border-b-0 hover:bg-gray-50/50">
                    <td className="px-4 py-3 font-medium">{c.check_type}</td>
                    <td className="px-4 py-3"><span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${STATUS_COLORS[c.status] || ""}`}>{c.status}</span></td>
                    <td className="px-4 py-3 text-gray-600 text-xs max-w-md truncate">{c.detail || "---"}</td>
                    <td className="px-4 py-3 text-gray-500">{c.response_ms ? `${c.response_ms}ms` : "---"}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">{c.checked_at ? new Date(c.checked_at).toLocaleString() : "---"}</td>
                  </tr>
                ))}
                {checks.length === 0 && <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-400">No checks yet</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
