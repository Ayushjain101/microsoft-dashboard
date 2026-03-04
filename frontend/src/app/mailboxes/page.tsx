"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Tenant, MailboxJob, WSEvent } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Plus, StopCircle, Download, ChevronDown, ChevronRight, Shield, ShieldCheck, Loader2 } from "lucide-react";
import MailboxPipelineProgress from "@/components/mailboxes/MailboxPipelineProgress";

export default function MailboxesPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [jobs, setJobs] = useState<MailboxJob[]>([]);
  const [selectedTenant, setSelectedTenant] = useState("");
  const [domain, setDomain] = useState("");
  const [count, setCount] = useState(50);
  const [cfEmail, setCfEmail] = useState("");
  const [cfApiKey, setCfApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set());
  const [dkimLoading, setDkimLoading] = useState<Set<string>>(new Set());

  const loadData = useCallback(async () => {
    try {
      const [t, j] = await Promise.all([api.listTenants(1, "complete"), api.listMailboxJobs()]);
      setTenants(t.tenants);
      setJobs(j.jobs);
    } catch {}
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const onWsMessage = useCallback((event: WSEvent) => {
    if (event.type === "mailbox_pipeline_progress") {
      loadData();
    }
    if (event.type === "mailbox_step_result" && event.job_id) {
      setJobs(prev => prev.map(j => {
        if (j.id !== event.job_id) return j;
        const updated = { ...(j.step_results || {}) };
        if (event.step) {
          updated[String(event.step)] = {
            status: event.step_status as any,
            message: event.message || "",
            detail: event.detail,
          };
        }
        return { ...j, step_results: updated };
      }));
    }
    if (event.type === "dkim_enabled" && event.job_id) {
      setDkimLoading(prev => { const n = new Set(prev); n.delete(event.job_id!); return n; });
      if (event.success) {
        setJobs(prev => prev.map(j =>
          j.id === event.job_id ? { ...j, dkim_enabled: true } : j
        ));
      } else {
        alert(`DKIM enable failed: ${event.error || "Unknown error"}`);
      }
    }
  }, [loadData]);

  useWebSocket(onWsMessage);

  function toggleExpanded(jobId: string) {
    setExpandedJobs(prev => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedTenant || !domain) return;
    setLoading(true);
    try {
      await api.createMailboxes(selectedTenant, {
        domain, mailbox_count: count,
        cf_email: cfEmail || undefined,
        cf_api_key: cfApiKey || undefined,
      });
      loadData();
      setDomain(""); setCfEmail(""); setCfApiKey("");
    } catch (err: any) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleEnableDkim(jobId: string) {
    setDkimLoading(prev => new Set(prev).add(jobId));
    try {
      await api.enableDkim(jobId);
    } catch (err: any) {
      setDkimLoading(prev => { const n = new Set(prev); n.delete(jobId); return n; });
      alert(err.message);
    }
  }

  async function handleExport(tenantId: string) {
    window.open(`/api/v1/mailboxes/${tenantId}/export`, "_blank");
  }

  // Parse current step number from phase string like "Step 3/9: Add Domain"
  function parseCurrentStep(phase: string | null): number | null {
    if (!phase) return null;
    const m = phase.match(/^Step (\d+)\//);
    return m ? parseInt(m[1], 10) : null;
  }

  const STATUS_COLORS: Record<string, string> = {
    queued: "bg-yellow-100 text-yellow-700",
    running: "bg-blue-100 text-blue-700",
    complete: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    stopped: "bg-gray-100 text-gray-700",
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Mailbox Creation</h1>

      {/* Create form */}
      <form onSubmit={handleCreate} className="bg-white rounded-lg border p-6 mb-6">
        <h2 className="font-semibold mb-4">Create Mailboxes</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Tenant *</label>
            <select
              value={selectedTenant}
              onChange={(e) => setSelectedTenant(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm"
              required
            >
              <option value="">Select tenant...</option>
              {tenants.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.admin_email})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Domain *</label>
            <input
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="example.com"
              className="w-full px-3 py-2 border rounded-lg text-sm"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Mailbox Count</label>
            <input
              type="number"
              value={count}
              onChange={(e) => setCount(parseInt(e.target.value) || 50)}
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Cloudflare Email</label>
            <input
              value={cfEmail}
              onChange={(e) => setCfEmail(e.target.value)}
              placeholder="Leave blank for default"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <div className="col-span-2">
            <label className="block text-sm font-medium mb-1">Cloudflare API Key</label>
            <input
              type="password"
              value={cfApiKey}
              onChange={(e) => setCfApiKey(e.target.value)}
              placeholder="Leave blank for default"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={loading}
          className="mt-4 bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm flex items-center gap-2"
        >
          <Plus size={16} /> {loading ? "Starting..." : "Start Pipeline"}
        </button>
      </form>

      {/* Jobs list */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <h2 className="font-semibold p-4 border-b">Pipeline Jobs</h2>
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="w-8 px-2 py-3"></th>
              <th className="text-left px-4 py-3">Domain</th>
              <th className="text-left px-4 py-3">Count</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Phase</th>
              <th className="text-left px-4 py-3">Created</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          {jobs.map((j) => {
              const isExpanded = expandedJobs.has(j.id);
              return (
                <tbody key={j.id}>
                  <tr className="border-t hover:bg-gray-50 cursor-pointer" onClick={() => toggleExpanded(j.id)}>
                    <td className="px-2 py-3 text-center">
                      {isExpanded
                        ? <ChevronDown size={14} className="text-gray-400 inline" />
                        : <ChevronRight size={14} className="text-gray-400 inline" />}
                    </td>
                    <td className="px-4 py-3">{j.domain}</td>
                    <td className="px-4 py-3">{j.mailbox_count}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[j.status] || ""}`}>
                        {j.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{j.current_phase || "—"}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">{new Date(j.created_at).toLocaleString()}</td>
                    <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        {j.status === "running" && (
                          <button
                            onClick={async () => { try { await api.stopJob(j.id); loadData(); } catch (err: any) { alert(err.message); } }}
                            className="p-1 hover:bg-red-50 rounded" title="Stop pipeline"
                          >
                            <StopCircle size={16} className="text-red-500" />
                          </button>
                        )}
                        {j.status === "complete" && (
                          <>
                            {j.dkim_enabled ? (
                              <span className="p-1" title="DKIM enabled">
                                <ShieldCheck size={16} className="text-green-600" />
                              </span>
                            ) : dkimLoading.has(j.id) ? (
                              <span className="p-1" title="Enabling DKIM...">
                                <Loader2 size={16} className="text-purple-500 animate-spin" />
                              </span>
                            ) : (
                              <button
                                onClick={() => handleEnableDkim(j.id)}
                                className="p-1 hover:bg-purple-50 rounded" title="Enable DKIM"
                              >
                                <Shield size={16} className="text-purple-500" />
                              </button>
                            )}
                            <button
                              onClick={() => handleExport(j.tenant_id)}
                              className="p-1 hover:bg-green-50 rounded" title="Export CSV"
                            >
                              <Download size={16} className="text-green-600" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="border-t bg-gray-50/50">
                      <td colSpan={7} className="px-6 py-2">
                        <MailboxPipelineProgress
                          stepResults={j.step_results}
                          jobStatus={j.status}
                          currentStep={parseCurrentStep(j.current_phase)}
                        />
                        {j.error_message && (
                          <div className="mt-2 p-3 bg-red-50 rounded text-xs text-red-700 font-mono whitespace-pre-wrap max-h-40 overflow-auto">
                            {j.error_message}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              );
            })}
            {jobs.length === 0 && (
              <tbody><tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">No jobs yet</td></tr></tbody>
            )}
        </table>
      </div>
    </div>
  );
}
