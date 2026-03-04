"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Upload } from "lucide-react";

export default function NewTenantPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"single" | "bulk">("single");

  // Single form
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Bulk
  const [file, setFile] = useState<File | null>(null);
  const [bulkResult, setBulkResult] = useState<any>(null);

  async function handleSingle(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const tenantName = name || email.split("@")[1]?.split(".")[0] || "tenant";
      await api.createTenant({
        name: tenantName,
        admin_email: email,
        admin_password: password,
        new_password: newPassword || undefined,
      });
      router.push("/tenants");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleBulk(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const result = await api.bulkCreateTenants(file);
      setBulkResult(result);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">Add Tenants</h1>

      {/* Mode tabs */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setMode("single")}
          className={`px-4 py-2 rounded-lg text-sm ${
            mode === "single" ? "bg-blue-600 text-white" : "bg-gray-100"
          }`}
        >
          Single Tenant
        </button>
        <button
          onClick={() => setMode("bulk")}
          className={`px-4 py-2 rounded-lg text-sm ${
            mode === "bulk" ? "bg-blue-600 text-white" : "bg-gray-100"
          }`}
        >
          Bulk Import (CSV)
        </button>
      </div>

      {error && <div className="bg-red-50 text-red-600 p-3 rounded-lg mb-4 text-sm">{error}</div>}

      {mode === "single" ? (
        <form onSubmit={handleSingle} className="bg-white rounded-lg border p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Tenant Name (optional)</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Auto-detected from email"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Admin Email *</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin@tenant.onmicrosoft.com"
              className="w-full px-3 py-2 border rounded-lg text-sm"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Admin Password *</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">New Password (if forced change)</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Leave blank to use default: Atoz12345@!"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
          >
            {loading ? "Creating..." : "Create Tenant"}
          </button>
        </form>
      ) : (
        <form onSubmit={handleBulk} className="bg-white rounded-lg border p-6 space-y-4">
          <p className="text-sm text-gray-600">
            Upload a CSV with columns: <code className="bg-gray-100 px-1">email, password, new_password, name</code>
          </p>
          <div className="border-2 border-dashed rounded-lg p-8 text-center">
            <Upload className="mx-auto mb-2 text-gray-400" size={32} />
            <input
              type="file"
              accept=".csv,.json"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !file}
            className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
          >
            {loading ? "Importing..." : "Import"}
          </button>
          {bulkResult && (
            <div className="bg-green-50 p-3 rounded-lg text-sm">
              Created: {bulkResult.created} | Skipped: {bulkResult.skipped}
              {bulkResult.skipped_emails?.length > 0 && (
                <div className="text-xs text-gray-500 mt-1">
                  Skipped: {bulkResult.skipped_emails.join(", ")}
                </div>
              )}
            </div>
          )}
        </form>
      )}
    </div>
  );
}
