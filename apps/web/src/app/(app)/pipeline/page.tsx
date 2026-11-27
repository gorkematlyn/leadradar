"use client";

import { useQueryClient } from "@tanstack/react-query";
import { HoverCard } from "radix-ui";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { CountryLabel, DateText, PageHeader, ScoreValue } from "@/components/app/bits";
import { CompanyQuickView } from "@/components/app/company-quick-view";
import { ScrollTable } from "@/components/app/scroll-table";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { Badge, Card, EmptyState, InfoTip } from "@/components/ui/misc";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useCrmStatuses, useCrmStatusOptions, useLocalizedName } from "@/hooks/use-catalog";
import { api } from "@/lib/api";
import { fmtNumber } from "@/lib/utils";

interface KanbanCard { id: string; name: string; score: number | null; country: string | null; follow_up_at: string | null }
interface TableRow {
  id: string; name: string; country: string | null; crm_status: string; score: number | null; classification: string | null; follow_up_at: string | null;
  services: { key: string; score: number; provisional: boolean }[];
  reports: { count: number; latest: { id: string; title: string; status: string; updated_at: string }[] };
  ads: { total: number; platforms: { platform: string; count: number }[] };
}

const VIEW_KEY = "leadradar.pipeline.view";
const PAGE_SIZE = 50;

function readView(): "kanban" | "table" {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(VIEW_KEY) === "table" ? "table" : "kanban";
  } catch {
    return "kanban";
  }
}

/** A number that reveals details on hover (and on keyboard focus). */
function HoverCount({ count, children }: { count: number; children: React.ReactNode }) {
  if (!count) return <span className="num text-muted">0</span>;
  return (
    <HoverCard.Root openDelay={120} closeDelay={80}>
      <HoverCard.Trigger asChild>
        <button type="button" className="num cursor-default rounded-sm px-1 hover:font-semibold hover:underline focus-visible:font-semibold focus-visible:underline focus-visible:outline-2 focus-visible:outline-ring">
          {count}
        </button>
      </HoverCard.Trigger>
      <HoverCard.Portal>
        <HoverCard.Content side="bottom" align="start" sideOffset={4} collisionPadding={12}
          className="z-50 w-[min(20rem,calc(100vw-24px))] rounded-md border border-border bg-surface p-3 text-[12px] shadow-md">
          {children}
        </HoverCard.Content>
      </HoverCard.Portal>
    </HoverCard.Root>
  );
}

