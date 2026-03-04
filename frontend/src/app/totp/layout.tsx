import AuthGuard from "@/components/layout/AuthGuard";

export default function TOTPLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
