"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Server,
  Mail,
  Activity,
  KeyRound,
  Settings,
  LogOut,
  ScrollText,
  LayoutDashboard,
} from "lucide-react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

const navItems = [
  { href: "/tenants", label: "Tenants", icon: Server },
  { href: "/mailboxes", label: "Mailboxes", icon: Mail },
  { href: "/monitor", label: "Monitoring", icon: Activity },
  { href: "/totp", label: "TOTP Vault", icon: KeyRound },
  { href: "/audit", label: "Audit Log", icon: ScrollText },
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
    <aside className="w-60 bg-gray-900 text-white min-h-screen flex flex-col border-r border-gray-800">
      <div className="px-5 py-5 border-b border-gray-800">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
            <LayoutDashboard size={16} />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight">Tenant Dashboard</h1>
            <p className="text-[10px] text-gray-500 font-medium">Microsoft 365</p>
          </div>
        </div>
      </div>
      <nav className="flex-1 py-3 px-3 space-y-0.5">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 px-3 py-2 text-[13px] rounded-lg transition-all duration-150 ${
                active
                  ? "bg-blue-600/90 text-white shadow-sm shadow-blue-900/50"
                  : "text-gray-400 hover:bg-gray-800/80 hover:text-gray-200"
              }`}
            >
              <Icon size={16} strokeWidth={active ? 2.5 : 2} />
              <span className={active ? "font-semibold" : "font-medium"}>{label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="px-3 pb-3">
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-gray-500 hover:text-red-400 hover:bg-gray-800/50 rounded-lg transition-colors"
        >
          <LogOut size={16} />
          <span className="font-medium">Logout</span>
        </button>
      </div>
    </aside>
  );
}
