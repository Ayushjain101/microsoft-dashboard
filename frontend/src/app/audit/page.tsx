"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { AuditEvent } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import { ScrollText, ChevronLeft, ChevronRight, Search } from "lucide-react";

const PAGE_SIZE = 50;

export default function AuditLogPage() {
  const authenticated = useAuth();
  const [offset, setOffset] = useState(0);
  const [tenantFilter, setTenantFilter] = useState("");
  const [jobFilter, setJobFilter] = useState("");

  const { data: events = [], isLoading } = useQuery<AuditEvent[]>({
    queryKey: ["audit", offset, tenantFilter, jobFilter],
    queryFn: () =>
      api.v2.listAuditEvents({
        tenant_id: tenantFilter || undefined,
        job_id: jobFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  if (authenticated === null) return null;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <ScrollText className="w-6 h-6" /> Audit Log
          </h1>
        </div>

        {/* Filters */}
        <div className="bg-white rounded-lg shadow-sm border p-4 mb-4 flex gap-4">
          <div className="flex items-center gap-2">
            <Search className="w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Filter by Tenant ID..."
              value={tenantFilter}
              onChange={(e) => { setTenantFilter(e.target.value); setOffset(0); }}
              className="border rounded px-3 py-1.5 text-sm w-72"
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Filter by Job ID..."
              value={jobFilter}
              onChange={(e) => { setJobFilter(e.target.value); setOffset(0); }}
              className="border rounded px-3 py-1.5 text-sm w-72"
            />
          </div>
        </div>

        {/* Table */}
        <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Event</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actor</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tenant</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Job</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400">Loading...</td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400">No audit events found.</td>
                </tr>
              ) : (
                events.map((evt) => (
                  <tr key={evt.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">
                      {new Date(evt.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2">
                      <span className="text-sm font-medium text-gray-900">{evt.event_type}</span>
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-500">{evt.actor}</td>
                    <td className="px-4 py-2 text-xs text-gray-400 font-mono">
                      {evt.tenant_id ? evt.tenant_id.slice(0, 8) + "..." : "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-400 font-mono">
                      {evt.job_id ? evt.job_id.slice(0, 8) + "..." : "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500 max-w-xs truncate">
                      {evt.payload ? JSON.stringify(evt.payload).slice(0, 100) : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          {/* Pagination */}
          <div className="flex items-center justify-between px-4 py-3 border-t bg-gray-50">
            <span className="text-sm text-gray-500">
              Showing {offset + 1}–{offset + events.length}
            </span>
            <div className="flex gap-2">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="px-3 py-1 text-sm border rounded hover:bg-gray-100 disabled:opacity-50"
              >
                <ChevronLeft className="w-4 h-4 inline" /> Prev
              </button>
              <button
                disabled={events.length < PAGE_SIZE}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="px-3 py-1 text-sm border rounded hover:bg-gray-100 disabled:opacity-50"
              >
                Next <ChevronRight className="w-4 h-4 inline" />
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
