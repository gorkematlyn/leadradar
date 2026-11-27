"use client";

import { Checkbox as CB, Switch as SW, Tooltip as TT } from "radix-ui";
import { Check, CircleHelp, Info, Minus } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg border border-border bg-surface", className)} {...props} />;
}

export function CardHeader({ title, description, actions, className }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3", className)}>
      <div className="min-w-0 flex-1 basis-48">
        <h3 className="text-[13px] font-semibold">{title}</h3>
        {description ? <p className="mt-0.5 text-[12px] text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div> : null}
    </div>
  );
}

const tones: Record<string, string> = {
  neutral: "border-border text-muted",
  success: "border-success/40 text-success",
  warning: "border-warning/40 text-warning",
  danger: "border-danger/40 text-danger",
  info: "border-info/40 text-info",
  accent: "border-transparent bg-highlight text-highlight-foreground",
  solid: "border-transparent bg-surface-2 text-foreground",
};

export function Badge({ tone = "neutral", className, ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof tones | string }) {
  return (
    <span
      className={cn("inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 text-[11px] font-medium", tones[tone] ?? tones.neutral, className)}
      {...props}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-surface-2", className)} />;
}

export function Checkbox({ checked, onCheckedChange, label, ...rest }: { checked: boolean | "indeterminate"; onCheckedChange: (v: boolean) => void; label?: string; disabled?: boolean }) {
  return (
    <CB.Root
      checked={checked}
      onCheckedChange={(v) => onCheckedChange(v === true)}
      aria-label={label}
      className="flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-border bg-surface data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=indeterminate]:bg-accent data-[state=checked]:text-accent-foreground data-[state=indeterminate]:text-accent-foreground"
      {...rest}
    >
      <CB.Indicator>{checked === "indeterminate" ? <Minus className="size-3" /> : <Check className="size-3" />}</CB.Indicator>
    </CB.Root>
  );
}

export function Switch({ checked, onCheckedChange, label, disabled }: { checked: boolean; onCheckedChange: (v: boolean) => void; label?: string; disabled?: boolean }) {
  return (
    <SW.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      aria-label={label}
      disabled={disabled}
      className="relative h-[18px] w-8 shrink-0 rounded-full border border-border bg-surface-2 transition-colors data-[state=checked]:border-accent data-[state=checked]:bg-accent disabled:opacity-50"
    >
      <SW.Thumb className="block size-3.5 translate-x-px rounded-full bg-foreground transition-transform data-[state=checked]:translate-x-[14px] data-[state=checked]:bg-accent-foreground" />
    </SW.Root>
  );
}

export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  return (
    <TT.Provider delayDuration={250}>
      <TT.Root>
        <TT.Trigger asChild>{children}</TT.Trigger>
        <TT.Portal>
          <TT.Content sideOffset={4} className="z-50 max-w-xs rounded-md border border-border bg-surface px-2 py-1 text-[12px] text-foreground shadow-sm">
            {content}
          </TT.Content>
        </TT.Portal>
      </TT.Root>
    </TT.Provider>
  );
}

/** Circled question mark that explains a term. Opens on hover, keyboard focus and tap. */
export function InfoTip({ children, label = "?", className }: { children: React.ReactNode; label?: string; className?: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <TT.Provider delayDuration={150}>
      <TT.Root open={open} onOpenChange={setOpen}>
        <TT.Trigger asChild>
          <button
            type="button"
            aria-label={label}
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o); }}
            className={cn("inline-flex size-4 shrink-0 items-center justify-center rounded-full align-middle text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring", className)}
          >
            <CircleHelp className="size-3.5" />
          </button>
        </TT.Trigger>
        <TT.Portal>
          <TT.Content side="top" sideOffset={4} collisionPadding={12}
            className="z-50 max-w-[min(22rem,calc(100vw-24px))] whitespace-pre-line rounded-md border border-border bg-surface px-3 py-2 text-[12px] font-normal leading-relaxed text-foreground shadow-md">
            {children}
          </TT.Content>
        </TT.Portal>
      </TT.Root>
    </TT.Provider>
  );
}

/** Highlighted explanation block for the top of a page or card. */
export function Callout({ title, children, className }: { title?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex gap-2.5 rounded-lg border border-info/30 bg-info/5 px-3 py-2.5 text-[12px] leading-relaxed", className)}>
      <Info className="mt-0.5 size-4 shrink-0 text-info" />
      <div className="min-w-0">
        {title ? <p className="mb-0.5 font-medium text-foreground">{title}</p> : null}
        <div className="text-muted [&_strong]:font-medium [&_strong]:text-foreground">{children}</div>
      </div>
    </div>
  );
}

export function EmptyState({ icon, title, description, action }: { icon?: React.ReactNode; title: React.ReactNode; description?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon ? <div className="text-muted [&_svg]:size-5">{icon}</div> : null}
      <p className="text-[13px] font-medium">{title}</p>
      {description ? <p className="max-w-md text-[12px] text-muted">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: React.ReactNode; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 px-4 py-3">
      <span className="text-[12px] text-muted">{label}</span>
      <span className="num text-[20px] font-medium leading-tight">{value}</span>
      {hint ? <span className="text-[11px] text-muted">{hint}</span> : null}
    </div>
  );
}

export function Progress({ value, total, className, tone }: { value: number; total: number | null; className?: string; tone?: "danger" | "muted" }) {
  if (!total) {
    return <div className={cn("h-1 w-24 overflow-hidden rounded-full bg-surface-2", className)}><div className="h-full w-1/3 animate-pulse rounded-full bg-muted" /></div>;
  }
  const pct = Math.max(0, Math.min(100, (value / total) * 100));
  return (
    <div className={cn("h-1 w-24 overflow-hidden rounded-full bg-surface-2", className)} role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn("h-full rounded-full", tone === "danger" ? "bg-danger" : tone === "muted" ? "bg-muted" : "bg-foreground")} style={{ width: `${pct}%` }} />
    </div>
  );
}
