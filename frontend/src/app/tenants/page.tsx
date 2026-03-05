"use client";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Tenant, TenantDomain, WSEvent } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import SetupProgress from "@/components/tenants/SetupProgress";
import TenantSetupProgress from "@/components/tenants/TenantSetupProgress";
import TenantHealthResults from "@/components/tenants/TenantHealthResults";
import { Plus, Play, RotateCcw, Trash2, Download, ChevronDown, Pencil, X, HeartPulse, Loader2, Check, XCircle } from "lucide-react";

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
  const [healthChecking, setHealthChecking] = useState<Record<string, boolean>>({});
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null);
  const [editPassword, setEditPassword] = useState("");
  const [editSaving, setEditSaving] = useState(false);

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
      setTenants((prev) =>
        prev.map((t) =>
          t.id === event.tenant_id
            ? { ...t, status: event.status || t.status, current_step: event.step ? `Step ${event.step}/${event.total}: ${event.message}` : t.current_step }
            : t
        )
      );
      if (event.status === "complete" || event.status === "failed") {
        if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = setTimeout(loadTenants, 1000);
      }
    }
    // Handle step result events — update tenant's step_results inline
    if (event.type === "tenant_step_result" && event.tenant_id) {
      setTenants((prev) =>
        prev.map((t) => {
          if (t.id !== event.tenant_id) return t;
          const updated = { ...(t.step_results || {}) };
          updated[String(event.step)] = {
            status: event.step_status as any,
            message: event.message || "",
            detail: event.detail || undefined,
          };
          return { ...t, step_results: updated };
        })
      );
    }
    // Handle health check events
    if (event.type === "tenant_health_check" && event.tenant_id) {
      setHealthChecking((prev) => ({ ...prev, [event.tenant_id!]: false }));
      setTenants((prev) =>
        prev.map((t) =>
          t.id === event.tenant_id
            ? { ...t, health_results: event.health_results, last_health_check: event.last_health_check }
            : t
        )
      );
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
  async function handleHealthCheck(id: string) {
    setHealthChecking((prev) => ({ ...prev, [id]: true }));
    setExpandedId(id);
    try {
      await api.healthCheckTenant(id);
    } catch (e: any) {
      alert(e.message);
      setHealthChecking((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function handleSavePassword() {
    if (!editingTenant || !editPassword.trim()) return;
    setEditSaving(true);
    try {
      await api.updateTenant(editingTenant.id, { admin_password: editPassword.trim() });
      setEditingTenant(null);
      setEditPassword("");
      loadTenants();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setEditSaving(false);
    }
  }

  function renderDomains(domains?: TenantDomain[]) {
    if (!domains || domains.length === 0) {
      return <span className="text-xs text-gray-400">No domains</span>;
    }
    return (
      <div className="flex flex-wrap gap-1.5">
        {domains.map((d) => (
          <span
            key={d.domain}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700"
          >
            {d.domain}
            {d.is_verified ? (
              <Check size={12} className="text-green-600" />
            ) : (
              <XCircle size={12} className="text-red-400" />
            )}
            {d.dkim_enabled && (
              <span className="text-[10px] font-semibold text-green-700 bg-green-100 px-1 rounded">DKIM</span>
            )}
          </span>
        ))}
      </div>
    );
  }

  function renderHealthSection(t: Tenant) {
    if (healthChecking[t.id]) {
      return (
        <div className="flex items-center gap-2 text-sm text-purple-600">
          <Loader2 size={14} className="animate-spin" />
          Running health check...
        </div>
      );
    }
    if (t.health_results) {
      return <TenantHealthResults healthResults={t.health_results} lastHealthCheck={t.last_health_check} />;
    }
    return <span className="text-xs text-gray-400">Not run yet</span>;
  }

  function renderExpandedContent(t: Tenant) {
    const hasStepResults = t.step_results && Object.keys(t.step_results).length > 0;
    const isRunning = t.status === "running" || t.status === "queued";
    const wsProgress = progress[t.id];

    // Running/queued tenants: show step results grid if available, else legacy progress bar
    if (isRunning) {
      if (hasStepResults) {
        return (
          <div>
            <TenantSetupProgress
              stepResults={t.step_results}
              tenantStatus={t.status}
              currentStep={wsProgress?.step || null}
            />
            {wsProgress && (
              <p className="text-xs text-gray-500 mt-1">{wsProgress.message}</p>
            )}
          </div>
        );
      }
      if (wsProgress) {
        return (
          <SetupProgress
            currentStep={wsProgress.step || 0}
            totalSteps={wsProgress.total || 13}
            message={wsProgress.message || ""}
            status={wsProgress.status || t.status}
          />
        );
      }
    }

    // Complete tenants: structured layout with domains, steps, health, timestamps
    if (t.status === "complete") {
      return (
        <div className="space-y-3">
          <div>
            <p className="text-xs font-medium text-gray-600 mb-1">Domains</p>
            {renderDomains(t.domains)}
          </div>
          {hasStepResults && (
            <div>
              <TenantSetupProgress
                stepResults={t.step_results}
                tenantStatus={t.status}
                currentStep={null}
              />
            </div>
          )}
          <div className="border-t pt-3">
            <p className="text-xs font-medium text-gray-600 mb-1">Health Check</p>
            {renderHealthSection(t)}
          </div>
          <div className="text-xs text-gray-400">
            Created: {new Date(t.created_at).toLocaleString()}
            {t.completed_at && <> | Completed: {new Date(t.completed_at).toLocaleString()}</>}
          </div>
        </div>
      );
    }

    // Failed tenants with step_results: show the grid + error
    if (hasStepResults) {
      return (
        <div>
          <TenantSetupProgress
            stepResults={t.step_results}
            tenantStatus={t.status}
            currentStep={null}
          />
          {t.error_message && (
            <div className="bg-red-50 p-3 rounded text-sm text-red-700 mt-2">
              <strong>Error:</strong> {t.error_message}
            </div>
          )}
        </div>
      );
    }

    // Failed without step_results: show error
    if (t.error_message) {
      return (
        <div className="bg-red-50 p-3 rounded text-sm text-red-700">
          <strong>Error:</strong> {t.error_message}
        </div>
      );
    }

    // Default
    return (
      <div className="text-sm text-gray-500">
        Created: {new Date(t.created_at).toLocaleString()}
        {t.completed_at && <> | Completed: {new Date(t.completed_at).toLocaleString()}</>}
      </div>
    );
  }

  return (
    <div>
      {/* Edit Password Modal */}
      {editingTenant && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold">Edit Password</h3>
              <button onClick={() => { setEditingTenant(null); setEditPassword(""); }} className="p-1 hover:bg-gray-100 rounded">
                <X size={18} />
              </button>
            </div>
            <p className="text-sm text-gray-500 mb-3">{editingTenant.name} ({editingTenant.admin_email})</p>
            <div className="mb-4">
              <label className="block text-sm font-medium mb-1">New Password</label>
              <input
                type="text"
                value={editPassword}
                onChange={(e) => setEditPassword(e.target.value)}
                placeholder="Enter new password"
                className="w-full px-3 py-2 border rounded-lg text-sm"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setEditingTenant(null); setEditPassword(""); }}
                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleSavePassword}
                disabled={editSaving || !editPassword.trim()}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {editSaving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

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
                  <td className="px-4 py-3 font-medium">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${(t.mailbox_count || 0) > 0 ? "bg-green-500" : "bg-gray-300"}`}
                        title={t.mailbox_count ? `${t.mailbox_count} mailboxes` : "No mailboxes"}
                      />
                      {t.name}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{t.admin_email}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[t.status] || ""}`}>
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs max-w-[300px]">
                    {t.error_message ? (
                      <span className="text-red-600 truncate block" title={t.error_message}>
                        {t.error_message.length > 80 ? t.error_message.slice(0, 80) + "…" : t.error_message}
                      </span>
                    ) : (
                      <span className="text-gray-500">{t.current_step || "—"}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {(t.status === "pending" || t.status === "failed") && (
                        <button onClick={() => { setEditingTenant(t); setEditPassword(""); }} className="p-1 hover:bg-gray-100 rounded" title="Edit Password">
                          <Pencil size={16} className="text-gray-500" />
                        </button>
                      )}
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
                        <>
                          <button
                            onClick={() => handleHealthCheck(t.id)}
                            disabled={healthChecking[t.id]}
                            className="p-1 hover:bg-purple-50 rounded disabled:opacity-50"
                            title="Health Check"
                          >
                            {healthChecking[t.id] ? (
                              <Loader2 size={16} className="text-purple-600 animate-spin" />
                            ) : (
                              <HeartPulse size={16} className="text-purple-600" />
                            )}
                          </button>
                          <button onClick={() => handleDownload(t.id)} className="p-1 hover:bg-green-50 rounded" title="Download Credentials">
                            <Download size={16} className="text-green-600" />
                          </button>
                        </>
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
                      {renderExpandedContent(t)}
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
