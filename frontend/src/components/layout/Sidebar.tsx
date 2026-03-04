"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Server, Mail, Activity, KeyRound, Settings, LogOut } from "lucide-react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

const navItems = [
  { href: "/tenants", label: "Tenant Setup", icon: Server },
  { href: "/mailboxes", label: "Mailboxes", icon: Mail },
  { href: "/monitor", label: "Monitoring", icon: Activity },
  { href: "/totp", label: "TOTP Vault", icon: KeyRound },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLogout() {
    await api.logout();
    router.push("/login");
  }

  return (
    <aside className="w-64 bg-gray-900 text-white min-h-screen flex flex-col">
      <div className="p-6 border-b border-gray-800">
        <h1 className="text-lg font-bold">Tenant Dashboard</h1>
        <p className="text-xs text-gray-400 mt-1">Microsoft 365 Automation</p>
      </div>
      <nav className="flex-1 py-4">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-6 py-3 text-sm transition-colors ${
                active ? "bg-blue-600 text-white" : "text-gray-300 hover:bg-gray-800"
              }`}
            >
              <Icon size={18} />
              {label}
            </Link>
          );
        })}
      </nav>
      <button
        onClick={handleLogout}
        className="flex items-center gap-3 px-6 py-4 text-sm text-gray-400 hover:text-white border-t border-gray-800"
      >
        <LogOut size={18} />
        Logout
      </button>
    </aside>
  );
}
