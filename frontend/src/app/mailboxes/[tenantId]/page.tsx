"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Mailbox } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import { Download, Search, ArrowLeft, Loader2 } from "lucide-react";

export default function TenantMailboxesPage() {
  const authenticated = useAuth();
  const params = useParams();
  const router = useRouter();
  const tenantId = params.tenantId as string;
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["mailboxes", tenantId],
    queryFn: () => api.listMailboxes(tenantId),
  });

  const mailboxes: Mailbox[] = data?.mailboxes ?? [];

  const filtered = mailboxes.filter(m => {
    if (searchQuery && !m.email.toLowerCase().includes(searchQuery.toLowerCase()) && !m.display_name?.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    if (statusFilter === "smtp_enabled" && !m.smtp_enabled) return false;
    if (statusFilter === "smtp_disabled" && m.smtp_enabled) return false;
    if (statusFilter === "healthy" && m.last_monitor_status !== "pass") return false;
    if (statusFilter === "unhealthy" && (m.last_monitor_status === "pass" || !m.last_monitor_status)) return false;
    return true;
  });

  function handleExport() {
    api.exportMailboxesCsv(tenantId);
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
            <h1 className="text-2xl font-bold">Mailboxes</h1>
            <p className="text-sm text-gray-500 mt-0.5">{mailboxes.length} mailboxes for tenant {tenantId.slice(0, 8)}...</p>
          </div>
          <button onClick={handleExport} className="flex items-center gap-2 bg-emerald-600 text-white px-4 py-2.5 rounded-lg hover:bg-emerald-700 text-sm font-medium shadow-sm">
            <Download size={16} /> Export CSV
          </button>
        </div>

        {/* Filters */}
        <div className="bg-white rounded-xl border p-3 mb-4 flex items-center gap-3">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input type="text" placeholder="Search by email or display name..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="w-full pl-9 pr-4 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/30" />
          </div>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="px-3 py-2 border rounded-lg text-sm focus:outline-none">
            <option value="">All Status</option>
            <option value="smtp_enabled">SMTP Enabled</option>
            <option value="smtp_disabled">SMTP Disabled</option>
            <option value="healthy">Healthy</option>
            <option value="unhealthy">Unhealthy</option>
          </select>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-blue-600" /></div>
        ) : (
          <div className="bg-white rounded-xl border overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50/80 border-b">
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Email</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Display Name</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">SMTP</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Health</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Created</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((m) => (
                  <tr key={m.id} className="border-b last:border-b-0 hover:bg-gray-50/50">
                    <td className="px-4 py-3 font-medium">{m.email}</td>
                    <td className="px-4 py-3 text-gray-600">{m.display_name || "---"}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${m.smtp_enabled ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-gray-100 text-gray-600"}`}>
                        {m.smtp_enabled ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {m.last_monitor_status ? (
                        <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${
                          m.last_monitor_status === "pass" ? "bg-emerald-50 text-emerald-700 border border-emerald-200" :
                          m.last_monitor_status === "fail" ? "bg-red-50 text-red-700 border border-red-200" :
                          "bg-amber-50 text-amber-700 border border-amber-200"
                        }`}>{m.last_monitor_status === "pass" ? "healthy" : m.last_monitor_status}</span>
                      ) : <span className="text-gray-400">---</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">{new Date(m.created_at).toLocaleString()}</td>
                  </tr>
                ))}
                {filtered.length === 0 && <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-400">{searchQuery || statusFilter ? "No matching mailboxes" : "No mailboxes"}</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
