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

interface Props {
  stepResults: Record<string, StepResult> | null;
  jobStatus: string;
  currentStep?: number | null;
}

export default function MailboxPipelineProgress({ stepResults, jobStatus, currentStep }: Props) {
  function getStepStatus(stepNum: number): string {
    if (stepResults && stepResults[String(stepNum)]) {
      return stepResults[String(stepNum)].status;
    }
    // Legacy jobs with null step_results: show all green if complete
    if (!stepResults && jobStatus === "complete") return "success";
    if (!stepResults && jobStatus === "failed") {
      // Can't know which step failed, show all as unknown
      return "success";
    }
    // Running job — figure out if this step is current, done, or pending
    if (jobStatus === "running" && currentStep) {
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
    <div className="grid grid-cols-3 gap-2 py-3">
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
