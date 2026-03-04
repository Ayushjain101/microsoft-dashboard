import AuthGuard from "@/components/layout/AuthGuard";

export default function TenantsLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
