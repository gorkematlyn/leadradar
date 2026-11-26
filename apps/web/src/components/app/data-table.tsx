"use client";

import {
  type ColumnDef,
  type ColumnOrderState,
  type ColumnSizingState,
  flexRender,
  getCoreRowModel,
  type RowSelectionState,
  useReactTable,
  type VisibilityState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3, MoveLeft, MoveRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox, EmptyState, Skeleton } from "@/components/ui/misc";
import { Popover } from "@/components/ui/overlay";
import { useSession } from "@/hooks/use-session";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface TablePrefs {
  visibility?: VisibilityState;
  sizing?: ColumnSizingState;
  order?: ColumnOrderState;
}

interface Props<T> {
  id: string; // key for saved preferences
  columns: ColumnDef<T, unknown>[];
  data: T[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (p: number) => void;
  sort?: { id: string; desc: boolean };
  onSortChange?: (s: { id: string; desc: boolean }) => void;
  sortable?: string[];
  loading?: boolean;
  selectable?: boolean;
  selection?: RowSelectionState;
  onSelectionChange?: (s: RowSelectionState) => void;
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty?: React.ReactNode;
  toolbar?: React.ReactNode;
}

export function DataTable<T>(props: Props<T>) {
  const t = useTranslations("common");
  const { data: session } = useSession();
  const saved = (session?.user?.table_preferences?.[props.id] ?? {}) as TablePrefs;
  const [visibility, setVisibility] = useState<VisibilityState>(saved.visibility ?? {});
  const [sizing, setSizing] = useState<ColumnSizingState>(saved.sizing ?? {});
  const [order, setOrder] = useState<ColumnOrderState>(saved.order ?? []);
  const initialized = useRef(false);

  useEffect(() => {
    if (!initialized.current && session?.user) {
      initialized.current = true;
      setVisibility(saved.visibility ?? {});
      setSizing(saved.sizing ?? {});
      setOrder(saved.order ?? []);
    }
  }, [session?.user, saved.visibility, saved.sizing, saved.order]);

  // Persist table preferences per administrator (debounced).
  useEffect(() => {
    if (!initialized.current || !session?.user) return;
    const handle = setTimeout(() => {
      const all = { ...(session.user?.table_preferences ?? {}), [props.id]: { visibility, sizing, order } };
      api("/auth/preferences", { method: "PUT", body: { table_preferences: all } }).catch(() => undefined);
    }, 800);
    return () => clearTimeout(handle);
  }, [visibility, sizing, order, props.id, session?.user]);

  const columns = useMemo<ColumnDef<T, unknown>[]>(() => {
    if (!props.selectable) return props.columns;
    return [
      {
        id: "_select",
        size: 36,
        enableResizing: false,
        enableHiding: false,
        header: ({ table }) => (
          <Checkbox
            label={t("selectAll")}
            checked={table.getIsAllPageRowsSelected() ? true : table.getIsSomePageRowsSelected() ? "indeterminate" : false}
            onCheckedChange={(v) => table.toggleAllPageRowsSelected(v)}
          />
        ),
        cell: ({ row }) => (
          <div onClick={(e) => e.stopPropagation()}>
            <Checkbox label="select" checked={row.getIsSelected()} onCheckedChange={(v) => row.toggleSelected(v)} />
          </div>
        ),
      },
      ...props.columns,
    ];
  }, [props.columns, props.selectable, t]);

  const table = useReactTable({
    data: props.data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    getRowId: props.getRowId,
    enableRowSelection: props.selectable,
    columnResizeMode: "onChange",
    state: { columnVisibility: visibility, columnSizing: sizing, columnOrder: order, rowSelection: props.selection ?? {} },
    onColumnVisibilityChange: setVisibility,
    onColumnSizingChange: setSizing,
    onColumnOrderChange: setOrder,
    onRowSelectionChange: (updater) => {
      const next = typeof updater === "function" ? updater(props.selection ?? {}) : updater;
      props.onSelectionChange?.(next);
    },
    defaultColumn: { minSize: 60, size: 140, maxSize: 600 },
  });

  const pages = Math.max(1, Math.ceil(props.total / props.pageSize));
  const move = (id: string, dir: -1 | 1) => {
    const current = order.length ? [...order] : table.getAllLeafColumns().map((c) => c.id);
    const i = current.indexOf(id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= current.length) return;
    [current[i], current[j]] = [current[j], current[i]];
    setOrder(current);
  };

  return (
    <div className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <div className="flex flex-1 flex-wrap items-center gap-2">{props.toolbar}</div>
        <Popover
          align="end"
          trigger={<Button size="sm" variant="ghost"><Columns3 />{t("columns")}</Button>}
        >
          <ul className="grid gap-1">
            {table.getAllLeafColumns().filter((c) => c.getCanHide()).map((c) => (
              <li key={c.id} className="flex items-center gap-2 text-[13px]">
                <Checkbox label={c.id} checked={c.getIsVisible()} onCheckedChange={(v) => c.toggleVisibility(v)} />
                <span className="flex-1 truncate">{typeof c.columnDef.header === "string" ? c.columnDef.header : c.id}</span>
                <button type="button" className="text-muted hover:text-foreground" aria-label="move left" onClick={() => move(c.id, -1)}><MoveLeft className="size-3.5" /></button>
                <button type="button" className="text-muted hover:text-foreground" aria-label="move right" onClick={() => move(c.id, 1)}><MoveRight className="size-3.5" /></button>
              </li>
            ))}
          </ul>
          <Button size="sm" variant="ghost" className="mt-2 w-full" onClick={() => { setVisibility({}); setSizing({}); setOrder([]); }}>{t("reset")}</Button>
        </Popover>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]" style={{ minWidth: table.getTotalSize() }}>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-border">
                {hg.headers.map((h) => {
                  const sortable = props.sortable?.includes(h.column.id);
                  const active = props.sort?.id === h.column.id;
                  return (
                    <th
                      key={h.id}
                      style={{ width: h.getSize() }}
                      className="relative h-8 select-none px-3 text-left text-[12px] font-medium text-muted"
                      aria-sort={active ? (props.sort?.desc ? "descending" : "ascending") : undefined}
                    >
                      {h.isPlaceholder ? null : sortable ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 hover:text-foreground"
                          onClick={() => props.onSortChange?.({ id: h.column.id, desc: active ? !props.sort?.desc : true })}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {active ? (props.sort?.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />) : null}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                      {h.column.getCanResize() ? (
                        <span
                          onMouseDown={h.getResizeHandler()}
                          onTouchStart={h.getResizeHandler()}
                          className={cn("absolute right-0 top-1.5 h-5 w-1 cursor-col-resize rounded-full hover:bg-border", h.column.getIsResizing() && "bg-ring")}
                        />
                      ) : null}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {props.loading && !props.data.length
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-b border-border last:border-b-0">
                    {table.getVisibleLeafColumns().map((c) => (
                      <td key={c.id} className="px-3 py-2"><Skeleton className="h-4 w-full" /></td>
                    ))}
                  </tr>
                ))
              : table.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    onClick={props.onRowClick ? () => props.onRowClick?.(row.original) : undefined}
                    className={cn("border-b border-border last:border-b-0", props.onRowClick && "cursor-pointer hover:bg-surface-2", row.getIsSelected() && "bg-surface-2")}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} style={{ width: cell.column.getSize() }} className="truncate px-3 py-2 align-middle">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>
        {!props.loading && !props.data.length ? (props.empty ?? <EmptyState title={t("noResults")} />) : null}
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-[12px] text-muted">
        <span className="num">{t("rows", { count: props.total })}</span>
        <div className="flex items-center gap-2">
          <span className="num">{t("page", { page: props.page, pages })}</span>
          <Button size="icon-sm" variant="ghost" aria-label={t("previous")} disabled={props.page <= 1} onClick={() => props.onPageChange(props.page - 1)}><ChevronLeft /></Button>
          <Button size="icon-sm" variant="ghost" aria-label={t("next")} disabled={props.page >= pages} onClick={() => props.onPageChange(props.page + 1)}><ChevronRight /></Button>
        </div>
      </div>
    </div>
  );
}
