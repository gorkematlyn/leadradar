"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { DateText, JobStatusBadge, PageHeader } from "@/components/app/bits";
import { JobActions, JobProgress, JobStage } from "@/components/app/job-bits";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, InfoTip, Tooltip } from "@/components/ui/misc";
import { ConfirmDialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import { fmtNumber } from "@/lib/utils";

const FILTERS = ["running", "queued", "waiting_review", "failed", "dead", "completed", "cancelled", "paused"];
const PAGE_SIZE = 50;

function JobsView() {
  const t = useTranslations();
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const params = useSearchParams();
  const [status, setStatus] = useState<string[]>(params.getAll("status").filter((s) => FILTERS.includes(s)));
  const [page, setPage] = useState(1);
  const [clearOpen, setClearOpen] = useState(false);
  const qs = new URLSearchParams();
  status.forEach((s) => qs.append("status", s));
  qs.set("page", String(page));
  qs.set("page_size", String(PAGE_SIZE));
  const { data } = useApi<{ total: number; counts: Record<string, number>; items: Job[] }>(["jobs", status, page], `/jobs?${qs.toString()}`, { refetchInterval: 5_000 });
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const all = Object.values(data?.counts ?? {}).reduce((a, b) => a + b, 0);
  const finished = ["completed", "failed", "dead", "cancelled"].reduce((a, s) => a + (data?.counts[s] ?? 0), 0);
  const go = (p: number) => setPage(Math.min(pages, Math.max(1, p)));
  const deleteFinished = async () => {
    try {
      const r = await api<{ deleted: number }>("/jobs/delete", { body: {} });
      toast.success(t("jobs.deleted", { count: r.deleted }));
      setPage(1);
      ["jobs", "dashboard", "notifications", "countries", "discovery-progress"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <>
      <PageHeader title={t("jobs.title")} description={t("jobs.subtitle")}
        actions={finished ? <Button size="sm" onClick={() => setClearOpen(true)}><Trash2 />{t("jobs.deleteFinished")}</Button> : null} />
      <div className="mb-3 flex flex-wrap gap-2">
        <Button size="sm" variant={!status.length ? "primary" : "secondary"} onClick={() => { setStatus([]); setPage(1); }}>
          {t("common.all")} <span className="num text-[11px] opacity-70">{all}</span>
        </Button>
        {FILTERS.map((s) => (
          <Tooltip key={s} content={t(`jobs.statusInfo.${s}`)}>
            <Button size="sm" variant={status.includes(s) ? "primary" : "secondary"} onClick={() => { setStatus(status.includes(s) ? status.filter((x) => x !== s) : [...status, s]); setPage(1); }}>
              {t(`jobs.status.${s}`)} <span className="num text-[11px] opacity-70">{data?.counts[s] ?? 0}</span>
            </Button>
          </Tooltip>
        ))}
      </div>
      <Card>
        {data && !data.items.length ? <EmptyState title={t("jobs.empty")} /> : null}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-[13px]">
            <thead><tr className="border-b border-border text-left text-[12px] text-muted">
              <th className="px-4 py-2 font-medium">{t("jobs.job")}</th><th className="px-2 py-2 font-medium">{t("common.status")}</th>
              <th className="px-2 py-2 font-medium">{t("jobs.stage")}</th><th className="px-2 py-2 font-medium">{t("jobs.progress")}</th>
              <th className="px-2 py-2 font-medium">{t("jobs.started")}</th><th className="px-2 py-2 font-medium">{t("jobs.heartbeat")}</th>
              <th className="px-2 py-2 font-medium">{t("jobs.attempts")}</th><th className="px-4 py-2" />
            </tr></thead>
            <tbody>
              {data?.items.map((j) => (
                <tr key={j.id} className="border-b border-border last:border-0">
                  <td className="max-w-80 px-4 py-2">
                    <Link href={`/jobs/${j.id}`} className="block truncate font-medium hover:underline">{j.name}</Link>
                    <span className="text-[11px] text-muted">{t.has(`jobs.types.${j.type}`) ? t(`jobs.types.${j.type}`) : j.type}</span>
                    {j.error ? <Link href={`/jobs/${j.id}`} className="block truncate text-[11px] text-danger hover:underline" title={j.error}>{j.error}</Link> : null}
                  </td>
                  <td className="px-2 py-2"><span className="inline-flex items-center gap-1"><JobStatusBadge status={j.status} />{["dead", "failed"].includes(j.status) ? <InfoTip>{t(`jobs.statusInfo.${j.status}`)}</InfoTip> : null}</span></td>
                  <td className="px-2 py-2 text-[12px] text-muted"><JobStage stage={j.stage} /></td>
                  <td className="px-2 py-2"><JobProgress job={j} /></td>
                  <td className="px-2 py-2"><DateText value={j.started_at} withTime /></td>
                  <td className="px-2 py-2"><DateText value={j.heartbeat_at} withTime /></td>
                  <td className="num px-2 py-2 text-[12px]">{j.attempts}/{j.max_attempts}</td>
                  <td className="px-4 py-2"><JobActions job={j} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2">
          <span className="num text-[12px] text-muted">
            {total ? t("common.range", { from: fmtNumber((page - 1) * PAGE_SIZE + 1, locale), to: fmtNumber(Math.min(total, page * PAGE_SIZE), locale), total: fmtNumber(total, locale) }) : null}
          </span>
          <div className="flex items-center gap-1">
            <Button size="icon-sm" variant="ghost" aria-label={t("common.first")} disabled={page <= 1} onClick={() => go(1)}><ChevronsLeft /></Button>
            <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => go(page - 1)}><ChevronLeft />{t("common.previous")}</Button>
            <span className="num px-2 text-[12px]">{t("common.pageOf", { page, pages })}</span>
            <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => go(page + 1)}>{t("common.next")}<ChevronRight /></Button>
            <Button size="icon-sm" variant="ghost" aria-label={t("common.last")} disabled={page >= pages} onClick={() => go(pages)}><ChevronsRight /></Button>
          </div>
        </div>
      </Card>
      <ConfirmDialog open={clearOpen} onOpenChange={setClearOpen} title={t("jobs.deleteFinished")} danger message={t("jobs.deleteFinishedConfirm")}
        confirmLabel={t("jobs.deleteFinished")} cancelLabel={t("common.cancel")} onConfirm={deleteFinished} />
    </>
  );
}

export default function JobsPage() {
  return <Suspense><JobsView /></Suspense>;
}
