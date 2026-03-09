"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import { Upload, ArrowLeft, User, FileSpreadsheet } from "lucide-react";

export default function NewTenantPage() {
  const authenticated = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<"single" | "bulk">("single");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [bulkResult, setBulkResult] = useState<any>(null);

  async function handleSingle(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const tenantName = name || email.split("@")[1]?.split(".")[0] || "tenant";
      await api.createTenant({ name: tenantName, admin_email: email, admin_password: password, new_password: newPassword || undefined });
      router.push("/tenants");
    } catch (err: any) { setError(err.message); }
    finally { setLoading(false); }
  }

  async function handleBulk(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const result = await api.bulkCreateTenants(file);
      setBulkResult(result);
    } catch (err: any) { setError(err.message); }
    finally { setLoading(false); }
  }

  if (authenticated === null) return null;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <button onClick={() => router.back()} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6">
          <ArrowLeft size={16} /> Back to Tenants
        </button>

        <div className="max-w-2xl">
          <h1 className="text-2xl font-bold mb-6">Add Tenants</h1>

          {/* Mode tabs */}
          <div className="flex gap-2 mb-6">
            <button onClick={() => setMode("single")} className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-colors ${mode === "single" ? "bg-blue-600 text-white shadow-sm" : "bg-white border text-gray-600 hover:bg-gray-50"}`}>
              <User size={16} /> Single Tenant
            </button>
            <button onClick={() => setMode("bulk")} className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-colors ${mode === "bulk" ? "bg-blue-600 text-white shadow-sm" : "bg-white border text-gray-600 hover:bg-gray-50"}`}>
              <FileSpreadsheet size={16} /> Bulk Import
            </button>
          </div>

          {error && <div className="bg-red-50 border border-red-200 text-red-600 p-3 rounded-xl mb-4 text-sm">{error}</div>}

          {mode === "single" ? (
            <form onSubmit={handleSingle} className="bg-white rounded-xl border p-6 space-y-4 shadow-sm">
              <div>
                <label className="block text-sm font-medium mb-1.5 text-gray-700">Tenant Name <span className="text-gray-400">(optional)</span></label>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Auto-detected from email" className="w-full px-4 py-2.5 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500/30 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1.5 text-gray-700">Admin Email</label>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@tenant.onmicrosoft.com" className="w-full px-4 py-2.5 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500/30 focus:outline-none" required />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1.5 text-gray-700">Admin Password</label>
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="w-full px-4 py-2.5 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500/30 focus:outline-none" required />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1.5 text-gray-700">New Password <span className="text-gray-400">(if forced change)</span></label>
                <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="Leave blank to use default" className="w-full px-4 py-2.5 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500/30 focus:outline-none" />
              </div>
              <button type="submit" disabled={loading} className="bg-blue-600 text-white px-6 py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium">
                {loading ? "Creating..." : "Create Tenant"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleBulk} className="bg-white rounded-xl border p-6 space-y-4 shadow-sm">
              <p className="text-sm text-gray-600">Upload a CSV with columns: <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">email, password, new_password, name</code></p>
              <div className="border-2 border-dashed rounded-xl p-10 text-center bg-gray-50/50 hover:bg-gray-50 transition-colors">
                <Upload className="mx-auto mb-3 text-gray-400" size={36} />
                <input type="file" accept=".csv,.json" onChange={(e) => setFile(e.target.files?.[0] || null)} className="text-sm" />
              </div>
              <button type="submit" disabled={loading || !file} className="bg-blue-600 text-white px-6 py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium">
                {loading ? "Importing..." : "Import"}
              </button>
              {bulkResult && (
                <div className="bg-green-50 border border-green-200 p-3 rounded-xl text-sm text-green-700">
                  Created: {bulkResult.created} | Skipped: {bulkResult.skipped}
                  {bulkResult.skipped_emails?.length > 0 && <div className="text-xs text-gray-500 mt-1">Skipped: {bulkResult.skipped_emails.join(", ")}</div>}
                </div>
              )}
            </form>
          )}
        </div>
      </main>
    </div>
  );
}
