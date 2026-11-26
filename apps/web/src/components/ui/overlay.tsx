"use client";

import { Dialog as D, DropdownMenu as DM, Popover as P, Tabs as T } from "radix-ui";
import { X } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Dialog({ open, onOpenChange, title, description, children, footer, wide }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: React.ReactNode; description?: React.ReactNode;
  children?: React.ReactNode; footer?: React.ReactNode; wide?: boolean;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <D.Content className={cn("fixed left-1/2 top-[8vh] z-50 flex max-h-[84vh] w-[calc(100vw-32px)] -translate-x-1/2 flex-col rounded-lg border border-border bg-surface shadow-lg", wide ? "max-w-3xl" : "max-w-lg")}>
          <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
            <div>
              <D.Title className="text-[14px] font-semibold">{title}</D.Title>
              {description ? <D.Description className="mt-0.5 text-[12px] text-muted">{description}</D.Description> : <D.Description className="sr-only">{String(title)}</D.Description>}
            </div>
            <D.Close className="rounded-md p-1 text-muted hover:bg-surface-2" aria-label="Close"><X className="size-4" /></D.Close>
          </div>
          <div className="overflow-y-auto px-4 py-4">{children}</div>
          {footer ? <div className="flex justify-end gap-2 border-t border-border px-4 py-3">{footer}</div> : null}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

export const Menu = DM.Root;
export const MenuTrigger = DM.Trigger;

export function MenuContent({ children, align = "end" }: { children: React.ReactNode; align?: "start" | "end" | "center" }) {
  return (
    <DM.Portal>
      <DM.Content align={align} sideOffset={4} className="z-50 min-w-44 rounded-md border border-border bg-surface p-1 shadow-md">
        {children}
      </DM.Content>
    </DM.Portal>
  );
}

export function MenuItem({ children, onSelect, danger, disabled }: { children: React.ReactNode; onSelect?: () => void; danger?: boolean; disabled?: boolean }) {
  return (
    <DM.Item
      disabled={disabled}
      onSelect={onSelect}
      className={cn("flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-2 [&_svg]:size-4 [&_svg]:text-muted", danger && "text-danger")}
    >
      {children}
    </DM.Item>
  );
}

export function MenuSeparator() {
  return <DM.Separator className="my-1 h-px bg-border" />;
}

export function MenuLabel({ children }: { children: React.ReactNode }) {
  return <DM.Label className="px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-muted">{children}</DM.Label>;
}

export function Popover({ trigger, children, align = "start", className }: { trigger: React.ReactNode; children: React.ReactNode; align?: "start" | "end"; className?: string }) {
  return (
    <P.Root>
      <P.Trigger asChild>{trigger}</P.Trigger>
      <P.Portal>
        <P.Content align={align} sideOffset={4} className={cn("z-50 w-72 rounded-md border border-border bg-surface p-3 shadow-md", className)}>
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  );
}

export function Tabs({ value, onValueChange, tabs, children }: { value: string; onValueChange: (v: string) => void; tabs: { value: string; label: React.ReactNode; count?: number }[]; children?: React.ReactNode }) {
  return (
    <T.Root value={value} onValueChange={onValueChange}>
      <T.List className="flex gap-1 overflow-x-auto border-b border-border">
        {tabs.map((t) => (
          <T.Trigger
            key={t.value}
            value={t.value}
            className="relative -mb-px whitespace-nowrap border-b-2 border-transparent px-2.5 py-2 text-[13px] text-muted hover:text-foreground data-[state=active]:border-foreground data-[state=active]:text-foreground"
          >
            {t.label}
            {t.count !== undefined ? <span className="num ml-1.5 text-[11px] text-muted">{t.count}</span> : null}
          </T.Trigger>
        ))}
      </T.List>
      {children}
    </T.Root>
  );
}
