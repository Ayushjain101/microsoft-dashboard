"use client";

import { StepResult } from "@/lib/types";

const STEP_NAMES = [
  "Assign License",
  "Enable Org SMTP",
  "Add Domain",
  "Verify Domain",
  "Setup DKIM",
  "Setup DMARC",
  "Create Mailboxes",
  "Enable SMTP",
  "Disable Calendar",
];

const STATUS_STYLES: Record<string, { bg: string; dot: string; text: string }> = {
  success: { bg: "bg-green-50", dot: "bg-green-500", text: "text-green-700" },
  warning: { bg: "bg-yellow-50", dot: "bg-yellow-500", text: "text-yellow-700" },
  failed: { bg: "bg-red-50", dot: "bg-red-500", text: "text-red-700" },
  running: { bg: "bg-blue-50", dot: "bg-blue-500 animate-pulse", text: "text-blue-700" },
  pending: { bg: "bg-gray-50", dot: "bg-gray-300", text: "text-gray-400" },
};

interface HealthResult {
  status: string;
  found_in_exchange?: number;
  total_in_db?: number;
  missing?: string[];
  smtp_ok?: number;
  smtp_tested?: number;
}

interface Props {
  stepResults: Record<string, StepResult> | null;
  jobStatus: string;
  currentStep?: number | null;
  healthResult?: HealthResult | null;
  mailboxCount?: number;
  dkimEnabled?: boolean;
}

export default function MailboxPipelineProgress({ stepResults, jobStatus, currentStep, healthResult, mailboxCount, dkimEnabled }: Props) {
  const healthComplete = healthResult?.status === "complete";
  const healthAllExchangeGood = healthComplete
    && healthResult.found_in_exchange != null
    && mailboxCount != null
    && healthResult.found_in_exchange >= mailboxCount;
  const healthSmtpGood = healthComplete
    && healthResult.smtp_ok != null
    && healthResult.smtp_tested != null
    && healthResult.smtp_ok >= healthResult.smtp_tested;

  function getStepStatus(stepNum: number): string {
    // If DKIM is enabled in DB, override stale step 5 warning
    if (dkimEnabled && stepNum === 5) return "success";
    // Health check overrides for steps 7-8
    if (healthAllExchangeGood && stepNum === 7) return "success";
    if (healthComplete && stepNum === 8) {
      if (healthSmtpGood) return "success";
      if (healthResult.smtp_ok != null && healthResult.smtp_tested != null && healthResult.smtp_ok > 0) return "warning";
      if (healthResult.smtp_tested != null && healthResult.smtp_ok === 0) return "failed";
    }

    if (stepResults && stepResults[String(stepNum)]) {
      return stepResults[String(stepNum)].status;
    }
    // Job completed — steps with no entry were either successful or skipped
    if (jobStatus === "complete") return "success";
    // Legacy jobs with null step_results: show all green if complete
    if (!stepResults && jobStatus === "failed") return "pending";
    // Running job — figure out if this step is current, done, or pending
    if (jobStatus === "running" && currentStep) {
      if (stepNum < currentStep) return "success";
      if (stepNum === currentStep) return "running";
      return "pending";
    }
    return "pending";
  }

  function getDetail(stepNum: number): string | undefined {
    // Override step 7 detail when health check confirms all good
    if (healthAllExchangeGood && stepNum === 7) {
      return `Exchange: ${healthResult!.found_in_exchange}/${mailboxCount} found`;
    }
    // Override step 8 detail with health SMTP data
    if (healthComplete && stepNum === 8 && healthResult.smtp_tested != null) {
      const detail = `SMTP: ${healthResult.smtp_ok ?? 0}/${healthResult.smtp_tested} passed`;
      if (!healthSmtpGood && healthResult.smtp_tested - (healthResult.smtp_ok ?? 0) > 0) {
        return `${detail} (${healthResult.smtp_tested - (healthResult.smtp_ok ?? 0)} failed)`;
      }
      return detail;
    }
    return stepResults?.[String(stepNum)]?.detail;
  }

  return (
    <div className="grid grid-cols-3 gap-2 py-3">
      {STEP_NAMES.map((name, i) => {
        const stepNum = i + 1;
        const status = getStepStatus(stepNum);
        const style = STATUS_STYLES[status] || STATUS_STYLES.pending;
        const detail = getDetail(stepNum);

        const showDetail = detail && (status === "warning" || status === "failed");
        // Extract first line as summary for inline display
        const detailSummary = detail?.split("\n")[0];

        return (
          <div
            key={stepNum}
            className={`flex flex-col gap-0.5 px-3 py-2 rounded-md ${style.bg} group relative`}
            title={detail || name}
          >
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full shrink-0 ${style.dot}`} />
              <span className={`text-xs font-medium ${style.text} truncate`}>
                {stepNum}. {name}
              </span>
            </div>
            {showDetail && (
              <span className={`text-[10px] ${style.text} opacity-75 truncate ml-4`} title={detail}>
                {detailSummary}
              </span>
            )}
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
