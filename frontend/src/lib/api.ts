const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options.headers as Record<string, string> },
    ...options,
  });
  if (res.status === 401) {
    if (typeof window !== "undefined" && !window.location.pathname.includes("/login")) {
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  // Auth
  login: (password: string) => request("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ password }) }),
  logout: () => request("/api/v1/auth/logout", { method: "POST" }),
  verify: () => request<{ status: string }>("/api/v1/auth/verify"),

  // Tenants
  listTenants: (page = 1, status?: string) =>
    request<{ tenants: any[]; total: number }>(`/api/v1/tenants?page=${page}${status ? `&status_filter=${status}` : ""}`),
  createTenant: (data: { name: string; admin_email: string; admin_password: string; new_password?: string }) =>
    request("/api/v1/tenants", { method: "POST", body: JSON.stringify(data) }),
  bulkCreateTenants: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const r = await fetch(`/api/v1/tenants/bulk`, { method: "POST", body: formData, credentials: "include" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return r.json();
  },
  getTenant: (id: string) => request<any>(`/api/v1/tenants/${id}`),
  updateTenant: (id: string, data: { admin_password?: string; new_password?: string }) =>
    request(`/api/v1/tenants/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteTenant: (id: string) => request(`/api/v1/tenants/${id}`, { method: "DELETE" }),
  setupTenant: (id: string) => request(`/api/v1/tenants/${id}/setup`, { method: "POST" }),
  retryTenant: (id: string) => request(`/api/v1/tenants/${id}/retry`, { method: "POST" }),
  healthCheckTenant: (id: string) => request<{ status: string }>(`/api/v1/tenants/${id}/health-check`, { method: "POST" }),
  fixHealth: (id: string) => request<{ status: string }>(`/api/v1/tenants/${id}/fix-health`, { method: "POST" }),
  fixSecurityDefaults: (id: string) => request<{ status: string }>(`/api/v1/tenants/${id}/fix-security-defaults`, { method: "POST" }),
  getCredentials: (id: string) => request<any>(`/api/v1/tenants/${id}/credentials`),

  exportTenantsCsv: (ids?: string[]) => {
    const params = ids?.length ? `?ids=${ids.join(",")}` : "";
    window.open(`/api/v1/tenants/export${params}`, "_blank");
  },
  exportAllMailboxesCsv: (tenantIds?: string[]) => {
    const params = tenantIds?.length ? `?tenant_ids=${tenantIds.join(",")}` : "";
    window.open(`/api/v1/mailboxes/export-all${params}`, "_blank");
  },

  // Mailboxes
  listMailboxes: (tenantId: string) => request<{ mailboxes: any[] }>(`/api/v1/mailboxes/${tenantId}`),
  createMailboxes: (tenantId: string, data: { domain: string; mailbox_count: number; cf_email?: string; cf_api_key?: string }) =>
    request(`/api/v1/mailboxes/${tenantId}/create`, { method: "POST", body: JSON.stringify(data) }),
  bulkCreateMailboxes: (items: { tenant_id: string; domain: string; mailbox_count: number; custom_names?: string[] }[], cfEmail?: string, cfApiKey?: string) =>
    request<import("./types").BulkMailboxResult>("/api/v1/mailboxes/bulk-create", {
      method: "POST",
      body: JSON.stringify({ items, cf_email: cfEmail || undefined, cf_api_key: cfApiKey || undefined }),
    }),
  bulkCreateMailboxesCsv: async (file: File, cfEmail?: string, cfApiKey?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    const params = new URLSearchParams();
    if (cfEmail) params.set("cf_email", cfEmail);
    if (cfApiKey) params.set("cf_api_key", cfApiKey);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const r = await fetch(`/api/v1/mailboxes/bulk-create-csv${qs}`, { method: "POST", body: formData, credentials: "include" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return r.json() as Promise<import("./types").BulkMailboxResult>;
  },
  listMailboxJobs: () => request<{ jobs: any[] }>("/api/v1/mailbox-jobs"),
  stopJob: (jobId: string) => request(`/api/v1/mailbox-jobs/${jobId}/stop`, { method: "POST" }),
  enableDkim: (jobId: string) => request<{ status: string }>(`/api/v1/mailbox-jobs/${jobId}/enable-dkim`, { method: "POST" }),
  healthCheckMailboxes: (jobId: string) => request<{ status: string }>(`/api/v1/mailbox-jobs/${jobId}/health-check`, { method: "POST" }),
  retryMissingMailboxes: (jobId: string) => request<{ status: string }>(`/api/v1/mailbox-jobs/${jobId}/retry-missing`, { method: "POST" }),

  // Monitor
  dashboard: () => request<any>("/api/v1/monitor/dashboard"),
  tenantHealth: (tenantId: string) => request<any>(`/api/v1/monitor/${tenantId}`),
  triggerCheck: (tenantId: string) => request(`/api/v1/monitor/${tenantId}/check-now`, { method: "POST" }),
  mailflowHistory: (tenantId: string) => request<any>(`/api/v1/monitor/${tenantId}/mailflow`),
  listAlerts: () => request<{ alerts: any[] }>("/api/v1/monitor/alerts"),
  ackAlert: (id: number) => request(`/api/v1/monitor/alerts/${id}/ack`, { method: "POST" }),

  // TOTP Vault
  listTOTP: () => request<import("./types").TOTPEntry[]>("/api/v1/totp"),
  getTOTP: (tenantId: string) => request<import("./types").TOTPEntry>(`/api/v1/totp/${tenantId}`),
  setTOTPSecret: (tenantId: string, secret: string) =>
    request(`/api/v1/totp/${tenantId}/secret`, { method: "PUT", body: JSON.stringify({ secret }) }),
  deleteTOTPSecret: (tenantId: string) =>
    request(`/api/v1/totp/${tenantId}/secret`, { method: "DELETE" }),

  // Settings
  listCFConfigs: () => request<{ configs: any[] }>("/api/v1/settings/cloudflare"),
  createCFConfig: (data: any) => request("/api/v1/settings/cloudflare", { method: "POST", body: JSON.stringify(data) }),
  deleteCFConfig: (id: string) => request(`/api/v1/settings/cloudflare/${id}`, { method: "DELETE" }),
  getAlertSettings: () => request<any>("/api/v1/settings/alerts"),
  updateAlertSettings: (data: any) => request("/api/v1/settings/alerts", { method: "PUT", body: JSON.stringify(data) }),
};
