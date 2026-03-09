import type { Metadata } from "next";
import "./globals.css";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { QueryProvider } from "@/components/QueryProvider";

export const metadata: Metadata = {
  title: "Tenant Dashboard",
  description: "Microsoft 365 Tenant Automation Tool",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>
          <ErrorBoundary>{children}</ErrorBoundary>
        </QueryProvider>
      </body>
    </html>
  );
}
