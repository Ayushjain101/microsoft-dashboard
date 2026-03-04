"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import AuthGuard from "@/components/layout/AuthGuard";
import { RefreshCw } from "lucide-react";

export default function TenantHealthPage() {
  const params = useParams();
  const tenantId = params.tenantId as string;
  const [checks, setChecks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  function loadChecks() {
    setLoading(true);
    api.tenantHealth(tenantId)
      .then((data) => setChecks(data.checks))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadChecks(); }, [tenantId]);

  async function handleCheckNow() {
    await api.triggerCheck(tenantId);
    setTimeout(loadChecks, 3000);
  }

  const STATUS_COLORS: Record<string, string> = {
    healthy: "bg-green-100 text-green-700",
    blocked: "bg-red-100 text-red-700",
    auth_failed: "bg-red-100 text-red-700",
    timeout: "bg-yellow-100 text-yellow-700",
    error: "bg-red-100 text-red-700",
    warning: "bg-yellow-100 text-yellow-700",
  };

  return (
    <AuthGuard>
      <div>
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Health History</h1>
          <button
            onClick={handleCheckNow}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm"
          >
            <RefreshCw size={16} /> Check Now
          </button>
        </div>

        {loading ? (
          <div className="text-center text-gray-400 py-8">Loading...</div>
        ) : (
          <div className="bg-white rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-4 py-3">Type</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-left px-4 py-3">Detail</th>
                  <th className="text-left px-4 py-3">Response</th>
                  <th className="text-left px-4 py-3">Time</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c) => (
                  <tr key={c.id} className="border-t">
                    <td className="px-4 py-3 font-medium">{c.check_type}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[c.status] || ""}`}>
                        {c.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs max-w-md truncate">{c.detail || "—"}</td>
                    <td className="px-4 py-3 text-gray-500">{c.response_ms ? `${c.response_ms}ms` : "—"}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {c.checked_at ? new Date(c.checked_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
                {checks.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No checks yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
