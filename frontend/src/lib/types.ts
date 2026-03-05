export interface HealthCheckResult {
  status: "pass" | "fail" | "warn" | "skip";
  message: string;
  detail?: string;
}

export interface Tenant {
  id: string;
  name: string;
  admin_email: string;
  status: string;
  current_step: string | null;
  error_message: string | null;
  step_results: Record<string, StepResult> | null;
  health_results: Record<string, HealthCheckResult> | null;
  last_health_check: string | null;
  created_at: string;
  updated_at: string;
  mailbox_count?: number;
  completed_at: string | null;
  // Detail fields (only on getTenant)
  tenant_id_ms?: string | null;
  client_id?: string | null;
  client_secret?: string | null;
  cert_password?: string | null;
  mfa_secret?: string | null;
}

export interface Mailbox {
  id: string;
  tenant_id: string;
  display_name: string | null;
  email: string;
  smtp_enabled: boolean;
  last_monitor_status: string | null;
  created_at: string;
}

export interface StepResult {
  status: "success" | "warning" | "failed";
  message: string;
  detail?: string;
}

export interface MailboxJob {
  id: string;
  tenant_id: string;
  domain: string;
  mailbox_count: number;
  status: string;
  current_phase: string | null;
  error_message: string | null;
  step_results: Record<string, StepResult> | null;
  dkim_enabled: boolean;
  created_at: string;
  completed_at: string | null;
}

export interface WSEvent {
  type: string;
  tenant_id?: string;
  job_id?: string;
  step?: number;
  total?: number;
  message?: string;
  status?: string;
  step_status?: string;
  detail?: string;
  success?: boolean;
  [key: string]: any;
}

export interface TOTPEntry {
  tenant_id: string;
  tenant_name: string;
  admin_email: string;
  code: string;
  remaining: number;
  period: number;
}

export interface BulkMailboxResult {
  created: number;
  jobs: { id: string; tenant_id: string; domain: string }[];
  errors: { tenant_id: string; error: string }[];
}

export interface Alert {
  id: number;
  tenant_id: string;
  alert_type: string;
  severity: string;
  message: string | null;
  acknowledged: boolean;
  created_at: string;
  resolved_at: string | null;
}
