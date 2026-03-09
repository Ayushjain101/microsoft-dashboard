"use client";

import { StepResult } from "@/lib/types";

const STEP_NAMES = [
  "Browser Login",
  "Security Setup",
  "Create App",
  "Create SP",
  "Client Secret",
  "Certificate",
  "API Permissions",
  "Admin Consent",
  "Exchange Role",
  "Save Creds",
  "Finalize",
  "Instantly Consent",
  "Delete MFA",
];

const STATUS_STYLES: Record<string, { bg: string; dot: string; text: string }> = {
  success: { bg: "bg-green-50", dot: "bg-green-500", text: "text-green-700" },
  warning: { bg: "bg-yellow-50", dot: "bg-yellow-500", text: "text-yellow-700" },
  failed: { bg: "bg-red-50", dot: "bg-red-500", text: "text-red-700" },
  running: { bg: "bg-blue-50", dot: "bg-blue-500 animate-pulse", text: "text-blue-700" },
  pending: { bg: "bg-gray-50", dot: "bg-gray-300", text: "text-gray-400" },
};

interface Props {
  stepResults: Record<string, StepResult> | null;
  tenantStatus: string;
  currentStep?: number | null;
}

export default function TenantSetupProgress({ stepResults, tenantStatus, currentStep }: Props) {
  function getStepStatus(stepNum: number): string {
    if (stepResults && stepResults[String(stepNum)]) {
      return stepResults[String(stepNum)].status;
    }
    // Job completed — steps with no entry were successful
    if (tenantStatus === "complete") return "success";
    if (tenantStatus === "running" && currentStep) {
      if (stepNum < currentStep) return "success";
      if (stepNum === currentStep) return "running";
      return "pending";
    }
    return "pending";
  }

  function getDetail(stepNum: number): string | undefined {
    return stepResults?.[String(stepNum)]?.detail;
  }

  return (
    <div className="grid grid-cols-4 gap-2 py-3">
      {STEP_NAMES.map((name, i) => {
        const stepNum = i + 1;
        const status = getStepStatus(stepNum);
        const style = STATUS_STYLES[status] || STATUS_STYLES.pending;
        const detail = getDetail(stepNum);

        return (
          <div
            key={stepNum}
            className={`flex items-center gap-2 px-3 py-2 rounded-md ${style.bg} group relative`}
            title={detail || name}
          >
            <span className={`w-2 h-2 rounded-full shrink-0 ${style.dot}`} />
            <span className={`text-xs font-medium ${style.text} truncate`}>
              {stepNum}. {name}
            </span>
            {detail && (
              <div className="absolute bottom-full left-0 mb-1 hidden group-hover:block z-10 max-w-xs">
                <div className="bg-gray-900 text-white text-xs rounded px-3 py-2 shadow-lg whitespace-pre-wrap">
                  {detail}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
