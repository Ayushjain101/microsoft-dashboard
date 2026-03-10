"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { AuditEvent } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import { ScrollText, ChevronLeft, ChevronRight, Search, Loader2, X } from "lucide-react";

const PAGE_SIZE = 50;

export default function AuditLogPage() {
  const authenticated = useAuth();
  const [offset, setOffset] = useState(0);
  const [tenantFilter, setTenantFilter] = useState("");
  const [jobFilter, setJobFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");

  const { data: events = [], isLoading } = useQuery<AuditEvent[]>({
    queryKey: ["audit", offset, tenantFilter, jobFilter],
    queryFn: () => api.listAuditEvents({ tenant_id: tenantFilter || undefined, job_id: jobFilter || undefined, limit: PAGE_SIZE, offset }),
  });

  const filtered = eventTypeFilter
    ? events.filter(e => e.event_type.toLowerCase().includes(eventTypeFilter.toLowerCase()))
    : events;

  if (authenticated === null) return null;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <div className="max-w-[1400px] mx-auto">
          <div className="mb-6">
            <h1 className="text-2xl font-bold flex items-center gap-2"><ScrollText size={24} className="text-blue-600" /> Audit Log</h1>
            <p className="text-sm text-gray-500 mt-0.5">Track all system events and actions</p>
          </div>

          {/* Filters */}
          <div className="bg-white rounded-xl border p-3 mb-4 flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[200px]">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input type="text" placeholder="Filter by event type..." value={eventTypeFilter} onChange={(e) => setEventTypeFilter(e.target.value)} className="w-full pl-9 pr-4 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/30" />
            </div>
            <div className="relative">
              <input type="text" placeholder="Tenant ID..." value={tenantFilter} onChange={(e) => { setTenantFilter(e.target.value); setOffset(0); }} className="pl-3 pr-8 py-2 border rounded-lg text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-500/30" />
              {tenantFilter && <button onClick={() => setTenantFilter("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"><X size={14} /></button>}
            </div>
            <div className="relative">
              <input type="text" placeholder="Job ID..." value={jobFilter} onChange={(e) => { setJobFilter(e.target.value); setOffset(0); }} className="pl-3 pr-8 py-2 border rounded-lg text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-500/30" />
              {jobFilter && <button onClick={() => setJobFilter("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"><X size={14} /></button>}
            </div>
          </div>

          {/* Table */}
          <div className="bg-white rounded-xl border overflow-hidden shadow-sm">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr className="bg-gray-50/80">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Time</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Event</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Actor</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Tenant</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Job</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {isLoading ? (
                  <tr><td colSpan={6} className="px-4 py-12 text-center"><Loader2 className="w-6 h-6 animate-spin text-blue-600 mx-auto" /></td></tr>
                ) : filtered.length === 0 ? (
                  <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-400">No audit events found.</td></tr>
                ) : (
                  filtered.map((evt) => (
                    <tr key={evt.id} className="hover:bg-gray-50/50 transition-colors">
                      <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">{new Date(evt.created_at).toLocaleString()}</td>
                      <td className="px-4 py-2.5"><span className="text-sm font-medium text-gray-900 bg-gray-100 px-2 py-0.5 rounded">{evt.event_type}</span></td>
                      <td className="px-4 py-2.5 text-sm text-gray-500">{evt.actor}</td>
                      <td className="px-4 py-2.5 text-xs text-gray-400 font-mono">{evt.tenant_id ? evt.tenant_id.slice(0, 8) + "..." : "---"}</td>
                      <td className="px-4 py-2.5 text-xs text-gray-400 font-mono">{evt.job_id ? evt.job_id.slice(0, 8) + "..." : "---"}</td>
                      <td className="px-4 py-2.5 text-xs text-gray-500 max-w-xs truncate">{evt.payload ? JSON.stringify(evt.payload).slice(0, 100) : "---"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>

            <div className="flex items-center justify-between px-4 py-3 border-t bg-gray-50/80">
              <span className="text-sm text-gray-500">Showing {offset + 1} – {offset + filtered.length}</span>
              <div className="flex gap-2">
                <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="px-3 py-1.5 text-sm border rounded-lg hover:bg-white disabled:opacity-50 flex items-center gap-1"><ChevronLeft className="w-4 h-4" /> Prev</button>
                <button disabled={events.length < PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)} className="px-3 py-1.5 text-sm border rounded-lg hover:bg-white disabled:opacity-50 flex items-center gap-1">Next <ChevronRight className="w-4 h-4" /></button>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
