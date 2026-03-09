"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Alert } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import {
  Activity, AlertTriangle, CheckCircle, XCircle, Bell, Mail,
  Search, Filter, Loader2,
} from "lucide-react";

export default function MonitorPage() {
  const authenticated = useAuth();
  const queryClient = useQueryClient();
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");

  const { data: dashboard, isLoading: dashLoading } = useQuery({
    queryKey: ["monitor-dashboard"],
    queryFn: () => api.dashboard(),
  });

  const { data: alertData, isLoading: alertsLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.listAlerts(),
  });

  if (authenticated === null) return null;

  const alerts: Alert[] = alertData?.alerts ?? [];
  const tenantCounts = dashboard?.tenant_counts || {};
  const checkCounts = dashboard?.check_status_counts || {};
  const mailflowCounts = dashboard?.mailflow_counts || {};

  const isLoading = dashLoading || alertsLoading;

  const filteredAlerts = alerts.filter(a => {
    if (severityFilter && a.severity !== severityFilter) return false;
    if (searchQuery && !a.message?.toLowerCase().includes(searchQuery.toLowerCase()) && !a.alert_type.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  async function handleAck(id: number) {
    await api.ackAlert(id);
    queryClient.invalidateQueries({ queryKey: ["alerts"] });
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <div className="max-w-[1400px] mx-auto">
          <div className="mb-6">
            <h1 className="text-2xl font-bold text-gray-900">Health Monitoring</h1>
            <p className="text-sm text-gray-500 mt-0.5">System overview and alert management</p>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-blue-600" /></div>
          ) : (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-5 gap-3 mb-6">
                <div className="bg-white rounded-xl border p-4">
                  <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2"><Activity size={14} /> TOTAL MAILBOXES</div>
                  <div className="text-2xl font-bold">{dashboard?.total_mailboxes || 0}</div>
                </div>
                <div className="bg-white rounded-xl border p-4">
                  <div className="flex items-center gap-2 text-emerald-600 text-xs font-medium mb-2"><CheckCircle size={14} /> HEALTHY</div>
                  <div className="text-2xl font-bold text-emerald-600">{checkCounts.healthy || 0}</div>
                </div>
                <div className="bg-white rounded-xl border p-4">
                  <div className="flex items-center gap-2 text-red-600 text-xs font-medium mb-2"><XCircle size={14} /> BLOCKED/FAILED</div>
                  <div className="text-2xl font-bold text-red-600">{(checkCounts.blocked || 0) + (checkCounts.auth_failed || 0) + (checkCounts.error || 0)}</div>
                </div>
                <div className="bg-white rounded-xl border p-4">
                  <div className="flex items-center gap-2 text-amber-600 text-xs font-medium mb-2"><Bell size={14} /> ACTIVE ALERTS</div>
                  <div className="text-2xl font-bold text-amber-600">{dashboard?.active_alerts || 0}</div>
                </div>
                <div className="bg-white rounded-xl border p-4">
                  <div className="flex items-center gap-2 text-orange-600 text-xs font-medium mb-2"><Mail size={14} /> MAILFLOW ISSUES</div>
                  <div className="text-2xl font-bold text-orange-600">{(mailflowCounts.critical || 0) + (mailflowCounts.warning || 0)}</div>
                </div>
              </div>

              {/* Tenant status summary */}
              <div className="bg-white rounded-xl border p-4 mb-6">
                <h2 className="font-semibold mb-3 text-sm">Tenants by Status</h2>
                <div className="flex gap-6">
                  {Object.entries(tenantCounts).map(([status, count]) => (
                    <div key={status} className="text-sm"><span className="font-medium capitalize text-gray-700">{status}:</span> <span className="text-gray-500">{count as number}</span></div>
                  ))}
                </div>
              </div>

              {/* Alerts */}
              <div className="bg-white rounded-xl border overflow-hidden shadow-sm">
                <div className="p-4 border-b flex items-center justify-between">
                  <h2 className="font-semibold">Recent Alerts</h2>
                  <div className="flex items-center gap-2">
                    <div className="relative">
                      <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                      <input type="text" placeholder="Search alerts..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="pl-8 pr-3 py-1.5 border rounded-lg text-xs w-52 focus:outline-none focus:ring-2 focus:ring-blue-500/30" />
                    </div>
                    <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)} className="px-3 py-1.5 border rounded-lg text-xs focus:outline-none">
                      <option value="">All Severities</option>
                      <option value="critical">Critical</option>
                      <option value="warning">Warning</option>
                      <option value="info">Info</option>
                    </select>
                  </div>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50/80 border-b">
                      <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Severity</th>
                      <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Type</th>
                      <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Message</th>
                      <th className="text-left px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Time</th>
                      <th className="text-right px-4 py-3 font-semibold text-gray-600 text-xs uppercase tracking-wider">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredAlerts.map((a) => (
                      <tr key={a.id} className="border-b last:border-b-0 hover:bg-gray-50/50">
                        <td className="px-4 py-3">
                          <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${
                            a.severity === "critical" ? "bg-red-50 text-red-700 border border-red-200" :
                            a.severity === "warning" ? "bg-amber-50 text-amber-700 border border-amber-200" :
                            "bg-blue-50 text-blue-700 border border-blue-200"
                          }`}>{a.severity}</span>
                        </td>
                        <td className="px-4 py-3 font-medium">{a.alert_type}</td>
                        <td className="px-4 py-3 text-gray-600">{a.message}</td>
                        <td className="px-4 py-3 text-xs text-gray-500">{new Date(a.created_at).toLocaleString()}</td>
                        <td className="px-4 py-3 text-right">
                          {!a.acknowledged && (
                            <button onClick={() => handleAck(a.id)} className="text-xs text-blue-600 hover:text-blue-800 font-medium">Acknowledge</button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filteredAlerts.length === 0 && (
                      <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-400">{searchQuery || severityFilter ? "No matching alerts" : "No alerts"}</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
