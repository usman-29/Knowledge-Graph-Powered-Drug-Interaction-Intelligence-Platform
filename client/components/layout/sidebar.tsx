"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  FileText,
  LogOut,
  MessageSquare,
  ShieldCheck,
  UserCircle,
  Users,
} from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ComponentType<{ className?: string }> };

const userNav: NavItem[] = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/patients", label: "Patients", icon: UserCircle },
];

const adminNav: NavItem[] = [
  { href: "/admin", label: "Overview", icon: Activity },
  { href: "/admin/logs", label: "Audit Logs", icon: FileText },
  { href: "/admin/users", label: "Users", icon: Users },
];

const STORAGE_KEY = "sidebar.collapsed";

type Props = {
  user: { name?: string | null; email?: string | null; role: "ADMIN" | "CLINICIAN" | "PATIENT" | "GUEST" };
};

export function Sidebar({ user }: Props) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && localStorage.getItem(STORAGE_KEY) === "1") {
      setCollapsed(true);
    }
  }, []);

  function toggle() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* storage unavailable — non-fatal */
      }
      return next;
    });
  }

  const initials = (user.name || user.email || "?").slice(0, 2).toUpperCase();
  const displayName = user.name || user.email || "Account";

  return (
    <aside
      data-collapsed={collapsed}
      className={cn(
        "group/sidebar relative flex h-screen flex-col border-r bg-card",
        "transition-[width] duration-200 ease-out",
        collapsed ? "w-[68px]" : "w-60",
      )}
    >
      {/* Brand */}
      <div
        className={cn(
          "flex h-14 items-center border-b",
          collapsed ? "justify-center px-2" : "gap-2.5 px-4",
        )}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <ShieldCheck className="h-4 w-4" />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold leading-tight">Clinical Safety</div>
            <div className="truncate text-[10px] uppercase tracking-wider text-muted-foreground">
              Drug-Safety Console
            </div>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className={cn("flex-1 space-y-5 py-4", collapsed ? "px-2" : "px-3")}>
        <NavSection items={userNav} pathname={pathname} collapsed={collapsed} />
        {user.role === "ADMIN" && (
          <>
            <Separator />
            <div>
              {!collapsed && (
                <div className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Admin
                </div>
              )}
              <NavSection items={adminNav} pathname={pathname} collapsed={collapsed} />
            </div>
          </>
        )}
      </nav>

      {/* Footer — user + actions */}
      <div className={cn("border-t", collapsed ? "p-2" : "p-3")}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-1.5">
            <Avatar className="h-8 w-8">
              <AvatarFallback className="text-xs">{initials}</AvatarFallback>
            </Avatar>
            <ThemeToggle />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => signOut({ callbackUrl: "/login" })}
              title="Sign out"
              aria-label="Sign out"
              className="text-muted-foreground"
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 rounded-md p-2">
              <Avatar className="h-8 w-8">
                <AvatarFallback className="text-xs">{initials}</AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{displayName}</div>
                <div className="truncate text-[11px] text-muted-foreground">{user.role}</div>
              </div>
              <ThemeToggle />
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="mt-1 w-full justify-start gap-2 text-muted-foreground"
              onClick={() => signOut({ callbackUrl: "/login" })}
            >
              <LogOut className="h-4 w-4" /> Sign out
            </Button>
          </>
        )}
      </div>

      {/* Collapse toggle — floats on the right edge */}
      <button
        type="button"
        onClick={toggle}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className={cn(
          "absolute -right-3 top-16 z-10 flex h-6 w-6 items-center justify-center",
          "rounded-full border bg-background text-muted-foreground shadow-sm",
          "opacity-0 transition hover:bg-accent hover:text-foreground",
          "group-hover/sidebar:opacity-100 focus-visible:opacity-100",
          collapsed && "opacity-100",
        )}
      >
        {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
      </button>
    </aside>
  );
}

function NavSection({
  items,
  pathname,
  collapsed,
}: {
  items: NavItem[];
  pathname: string;
  collapsed: boolean;
}) {
  return (
    <div className="space-y-1">
      {items.map((item) => {
        const active =
          item.href === "/admin" || item.href === "/chat"
            ? pathname === item.href
            : pathname.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            title={collapsed ? item.label : undefined}
            aria-label={collapsed ? item.label : undefined}
            className={cn(
              "flex items-center rounded-md text-sm transition-colors",
              collapsed ? "h-9 w-9 justify-center" : "gap-2.5 px-2.5 py-1.5",
              active
                ? "bg-accent font-medium text-accent-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </Link>
        );
      })}
    </div>
  );
}
