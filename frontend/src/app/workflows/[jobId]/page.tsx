"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WorkflowJob, WSEvent } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuth } from "@/hooks/useAuth";
import Sidebar from "@/components/layout/Sidebar";
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Loader2,
  RotateCcw,
  Ban,
  SkipForward,
} from "lucide-react";

const STATUS_CONFIG: Record<string, { icon: React.ReactNode; color: string; bg: string }> = {
  pending: { icon: <Clock className="w-4 h-4" />, color: "text-gray-400", bg: "bg-gray-100" },
  running: { icon: <Loader2 className="w-4 h-4 animate-spin" />, color: "text-blue-600", bg: "bg-blue-50" },
  success: { icon: <CheckCircle2 className="w-4 h-4" />, color: "text-green-600", bg: "bg-green-50" },
  failed: { icon: <XCircle className="w-4 h-4" />, color: "text-red-600", bg: "bg-red-50" },
  warning: { icon: <AlertTriangle className="w-4 h-4" />, color: "text-yellow-600", bg: "bg-yellow-50" },
  skipped: { icon: <SkipForward className="w-4 h-4" />, color: "text-gray-400", bg: "bg-gray-50" },
  queued: { icon: <Clock className="w-4 h-4" />, color: "text-blue-400", bg: "bg-blue-50" },
  complete: { icon: <CheckCircle2 className="w-4 h-4" />, color: "text-green-600", bg: "bg-green-50" },
  cancelled: { icon: <Ban className="w-4 h-4" />, color: "text-gray-500", bg: "bg-gray-100" },
};

export default function WorkflowDetailPage() {
  const authenticated = useAuth();
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const jobId = params.jobId as string;
  const [retryingStep, setRetryingStep] = useState<number | null>(null);

  const { data: job, isLoading } = useQuery<WorkflowJob>({
    queryKey: ["workflow", jobId],
    queryFn: () => api.v2.getWorkflow(jobId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && ["running", "queued"].includes(data.status)) return 3000;
      return false;
    },
  });

  useWebSocket((event: WSEvent) => {
    if (event.job_id === jobId || event.tenant_id === job?.tenant_id) {
      queryClient.invalidateQueries({ queryKey: ["workflow", jobId] });
    }
  });

  async function handleRetryStep(stepIndex: number) {
    setRetryingStep(stepIndex);
    try {
      await api.v2.retryStep(jobId, stepIndex);
      queryClient.invalidateQueries({ queryKey: ["workflow", jobId] });
    } catch (e: any) {
      alert(e.message);
    } finally {
      setRetryingStep(null);
    }
  }

  async function handleRetryAll() {
    try {
      await api.v2.retryWorkflow(jobId);
      queryClient.invalidateQueries({ queryKey: ["workflow", jobId] });
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function handleCancel() {
    if (!confirm("Cancel this workflow?")) return;
    try {
      await api.v2.cancelWorkflow(jobId);
      queryClient.invalidateQueries({ queryKey: ["workflow", jobId] });
    } catch (e: any) {
      alert(e.message);
    }
  }

  if (authenticated === null) return null;

  const cfg = job ? STATUS_CONFIG[job.status] || STATUS_CONFIG.pending : STATUS_CONFIG.pending;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <button
          onClick={() => router.back()}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-4"
        >
          <ArrowLeft className="w-4 h-4" /> Back
        </button>

        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
          </div>
        ) : !job ? (
          <p className="text-gray-500">Workflow job not found.</p>
        ) : (
          <>
            {/* Header */}
            <div className="bg-white rounded-lg shadow-sm border p-6 mb-6">
              <div className="flex items-center justify-between">
                <div>
                  <h1 className="text-xl font-semibold text-gray-900">
                    {job.job_type === "mailbox_pipeline" ? "Mailbox Pipeline" : "Tenant Setup"}
                  </h1>
                  <p className="text-sm text-gray-500 mt-1">
                    Job ID: <code className="text-xs bg-gray-100 px-1 rounded">{job.id}</code>
                  </p>
                  {job.config?.domain && (
                    <p className="text-sm text-gray-500">Domain: {job.config.domain}</p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium ${cfg.bg} ${cfg.color}`}>
                    {cfg.icon} {job.status}
                  </span>
                  {job.status === "failed" && (
                    <button
                      onClick={handleRetryAll}
                      className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
                    >
                      <RotateCcw className="w-4 h-4 inline mr-1" /> Retry
                    </button>
                  )}
                  {["running", "queued"].includes(job.status) && (
                    <button
                      onClick={handleCancel}
                      className="px-3 py-1.5 bg-red-50 text-red-600 text-sm rounded hover:bg-red-100"
                    >
                      <Ban className="w-4 h-4 inline mr-1" /> Cancel
                    </button>
                  )}
                </div>
              </div>
              {job.error_message && (
                <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                  {job.error_message}
                </div>
              )}
              <div className="mt-4 grid grid-cols-4 gap-4 text-sm text-gray-500">
                <div>Created: {new Date(job.created_at).toLocaleString()}</div>
                <div>Started: {job.started_at ? new Date(job.started_at).toLocaleString() : "—"}</div>
                <div>Completed: {job.completed_at ? new Date(job.completed_at).toLocaleString() : "—"}</div>
                <div>Steps: {job.steps?.filter(s => s.status === "success").length || 0}/{job.total_steps || 0}</div>
              </div>
            </div>

            {/* Steps */}
            <div className="bg-white rounded-lg shadow-sm border">
              <h2 className="px-6 py-4 text-lg font-medium border-b">Steps</h2>
              <div className="divide-y">
                {(job.steps || [])
                  .sort((a, b) => a.step_index - b.step_index)
                  .map((step) => {
                    const sc = STATUS_CONFIG[step.status] || STATUS_CONFIG.pending;
                    return (
                      <div key={step.id} className={`px-6 py-4 ${sc.bg}`}>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <span className={`flex items-center justify-center w-8 h-8 rounded-full ${sc.bg} ${sc.color} border`}>
                              {step.step_index + 1}
                            </span>
                            <div>
                              <span className={`font-medium ${sc.color}`}>{step.step_name}</span>
                              <span className={`ml-2 text-xs ${sc.color}`}>({step.status})</span>
                              {step.attempts > 0 && (
                                <span className="ml-2 text-xs text-gray-400">
                                  attempt {step.attempts}/{step.max_attempts}
                                </span>
                              )}
                            </div>
                          </div>
                          {(step.status === "failed" || step.status === "warning") && (
                            <button
                              onClick={() => handleRetryStep(step.step_index)}
                              disabled={retryingStep === step.step_index}
                              className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                            >
                              {retryingStep === step.step_index ? (
                                <Loader2 className="w-3 h-3 animate-spin inline" />
                              ) : (
                                <RotateCcw className="w-3 h-3 inline mr-1" />
                              )}
                              Retry
                            </button>
                          )}
                        </div>
                        {step.detail && (
                          <pre className="mt-2 ml-11 text-xs text-gray-600 whitespace-pre-wrap bg-white/50 p-2 rounded border">
                            {step.detail}
                          </pre>
                        )}
                        {step.last_error && step.status === "failed" && (
                          <pre className="mt-2 ml-11 text-xs text-red-600 whitespace-pre-wrap bg-red-50 p-2 rounded border border-red-200">
                            {step.last_error}
                          </pre>
                        )}
                        {step.started_at && (
                          <div className="mt-1 ml-11 text-xs text-gray-400">
                            {new Date(step.started_at).toLocaleTimeString()}
                            {step.completed_at && ` — ${new Date(step.completed_at).toLocaleTimeString()}`}
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
