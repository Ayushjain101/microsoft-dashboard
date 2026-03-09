"use client";

const STEPS = [
  "Browser Login", "Security Setup", "Create App Registration",
  "Create Service Principal", "Create Client Secret", "Generate Certificate",
  "Add API Permissions", "Grant Admin Consent", "Assign Exchange Admin Role",
  "Save Credentials", "Finalize", "Grant Instantly Consent", "Delete MFA",
];

interface Props {
  currentStep: number;
  totalSteps: number;
  message: string;
  status: string;
}

export default function SetupProgress({ currentStep, totalSteps, message, status }: Props) {
  const pct = totalSteps > 0 ? Math.round((currentStep / totalSteps) * 100) : 0;
  const isFailed = status === "failed";
  const isComplete = status === "complete";

  return (
    <div className="bg-white rounded-lg border p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium">
          {isComplete ? "Setup Complete" : isFailed ? "Setup Failed" : message}
        </span>
        <span className="text-sm text-gray-500">{pct}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2 mb-4">
        <div
          className={`h-2 rounded-full transition-all duration-500 ${
            isFailed ? "bg-red-500" : isComplete ? "bg-green-500" : "bg-blue-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="grid grid-cols-4 gap-1">
        {STEPS.map((step, i) => {
          const stepNum = i + 1;
          const done = currentStep >= stepNum;
          const active = currentStep === stepNum && !isComplete && !isFailed;
          return (
            <div
              key={i}
              className={`text-xs px-2 py-1 rounded text-center ${
                active
                  ? "bg-blue-100 text-blue-700 font-medium"
                  : done
                  ? "bg-green-50 text-green-700"
                  : "bg-gray-50 text-gray-400"
              }`}
            >
              {stepNum}. {step}
            </div>
          );
        })}
      </div>
    </div>
  );
}
