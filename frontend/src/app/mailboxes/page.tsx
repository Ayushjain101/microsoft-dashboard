"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Tenant, MailboxJob, WSEvent, BulkMailboxResult, MailboxHealthResult, RetryMissingResult } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Plus, StopCircle, Download, ChevronDown, ChevronRight, Shield, ShieldCheck, Loader2, Upload, FileDown, HeartPulse, RefreshCw, Lock } from "lucide-react";
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
  const [useCustomNames, setUseCustomNames] = useState(false);
  const [customNameCount, setCustomNameCount] = useState(3);
  const [firstNames, setFirstNames] = useState<string[]>([]);
  const [lastNames, setLastNames] = useState<string[]>([]);

  // CSV state
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvCfEmail, setCsvCfEmail] = useState("");
  const [csvCfApiKey, setCsvCfApiKey] = useState("");

  // Job selection for export
  const [selectedJobTenantIds, setSelectedJobTenantIds] = useState<Set<string>>(new Set());

  // Health check state
  const [healthLoading, setHealthLoading] = useState<Set<string>>(new Set());
  const [healthResults, setHealthResults] = useState<Record<string, MailboxHealthResult>>({});

  // Retry missing state
  const [retryLoading, setRetryLoading] = useState<Set<string>>(new Set());
  const [retryResults, setRetryResults] = useState<Record<string, RetryMissingResult>>({});

  // Fix security defaults state
  const [fixLoading, setFixLoading] = useState<Set<string>>(new Set());
  const [fixResults, setFixResults] = useState<Record<string, { status: string; detail?: string; error?: string }>>({});

  // Result banner
  const [result, setResult] = useState<BulkMailboxResult | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [t, j] = await Promise.all([api.listTenants(1, "complete"), api.listMailboxJobs()]);
      setTenants(t.tenants);
      setJobs(j.jobs);
      // Initialize health results from persisted data
      const cached: Record<string, MailboxHealthResult> = {};
      for (const job of j.jobs) {
        if (job.health_results) {
          cached[job.id] = job.health_results as unknown as MailboxHealthResult;
        }
      }
      if (Object.keys(cached).length > 0) {
        setHealthResults(prev => ({ ...cached, ...prev }));
      }
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
    if (event.type === "mailbox_health_check" && event.job_id) {
      const r = event as unknown as MailboxHealthResult;
      if (r.status === "running") {
        setHealthLoading(prev => new Set(prev).add(event.job_id!));
      } else {
        setHealthLoading(prev => { const n = new Set(prev); n.delete(event.job_id!); return n; });
        setHealthResults(prev => ({ ...prev, [event.job_id!]: r }));
      }
    }
    if (event.type === "retry_missing_result" && event.job_id) {
      const r = event as unknown as RetryMissingResult;
      if (r.status === "running") {
        setRetryLoading(prev => new Set(prev).add(event.job_id!));
      } else {
        setRetryLoading(prev => { const n = new Set(prev); n.delete(event.job_id!); return n; });
        setRetryResults(prev => ({ ...prev, [event.job_id!]: r }));
        // Clear old health results since they're stale now
        setHealthResults(prev => { const n = { ...prev }; delete n[event.job_id!]; return n; });
      }
    }
    if (event.type === "fix_security_defaults" && event.tenant_id) {
      setFixLoading(prev => { const n = new Set(prev); n.delete(event.tenant_id!); return n; });
      setFixResults(prev => ({ ...prev, [event.tenant_id!]: { status: event.status || "complete", detail: event.detail, error: event.error } }));
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
      let customNames: string[] | undefined;
      if (useCustomNames) {
        const missing = [];
        for (let i = 0; i < customNameCount; i++) {
          if (!firstNames[i]?.trim() || !lastNames[i]?.trim()) missing.push(i + 1);
        }
        if (missing.length > 0) {
          alert(`Please fill in both first and last name for row(s): ${missing.join(", ")}`);
          setLoading(false);
          return;
        }
        customNames = Array.from({ length: customNameCount }, (_, i) =>
          `${firstNames[i].trim()} ${lastNames[i].trim()}`
        );
      }
      const items = Array.from(selectedTenants).map(id => ({
        tenant_id: id,
        domain: domainMap[id].trim(),
        mailbox_count: count,
        ...(customNames ? { custom_names: customNames } : {}),
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

  async function handleHealthCheck(jobId: string) {
    setHealthLoading(prev => new Set(prev).add(jobId));
    try {
      await api.healthCheckMailboxes(jobId);
    } catch (err: any) {
      setHealthLoading(prev => { const n = new Set(prev); n.delete(jobId); return n; });
      alert(err.message);
    }
  }

  async function handleRetryMissing(jobId: string) {
    setRetryLoading(prev => new Set(prev).add(jobId));
    try {
      await api.retryMissingMailboxes(jobId);
    } catch (err: any) {
      setRetryLoading(prev => { const n = new Set(prev); n.delete(jobId); return n; });
      alert(err.message);
    }
  }

  async function handleFixSecurityDefaults(tenantId: string) {
    setFixLoading(prev => new Set(prev).add(tenantId));
    try {
      await api.fixSecurityDefaults(tenantId);
    } catch (err: any) {
      setFixLoading(prev => { const n = new Set(prev); n.delete(tenantId); return n; });
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

  function getActualCount(job: MailboxJob): { actual: number; requested: number; mismatch: boolean } | null {
    const step7 = job.step_results?.["7"];
    if (!step7?.detail) return null;
    const m = step7.detail.match(/Created:\s*(\d+),\s*Existed:\s*(\d+),\s*Failed:\s*(\d+)/);
    if (!m) return null;
    const actual = parseInt(m[1]) + parseInt(m[2]);
    const failed = parseInt(m[3]);
    return { actual, requested: job.mailbox_count, mismatch: failed > 0 };
  }

  function HealthCheckBanner({ result: r, tenantId }: { result: MailboxHealthResult; tenantId: string }) {
    if (r.status === "error") {
      return (
        <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded text-xs text-red-700">
          <span className="font-medium">Health check error:</span> {r.error}
        </div>
      );
    }
    if (r.status !== "complete") return null;

    const allGood = r.missing?.length === 0 && r.smtp_failed?.length === 0;
    const bgColor = allGood ? "bg-green-50 border-green-200" : "bg-yellow-50 border-yellow-200";
    const textColor = allGood ? "text-green-800" : "text-yellow-800";

    return (
      <div className={`mt-2 p-3 ${bgColor} border rounded text-xs ${textColor}`}>
        <div className="flex items-center gap-4 mb-1">
          <span className="font-medium">
            {allGood ? "All mailboxes healthy" : "Health check issues found"}
          </span>
          <span>Exchange: {r.found_in_exchange}/{r.total_in_db} found</span>
          <span>SMTP: {r.smtp_ok}/{r.smtp_tested} passed</span>
        </div>
        {(r.missing?.length ?? 0) > 0 && (
          <div className="mt-1">
            <span className="font-medium text-red-700">Missing from Exchange ({r.missing!.length}):</span>{" "}
            <span className="font-mono">{r.missing!.slice(0, 10).join(", ")}{r.missing!.length > 10 ? ` +${r.missing!.length - 10} more` : ""}</span>
          </div>
        )}
        {(r.extra_in_exchange?.length ?? 0) > 0 && (
          <div className="mt-1">
            <span className="font-medium">Extra in Exchange ({r.extra_in_exchange!.length}):</span>{" "}
            <span className="font-mono">{r.extra_in_exchange!.slice(0, 10).join(", ")}{r.extra_in_exchange!.length > 10 ? ` +${r.extra_in_exchange!.length - 10} more` : ""}</span>
          </div>
        )}
        {(r.smtp_failed?.length ?? 0) > 0 && (
          <div className="mt-1">
            <span className="font-medium text-red-700">SMTP auth failed ({r.smtp_failed!.length}):</span>{" "}
            {r.smtp_failed!.map((f, i) => (
              <span key={i} className="font-mono">{f.email}{i < r.smtp_failed!.length - 1 ? ", " : ""}</span>
            ))}
          </div>
        )}
        {(r.smtp_failed?.length ?? 0) > 0 && (
          <div className="mt-2">
            {fixLoading.has(tenantId) ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-blue-600">
                <Loader2 size={12} className="animate-spin" /> Fixing security defaults...
              </span>
            ) : fixResults[tenantId] ? (
              <span className={`text-xs ${fixResults[tenantId].status === "complete" ? "text-green-700" : "text-red-700"}`}>
                {fixResults[tenantId].status === "complete" ? fixResults[tenantId].detail : `Error: ${fixResults[tenantId].error}`}
                {fixResults[tenantId].status === "complete" && " — Run health check again to verify."}
              </span>
            ) : (
              <button
                onClick={(e) => { e.stopPropagation(); handleFixSecurityDefaults(tenantId); }}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
              >
                <Lock size={12} /> Fix SMTP Auth (Disable Security Defaults)
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  function RetryResultBanner({ result: r }: { result: RetryMissingResult }) {
    if (r.status === "error") {
      return (
        <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded text-xs text-red-700">
          <span className="font-medium">Retry error:</span> {r.error}
        </div>
      );
    }
    if (r.status !== "complete") return null;

    const allGood = (r.failed ?? 0) === 0;
    const bgColor = allGood ? "bg-blue-50 border-blue-200" : "bg-orange-50 border-orange-200";
    const textColor = allGood ? "text-blue-800" : "text-orange-800";

    return (
      <div className={`mt-2 p-3 ${bgColor} border rounded text-xs ${textColor}`}>
        <div className="flex items-center gap-4">
          <span className="font-medium">Retry complete</span>
          <span>Missing: {r.missing_count}</span>
          <span>Created: {r.created ?? 0}</span>
          {(r.existed ?? 0) > 0 && <span>Already existed: {r.existed}</span>}
          {(r.failed ?? 0) > 0 && <span className="text-red-600 font-medium">Failed: {r.failed}</span>}
        </div>
        {(r.failed_list?.length ?? 0) > 0 && (
          <div className="mt-1">
            <span className="font-medium text-red-700">Failed:</span>{" "}
            <span className="font-mono">{r.failed_list!.map(f => f.email).slice(0, 10).join(", ")}</span>
          </div>
        )}
      </div>
    );
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

              {/* Custom Names */}
              <div className="mb-4">
                <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
                  <input
                    type="checkbox"
                    checked={useCustomNames}
                    onChange={e => {
                      setUseCustomNames(e.target.checked);
                      if (e.target.checked && firstNames.length === 0) {
                        setFirstNames(Array(customNameCount).fill(""));
                        setLastNames(Array(customNameCount).fill(""));
                      }
                    }}
                    className="rounded"
                  />
                  Custom Names
                </label>
                {useCustomNames && (
                  <div className="mt-3 ml-6">
                    <div className="flex items-center gap-3 mb-3">
                      <label className="text-sm text-gray-600">Number of names:</label>
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={customNameCount}
                        onChange={e => {
                          const n = Math.max(1, Math.min(20, parseInt(e.target.value) || 1));
                          setCustomNameCount(n);
                          setFirstNames(prev => {
                            const arr = [...prev];
                            while (arr.length < n) arr.push("");
                            return arr.slice(0, n);
                          });
                          setLastNames(prev => {
                            const arr = [...prev];
                            while (arr.length < n) arr.push("");
                            return arr.slice(0, n);
                          });
                        }}
                        className="w-20 px-2 py-1 border rounded text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <div className="grid grid-cols-[2rem_1fr_1fr] gap-2 text-xs font-medium text-gray-500">
                        <span>#</span>
                        <span>First Name</span>
                        <span>Last Name</span>
                      </div>
                      {Array.from({ length: customNameCount }, (_, i) => (
                        <div key={i} className="grid grid-cols-[2rem_1fr_1fr] gap-2 items-center">
                          <span className="text-xs text-gray-400">{i + 1}</span>
                          <input
                            value={firstNames[i] || ""}
                            onChange={e => setFirstNames(prev => { const n = [...prev]; n[i] = e.target.value; return n; })}
                            placeholder="e.g. Ayush"
                            className="px-2 py-1.5 border rounded text-sm"
                          />
                          <input
                            value={lastNames[i] || ""}
                            onChange={e => setLastNames(prev => { const n = [...prev]; n[i] = e.target.value; return n; })}
                            placeholder="e.g. Baldota"
                            className="px-2 py-1.5 border rounded text-sm"
                          />
                        </div>
                      ))}
                    </div>
                    {(() => {
                      const filled = Array.from({ length: customNameCount }, (_, i) =>
                        firstNames[i]?.trim() && lastNames[i]?.trim()
                      ).filter(Boolean).length;
                      if (filled === 0) return null;
                      const perName = Math.floor(count / filled);
                      const remainder = count % filled;
                      const allocation = Array.from({ length: filled }, (_, i) => perName + (i < remainder ? 1 : 0));
                      return (
                        <p className="text-xs text-gray-500 mt-2">
                          {filled} name{filled > 1 ? "s" : ""} &rarr; {allocation.join("/")} email variations each = {count} mailboxes
                          {perName > 50 && (
                            <span className="text-yellow-600 ml-2">(high variation count per name)</span>
                          )}
                        </p>
                      );
                    })()}
                  </div>
                )}
              </div>

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
                  Expected columns: <code className="bg-gray-100 px-1 rounded">tenant_email, domain, count, custom_names</code> (count defaults to 50, custom_names is optional, pipe-delimited e.g. &quot;John Doe|Jane Smith&quot;)
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

      {/* Action Bar */}
      <div className="flex items-center gap-2 mb-4">
        <button
          onClick={() => api.exportAllMailboxesCsv()}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white border rounded-lg hover:bg-gray-50"
        >
          <FileDown size={14} /> Export All
        </button>
        {selectedJobTenantIds.size > 0 && (
          <>
            <button
              onClick={() => api.exportAllMailboxesCsv(Array.from(selectedJobTenantIds))}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              <FileDown size={14} /> Export Selected ({selectedJobTenantIds.size})
            </button>
            <button
              onClick={() => {
                const eligibleJobs = jobs.filter(j =>
                  selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed")
                );
                if (eligibleJobs.length === 0) { alert("No complete/failed jobs selected"); return; }
                eligibleJobs.forEach(j => handleRetryMissing(j.id));
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-orange-500 text-white rounded-lg hover:bg-orange-600"
            >
              <RefreshCw size={14} /> Retry Missing ({jobs.filter(j => selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed")).length})
            </button>
            <button
              onClick={() => {
                const eligibleJobs = jobs.filter(j =>
                  selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed")
                );
                if (eligibleJobs.length === 0) { alert("No complete/failed jobs selected"); return; }
                eligibleJobs.forEach(j => handleHealthCheck(j.id));
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-pink-500 text-white rounded-lg hover:bg-pink-600"
            >
              <HeartPulse size={14} /> Health Check ({jobs.filter(j => selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed")).length})
            </button>
            <button
              onClick={() => {
                const tenantIds = new Set(
                  jobs.filter(j => selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed"))
                    .map(j => j.tenant_id)
                );
                if (tenantIds.size === 0) { alert("No complete/failed jobs selected"); return; }
                tenantIds.forEach(tid => handleFixSecurityDefaults(tid));
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-indigo-500 text-white rounded-lg hover:bg-indigo-600"
            >
              <Lock size={14} /> Fix SMTP Auth ({new Set(jobs.filter(j => selectedJobTenantIds.has(j.tenant_id) && (j.status === "complete" || j.status === "failed")).map(j => j.tenant_id)).size})
            </button>
          </>
        )}
      </div>

      {/* Jobs list */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <h2 className="font-semibold p-4 border-b">Pipeline Jobs</h2>
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="w-10 px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={jobs.length > 0 && selectedJobTenantIds.size === jobs.length}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedJobTenantIds(new Set(jobs.map(j => j.tenant_id)));
                    } else {
                      setSelectedJobTenantIds(new Set());
                    }
                  }}
                  className="rounded"
                />
              </th>
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
                    <td className="w-10 px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedJobTenantIds.has(j.tenant_id)}
                        onChange={(e) => {
                          setSelectedJobTenantIds(prev => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(j.tenant_id);
                            else next.delete(j.tenant_id);
                            return next;
                          });
                        }}
                        className="rounded"
                      />
                    </td>
                    <td className="px-2 py-3 text-center">
                      {isExpanded
                        ? <ChevronDown size={14} className="text-gray-400 inline" />
                        : <ChevronRight size={14} className="text-gray-400 inline" />}
                    </td>
                    <td className="px-4 py-3">{j.domain}</td>
                    <td className="px-4 py-3">
                      {(() => {
                        const counts = getActualCount(j);
                        if (counts && counts.mismatch) {
                          const color = counts.actual === 0 ? "text-red-600" : "text-yellow-600";
                          return <span className={`font-medium ${color}`}>{counts.actual}/{counts.requested}</span>;
                        }
                        return j.mailbox_count;
                      })()}
                    </td>
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
                        {(j.status === "complete" || j.status === "failed") && (
                          <>
                            {(() => {
                              const hr = healthResults[j.id];
                              const hasIssues = hr?.status === "complete" && ((hr.missing?.length ?? 0) > 0 || (hr.smtp_failed?.length ?? 0) > 0);
                              const isHealthy = hr?.status === "complete" && !hasIssues;
                              const isError = hr?.status === "error";
                              const color = isHealthy ? "text-green-500" : (hasIssues || isError) ? "text-red-500" : "text-pink-500";
                              const hoverBg = isHealthy ? "hover:bg-green-50" : (hasIssues || isError) ? "hover:bg-red-50" : "hover:bg-pink-50";
                              const title = isHealthy ? "All mailboxes healthy" : hasIssues ? `Issues: ${hr!.missing?.length ?? 0} missing, ${hr!.smtp_failed?.length ?? 0} SMTP failed` : isError ? `Error: ${hr!.error}` : "Health check mailboxes";

                              if (healthLoading.has(j.id)) {
                                return (
                                  <span className="p-1" title="Checking mailboxes...">
                                    <Loader2 size={16} className="text-pink-500 animate-spin" />
                                  </span>
                                );
                              }
                              return (
                                <button
                                  onClick={() => handleHealthCheck(j.id)}
                                  className={`p-1 ${hoverBg} rounded`} title={title}
                                >
                                  <HeartPulse size={16} className={color} />
                                </button>
                              );
                            })()}
                            {retryLoading.has(j.id) ? (
                              <span className="p-1" title="Retrying missing mailboxes...">
                                <Loader2 size={16} className="text-orange-500 animate-spin" />
                              </span>
                            ) : (
                              <button
                                onClick={() => handleRetryMissing(j.id)}
                                className="p-1 hover:bg-orange-50 rounded" title="Retry missing mailboxes"
                              >
                                <RefreshCw size={16} className="text-orange-500" />
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
                              </>
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
                      <td colSpan={8} className="px-6 py-2">
                        <MailboxPipelineProgress
                          stepResults={j.step_results}
                          jobStatus={j.status}
                          currentStep={parseCurrentStep(j.current_phase)}
                        />
                        {healthResults[j.id] && (
                          <HealthCheckBanner result={healthResults[j.id]} tenantId={j.tenant_id} />
                        )}
                        {retryResults[j.id] && (
                          <RetryResultBanner result={retryResults[j.id]} />
                        )}
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
              <tbody><tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No jobs yet</td></tr></tbody>
            )}
        </table>
      </div>
    </div>
  );
}
