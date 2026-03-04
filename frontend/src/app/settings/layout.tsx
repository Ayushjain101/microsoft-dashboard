import AuthGuard from "@/components/layout/AuthGuard";
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
