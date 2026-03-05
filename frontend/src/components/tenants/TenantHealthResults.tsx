"use client";

import { HealthCheckResult } from "@/lib/types";

const CHECK_NAMES = [
  "Credentials Exist",
  "Token Acquisition",
  "App Registration",
  "Service Principal",
  "Graph Permissions",
  "Exchange Admin Role",
  "Certificate Valid",
  "Instantly Consent",
];

const STATUS_STYLES: Record<string, { bg: string; dot: string; text: string }> = {
  pass: { bg: "bg-green-50", dot: "bg-green-500", text: "text-green-700" },
  fail: { bg: "bg-red-50", dot: "bg-red-500", text: "text-red-700" },
  warn: { bg: "bg-yellow-50", dot: "bg-yellow-500", text: "text-yellow-700" },
  skip: { bg: "bg-gray-50", dot: "bg-gray-300", text: "text-gray-400" },
};

interface Props {
  healthResults: Record<string, HealthCheckResult>;
  lastHealthCheck: string | null;
}

export default function TenantHealthResults({ healthResults, lastHealthCheck }: Props) {
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 py-3">
        {CHECK_NAMES.map((name, i) => {
          const checkNum = String(i + 1);
          const result = healthResults[checkNum];
          const status = result?.status || "skip";
          const style = STATUS_STYLES[status] || STATUS_STYLES.skip;
          const detail = result?.detail;

          return (
            <div
              key={checkNum}
              className={`flex items-center gap-2 px-3 py-2 rounded-md ${style.bg} group relative`}
              title={detail || name}
            >
              <span className={`w-2 h-2 rounded-full shrink-0 ${style.dot}`} />
              <span className={`text-xs font-medium ${style.text} truncate`}>
                {name}
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
      {lastHealthCheck && (
        <p className="text-xs text-gray-400 mt-1">
          Last checked: {new Date(lastHealthCheck).toLocaleString()}
        </p>
      )}
    </div>
  );
}