export default function PipelinePage() {
  const t = useTranslations();
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const name = useLocalizedName();
  const statusOptions = useCrmStatusOptions();
  const [view, setViewState] = useState<"kanban" | "table">(readView);
  const [open, setOpen] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const { data: statuses } = useCrmStatuses();
  const { data } = useApi<{ columns: Record<string, KanbanCard[]> }>(["pipeline"], view === "kanban" ? "/crm/pipeline" : null);
  const { data: table } = useApi<{ total: number; items: TableRow[] }>(["pipeline-table", page], view === "table" ? `/crm/pipeline/table?page=${page}&page_size=${PAGE_SIZE}` : null);
  const [dragging, setDragging] = useState<string | null>(null);
  const setView = (v: "kanban" | "table") => {
    setViewState(v);
    try { window.localStorage.setItem(VIEW_KEY, v); } catch { /* storage unavailable: choice is kept for this visit only */ }
  };
  const move = async (id: string, status: string) => {
    try {
      await api(`/companies/${id}`, { method: "PATCH", body: { crm_status: status } });
      ["pipeline", "pipeline-table", "crm-statuses", "company"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    } catch (e) {
      toast.error(err(e));
    }
  };
  const statusName = (key: string) => { const s = statuses?.find((x) => x.key === key); return s ? name(s) : key; };
  const cols = Object.keys(data?.columns ?? {});
  const pages = Math.max(1, Math.ceil((table?.total ?? 0) / PAGE_SIZE));
  return (
    <>
      <PageHeader title={t("crm.title")} description={t("crm.subtitle")} actions={
        <div className="flex rounded-md border border-border">
          <Button size="sm" variant={view === "kanban" ? "primary" : "ghost"} onClick={() => setView("kanban")}>{t("crm.kanban")}</Button>
          <Button size="sm" variant={view === "table" ? "primary" : "ghost"} onClick={() => setView("table")}>{t("crm.table")}</Button>
        </div>
      } />
      {view === "kanban" ? (
        <div className="flex gap-3 overflow-x-auto pb-3">
          {cols.map((col) => (
            <div key={col} className="w-64 shrink-0" onDragOver={(e) => e.preventDefault()} onDrop={() => dragging && move(dragging, col)}>
              <div className="mb-2 flex items-center justify-between px-1 text-[12px]">
                <span className="font-medium">{statusName(col)}</span>
                <span className="num text-muted">{statuses?.find((s) => s.key === col)?.count ?? 0}</span>
              </div>
              <div className="grid min-h-24 gap-2 rounded-lg border border-dashed border-border p-2">
                {data?.columns[col].map((c) => (
                  <Card key={c.id} draggable onDragStart={() => setDragging(c.id)} onDragEnd={() => setDragging(null)} className="cursor-grab p-2.5 active:cursor-grabbing">
                    <button type="button" onClick={() => setOpen(c.id)} className="block w-full truncate text-left text-[13px] font-medium hover:underline">{c.name}</button>
                    <div className="mt-1 flex items-center justify-between text-[12px]">
                      <CountryLabel code={c.country} short />
                      <ScoreValue score={c.score} />
                    </div>
                    {c.follow_up_at ? <p className="mt-1 text-[11px] text-muted">{t("crm.followUps")}: <DateText value={c.follow_up_at} /></p> : null}
                    <NativeSelect className="mt-2 h-6 text-[11px]" value={col} onChange={(e) => move(c.id, e.target.value)} aria-label={t("crm.moveTo")}>
                      {statusOptions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </NativeSelect>
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <ScrollTable
          footer={<>
            <span className="num">{t("common.rows", { count: table?.total ?? 0 })}</span>
            <span className="flex items-center gap-2">
              <span className="num">{t("common.pageOf", { page, pages })}</span>
              <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("common.previous")}</Button>
              <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("common.next")}</Button>
            </span>
          </>}>
          {table && !table.items.length ? <EmptyState title={t("crm.empty")} /> : (
            <table className="w-full min-w-[980px] text-[13px]">
              <thead>
                <tr className="text-left text-[12px] text-muted">
                  <th className="px-4 py-2 font-medium">{t("companies.col.company")}</th>
                  <th className="px-2 py-2 font-medium">{t("companies.col.crmStatus")}</th>
                  <th className="px-2 py-2 font-medium"><span className="inline-flex items-center gap-1">{t("crm.opportunities")}<InfoTip>{t("crm.opportunitiesInfo")}</InfoTip></span></th>
                  <th className="px-2 py-2 font-medium">{t("companies.col.leadScore")}</th>
                  <th className="px-2 py-2 text-center font-medium">{t("crm.reports")}</th>
                  <th className="px-2 py-2 text-center font-medium"><span className="inline-flex items-center gap-1">{t("crm.ads")}<InfoTip>{t("crm.adsInfo")}</InfoTip></span></th>
                  <th className="px-4 py-2 font-medium">{t("crm.followUps")}</th>
                </tr>
              </thead>
              <tbody>
                {table?.items.map((r) => (
                  <tr key={r.id} className="border-t border-border align-top">
                    <td className="max-w-64 px-4 py-2">
                      <button type="button" onClick={() => setOpen(r.id)} className="block max-w-full truncate text-left font-medium hover:underline">{r.name}</button>
                      <CountryLabel code={r.country} short />
                    </td>
                    <td className="px-2 py-2">
                      <NativeSelect className="h-7 w-44" value={r.crm_status} onChange={(e) => move(r.id, e.target.value)} aria-label={t("crm.moveTo")}>
                        {statusOptions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                      </NativeSelect>
                    </td>
                    <td className="px-2 py-2">
                      {r.services.length ? (
                        <span className="flex max-w-96 flex-wrap gap-1">
                          {r.services.map((s) => <Badge key={s.key} tone="solid">{t(`services.${s.key}`)}{s.provisional ? "*" : ""} <span className="num ml-1 text-muted">{s.score}</span></Badge>)}
                        </span>
                      ) : <span className="text-muted">—</span>}
                    </td>
                    <td className="px-2 py-2"><ScoreValue score={r.score} /></td>
                    <td className="px-2 py-2 text-center">
                      <HoverCount count={r.reports.count}>
                        <p className="mb-1.5 font-medium">{t("crm.latestReports")}</p>
                        <ul className="grid gap-1">
                          {r.reports.latest.map((x) => (
                            <li key={x.id} className="flex items-baseline justify-between gap-3">
                              <Link href={`/reports/${x.id}`} className="min-w-0 truncate hover:underline">{x.title}</Link>
                              <span className="shrink-0 text-[11px] text-muted"><DateText value={x.updated_at} /></span>
                            </li>
                          ))}
                        </ul>
                        {r.reports.count > r.reports.latest.length ? (
                          <Link href={`/companies/${r.id}?tab=reports`} className="mt-1.5 block text-[11px] text-muted hover:underline">
                            {t("crm.moreReports", { count: r.reports.count - r.reports.latest.length })}
                          </Link>
                        ) : null}
                      </HoverCount>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <HoverCount count={r.ads.total}>
                        <p className="mb-1.5 font-medium">{t("crm.adsByPlatform")}</p>
                        <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1">
                          {r.ads.platforms.map((p) => (
                            <div key={p.platform} className="contents">
                              <dt>{t.has(`ads.platforms.${p.platform}`) ? t(`ads.platforms.${p.platform}`) : p.platform}</dt>
                              <dd className="num text-right">{fmtNumber(p.count, locale)}</dd>
                            </div>
                          ))}
                        </dl>
                      </HoverCount>
                    </td>
                    <td className="px-4 py-2"><DateText value={r.follow_up_at} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </ScrollTable>
      )}
      <CompanyQuickView id={open} onOpenChange={(v) => !v && setOpen(null)} />
    </>
  );
}
