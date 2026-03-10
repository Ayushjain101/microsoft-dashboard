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
  // ── Auth (stays v1) ──────────────────────────────────────────
  login: (password: string) =>
    request("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ password }) }),
  logout: () =>
    request("/api/v1/auth/logout", { method: "POST" }),
  verify: () =>
    request<{ status: string }>("/api/v1/auth/verify"),

  // ── Tenants (v2) ────────────────────────────────────────────
  listTenants: (page = 1, status?: string) =>
    request<{ tenants: any[]; total: number }>(
      `/api/v2/tenants?page=${page}${status ? `&status_filter=${status}` : ""}`
    ),
  createTenant: (data: { name: string; admin_email: string; admin_password: string; new_password?: string }) =>
    request("/api/v2/tenants", { method: "POST", body: JSON.stringify(data) }),
  bulkCreateTenants: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const r = await fetch(`${API_URL}/api/v2/tenants/bulk`, {
      method: "POST",
      body: formData,
      credentials: "include",
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return r.json();
  },
  getTenant: (id: string) =>
    request<any>(`/api/v2/tenants/${id}`),
  getCredentials: (id: string) =>
    request<any>(`/api/v2/tenants/${id}/credentials`),
  updateTenant: (id: string, data: { admin_password?: string; new_password?: string }) =>
    request(`/api/v2/tenants/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteTenant: (id: string) =>
    request(`/api/v2/tenants/${id}`, { method: "DELETE" }),
  setupTenant: (id: string) =>
    request(`/api/v2/tenants/${id}/setup`, { method: "POST" }),
  retryTenant: (id: string) =>
    request(`/api/v2/tenants/${id}/retry`, { method: "POST" }),
  healthCheckTenant: (id: string) =>
    request<{ status: string }>(`/api/v2/tenants/${id}/health-check`, { method: "POST" }),
  fixHealth: (id: string) =>
    request<{ status: string }>(`/api/v2/tenants/${id}/fix-health`, { method: "POST" }),
  fixSecurityDefaults: (id: string) =>
    request<{ status: string }>(`/api/v2/tenants/${id}/fix-security-defaults`, { method: "POST" }),
  startMailboxPipeline: (tenantId: string, data: {
    domain: string;
    mailbox_count?: number;
    cf_email?: string;
    cf_api_key?: string;
    custom_names?: string[];
  }) =>
    request<import("./types").WorkflowJob>(
      `/api/v2/tenants/${tenantId}/mailboxes`,
      { method: "POST", body: JSON.stringify(data) },
    ),

  exportTenantsCsv: (ids?: string[]) => {
    const params = ids?.length ? `?ids=${ids.join(",")}` : "";
    window.open(`${API_URL}/api/v2/tenants/export${params}`, "_blank");
  },

  // ── Mailboxes (v2) ──────────────────────────────────────────
  listMailboxes: (tenantId: string) =>
    request<{ mailboxes: import("./types").Mailbox[] }>(`/api/v2/mailboxes/tenant/${tenantId}`),
  exportMailboxesCsv: (tenantId: string) => {
    window.open(`${API_URL}/api/v2/mailboxes/tenant/${tenantId}/export`, "_blank");
  },
  exportAllMailboxesCsv: (tenantIds?: string[]) => {
    const params = tenantIds?.length ? `?tenant_ids=${tenantIds.join(",")}` : "";
    window.open(`${API_URL}/api/v2/mailboxes/export-all${params}`, "_blank");
  },
  bulkCreateMailboxes: (
    items: { tenant_id: string; domain: string; mailbox_count: number; custom_names?: string[] }[],
    cfEmail?: string,
    cfApiKey?: string,
  ) =>
    request<import("./types").BulkMailboxResult>("/api/v2/mailboxes/bulk-create", {
      method: "POST",
      body: JSON.stringify({
        items,
        cf_email: cfEmail || undefined,
        cf_api_key: cfApiKey || undefined,
      }),
    }),
  bulkCreateMailboxesCsv: async (file: File, cfEmail?: string, cfApiKey?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    const params = new URLSearchParams();
    if (cfEmail) params.set("cf_email", cfEmail);
    if (cfApiKey) params.set("cf_api_key", cfApiKey);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const r = await fetch(`${API_URL}/api/v2/mailboxes/bulk-create-csv${qs}`, {
      method: "POST",
      body: formData,
      credentials: "include",
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return r.json() as Promise<import("./types").BulkMailboxResult>;
  },
  listMailboxJobs: () =>
    request<{ jobs: any[] }>("/api/v2/mailboxes/jobs"),
  stopJob: (jobId: string) =>
    request(`/api/v2/mailboxes/jobs/${jobId}/stop`, { method: "POST" }),
  healthCheckMailboxes: (jobId: string) =>
    request<{ status: string }>(`/api/v2/mailboxes/jobs/${jobId}/health-check`, { method: "POST" }),
  retryMissingMailboxes: (jobId: string) =>
    request<{ status: string }>(`/api/v2/mailboxes/jobs/${jobId}/retry-missing`, { method: "POST" }),
  enableDkim: (jobId: string) =>
    request<{ status: string }>(`/api/v2/mailboxes/jobs/${jobId}/enable-dkim`, { method: "POST" }),

  // ── Monitoring (v2) ─────────────────────────────────────────
  dashboard: () =>
    request<any>("/api/v2/monitoring/dashboard"),
  listAlerts: () =>
    request<{ alerts: any[] }>("/api/v2/monitoring/alerts"),
  ackAlert: (id: number) =>
    request(`/api/v2/monitoring/alerts/${id}/ack`, { method: "POST" }),
  deleteAlert: (id: number) =>
    request(`/api/v2/monitoring/alerts/${id}`, { method: "DELETE" }),
  bulkDeleteAlerts: (body: { ids?: number[]; all_acknowledged?: boolean; all?: boolean }) =>
    request<{ deleted: number }>("/api/v2/monitoring/alerts/bulk-delete", { method: "POST", body: JSON.stringify(body) }),
  bulkAckAlerts: () =>
    request<{ acknowledged: number }>("/api/v2/monitoring/alerts/bulk-ack", { method: "POST" }),
  tenantHealth: (tenantId: string) =>
    request<any>(`/api/v2/monitoring/${tenantId}`),
  mailflowHistory: (tenantId: string) =>
    request<any>(`/api/v2/monitoring/${tenantId}/mailflow`),
  triggerCheck: (tenantId: string) =>
    request(`/api/v2/monitoring/${tenantId}/check-now`, { method: "POST" }),

  // ── TOTP (v2) ───────────────────────────────────────────────
  listTOTP: () =>
    request<import("./types").TOTPEntry[]>("/api/v2/totp"),
  getTOTP: (tenantId: string) =>
    request<import("./types").TOTPEntry>(`/api/v2/totp/${tenantId}`),
  setTOTPSecret: (tenantId: string, secret: string) =>
    request(`/api/v2/totp/${tenantId}/secret`, { method: "PUT", body: JSON.stringify({ secret }) }),
  deleteTOTPSecret: (tenantId: string) =>
    request(`/api/v2/totp/${tenantId}/secret`, { method: "DELETE" }),

  // ── Settings (v2) ──────────────────────────────────────────
  listCFConfigs: () =>
    request<{ configs: any[] }>("/api/v2/settings/cloudflare"),
  createCFConfig: (data: any) =>
    request("/api/v2/settings/cloudflare", { method: "POST", body: JSON.stringify(data) }),
  deleteCFConfig: (id: string) =>
    request(`/api/v2/settings/cloudflare/${id}`, { method: "DELETE" }),
  getAlertSettings: () =>
    request<any>("/api/v2/settings/alerts"),
  updateAlertSettings: (data: any) =>
    request("/api/v2/settings/alerts", { method: "PUT", body: JSON.stringify(data) }),

  // ── Workflows (v2) ─────────────────────────────────────────
  getWorkflow: (jobId: string) =>
    request<import("./types").WorkflowJob>(`/api/v2/workflows/${jobId}`),
  retryWorkflow: (jobId: string, stepIndex?: number) =>
    request<import("./types").WorkflowJob>(`/api/v2/workflows/${jobId}/retry`, {
      method: "POST",
      body: JSON.stringify(stepIndex !== undefined ? { step_index: stepIndex } : {}),
    }),
  cancelWorkflow: (jobId: string) =>
    request<{ status: string }>(`/api/v2/workflows/${jobId}/cancel`, { method: "POST" }),
  retryStep: (jobId: string, stepIndex: number) =>
    request<import("./types").WorkflowJob>(`/api/v2/workflows/${jobId}/steps/${stepIndex}/retry`, {
      method: "POST",
    }),

  // ── Audit (v2) ─────────────────────────────────────────────
  listAuditEvents: (params?: { tenant_id?: string; job_id?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.tenant_id) qs.set("tenant_id", params.tenant_id);
    if (params?.job_id) qs.set("job_id", params.job_id);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    return request<import("./types").AuditEvent[]>(`/api/v2/monitoring/audit?${qs.toString()}`);
  },
};
