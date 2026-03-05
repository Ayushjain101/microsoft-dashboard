"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Alert } from "@/lib/types";
import { Activity, AlertTriangle, CheckCircle, XCircle, Bell, Mail } from "lucide-react";

export default function MonitorPage() {
  const [dashboard, setDashboard] = useState<any>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.dashboard(), api.listAlerts()])
      .then(([d, a]) => { setDashboard(d); setAlerts(a.alerts); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-center text-gray-400">Loading...</div>;
  if (error) return <div className="p-8 text-center text-red-500">Failed to load monitoring data: {error}</div>;

  const tenantCounts = dashboard?.tenant_counts || {};
  const checkCounts = dashboard?.check_status_counts || {};
  const mailflowCounts = dashboard?.mailflow_counts || {};

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Health Monitoring</h1>

      {/* Summary cards */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        <div className="bg-white rounded-lg border p-4">
          <div className="flex items-center gap-2 text-gray-500 text-sm mb-1">
            <Activity size={16} /> Total Mailboxes
          </div>
          <div className="text-2xl font-bold">{dashboard?.total_mailboxes || 0}</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="flex items-center gap-2 text-green-600 text-sm mb-1">
            <CheckCircle size={16} /> Healthy
          </div>
          <div className="text-2xl font-bold text-green-700">{checkCounts.healthy || 0}</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="flex items-center gap-2 text-red-600 text-sm mb-1">
            <XCircle size={16} /> Blocked/Failed
          </div>
          <div className="text-2xl font-bold text-red-700">
            {(checkCounts.blocked || 0) + (checkCounts.auth_failed || 0) + (checkCounts.error || 0)}
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="flex items-center gap-2 text-yellow-600 text-sm mb-1">
            <Bell size={16} /> Active Alerts
          </div>
          <div className="text-2xl font-bold text-yellow-700">{dashboard?.active_alerts || 0}</div>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <div className="flex items-center gap-2 text-orange-600 text-sm mb-1">
            <Mail size={16} /> Mailflow Issues
          </div>
          <div className="text-2xl font-bold text-orange-700">
            {(mailflowCounts.critical || 0) + (mailflowCounts.warning || 0)}
          </div>
        </div>
      </div>

      {/* Tenant status summary */}
      <div className="bg-white rounded-lg border p-4 mb-6">
        <h2 className="font-semibold mb-3">Tenants by Status</h2>
        <div className="flex gap-4">
          {Object.entries(tenantCounts).map(([status, count]) => (
            <div key={status} className="text-sm">
              <span className="font-medium capitalize">{status}:</span> {count as number}
            </div>
          ))}
        </div>
      </div>

      {/* Alerts */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <h2 className="font-semibold p-4 border-b">Recent Alerts</h2>
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left px-4 py-3">Severity</th>
              <th className="text-left px-4 py-3">Type</th>
              <th className="text-left px-4 py-3">Message</th>
              <th className="text-left px-4 py-3">Time</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id} className="border-t">
                <td className="px-4 py-3">
                  <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                    a.severity === "critical" ? "bg-red-100 text-red-700" :
                    a.severity === "warning" ? "bg-yellow-100 text-yellow-700" :
                    "bg-blue-100 text-blue-700"
                  }`}>
                    {a.severity}
                  </span>
                </td>
                <td className="px-4 py-3">{a.alert_type}</td>
                <td className="px-4 py-3 text-gray-600">{a.message}</td>
                <td className="px-4 py-3 text-xs text-gray-500">{new Date(a.created_at).toLocaleString()}</td>
                <td className="px-4 py-3 text-right">
                  {!a.acknowledged && (
                    <button
                      onClick={async () => {
                        await api.ackAlert(a.id);
                        setAlerts((prev) => prev.map((x) => x.id === a.id ? { ...x, acknowledged: true } : x));
                      }}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Acknowledge
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {alerts.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No alerts</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
