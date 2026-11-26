"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useState } from "react";
import { DateText, JobStatusBadge, PageHeader } from "@/components/app/bits";
import { JobActions, JobProgress } from "@/components/app/job-bits";
import { Button } from "@/components/ui/button";
import { Card, EmptyState } from "@/components/ui/misc";
import { useApi } from "@/hooks/use-api";
import type { Job } from "@/lib/types";

const FILTERS = ["running", "queued", "waiting_review", "failed", "dead", "completed", "cancelled", "paused"];

function JobsView() {
  const t = useTranslations();
  const params = useSearchParams();
  const [status, setStatus] = useState<string[]>(params.get("status") ? [params.get("status") as string] : []);
  const [page, setPage] = useState(1);
  const qs = new URLSearchParams();
  status.forEach((s) => qs.append("status", s));
  qs.set("page", String(page));
  const { data } = useApi<{ total: number; counts: Record<string, number>; items: Job[] }>(["jobs", status, page], `/jobs?${qs.toString()}`, { refetchInterval: 5_000 });
  return (
    <>
      <PageHeader title={t("jobs.title")} description={t("jobs.subtitle")} />
      <div className="mb-3 flex flex-wrap gap-2">
        <Button size="sm" variant={!status.length ? "primary" : "secondary"} onClick={() => setStatus([])}>{t("common.all")}</Button>
        {FILTERS.map((s) => (
          <Button key={s} size="sm" variant={status.includes(s) ? "primary" : "secondary"} onClick={() => { setStatus(status.includes(s) ? status.filter((x) => x !== s) : [...status, s]); setPage(1); }}>
            {t(`jobs.status.${s}`)} <span className="num text-[11px] opacity-70">{data?.counts[s] ?? 0}</span>
          </Button>
        ))}
      </div>
      <Card>
        {data && !data.items.length ? <EmptyState title={t("jobs.empty")} /> : null}
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
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
                    {j.error ? <p className="truncate text-[11px] text-danger">{j.error}</p> : null}
                  </td>
                  <td className="px-2 py-2"><JobStatusBadge status={j.status} /></td>
                  <td className="num px-2 py-2 text-[12px] text-muted">{j.stage ?? "—"}</td>
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
        <div className="flex justify-end gap-2 border-t border-border px-3 py-2">
          <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("common.previous")}</Button>
          <Button size="sm" variant="ghost" disabled={(data?.items.length ?? 0) < 50} onClick={() => setPage(page + 1)}>{t("common.next")}</Button>
        </div>
      </Card>
    </>
  );
}

export default function JobsPage() {
  return <Suspense><JobsView /></Suspense>;
}
