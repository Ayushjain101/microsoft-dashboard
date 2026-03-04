"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Tenant, MailboxJob, WSEvent } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Plus, StopCircle, Download } from "lucide-react";

export default function MailboxesPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [jobs, setJobs] = useState<MailboxJob[]>([]);
  const [selectedTenant, setSelectedTenant] = useState("");
  const [domain, setDomain] = useState("");
  const [count, setCount] = useState(50);
  const [cfEmail, setCfEmail] = useState("");
  const [cfApiKey, setCfApiKey] = useState("");
  const [loading, setLoading] = useState(false);

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
  }, [loadData]);

  useWebSocket(onWsMessage);

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

  async function handleExport(tenantId: string) {
    window.open(`/api/v1/mailboxes/${tenantId}/export`, "_blank");
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
              <th className="text-left px-4 py-3">Domain</th>
              <th className="text-left px-4 py-3">Count</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Phase</th>
              <th className="text-left px-4 py-3">Created</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className="border-t">
                <td className="px-4 py-3">{j.domain}</td>
                <td className="px-4 py-3">{j.mailbox_count}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[j.status] || ""}`}>
                    {j.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">{j.current_phase || "—"}</td>
                <td className="px-4 py-3 text-xs text-gray-500">{new Date(j.created_at).toLocaleString()}</td>
                <td className="px-4 py-3 text-right">
                  {j.status === "running" && (
                    <button
                      onClick={async () => { try { await api.stopJob(j.id); loadData(); } catch (err: any) { alert(err.message); } }}
                      className="p-1 hover:bg-red-50 rounded"
                    >
                      <StopCircle size={16} className="text-red-500" />
                    </button>
                  )}
                  {j.status === "complete" && (
                    <button
                      onClick={() => handleExport(j.tenant_id)}
                      className="p-1 hover:bg-green-50 rounded"
                    >
                      <Download size={16} className="text-green-600" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {jobs.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No jobs yet</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
