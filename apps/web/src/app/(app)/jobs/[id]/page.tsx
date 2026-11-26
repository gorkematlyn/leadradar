"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { DateText, JobStatusBadge, KeyValue, PageHeader } from "@/components/app/bits";
import { JobActions, JobProgress } from "@/components/app/job-bits";
import { Card, CardHeader, Skeleton } from "@/components/ui/misc";
import { useApi } from "@/hooks/use-api";
import type { Job } from "@/lib/types";

interface JobDetail extends Job {
  payload: Record<string, unknown>; result: Record<string, unknown>; checkpoint: Record<string, unknown>;
  logs: { level: string; message: string; data: Record<string, unknown>; at: string }[];
  attempts_detail: { attempt: number; worker: string; started_at: string; finished_at: string | null; outcome: string | null; error: string | null }[];
  children: Job[];
}

export default function JobPage() {
  const t = useTranslations();
  const { id } = useParams<{ id: string }>();
  const { data: j } = useApi<JobDetail>(["job", id], `/jobs/${id}`, { refetchInterval: 4_000 });
  if (!j) return <Skeleton className="h-64 w-full" />;
  return (
    <>
      <PageHeader title={j.name} description={t.has(`jobs.types.${j.type}`) ? t(`jobs.types.${j.type}`) : j.type} actions={<JobActions job={j} />} />
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card>
          <dl className="px-4 py-2">
            <KeyValue label={t("common.status")}><JobStatusBadge status={j.status} />{j.cancel_requested ? <span className="ml-2 text-[12px] text-muted">{t("jobs.cancelRequested")}</span> : null}</KeyValue>
            <KeyValue label={t("jobs.stage")}><span className="num">{j.stage ?? "—"}</span></KeyValue>
            <KeyValue label={t("jobs.progress")}><JobProgress job={j} /></KeyValue>
            <KeyValue label={t("jobs.attempts")}><span className="num">{j.attempts}/{j.max_attempts}</span></KeyValue>
            <KeyValue label={t("common.created")}><DateText value={j.created_at} withTime /></KeyValue>
            <KeyValue label={t("jobs.started")}><DateText value={j.started_at} withTime /></KeyValue>
            <KeyValue label={t("jobs.heartbeat")}><DateText value={j.heartbeat_at} withTime /></KeyValue>
            {j.company_id ? <KeyValue label={t("nav.companies")}><Link href={`/companies/${j.company_id}`} className="hover:underline">{t("common.open")}</Link></KeyValue> : null}
            {j.parent_id ? <KeyValue label="Parent"><Link href={`/jobs/${j.parent_id}`} className="hover:underline">{j.parent_id.slice(0, 8)}</Link></KeyValue> : null}
            {j.error ? <KeyValue label={t("jobs.error")}><span className="text-danger">{j.error}</span></KeyValue> : null}
          </dl>
        </Card>
        <Card>
          <CardHeader title={t("jobs.payload")} />
          <pre className="num max-h-48 overflow-auto p-4 text-[11px]">{JSON.stringify(j.payload, null, 2)}</pre>
          <CardHeader title={t("jobs.result")} className="border-t" />
          <pre className="num max-h-48 overflow-auto p-4 text-[11px]">{JSON.stringify(j.result, null, 2)}</pre>
        </Card>
      </div>
      {j.children.length ? (
        <Card className="mt-4">
          <CardHeader title={t("jobs.children")} />
          <ul className="divide-y divide-border">
            {j.children.map((c) => (
              <li key={c.id} className="flex items-center gap-3 px-4 py-2 text-[13px]">
                <Link href={`/jobs/${c.id}`} className="flex-1 truncate hover:underline">{c.name}</Link>
                <JobStatusBadge status={c.status} /><JobProgress job={c} />
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <Card className="mt-4">
        <CardHeader title={t("jobs.logs")} />
        <ul className="num divide-y divide-border text-[12px]">
          {j.logs.map((l, i) => (
            <li key={i} className="grid grid-cols-[150px_60px_1fr] gap-3 px-4 py-1.5">
              <DateText value={l.at} withTime />
              <span className={l.level === "error" ? "text-danger" : l.level === "warning" ? "text-warning" : "text-muted"}>{l.level}</span>
              <span className="break-words">{l.message}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card className="mt-4">
        <CardHeader title={t("jobs.attempts")} />
        <ul className="divide-y divide-border text-[12px]">
          {j.attempts_detail.map((a) => (
            <li key={a.attempt} className="grid grid-cols-[40px_1fr_100px_1fr] gap-3 px-4 py-1.5">
              <span className="num">#{a.attempt}</span><span className="num truncate text-muted">{a.worker}</span><span>{a.outcome ?? "…"}</span>
              <span className="truncate text-danger">{a.error}</span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
