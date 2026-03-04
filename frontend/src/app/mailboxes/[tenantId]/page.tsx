"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { Mailbox } from "@/lib/types";
import AuthGuard from "@/components/layout/AuthGuard";
import { Download } from "lucide-react";

export default function TenantMailboxesPage() {
  const params = useParams();
  const tenantId = params.tenantId as string;
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listMailboxes(tenantId)
      .then((data) => setMailboxes(data.mailboxes))
      .finally(() => setLoading(false));
  }, [tenantId]);

  function handleExport() {
    window.open(`/api/v1/mailboxes/${tenantId}/export`, "_blank");
  }

  return (
    <AuthGuard>
      <div>
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Mailboxes</h1>
          <button
            onClick={handleExport}
            className="flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 text-sm"
          >
            <Download size={16} /> Export CSV
          </button>
        </div>

        {loading ? (
          <div className="text-center text-gray-400 py-8">Loading...</div>
        ) : (
          <div className="bg-white rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-4 py-3">Email</th>
                  <th className="text-left px-4 py-3">Display Name</th>
                  <th className="text-left px-4 py-3">SMTP</th>
                  <th className="text-left px-4 py-3">Health</th>
                  <th className="text-left px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody>
                {mailboxes.map((m) => (
                  <tr key={m.id} className="border-t">
                    <td className="px-4 py-3">{m.email}</td>
                    <td className="px-4 py-3 text-gray-600">{m.display_name}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-xs ${
                        m.smtp_enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"
                      }`}>
                        {m.smtp_enabled ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {m.last_monitor_status ? (
                        <span className={`px-2 py-1 rounded-full text-xs ${
                          m.last_monitor_status === "healthy" ? "bg-green-100 text-green-700" :
                          m.last_monitor_status === "blocked" ? "bg-red-100 text-red-700" :
                          "bg-yellow-100 text-yellow-700"
                        }`}>
                          {m.last_monitor_status}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">{new Date(m.created_at).toLocaleString()}</td>
                  </tr>
                ))}
                {mailboxes.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No mailboxes</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
