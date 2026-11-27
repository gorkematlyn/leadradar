"use client";

import { cn } from "@/lib/utils";

/**
 * Table container that fits the screen: the toolbar, the column headers and the footer
 * (row count, pages) stay in place while only the rows scroll. Because the box is never
 * taller than the viewport, its horizontal scrollbar is always visible without scrolling
 * to the end of the page.
 */
export const SCROLL_BOX = "flex max-h-[calc(100dvh-9rem)] min-h-64 flex-col rounded-lg border border-border bg-surface";
export const SCROLL_AREA =
  "min-h-0 flex-1 overflow-auto overscroll-contain [&_thead_th]:sticky [&_thead_th]:top-0 [&_thead_th]:z-10 " +
  "[&_thead_th]:bg-surface [&_thead_th]:shadow-[inset_0_-1px_0_var(--border)]";
export const SCROLL_FOOTER = "flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2 text-[12px] text-muted";

export function ScrollTable({ toolbar, footer, children, className }: {
  toolbar?: React.ReactNode; footer?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={cn(SCROLL_BOX, className)}>
      {toolbar ? <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2">{toolbar}</div> : null}
      <div className={SCROLL_AREA}>{children}</div>
      {footer ? <div className={SCROLL_FOOTER}>{footer}</div> : null}
    </div>
  );
}
