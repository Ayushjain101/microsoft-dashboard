"use client";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Tenant, WSEvent } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import SetupProgress from "@/components/tenants/SetupProgress";
import { Plus, Play, RotateCcw, Trash2, Download, ChevronDown } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-700",
  queued: "bg-yellow-100 text-yellow-700",
  running: "bg-blue-100 text-blue-700",
  complete: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Record<string, WSEvent>>({});
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const loadTenants = useCallback(async () => {
    try {
      const data = await api.listTenants(page, filter || undefined);
      setTenants(data.tenants);
      setTotal(data.total);
    } catch (e: any) {
      console.error("Failed to load tenants:", e);
      alert("Failed to load tenants: " + e.message);
    }
  }, [page, filter]);

  useEffect(() => { loadTenants(); }, [loadTenants]);

  // Cleanup refresh timer on unmount
  useEffect(() => {
    return () => { if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current); };
  }, []);

  const onWsMessage = useCallback((event: WSEvent) => {
    if (event.type === "tenant_setup_progress" && event.tenant_id) {
      setProgress((prev) => ({ ...prev, [event.tenant_id!]: event }));
      // Update tenant inline from WS data so main row reflects progress
      setTenants((prev) =>
        prev.map((t) =>
          t.id === event.tenant_id
            ? { ...t, status: event.status || t.status, current_step: event.step ? `Step ${event.step}/${event.total}: ${event.message}` : t.current_step }
            : t
        )
      );
      // Refresh list if status changed
      if (event.status === "complete" || event.status === "failed") {
        if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = setTimeout(loadTenants, 1000);
      }
    }
  }, [loadTenants]);

  useWebSocket(onWsMessage);

  async function handleSetup(id: string) {
    try { await api.setupTenant(id); loadTenants(); } catch (e: any) { alert(e.message); }
  }
  async function handleRetry(id: string) {
    try { await api.retryTenant(id); loadTenants(); } catch (e: any) { alert(e.message); }
  }
  async function handleDelete(id: string) {
    if (!confirm("Delete this tenant?")) return;
    try { await api.deleteTenant(id); loadTenants(); } catch (e: any) { alert(e.message); }
  }
  async function handleDownload(id: string) {
    try {
      const creds = await api.getCredentials(id);
      const blob = new Blob([JSON.stringify(creds, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `credentials_${id}.json`; a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) { alert(e.message); }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Tenant Setup</h1>
        <Link
          href="/tenants/new"
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm"
        >
          <Plus size={16} /> Add Tenants
        </Link>
      </div>

      {/* Filter */}
      <div className="flex gap-2 mb-4">
        {["", "pending", "queued", "running", "complete", "failed"].map((s) => (
          <button
            key={s}
            onClick={() => { setFilter(s); setPage(1); }}
            className={`px-3 py-1 rounded-full text-xs ${
              filter === s ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {s || "All"}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left px-4 py-3 font-medium">Name</th>
              <th className="text-left px-4 py-3 font-medium">Admin Email</th>
              <th className="text-left px-4 py-3 font-medium">Status</th>
              <th className="text-left px-4 py-3 font-medium">Step</th>
              <th className="text-right px-4 py-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {tenants.map((t) => (
              <Fragment key={t.id}>
                <tr className="border-t hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{t.name}</td>
                  <td className="px-4 py-3 text-gray-600">{t.admin_email}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[t.status] || ""}`}>
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{t.current_step || "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {t.status === "pending" && (
                        <button onClick={() => handleSetup(t.id)} className="p-1 hover:bg-blue-50 rounded" title="Start Setup">
                          <Play size={16} className="text-blue-600" />
                        </button>
                      )}
                      {t.status === "failed" && (
                        <button onClick={() => handleRetry(t.id)} className="p-1 hover:bg-yellow-50 rounded" title="Retry">
                          <RotateCcw size={16} className="text-yellow-600" />
                        </button>
                      )}
                      {t.status === "complete" && (
                        <button onClick={() => handleDownload(t.id)} className="p-1 hover:bg-green-50 rounded" title="Download Credentials">
                          <Download size={16} className="text-green-600" />
                        </button>
                      )}
                      <button onClick={() => handleDelete(t.id)} className="p-1 hover:bg-red-50 rounded" title="Delete">
                        <Trash2 size={16} className="text-red-500" />
                      </button>
                      <button
                        onClick={() => setExpandedId(expandedId === t.id ? null : t.id)}
                        className="p-1 hover:bg-gray-100 rounded"
                      >
                        <ChevronDown size={16} className={`transition-transform ${expandedId === t.id ? "rotate-180" : ""}`} />
                      </button>
                    </div>
                  </td>
                </tr>
                {expandedId === t.id && (
                  <tr key={`${t.id}-exp`} className="border-t bg-gray-50">
                    <td colSpan={5} className="px-4 py-4">
                      {(t.status === "running" || t.status === "queued") && progress[t.id] ? (
                        <SetupProgress
                          currentStep={progress[t.id].step || 0}
                          totalSteps={progress[t.id].total || 12}
                          message={progress[t.id].message || ""}
                          status={progress[t.id].status || t.status}
                        />
                      ) : t.error_message ? (
                        <div className="bg-red-50 p-3 rounded text-sm text-red-700">
                          <strong>Error:</strong> {t.error_message}
                        </div>
                      ) : (
                        <div className="text-sm text-gray-500">
                          Created: {new Date(t.created_at).toLocaleString()}
                          {t.completed_at && <> | Completed: {new Date(t.completed_at).toLocaleString()}</>}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {tenants.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No tenants found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > 50 && (
        <div className="flex justify-center gap-2 mt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 bg-white border rounded text-sm disabled:opacity-50"
          >
            Previous
          </button>
          <span className="px-3 py-1 text-sm text-gray-600">
            Page {page} of {Math.ceil(total / 50)}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page * 50 >= total}
            className="px-3 py-1 bg-white border rounded text-sm disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
