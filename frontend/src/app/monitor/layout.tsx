import AuthGuard from "@/components/layout/AuthGuard";
export default function MonitorLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
