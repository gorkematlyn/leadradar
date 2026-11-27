"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  Bell, BriefcaseBusiness, Building2, ClipboardCheck, Coins, Database, FileText, Filter, KanbanSquare,
  Languages, LayoutDashboard, ListChecks, LogOut, Menu as MenuIcon, Monitor, Moon, PanelLeftClose, PanelLeftOpen, Radar,
  Settings, Sun, Tag as TagIcon, Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { QuickAuditDialog } from "@/components/app/quick-audit";
import { Button } from "@/components/ui/button";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Popover } from "@/components/ui/overlay";
import { useApi } from "@/hooks/use-api";
import { useNotificationText } from "@/hooks/use-notification-text";
import { useSession } from "@/hooks/use-session";
import { api } from "@/lib/api";
import { cn, relativeTime } from "@/lib/utils";

const WORKSPACE = [
  { href: "/", key: "overview", icon: LayoutDashboard },
  { href: "/discovery", key: "discovery", icon: Radar },
  { href: "/companies", key: "companies", icon: Building2 },
  { href: "/pipeline", key: "pipeline", icon: KanbanSquare },
  { href: "/review", key: "review", icon: ClipboardCheck },
  { href: "/reports", key: "reports", icon: FileText },
];
const MANAGEMENT = [
  { href: "/data-sources", key: "dataSources", icon: Database },
  { href: "/saved-filters", key: "savedFilters", icon: Filter },
  { href: "/campaigns", key: "campaigns", icon: BriefcaseBusiness },
  { href: "/tags", key: "tags", icon: TagIcon },
  { href: "/jobs", key: "jobs", icon: ListChecks },
  { href: "/usage", key: "usage", icon: Coins },
  { href: "/settings", key: "settings", icon: Settings },
];

