"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Tenant, MailboxJob, WSEvent, BulkMailboxResult } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Plus, StopCircle, Download, ChevronDown, ChevronRight, Shield, ShieldCheck, Loader2, Upload, FileDown } from "lucide-react";
import MailboxPipelineProgress from "@/components/mailboxes/MailboxPipelineProgress";

export default function MailboxesPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [jobs, setJobs] = useState<MailboxJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set());
  const [dkimLoading, setDkimLoading] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<"quick" | "csv">("quick");

  // Quick Create state
  const [selectedTenants, setSelectedTenants] = useState<Set<string>>(new Set());
  const [domainMap, setDomainMap] = useState<Record<string, string>>({});
  const [count, setCount] = useState(50);
  const [cfEmail, setCfEmail] = useState("");
  const [cfApiKey, setCfApiKey] = useState("");

  // CSV state
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvCfEmail, setCsvCfEmail] = useState("");
  const [csvCfApiKey, setCsvCfApiKey] = useState("");

  // Result banner
  const [result, setResult] = useState<BulkMailboxResult | null>(null);

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

  function toggleTenant(tenantId: string) {
    setSelectedTenants(prev => {
      const next = new Set(prev);
      if (next.has(tenantId)) {
        next.delete(tenantId);
        setDomainMap(d => { const n = { ...d }; delete n[tenantId]; return n; });
      } else {
        next.add(tenantId);
      }
      return next;
    });
  }

  async function handleQuickCreate(e: React.FormEvent) {
    e.preventDefault();
    if (selectedTenants.size === 0) return;

    // Validate all selected tenants have domains
    const missing = Array.from(selectedTenants).filter(id => !domainMap[id]?.trim());
    if (missing.length > 0) {
      alert("Please enter a domain for all selected tenants");
      return;
    }

    setLoading(true);
    setResult(null);
    try {
      const items = Array.from(selectedTenants).map(id => ({
        tenant_id: id,
        domain: domainMap[id].trim(),
        mailbox_count: count,
      }));
      const res = await api.bulkCreateMailboxes(items, cfEmail || undefined, cfApiKey || undefined);
      setResult(res);
      loadData();
      setSelectedTenants(new Set());
      setDomainMap({});
    } catch (err: any) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCsvCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!csvFile) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await api.bulkCreateMailboxesCsv(csvFile, csvCfEmail || undefined, csvCfApiKey || undefined);
      setResult(res);
      loadData();
      setCsvFile(null);
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
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Mailbox Creation</h1>
        <button
          onClick={() => api.exportAllMailboxesCsv()}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white border rounded-lg hover:bg-gray-50"
        >
          <FileDown size={14} /> Export All Mailboxes
        </button>
      </div>

      {/* Result Banner */}
      {result && (
        <div className="mb-4">
          {result.created > 0 && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-2 text-sm text-green-800">
              {result.created} job(s) queued successfully
            </div>
          )}
          {result.errors.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">
              <p className="font-medium mb-1">Errors:</p>
              <ul className="list-disc list-inside">
                {result.errors.map((e, i) => (
                  <li key={i}>{e.tenant_id}: {e.error}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Tabbed Form */}
      <div className="bg-white rounded-lg border mb-6">
        <div className="flex border-b">
          <button
            onClick={() => setActiveTab("quick")}
            className={`px-6 py-3 text-sm font-medium border-b-2 -mb-px ${
              activeTab === "quick" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Quick Create
          </button>
          <button
            onClick={() => setActiveTab("csv")}
            className={`px-6 py-3 text-sm font-medium border-b-2 -mb-px ${
              activeTab === "csv" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            CSV Import
          </button>
        </div>

        <div className="p-6">
          {activeTab === "quick" && (
            <form onSubmit={handleQuickCreate}>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-2">Select Tenants</label>
                <div className="border rounded-lg max-h-48 overflow-y-auto">
                  {tenants.length === 0 && (
                    <p className="px-3 py-4 text-sm text-gray-400 text-center">No completed tenants available</p>
                  )}
                  {tenants.map(t => (
                    <label
                      key={t.id}
                      className="flex items-center px-3 py-2 hover:bg-gray-50 cursor-pointer border-b last:border-b-0"
                    >
                      <input
                        type="checkbox"
                        checked={selectedTenants.has(t.id)}
                        onChange={() => toggleTenant(t.id)}
                        className="mr-3 rounded"
                      />
                      <span className="text-sm">
                        {t.name} <span className="text-gray-400">({t.admin_email})</span>
                        <span className="text-gray-400 ml-1">— {t.mailbox_count ?? 0} mailboxes</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Domain inputs for selected tenants */}
              {selectedTenants.size > 0 && (
                <div className="mb-4 space-y-2">
                  <label className="block text-sm font-medium mb-1">Domains</label>
                  {Array.from(selectedTenants).map(id => {
                    const tenant = tenants.find(t => t.id === id);
                    return (
                      <div key={id} className="flex items-center gap-3">
                        <span className="text-sm text-gray-600 w-48 truncate" title={tenant?.name}>
                          {tenant?.name}
                        </span>
                        <span className="text-gray-400">—</span>
                        <input
                          value={domainMap[id] || ""}
                          onChange={e => setDomainMap(prev => ({ ...prev, [id]: e.target.value }))}
                          placeholder="example.com"
                          className="flex-1 px-3 py-1.5 border rounded-lg text-sm"
                          required
                        />
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Mailbox Count</label>
                  <input
                    type="number"
                    value={count}
                    onChange={e => setCount(parseInt(e.target.value) || 50)}
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Cloudflare Email</label>
                  <input
                    value={cfEmail}
                    onChange={e => setCfEmail(e.target.value)}
                    placeholder="Leave blank for default"
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Cloudflare API Key</label>
                  <input
                    type="password"
                    value={cfApiKey}
                    onChange={e => setCfApiKey(e.target.value)}
                    placeholder="Leave blank for default"
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading || selectedTenants.size === 0}
                className="mt-4 bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm flex items-center gap-2"
              >
                <Plus size={16} /> {loading ? "Starting..." : `Start ${selectedTenants.size} Pipeline(s)`}
              </button>
            </form>
          )}

          {activeTab === "csv" && (
            <form onSubmit={handleCsvCreate}>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">CSV File</label>
                <input
                  type="file"
                  accept=".csv"
                  onChange={e => setCsvFile(e.target.files?.[0] || null)}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Expected columns: <code className="bg-gray-100 px-1 rounded">tenant_email, domain, count</code> (count is optional, defaults to 50)
                </p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Cloudflare Email</label>
                  <input
                    value={csvCfEmail}
                    onChange={e => setCsvCfEmail(e.target.value)}
                    placeholder="Leave blank for default"
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Cloudflare API Key</label>
                  <input
                    type="password"
                    value={csvCfApiKey}
                    onChange={e => setCsvCfApiKey(e.target.value)}
                    placeholder="Leave blank for default"
                    className="w-full px-3 py-2 border rounded-lg text-sm"
                  />
                </div>
              </div>
              <button
                type="submit"
                disabled={loading || !csvFile}
                className="mt-4 bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm flex items-center gap-2"
              >
                <Upload size={16} /> {loading ? "Uploading..." : "Upload & Start"}
              </button>
            </form>
          )}
        </div>
      </div>

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
