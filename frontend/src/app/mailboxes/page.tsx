"use client";

import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Tenant, MailboxJob, WSEvent, BulkMailboxResult, MailboxHealthResult, RetryMissingResult } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuth } from "@/hooks/useAuth";
import { useToast } from "@/components/ui/Toast";
import Sidebar from "@/components/layout/Sidebar";
import MailboxPipelineProgress from "@/components/mailboxes/MailboxPipelineProgress";
import {
  Plus, StopCircle, Download, ChevronDown, ChevronRight, Shield, ShieldCheck,
  Loader2, Upload, FileDown, HeartPulse, RefreshCw, Lock, Search, Mail,
} from "lucide-react";

export default function MailboxesPage() {
  const authenticated = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set());
  const [dkimLoading, setDkimLoading] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<"quick" | "csv">("quick");
  const [selectedTenants, setSelectedTenants] = useState<Set<string>>(new Set());
  const [domainMap, setDomainMap] = useState<Record<string, string>>({});
  const [count, setCount] = useState(50);
  const [cfEmail, setCfEmail] = useState("");
  const [cfApiKey, setCfApiKey] = useState("");
  const [useCustomNames, setUseCustomNames] = useState(false);
  const [customNameCount, setCustomNameCount] = useState(3);
  const [firstNames, setFirstNames] = useState<string[]>([]);
  const [lastNames, setLastNames] = useState<string[]>([]);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvCfEmail, setCsvCfEmail] = useState("");
  const [csvCfApiKey, setCsvCfApiKey] = useState("");
  const [selectedJobTenantIds, setSelectedJobTenantIds] = useState<Set<string>>(new Set());
  const [healthLoading, setHealthLoading] = useState<Set<string>>(new Set());
  const [healthResults, setHealthResults] = useState<Record<string, MailboxHealthResult>>({});
  const [retryLoading, setRetryLoading] = useState<Set<string>>(new Set());
  const [retryResults, setRetryResults] = useState<Record<string, RetryMissingResult>>({});
  const [fixLoading, setFixLoading] = useState<Set<string>>(new Set());
  const [fixResults, setFixResults] = useState<Record<string, { status: string; detail?: string; error?: string }>>({});
  const [result, setResult] = useState<BulkMailboxResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [jobSearchQuery, setJobSearchQuery] = useState("");
  const [jobStatusFilter, setJobStatusFilter] = useState("");

  const { data: tenantData } = useQuery({
    queryKey: ["tenants-complete"],
    queryFn: () => api.listTenants(1, "complete"),
  });

  const { data: jobData } = useQuery({
    queryKey: ["mailbox-jobs"],
    queryFn: async () => {
      const result = await api.listMailboxJobs();
      const cached: Record<string, MailboxHealthResult> = {};
      for (const job of result.jobs) {
        if ((job as any).health_results) cached[job.id] = (job as any).health_results;
      }
      if (Object.keys(cached).length > 0) setHealthResults(prev => ({ ...cached, ...prev }));
      return result;
    },
  });

  const tenants: Tenant[] = tenantData?.tenants ?? [];
  const jobs: MailboxJob[] = jobData?.jobs ?? [];

  const onWsMessage = useCallback((event: WSEvent) => {
    if (event.type === "mailbox_pipeline_progress") queryClient.invalidateQueries({ queryKey: ["mailbox-jobs"] });
    if (event.type === "mailbox_step_result" && event.job_id) queryClient.invalidateQueries({ queryKey: ["mailbox-jobs"] });
    if (event.type === "mailbox_health_check" && event.job_id) {
      const r = event as unknown as MailboxHealthResult;
      if (r.status === "running") setHealthLoading(prev => new Set(prev).add(event.job_id!));
      else { setHealthLoading(prev => { const n = new Set(prev); n.delete(event.job_id!); return n; }); setHealthResults(prev => ({ ...prev, [event.job_id!]: r })); }
    }
    if (event.type === "retry_missing_result" && event.job_id) {
      const r = event as unknown as RetryMissingResult;
      if (r.status === "running") setRetryLoading(prev => new Set(prev).add(event.job_id!));
      else { setRetryLoading(prev => { const n = new Set(prev); n.delete(event.job_id!); return n; }); setRetryResults(prev => ({ ...prev, [event.job_id!]: r })); setHealthResults(prev => { const n = { ...prev }; delete n[event.job_id!]; return n; }); }
    }
    if (event.type === "fix_security_defaults" && event.tenant_id) { setFixLoading(prev => { const n = new Set(prev); n.delete(event.tenant_id!); return n; }); setFixResults(prev => ({ ...prev, [event.tenant_id!]: { status: event.status || "complete", detail: event.detail, error: event.error } })); }
    if (event.type === "dkim_enabled" && event.job_id) { setDkimLoading(prev => { const n = new Set(prev); n.delete(event.job_id!); return n; }); if (event.success) queryClient.invalidateQueries({ queryKey: ["mailbox-jobs"] }); else toast.error(`DKIM failed: ${event.error}`); }
  }, [queryClient]);

  useWebSocket(onWsMessage);

  function toggleExpanded(jobId: string) { setExpandedJobs(prev => { const n = new Set(prev); if (n.has(jobId)) n.delete(jobId); else n.add(jobId); return n; }); }
  function toggleTenant(tenantId: string) { setSelectedTenants(prev => { const n = new Set(prev); if (n.has(tenantId)) { n.delete(tenantId); setDomainMap(d => { const x = { ...d }; delete x[tenantId]; return x; }); } else n.add(tenantId); return n; }); }

  async function handleQuickCreate(e: React.FormEvent) {
    e.preventDefault();
    if (selectedTenants.size === 0) return;
    const missing = Array.from(selectedTenants).filter(id => !domainMap[id]?.trim());
    if (missing.length > 0) { toast.error("Please enter a domain for all selected tenants"); return; }
    setLoading(true); setResult(null);
    try {
      let customNames: string[] | undefined;
      if (useCustomNames) {
        const m = []; for (let i = 0; i < customNameCount; i++) { if (!firstNames[i]?.trim() || !lastNames[i]?.trim()) m.push(i + 1); }
        if (m.length > 0) { toast.error(`Fill in both names for row(s): ${m.join(", ")}`); setLoading(false); return; }
        customNames = Array.from({ length: customNameCount }, (_, i) => `${firstNames[i].trim()} ${lastNames[i].trim()}`);
      }
      const items = Array.from(selectedTenants).map(id => ({ tenant_id: id, domain: domainMap[id].trim(), mailbox_count: count, ...(customNames ? { custom_names: customNames } : {}) }));
      const res = await api.bulkCreateMailboxes(items, cfEmail || undefined, cfApiKey || undefined);
      setResult(res);
      queryClient.invalidateQueries({ queryKey: ["mailbox-jobs"] });
      setSelectedTenants(new Set()); setDomainMap({});
    } catch (err: any) { toast.error(err.message); } finally { setLoading(false); }
  }

  async function handleCsvCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!csvFile) return;
    setLoading(true); setResult(null);
    try {
      const res = await api.bulkCreateMailboxesCsv(csvFile, csvCfEmail || undefined, csvCfApiKey || undefined);
      setResult(res);
      queryClient.invalidateQueries({ queryKey: ["mailbox-jobs"] });
      setCsvFile(null);
    } catch (err: any) { toast.error(err.message); } finally { setLoading(false); }
  }

  async function handleEnableDkim(jobId: string) { setDkimLoading(prev => new Set(prev).add(jobId)); try { await api.enableDkim(jobId); } catch (err: any) { setDkimLoading(prev => { const n = new Set(prev); n.delete(jobId); return n; }); toast.error(err.message); } }
  async function handleHealthCheck(jobId: string) { setHealthLoading(prev => new Set(prev).add(jobId)); try { await api.healthCheckMailboxes(jobId); } catch (err: any) { setHealthLoading(prev => { const n = new Set(prev); n.delete(jobId); return n; }); toast.error(err.message); } }
  async function handleRetryMissing(jobId: string) { setRetryLoading(prev => new Set(prev).add(jobId)); try { await api.retryMissingMailboxes(jobId); } catch (err: any) { setRetryLoading(prev => { const n = new Set(prev); n.delete(jobId); return n; }); toast.error(err.message); } }
  async function handleFixSecurityDefaults(tenantId: string) { setFixLoading(prev => new Set(prev).add(tenantId)); try { await api.fixSecurityDefaults(tenantId); } catch (err: any) { setFixLoading(prev => { const n = new Set(prev); n.delete(tenantId); return n; }); toast.error(err.message); } }

  function parseCurrentStep(phase: string | null): number | null { if (!phase) return null; const m = phase.match(/^Step (\d+)\//); return m ? parseInt(m[1], 10) : null; }

  function getActualCount(job: MailboxJob): { actual: number; requested: number; mismatch: boolean } | null {
    const hr = healthResults[job.id];
    if (hr?.status === "complete" && hr.found_in_exchange != null) return { actual: hr.found_in_exchange, requested: job.mailbox_count, mismatch: hr.found_in_exchange < job.mailbox_count };
    const step7 = job.step_results?.["7"];
    if (!step7?.detail) return null;
    const m = step7.detail.match(/Created:\s*(\d+),\s*Existed:\s*(\d+),\s*Failed:\s*(\d+)/);
    if (!m) return null;
    return { actual: parseInt(m[1]) + parseInt(m[2]), requested: job.mailbox_count, mismatch: parseInt(m[3]) > 0 };
  }

  const STATUS_COLORS: Record<string, string> = {
    queued: "bg-amber-50 text-amber-700 border border-amber-200",
    running: "bg-blue-50 text-blue-700 border border-blue-200",
    complete: "bg-emerald-50 text-emerald-700 border border-emerald-200",
    failed: "bg-red-50 text-red-700 border border-red-200",
    stopped: "bg-gray-100 text-gray-700",
  };

  const filteredJobs = jobs.filter(j => {
    if (jobStatusFilter && j.status !== jobStatusFilter) return false;
    if (jobSearchQuery && !j.domain.toLowerCase().includes(jobSearchQuery.toLowerCase())) return false;
    return true;
  });

  if (authenticated === null) return null;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <div className="max-w-[1400px] mx-auto">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold flex items-center gap-2"><Mail size={24} className="text-blue-600" /> Mailbox Creation</h1>
              <p className="text-sm text-gray-500 mt-0.5">{jobs.length} pipeline jobs</p>
            </div>
            <button onClick={() => api.exportAllMailboxesCsv()} className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-white border rounded-lg hover:bg-gray-50">
              <FileDown size={14} /> Export All
            </button>
          </div>

          {/* Result Banner */}
          {result && (
            <div className="mb-4 space-y-2">
              {result.created > 0 && <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 text-sm text-emerald-800">{result.created} job(s) queued successfully</div>}
              {result.errors.length > 0 && (
                <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-sm text-red-800">
                  <p className="font-medium mb-1">Errors:</p>
                  <ul className="list-disc list-inside">{result.errors.map((e, i) => <li key={i}>{e.tenant_id}: {e.error}</li>)}</ul>
                </div>
              )}
            </div>
          )}

          {/* Tabbed Form */}
          <div className="bg-white rounded-xl border mb-6 shadow-sm">
            <div className="flex border-b">
              <button onClick={() => setActiveTab("quick")} className={`px-6 py-3 text-sm font-medium border-b-2 -mb-px transition-colors ${activeTab === "quick" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>Quick Create</button>
              <button onClick={() => setActiveTab("csv")} className={`px-6 py-3 text-sm font-medium border-b-2 -mb-px transition-colors ${activeTab === "csv" ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>CSV Import</button>
            </div>
            <div className="p-6">
              {activeTab === "quick" && (
                <form onSubmit={handleQuickCreate}>
                  <div className="mb-4">
                    <label className="block text-sm font-medium mb-2">Select Tenants</label>
                    <div className="border rounded-xl max-h-48 overflow-y-auto">
                      {tenants.length === 0 && <p className="px-3 py-4 text-sm text-gray-400 text-center">No completed tenants available</p>}
                      {tenants.map(t => (
                        <label key={t.id} className="flex items-center px-3 py-2.5 hover:bg-gray-50 cursor-pointer border-b last:border-b-0">
                          <input type="checkbox" checked={selectedTenants.has(t.id)} onChange={() => toggleTenant(t.id)} className="mr-3 rounded" />
                          <span className="text-sm">{t.name} <span className="text-gray-400">({t.admin_email})</span> <span className="text-gray-400 ml-1">--- {t.mailbox_count ?? 0} mailboxes</span></span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {selectedTenants.size > 0 && (
                    <div className="mb-4 space-y-2">
                      <label className="block text-sm font-medium mb-1">Domains</label>
                      {Array.from(selectedTenants).map(id => {
                        const tenant = tenants.find(t => t.id === id);
                        return (
                          <div key={id} className="flex items-center gap-3">
                            <span className="text-sm text-gray-600 w-48 truncate">{tenant?.name}</span>
                            <input value={domainMap[id] || ""} onChange={e => setDomainMap(prev => ({ ...prev, [id]: e.target.value }))} placeholder="example.com" className="flex-1 px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500/30 focus:outline-none" required />
                          </div>
                        );
                      })}
                    </div>
                  )}

                  <div className="mb-4">
                    <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                      <input type="checkbox" checked={useCustomNames} onChange={e => { setUseCustomNames(e.target.checked); if (e.target.checked && firstNames.length === 0) { setFirstNames(Array(customNameCount).fill("")); setLastNames(Array(customNameCount).fill("")); } }} className="rounded" />
                      Custom Names
                    </label>
                    {useCustomNames && (
                      <div className="mt-3 ml-6">
                        <div className="flex items-center gap-3 mb-3">
                          <label className="text-sm text-gray-600">Number of names:</label>
                          <input type="number" min={1} max={20} value={customNameCount} onChange={e => {
                            const n = Math.max(1, Math.min(20, parseInt(e.target.value) || 1));
                            setCustomNameCount(n);
                            setFirstNames(prev => { const a = [...prev]; while (a.length < n) a.push(""); return a.slice(0, n); });
                            setLastNames(prev => { const a = [...prev]; while (a.length < n) a.push(""); return a.slice(0, n); });
                          }} className="w-20 px-2 py-1.5 border rounded-lg text-sm" />
                        </div>
                        <div className="space-y-2">
                          <div className="grid grid-cols-[2rem_1fr_1fr] gap-2 text-xs font-medium text-gray-500"><span>#</span><span>First Name</span><span>Last Name</span></div>
                          {Array.from({ length: customNameCount }, (_, i) => (
                            <div key={i} className="grid grid-cols-[2rem_1fr_1fr] gap-2 items-center">
                              <span className="text-xs text-gray-400">{i + 1}</span>
                              <input value={firstNames[i] || ""} onChange={e => setFirstNames(prev => { const n = [...prev]; n[i] = e.target.value; return n; })} placeholder="First" className="px-2 py-1.5 border rounded-lg text-sm" />
                              <input value={lastNames[i] || ""} onChange={e => setLastNames(prev => { const n = [...prev]; n[i] = e.target.value; return n; })} placeholder="Last" className="px-2 py-1.5 border rounded-lg text-sm" />
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="grid grid-cols-3 gap-4">
                    <div><label className="block text-sm font-medium mb-1.5">Mailbox Count</label><input type="number" value={count} onChange={e => setCount(parseInt(e.target.value) || 50)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="block text-sm font-medium mb-1.5">CF Email <span className="text-gray-400 font-normal">(optional)</span></label><input value={cfEmail} onChange={e => setCfEmail(e.target.value)} placeholder="Default" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="block text-sm font-medium mb-1.5">CF API Key <span className="text-gray-400 font-normal">(optional)</span></label><input type="password" value={cfApiKey} onChange={e => setCfApiKey(e.target.value)} placeholder="Default" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                  </div>
                  <button type="submit" disabled={loading || selectedTenants.size === 0} className="mt-4 bg-blue-600 text-white px-6 py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium flex items-center gap-2">
                    <Plus size={16} /> {loading ? "Starting..." : `Start ${selectedTenants.size} Pipeline(s)`}
                  </button>
                </form>
              )}

              {activeTab === "csv" && (
                <form onSubmit={handleCsvCreate}>
                  <div className="mb-4">
                    <label className="block text-sm font-medium mb-1.5">CSV File</label>
                    <div className="border-2 border-dashed rounded-xl p-8 text-center bg-gray-50/50 hover:bg-gray-50 transition-colors">
                      <Upload className="mx-auto mb-2 text-gray-400" size={32} />
                      <input type="file" accept=".csv" onChange={e => setCsvFile(e.target.files?.[0] || null)} className="text-sm" />
                    </div>
                    <p className="text-xs text-gray-400 mt-1.5">Columns: <code className="bg-gray-100 px-1 rounded">tenant_email, domain, count, custom_names</code></p>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div><label className="block text-sm font-medium mb-1.5">CF Email</label><input value={csvCfEmail} onChange={e => setCsvCfEmail(e.target.value)} placeholder="Default" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="block text-sm font-medium mb-1.5">CF API Key</label><input type="password" value={csvCfApiKey} onChange={e => setCsvCfApiKey(e.target.value)} placeholder="Default" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                  </div>
                  <button type="submit" disabled={loading || !csvFile} className="mt-4 bg-blue-600 text-white px-6 py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium flex items-center gap-2">
                    <Upload size={16} /> {loading ? "Uploading..." : "Upload & Start"}
                  </button>
                </form>
              )}
            </div>
          </div>

          {/* Action Bar */}
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            {selectedJobTenantIds.size > 0 && (
              <>
                <button onClick={() => api.exportAllMailboxesCsv(Array.from(selectedJobTenantIds))} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700"><FileDown size={14} /> Export ({selectedJobTenantIds.size})</button>
                <button onClick={() => { const ej = jobs.filter(j => selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed")); if (!ej.length) { toast.error("No eligible jobs"); return; } ej.forEach(j => handleRetryMissing(j.id)); }} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-orange-500 text-white rounded-lg hover:bg-orange-600"><RefreshCw size={14} /> Retry Missing</button>
                <button onClick={() => { const ej = jobs.filter(j => selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed")); if (!ej.length) { toast.error("No eligible jobs"); return; } ej.forEach(j => handleHealthCheck(j.id)); }} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-pink-500 text-white rounded-lg hover:bg-pink-600"><HeartPulse size={14} /> Health Check</button>
                <button onClick={() => { const tids = new Set(jobs.filter(j => selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed")).map(j => j.tenant_id)); if (!tids.size) { toast.error("No eligible jobs"); return; } tids.forEach(tid => handleFixSecurityDefaults(tid)); }} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-indigo-500 text-white rounded-lg hover:bg-indigo-600"><Lock size={14} /> Fix SMTP Auth</button>
              </>
            )}
          </div>

          {/* Search & Filter for Jobs */}
          <div className="bg-white rounded-xl border p-3 mb-4 flex items-center gap-3">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input type="text" placeholder="Search by domain..." value={jobSearchQuery} onChange={(e) => setJobSearchQuery(e.target.value)} className="w-full pl-9 pr-4 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/30" />
            </div>
            <select value={jobStatusFilter} onChange={(e) => setJobStatusFilter(e.target.value)} className="px-3 py-2 border rounded-lg text-sm focus:outline-none">
              <option value="">All Status</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="complete">Complete</option>
              <option value="failed">Failed</option>
            </select>
          </div>

          {/* Jobs list */}
          <div className="bg-white rounded-xl border overflow-hidden shadow-sm">
            <div className="p-4 border-b flex items-center justify-between">
              <h2 className="font-semibold">Pipeline Jobs</h2>
              <span className="text-xs text-gray-400">{filteredJobs.length} of {jobs.length} jobs</span>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50/80 border-b">
                  <th className="w-10 px-4 py-3"><input type="checkbox" checked={jobs.length > 0 && selectedJobTenantIds.size === jobs.length} onChange={(e) => setSelectedJobTenantIds(e.target.checked ? new Set(jobs.map(j => j.tenant_id)) : new Set())} className="rounded" /></th>
                  <th className="w-8 px-2 py-3"></th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Domain</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Count</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Status</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Phase</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Created</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              {filteredJobs.map((j) => {
                const isExpanded = expandedJobs.has(j.id);
                return (
                  <tbody key={j.id}>
                    <tr className="border-b hover:bg-gray-50/50 cursor-pointer transition-colors" onClick={() => toggleExpanded(j.id)}>
                      <td className="w-10 px-4 py-3" onClick={e => e.stopPropagation()}><input type="checkbox" checked={selectedJobTenantIds.has(j.tenant_id)} onChange={e => setSelectedJobTenantIds(prev => { const n = new Set(prev); if (e.target.checked) n.add(j.tenant_id); else n.delete(j.tenant_id); return n; })} className="rounded" /></td>
                      <td className="px-2 py-3 text-center">{isExpanded ? <ChevronDown size={14} className="text-gray-400 inline" /> : <ChevronRight size={14} className="text-gray-400 inline" />}</td>
                      <td className="px-4 py-3 font-medium">{j.domain}</td>
                      <td className="px-4 py-3">{(() => { const c = getActualCount(j); if (c?.mismatch) return <span className={`font-medium ${c.actual === 0 ? "text-red-600" : "text-yellow-600"}`}>{c.actual}/{c.requested}</span>; return j.mailbox_count; })()}</td>
                      <td className="px-4 py-3"><span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${STATUS_COLORS[j.status] || ""}`}>{j.status}</span></td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{j.current_phase || "---"}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">{new Date(j.created_at).toLocaleString()}</td>
                      <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-0.5">
                          {j.status === "running" && <button onClick={async () => { try { await api.stopJob(j.id); queryClient.invalidateQueries({ queryKey: ["mailbox-jobs"] }); } catch (err: any) { toast.error(err.message); } }} className="p-1.5 hover:bg-red-50 rounded-lg" title="Stop"><StopCircle size={15} className="text-red-500" /></button>}
                          {(j.status === "complete" || j.status === "failed") && (
                            <>
                              {healthLoading.has(j.id) ? <span className="p-1.5"><Loader2 size={15} className="text-pink-500 animate-spin" /></span> : <button onClick={() => handleHealthCheck(j.id)} className="p-1.5 hover:bg-pink-50 rounded-lg" title="Health check"><HeartPulse size={15} className={healthResults[j.id]?.status === "complete" && !healthResults[j.id]?.missing?.length && (healthResults[j.id]?.smtp_ok == null || healthResults[j.id]?.smtp_ok === healthResults[j.id]?.smtp_tested) ? "text-green-500" : healthResults[j.id]?.status === "complete" ? "text-amber-500" : "text-pink-500"} /></button>}
                              {retryLoading.has(j.id) ? <span className="p-1.5"><Loader2 size={15} className="text-orange-500 animate-spin" /></span> : <button onClick={() => handleRetryMissing(j.id)} className="p-1.5 hover:bg-orange-50 rounded-lg" title="Retry missing"><RefreshCw size={15} className="text-orange-500" /></button>}
                              {j.status === "complete" && (j.dkim_enabled ? <span className="p-1.5"><ShieldCheck size={15} className="text-green-600" /></span> : dkimLoading.has(j.id) ? <span className="p-1.5"><Loader2 size={15} className="text-purple-500 animate-spin" /></span> : <button onClick={() => handleEnableDkim(j.id)} className="p-1.5 hover:bg-purple-50 rounded-lg" title="Enable DKIM"><Shield size={15} className="text-purple-500" /></button>)}
                              <button onClick={() => api.exportMailboxesCsv(j.tenant_id)} className="p-1.5 hover:bg-green-50 rounded-lg" title="Export"><Download size={15} className="text-green-600" /></button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-gray-50/50">
                        <td colSpan={8} className="px-6 py-3">
                          <MailboxPipelineProgress stepResults={j.step_results} jobStatus={j.status} currentStep={parseCurrentStep(j.current_phase)} healthResult={healthResults[j.id] || null} mailboxCount={j.mailbox_count} dkimEnabled={j.dkim_enabled} />
                          {healthResults[j.id] && <HealthCheckBanner result={healthResults[j.id]} tenantId={j.tenant_id} fixLoading={fixLoading} fixResults={fixResults} onFix={handleFixSecurityDefaults} />}
                          {retryResults[j.id] && <RetryResultBanner result={retryResults[j.id]} />}
                          {j.error_message && j.status !== "complete" && <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 font-mono whitespace-pre-wrap max-h-40 overflow-auto">{j.error_message}</div>}
                        </td>
                      </tr>
                    )}
                  </tbody>
                );
              })}
              {filteredJobs.length === 0 && <tbody><tr><td colSpan={8} className="px-4 py-12 text-center text-gray-400">{jobSearchQuery || jobStatusFilter ? "No matching jobs" : "No jobs yet"}</td></tr></tbody>}
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}

function HealthCheckBanner({ result: r, tenantId, fixLoading, fixResults, onFix }: { result: MailboxHealthResult; tenantId: string; fixLoading: Set<string>; fixResults: Record<string, any>; onFix: (id: string) => void }) {
  if (r.status === "error") return <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700"><span className="font-medium">Health check error:</span> {r.error}</div>;
  if (r.status !== "complete") return null;
  const allGood = r.missing?.length === 0 && r.smtp_failed?.length === 0 && (r.smtp_ok == null || r.smtp_ok === r.smtp_tested);
  return (
    <div className={`mt-2 p-3 ${allGood ? "bg-emerald-50 border-emerald-200" : "bg-amber-50 border-amber-200"} border rounded-xl text-xs`}>
      <div className="flex items-center gap-4 mb-1">
        <span className="font-medium">{allGood ? "All mailboxes healthy" : "Issues found"}</span>
        <span>Exchange: {r.found_in_exchange}/{r.total_in_db}</span>
        <span>SMTP: {r.smtp_ok}/{r.smtp_tested}</span>
      </div>
      {(r.missing?.length ?? 0) > 0 && <div className="mt-1"><span className="font-medium text-red-700">Missing ({r.missing!.length}):</span> <span className="font-mono">{r.missing!.slice(0, 10).join(", ")}{r.missing!.length > 10 ? ` +${r.missing!.length - 10}` : ""}</span></div>}
      {(r.smtp_failed?.length ?? 0) > 0 && (
        <>
          <div className="mt-1"><span className="font-medium text-red-700">SMTP failed ({r.smtp_failed!.length}):</span> <span className="font-mono">{r.smtp_failed!.map(f => f.email).slice(0, 5).join(", ")}</span></div>
          <div className="mt-2">
            {fixLoading.has(tenantId) ? <span className="text-xs text-blue-600 flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Fixing...</span> :
             fixResults[tenantId] ? <span className={`text-xs ${fixResults[tenantId].status === "complete" ? "text-green-700" : "text-red-700"}`}>{fixResults[tenantId].status === "complete" ? fixResults[tenantId].detail : `Error: ${fixResults[tenantId].error}`}</span> :
             <button onClick={e => { e.stopPropagation(); onFix(tenantId); }} className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700"><Lock size={12} /> Fix SMTP Auth</button>}
          </div>
        </>
      )}
    </div>
  );
}

function RetryResultBanner({ result: r }: { result: RetryMissingResult }) {
  if (r.status === "error") return <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700"><span className="font-medium">Retry error:</span> {r.error}</div>;
  if (r.status !== "complete") return null;
  const allGood = (r.failed ?? 0) === 0;
  return (
    <div className={`mt-2 p-3 ${allGood ? "bg-blue-50 border-blue-200" : "bg-orange-50 border-orange-200"} border rounded-xl text-xs`}>
      <div className="flex items-center gap-4">
        <span className="font-medium">Retry complete</span>
        <span>Missing: {r.missing_count}</span>
        <span>Created: {r.created ?? 0}</span>
        {(r.existed ?? 0) > 0 && <span>Existed: {r.existed}</span>}
        {(r.failed ?? 0) > 0 && <span className="text-red-600 font-medium">Failed: {r.failed}</span>}
      </div>
      {(r.failed_list?.length ?? 0) > 0 && <div className="mt-1"><span className="font-medium text-red-700">Failed:</span> <span className="font-mono">{r.failed_list!.map(f => f.email).slice(0, 10).join(", ")}</span></div>}
    </div>
  );
}
