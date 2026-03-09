"use client";

import { Fragment, useCallback, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Tenant, TenantDomain, WSEvent } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import TenantSetupProgress from "@/components/tenants/TenantSetupProgress";
import TenantHealthResults from "@/components/tenants/TenantHealthResults";
import SetupProgress from "@/components/tenants/SetupProgress";
import {
  Plus, Play, RotateCcw, Trash2, Download, ChevronDown, Pencil, X,
  HeartPulse, Loader2, Check, XCircle, FileDown, AlertTriangle,
  CheckCircle, Wrench, Search, Server,
} from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-600",
  queued: "bg-amber-50 text-amber-700 border border-amber-200",
  running: "bg-blue-50 text-blue-700 border border-blue-200",
  complete: "bg-emerald-50 text-emerald-700 border border-emerald-200",
  failed: "bg-red-50 text-red-700 border border-red-200",
};

export default function TenantsPage() {
  const authenticated = useAuth();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Record<string, WSEvent>>({});
  const [healthChecking, setHealthChecking] = useState<Record<string, boolean>>({});
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null);
  const [editPassword, setEditPassword] = useState("");
  const [editSaving, setEditSaving] = useState(false);
  const [fixing, setFixing] = useState<Record<string, boolean>>({});
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const { data, isLoading } = useQuery({
    queryKey: ["tenants", page, filter],
    queryFn: () => api.listTenants(page, filter || undefined),
  });

  const tenants = data?.tenants ?? [];
  const total = data?.total ?? 0;

  const onWsMessage = useCallback((event: WSEvent) => {
    if (event.type === "tenant_setup_progress" && event.tenant_id) {
      setProgress((prev) => ({ ...prev, [event.tenant_id!]: event }));
      if (event.status === "complete" || event.status === "failed") {
        if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ["tenants"] });
        }, 1000);
      }
    }
    if (event.type === "tenant_step_result" && event.tenant_id) {
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
    }
    if (event.type === "fix_health_result" && event.tenant_id) {
      setFixing((prev) => ({ ...prev, [event.tenant_id!]: false }));
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
    }
    if (event.type === "tenant_health_check" && event.tenant_id) {
      setHealthChecking((prev) => ({ ...prev, [event.tenant_id!]: false }));
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
    }
  }, [queryClient]);

  useWebSocket(onWsMessage);

  const filtered = searchQuery
    ? tenants.filter(
        (t) =>
          t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.admin_email.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : tenants;

  async function handleSetup(id: string) {
    try { await api.setupTenant(id); queryClient.invalidateQueries({ queryKey: ["tenants"] }); } catch (e: any) { alert(e.message); }
  }
  async function handleRetry(id: string) {
    try { await api.retryTenant(id); queryClient.invalidateQueries({ queryKey: ["tenants"] }); } catch (e: any) { alert(e.message); }
  }
  async function handleDelete(id: string) {
    if (!confirm("Delete this tenant?")) return;
    try { await api.deleteTenant(id); queryClient.invalidateQueries({ queryKey: ["tenants"] }); } catch (e: any) { alert(e.message); }
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
    try { await api.healthCheckTenant(id); } catch (e: any) {
      alert(e.message);
      setHealthChecking((prev) => ({ ...prev, [id]: false }));
    }
  }
  async function handleFixHealth(id: string) {
    setFixing((prev) => ({ ...prev, [id]: true }));
    try { await api.fixHealth(id); } catch (e: any) {
      alert(e.message);
      setFixing((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function handleBulkHealthCheck() {
    const ids = selectedIds.size > 0
      ? Array.from(selectedIds).filter(id => tenants.find(t => t.id === id && t.status === "complete"))
      : tenants.filter(t => t.status === "complete").map(t => t.id);
    if (ids.length === 0) { alert("No complete tenants to check"); return; }
    for (const id of ids) {
      setHealthChecking((prev) => ({ ...prev, [id]: true }));
      try { await api.healthCheckTenant(id); } catch {}
    }
  }

  async function handleBulkFixHealth() {
    const ids = selectedIds.size > 0
      ? Array.from(selectedIds).filter(id => {
          const t = tenants.find(t => t.id === id);
          return t?.status === "complete" && getHealthSummary(t)?.hasIssues;
        })
      : tenants.filter(t => t.status === "complete" && getHealthSummary(t)?.hasIssues).map(t => t.id);
    if (ids.length === 0) { alert("No tenants with fixable issues"); return; }
    for (const id of ids) {
      setFixing((prev) => ({ ...prev, [id]: true }));
      try { await api.fixHealth(id); } catch {}
    }
  }

  async function handleSavePassword() {
    if (!editingTenant || !editPassword.trim()) return;
    setEditSaving(true);
    try {
      await api.updateTenant(editingTenant.id, { admin_password: editPassword.trim() });
      setEditingTenant(null);
      setEditPassword("");
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
    } catch (e: any) { alert(e.message); }
    finally { setEditSaving(false); }
  }

  function getHealthSummary(t: Tenant): { hasIssues: boolean; issues: string[] } | null {
    if (!t.health_results) return null;
    const issues: string[] = [];
    for (const [key, result] of Object.entries(t.health_results)) {
      const r = result as any;
      if (r.status === "fail" || r.status === "warn") issues.push(r.message || `Check ${key}`);
    }
    return { hasIssues: issues.length > 0, issues };
  }

  function renderDomains(domains?: TenantDomain[]) {
    if (!domains || domains.length === 0) return <span className="text-xs text-gray-400">No domains</span>;
    return (
      <div className="flex flex-wrap gap-1.5">
        {domains.map((d) => (
          <span key={d.domain} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border">
            {d.domain}
            {d.is_verified ? <Check size={11} className="text-green-600" /> : <XCircle size={11} className="text-red-400" />}
            {d.dkim_enabled && <span className="text-[10px] font-semibold text-green-700 bg-green-100 px-1 rounded">DKIM</span>}
          </span>
        ))}
      </div>
    );
  }

  function renderExpandedContent(t: Tenant) {
    const hasStepResults = t.step_results && Object.keys(t.step_results).length > 0;
    const isRunning = t.status === "running" || t.status === "queued";
    const wsProgress = progress[t.id];

    if (isRunning) {
      if (hasStepResults) {
        return (
          <div>
            <TenantSetupProgress stepResults={t.step_results} tenantStatus={t.status} currentStep={wsProgress?.step || null} />
            {wsProgress && <p className="text-xs text-gray-500 mt-1">{wsProgress.message}</p>}
          </div>
        );
      }
      if (wsProgress) {
        return <SetupProgress currentStep={wsProgress.step || 0} totalSteps={wsProgress.total || 13} message={wsProgress.message || ""} status={wsProgress.status || t.status} />;
      }
    }

    if (t.status === "complete") {
      return (
        <div className="space-y-4">
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Domains</p>
            {renderDomains(t.domains)}
          </div>
          {hasStepResults && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Setup Steps</p>
              <TenantSetupProgress stepResults={t.step_results} tenantStatus={t.status} currentStep={null} />
            </div>
          )}
          <div className="border-t pt-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Health Check</p>
            {healthChecking[t.id] ? (
              <div className="flex items-center gap-2 text-sm text-purple-600">
                <Loader2 size={14} className="animate-spin" /> Running health check...
              </div>
            ) : t.health_results ? (
              <TenantHealthResults healthResults={t.health_results} lastHealthCheck={t.last_health_check} />
            ) : (
              <span className="text-xs text-gray-400">Not run yet</span>
            )}
          </div>
          <div className="text-xs text-gray-400 pt-1">
            Created: {new Date(t.created_at).toLocaleString()}
            {t.completed_at && <> | Completed: {new Date(t.completed_at).toLocaleString()}</>}
          </div>
        </div>
      );
    }

    if (hasStepResults) {
      return (
        <div>
          <TenantSetupProgress stepResults={t.step_results} tenantStatus={t.status} currentStep={null} />
          {t.error_message && (
            <div className="bg-red-50 border border-red-200 p-3 rounded-lg text-sm text-red-700 mt-2">
              <strong>Error:</strong> {t.error_message}
            </div>
          )}
        </div>
      );
    }

    if (t.error_message) {
      return (
        <div className="bg-red-50 border border-red-200 p-3 rounded-lg text-sm text-red-700">
          <strong>Error:</strong> {t.error_message}
        </div>
      );
    }

    return (
      <div className="text-sm text-gray-500">
        Created: {new Date(t.created_at).toLocaleString()}
      </div>
    );
  }

  if (authenticated === null) return null;

  const completeTenantCount = tenants.filter(t => t.status === "complete").length;
  const failedTenantCount = tenants.filter(t => t.status === "failed").length;
  const runningTenantCount = tenants.filter(t => t.status === "running" || t.status === "queued").length;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        {/* Edit Password Modal */}
        {editingTenant && (
          <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-lg">Edit Password</h3>
                <button onClick={() => { setEditingTenant(null); setEditPassword(""); }} className="p-1.5 hover:bg-gray-100 rounded-lg"><X size={18} /></button>
              </div>
              <p className="text-sm text-gray-500 mb-4">{editingTenant.name} ({editingTenant.admin_email})</p>
              <input
                type="text"
                value={editPassword}
                onChange={(e) => setEditPassword(e.target.value)}
                placeholder="Enter new password"
                className="w-full px-4 py-2.5 border rounded-lg text-sm mb-4 focus:ring-2 focus:ring-blue-500 focus:outline-none"
                autoFocus
              />
              <div className="flex justify-end gap-2">
                <button onClick={() => { setEditingTenant(null); setEditPassword(""); }} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
                <button onClick={handleSavePassword} disabled={editSaving || !editPassword.trim()} className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                  {editSaving ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="p-6 max-w-[1400px] mx-auto">
          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Tenants</h1>
              <p className="text-sm text-gray-500 mt-0.5">{total} total tenants</p>
            </div>
            <Link href="/tenants/new" className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2.5 rounded-lg hover:bg-blue-700 text-sm font-medium shadow-sm">
              <Plus size={16} /> Add Tenants
            </Link>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-4 gap-3 mb-5">
            <div className="bg-white rounded-xl border p-3.5 flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center"><Server size={18} className="text-blue-600" /></div>
              <div><p className="text-2xl font-bold">{total}</p><p className="text-xs text-gray-500">Total</p></div>
            </div>
            <div className="bg-white rounded-xl border p-3.5 flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center"><CheckCircle size={18} className="text-emerald-600" /></div>
              <div><p className="text-2xl font-bold text-emerald-600">{completeTenantCount}</p><p className="text-xs text-gray-500">Complete</p></div>
            </div>
            <div className="bg-white rounded-xl border p-3.5 flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center"><Loader2 size={18} className="text-blue-600" /></div>
              <div><p className="text-2xl font-bold text-blue-600">{runningTenantCount}</p><p className="text-xs text-gray-500">Running</p></div>
            </div>
            <div className="bg-white rounded-xl border p-3.5 flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-red-50 flex items-center justify-center"><XCircle size={18} className="text-red-600" /></div>
              <div><p className="text-2xl font-bold text-red-600">{failedTenantCount}</p><p className="text-xs text-gray-500">Failed</p></div>
            </div>
          </div>

          {/* Search & Filter Bar */}
          <div className="bg-white rounded-xl border p-3 mb-4 flex items-center gap-3">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search by name or email..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              />
            </div>
            <div className="flex gap-1.5">
              {["", "pending", "queued", "running", "complete", "failed"].map((s) => (
                <button
                  key={s}
                  onClick={() => { setFilter(s); setPage(1); }}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    filter === s ? "bg-blue-600 text-white" : "bg-gray-50 text-gray-600 hover:bg-gray-100 border"
                  }`}
                >
                  {s || "All"}
                </button>
              ))}
            </div>
          </div>

          {/* Action Bar */}
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            <button onClick={() => api.exportTenantsCsv()} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-white border rounded-lg hover:bg-gray-50">
              <FileDown size={14} /> Export All
            </button>
            <button onClick={handleBulkHealthCheck} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-purple-600 text-white rounded-lg hover:bg-purple-700">
              <HeartPulse size={14} /> Health Check {selectedIds.size > 0 ? `(${Array.from(selectedIds).filter(id => tenants.find(t => t.id === id && t.status === "complete")).length})` : `(${completeTenantCount})`}
            </button>
            {tenants.some(t => getHealthSummary(t)?.hasIssues) && (
              <button onClick={handleBulkFixHealth} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-orange-500 text-white rounded-lg hover:bg-orange-600">
                <Wrench size={14} /> Fix Issues
              </button>
            )}
            {selectedIds.size > 0 && (
              <button onClick={() => api.exportTenantsCsv(Array.from(selectedIds))} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                <FileDown size={14} /> Export Selected ({selectedIds.size})
              </button>
            )}
          </div>

          {/* Table */}
          <div className="bg-white rounded-xl border overflow-hidden shadow-sm">
            {isLoading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50/80 border-b">
                    <th className="w-10 px-4 py-3">
                      <input type="checkbox" checked={filtered.length > 0 && selectedIds.size === filtered.length} onChange={(e) => setSelectedIds(e.target.checked ? new Set(filtered.map(t => t.id)) : new Set())} className="rounded" />
                    </th>
                    <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Name</th>
                    <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Admin Email</th>
                    <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Status</th>
                    <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Info</th>
                    <th className="text-right px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((t) => (
                    <Fragment key={t.id}>
                      <tr className="border-b last:border-b-0 hover:bg-gray-50/50 transition-colors">
                        <td className="w-10 px-4 py-3">
                          <input type="checkbox" checked={selectedIds.has(t.id)} onChange={(e) => {
                            setSelectedIds(prev => { const next = new Set(prev); if (e.target.checked) next.add(t.id); else next.delete(t.id); return next; });
                          }} className="rounded" />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${(t.mailbox_count || 0) > 0 ? "bg-green-500" : "bg-gray-300"}`} title={t.mailbox_count ? `${t.mailbox_count} mailboxes` : "No mailboxes"} />
                            <span className="font-medium text-gray-900">{t.name}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-gray-600">{t.admin_email}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1.5">
                            <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${STATUS_COLORS[t.status] || ""}`}>{t.status}</span>
                            {healthChecking[t.id] && <Loader2 size={13} className="text-purple-500 animate-spin" />}
                            {!healthChecking[t.id] && (() => {
                              const health = getHealthSummary(t);
                              if (!health) return null;
                              return health.hasIssues
                                ? <span title={`${health.issues.length} issue(s)`}><AlertTriangle size={13} className="text-red-500" /></span>
                                : <span title="All checks passed"><CheckCircle size={13} className="text-green-500" /></span>;
                            })()}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-xs max-w-[350px]">
                          {t.error_message ? (
                            <span className="text-red-600 truncate block" title={t.error_message}>
                              {t.error_message.length > 60 ? t.error_message.slice(0, 60) + "..." : t.error_message}
                            </span>
                          ) : (() => {
                            const health = getHealthSummary(t);
                            if (health?.hasIssues) {
                              return (
                                <div className="flex flex-wrap items-center gap-1">
                                  {health.issues.slice(0, 2).map((issue, i) => (
                                    <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-50 text-red-700 border border-red-200" title={issue}>
                                      {issue.length > 30 ? issue.slice(0, 30) + "..." : issue}
                                    </span>
                                  ))}
                                  {health.issues.length > 2 && <span className="text-[10px] text-gray-400">+{health.issues.length - 2}</span>}
                                  <button onClick={(e) => { e.stopPropagation(); handleFixHealth(t.id); }} disabled={fixing[t.id]} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-50 text-orange-700 border border-orange-300 hover:bg-orange-100 disabled:opacity-50">
                                    {fixing[t.id] ? <Loader2 size={10} className="animate-spin" /> : <Wrench size={10} />} Fix
                                  </button>
                                </div>
                              );
                            }
                            if (health && !health.hasIssues) return <span className="text-green-600 font-medium">All checks passed</span>;
                            return <span className="text-gray-400">{t.current_step || "---"}</span>;
                          })()}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-0.5">
                            {(t.status === "pending" || t.status === "failed") && (
                              <button onClick={() => { setEditingTenant(t); setEditPassword(""); }} className="p-1.5 hover:bg-gray-100 rounded-lg" title="Edit Password"><Pencil size={15} className="text-gray-500" /></button>
                            )}
                            {t.status === "pending" && (
                              <button onClick={() => handleSetup(t.id)} className="p-1.5 hover:bg-blue-50 rounded-lg" title="Start Setup"><Play size={15} className="text-blue-600" /></button>
                            )}
                            {t.status === "failed" && (
                              <button onClick={() => handleRetry(t.id)} className="p-1.5 hover:bg-yellow-50 rounded-lg" title="Retry"><RotateCcw size={15} className="text-yellow-600" /></button>
                            )}
                            {t.status === "complete" && (
                              <>
                                <button onClick={() => handleHealthCheck(t.id)} disabled={healthChecking[t.id]} className="p-1.5 hover:bg-purple-50 rounded-lg disabled:opacity-50" title="Health Check">
                                  {healthChecking[t.id] ? <Loader2 size={15} className="text-purple-600 animate-spin" /> : <HeartPulse size={15} className="text-purple-600" />}
                                </button>
                                <button onClick={() => handleDownload(t.id)} className="p-1.5 hover:bg-green-50 rounded-lg" title="Download Credentials"><Download size={15} className="text-green-600" /></button>
                              </>
                            )}
                            <button onClick={() => handleDelete(t.id)} className="p-1.5 hover:bg-red-50 rounded-lg" title="Delete"><Trash2 size={15} className="text-red-500" /></button>
                            <button onClick={() => setExpandedId(expandedId === t.id ? null : t.id)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                              <ChevronDown size={15} className={`text-gray-400 transition-transform ${expandedId === t.id ? "rotate-180" : ""}`} />
                            </button>
                          </div>
                        </td>
                      </tr>
                      {expandedId === t.id && (
                        <tr className="bg-gray-50/50">
                          <td colSpan={6} className="px-6 py-4">{renderExpandedContent(t)}</td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                  {filtered.length === 0 && !isLoading && (
                    <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-400">No tenants found</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </div>

          {/* Pagination */}
          {total > 50 && (
            <div className="flex items-center justify-between mt-4">
              <span className="text-sm text-gray-500">Page {page} of {Math.ceil(total / 50)}</span>
              <div className="flex gap-2">
                <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="px-4 py-2 bg-white border rounded-lg text-sm disabled:opacity-50 hover:bg-gray-50">Previous</button>
                <button onClick={() => setPage((p) => p + 1)} disabled={page * 50 >= total} className="px-4 py-2 bg-white border rounded-lg text-sm disabled:opacity-50 hover:bg-gray-50">Next</button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
