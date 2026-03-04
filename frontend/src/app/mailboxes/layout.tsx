import AuthGuard from "@/components/layout/AuthGuard";
export default function MailboxesLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