function NavList({ items, collapsed, onNavigate, reviewCount }: { items: typeof WORKSPACE; collapsed: boolean; onNavigate?: () => void; reviewCount?: number }) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        const Icon = item.icon;
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              title={collapsed ? t(item.key) : undefined}
              className={cn(
                "relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] text-muted hover:bg-surface-2 hover:text-foreground",
                active && "bg-surface-2 text-foreground",
                collapsed && "justify-center px-0",
              )}
            >
              {active ? <span className="absolute left-0 top-1.5 h-5 w-[2px] rounded-full bg-highlight" /> : null}
              <Icon className="size-4 shrink-0" />
              {!collapsed ? <span className="truncate">{t(item.key)}</span> : null}
              {!collapsed && item.key === "review" && reviewCount ? <span className="num ml-auto text-[11px] text-muted">{reviewCount}</span> : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Sidebar({ collapsed, onToggle, onNavigate, reviewCount }: { collapsed: boolean; onToggle?: () => void; onNavigate?: () => void; reviewCount?: number }) {
  const t = useTranslations("nav");
  return (
    <div className="flex h-full flex-col gap-4 px-2 py-3">
      <div className={cn("flex h-8 items-center gap-2 px-2", collapsed && "justify-center px-0")}>
        <span className="relative flex size-5 items-center justify-center rounded-[5px] bg-foreground">
          <span className="size-1.5 rounded-full bg-highlight" />
        </span>
        {!collapsed ? <span className="text-[14px] font-semibold tracking-tight">LeadRadar</span> : null}
      </div>
      <nav className="flex flex-1 flex-col gap-4 overflow-y-auto" aria-label="Main">
        <div>
          {!collapsed ? <p className="mb-1 px-2.5 text-[11px] font-medium uppercase tracking-wide text-muted">{t("workspace")}</p> : null}
          <NavList items={WORKSPACE} collapsed={collapsed} onNavigate={onNavigate} reviewCount={reviewCount} />
        </div>
        <div>
          {!collapsed ? <p className="mb-1 px-2.5 text-[11px] font-medium uppercase tracking-wide text-muted">{t("management")}</p> : null}
          <NavList items={MANAGEMENT} collapsed={collapsed} onNavigate={onNavigate} />
        </div>
      </nav>
      {onToggle ? (
        <Button variant="ghost" size="sm" onClick={onToggle} className={cn("justify-start text-muted", collapsed && "justify-center")} aria-label={collapsed ? t("expand") : t("collapse")}>
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          {!collapsed ? t("collapse") : null}
        </Button>
      ) : null}
    </div>
  );
}

interface NotificationItem { id: string; severity: string; message_key: string; params: Record<string, string | number>; link: string | null; read: boolean; created_at: string }

function Notifications() {
  const t = useTranslations("notifications");
  const locale = useLocale();
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data } = useApi<{ unread: number; items: NotificationItem[] }>(["notifications"], "/notifications", { refetchInterval: 30_000 });
  const refresh = () => ["notifications", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const markAll = async () => {
    await api("/notifications/read", { body: {} }).catch(() => undefined);
    refresh();
  };
  const clearAll = async () => {
    await api("/notifications/delete", { body: {} }).catch(() => undefined);
    refresh();
  };
  const render = useNotificationText();
  const text = (n: NotificationItem) => render(n.message_key, n.params);
  const openItem = (n: NotificationItem) => {
    // Navigate first; marking as read must never block the navigation.
    setOpen(false);
    if (n.link) router.push(n.link);
    api("/notifications/read", { body: { ids: [n.id] } }).then(refresh, () => undefined);
  };
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      align="end"
      className="w-[min(22rem,calc(100vw-24px))] p-0"
      trigger={
        <Button variant="ghost" size="icon" aria-label={t("title")} className="relative">
          <Bell />
          {data?.unread ? <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-highlight ring-2 ring-background" /> : null}
        </Button>
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-x-2 border-b border-border px-3 py-2">
        <span className="text-[13px] font-semibold">{t("title")}</span>
        <span className="flex shrink-0 gap-1">
          {data?.unread ? <Button size="sm" variant="ghost" onClick={markAll}>{t("markAllRead")}</Button> : null}
          {data?.items.length ? <Button size="sm" variant="ghost" onClick={clearAll}>{t("clearAll")}</Button> : null}
        </span>
      </div>
      <ul className="max-h-96 overflow-y-auto">
        {!data?.items.length ? <li className="px-3 py-6 text-center text-[12px] text-muted">{t("empty")}</li> : null}
        {data?.items.map((n) => (
          <li key={n.id}>
            <button
              type="button"
              onClick={() => openItem(n)}
              className="flex w-full flex-col gap-0.5 border-b border-border px-3 py-2 text-left last:border-b-0 hover:bg-surface-2"
            >
              <span className={cn("text-[13px]", n.read ? "text-muted" : "text-foreground", n.severity === "error" && "text-danger")}>
                {text(n)}
              </span>
              <span className="text-[11px] text-muted">{relativeTime(n.created_at, locale)}</span>
            </button>
          </li>
        ))}
      </ul>
    </Popover>
  );
}

function Preferences() {
  const t = useTranslations("common");
  const tn = useTranslations("nav");
  const locale = useLocale();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const { data: session } = useSession();
  const qc = useQueryClient();
  const setLocale = async (l: "en" | "tr") => {
    document.cookie = `NEXT_LOCALE=${l}; path=/; max-age=31536000; samesite=lax`;
    await api("/auth/preferences", { method: "PUT", body: { locale: l } }).catch(() => undefined);
    router.refresh();
  };
  const saveTheme = (v: "light" | "dark" | "system") => {
    setTheme(v);
    api("/auth/preferences", { method: "PUT", body: { theme: v } }).catch(() => undefined);
  };
  const logout = async () => {
    await api("/auth/logout", { body: {} }).catch(() => undefined);
    qc.clear();
    window.location.href = "/login";
  };
  return (
    <>
      <Menu>
        <MenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("language")}><Languages /></Button>
        </MenuTrigger>
        <MenuContent>
          <MenuLabel>{t("language")}</MenuLabel>
          <MenuItem onSelect={() => setLocale("en")}>{locale === "en" ? "• " : ""}{t("english")}</MenuItem>
          <MenuItem onSelect={() => setLocale("tr")}>{locale === "tr" ? "• " : ""}{t("turkish")}</MenuItem>
        </MenuContent>
      </Menu>
      <Menu>
        <MenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("theme")}>{theme === "dark" ? <Moon /> : theme === "light" ? <Sun /> : <Monitor />}</Button>
        </MenuTrigger>
        <MenuContent>
          <MenuLabel>{t("theme")}</MenuLabel>
          <MenuItem onSelect={() => saveTheme("light")}><Sun />{t("themeLight")}</MenuItem>
          <MenuItem onSelect={() => saveTheme("dark")}><Moon />{t("themeDark")}</MenuItem>
          <MenuItem onSelect={() => saveTheme("system")}><Monitor />{t("themeSystem")}</MenuItem>
        </MenuContent>
      </Menu>
      <Menu>
        <MenuTrigger asChild>
          <Button variant="ghost" size="sm" className="max-w-40" aria-label={tn("account")}>
            <span className="flex size-5 items-center justify-center rounded-full bg-surface-2 text-[11px] font-semibold uppercase">{session?.user?.display_name?.[0] ?? "·"}</span>
            <span className="hidden truncate sm:inline">{session?.user?.display_name}</span>
          </Button>
        </MenuTrigger>
        <MenuContent>
          <MenuLabel>{session?.user?.email}</MenuLabel>
          <MenuItem onSelect={() => router.push("/settings?tab=account")}><Settings />{tn("account")}</MenuItem>
          <MenuSeparator />
          <MenuItem onSelect={logout}><LogOut />{tn("logout")}</MenuItem>
        </MenuContent>
      </Menu>
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations();
  const { data: session, isLoading } = useSession();
  const { setTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [quickAudit, setQuickAudit] = useState(false);
  const { data: queue } = useApi<unknown[]>(["review-queue-count"], session?.authenticated ? "/review-queue" : null, { refetchInterval: 60_000 });

  useEffect(() => {
    if (!isLoading && session && !session.authenticated) window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }, [isLoading, session]);
  useEffect(() => {
    if (session?.user) {
      setCollapsed(session.user.sidebar_collapsed);
      if (session.user.theme && !localStorage.getItem("theme")) setTheme(session.user.theme);
    }
  }, [session?.user, setTheme]);

  const toggle = () => {
    setCollapsed((c) => {
      api("/auth/preferences", { method: "PUT", body: { sidebar_collapsed: !c } }).catch(() => undefined);
      return !c;
    });
  };

  if (!session?.authenticated) {
    return <div className="flex min-h-screen items-center justify-center text-[13px] text-muted">{t("common.loading")}</div>;
  }
  return (
    <div className="flex min-h-screen">
      <aside className={cn("sticky top-0 hidden h-screen shrink-0 border-r border-border bg-background md:block", collapsed ? "w-14" : "w-56")}>
        <Sidebar collapsed={collapsed} onToggle={toggle} reviewCount={queue?.length} />
      </aside>
      {mobileOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button type="button" aria-label={t("common.close")} className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-border bg-background">
            <Sidebar collapsed={false} onNavigate={() => setMobileOpen(false)} reviewCount={queue?.length} />
          </aside>
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-border bg-background/95 px-3 backdrop-blur-none sm:px-5">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMobileOpen(true)} aria-label={t("nav.menu")}><MenuIcon /></Button>
          <div className="flex-1" />
          <Button size="sm" onClick={() => setQuickAudit(true)}><Zap />{t("overview.quickAudit")}</Button>
          <Notifications />
          <Preferences />
        </header>
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-3 py-5 sm:px-5">{children}</main>
        <footer className="px-5 py-3 text-[11px] text-muted">{t("common.osmAttribution")}</footer>
      </div>
      <QuickAuditDialog open={quickAudit} onOpenChange={setQuickAudit} />
    </div>
  );
}

