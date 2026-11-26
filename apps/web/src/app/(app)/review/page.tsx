"use client";

import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { CountryLabel, DateText, PageHeader, ScoreValue } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Card, EmptyState } from "@/components/ui/misc";
import { useApi } from "@/hooks/use-api";

interface QueueItem { audit_id: string; company_id: string; company: string; website: string | null; country: string | null; preliminary_score: number | null; confidence: number | null; automated_completed_at: string | null; mode: string; error: string | null }

export default function ReviewQueuePage() {
  const t = useTranslations();
  const { data } = useApi<QueueItem[]>(["review-queue"], "/review-queue", { refetchInterval: 20_000 });
  return (
    <>
      <PageHeader title={t("review.title")} description={t("review.subtitle")} />
      <Card>
        {data && !data.length ? <EmptyState icon={<ClipboardCheck />} title={t("review.empty")} description={t("review.emptyHint")} /> : null}
        <ul className="divide-y divide-border">
          {data?.map((i) => (
            <li key={i.audit_id} className="grid items-center gap-2 px-4 py-2.5 text-[13px] sm:grid-cols-[1fr_120px_80px_150px_auto]">
              <div className="min-w-0">
                <Link href={`/companies/${i.company_id}`} className="font-medium hover:underline">{i.company}</Link>
                <p className="num truncate text-[11px] text-muted">{i.website ?? i.error ?? "—"}</p>
              </div>
              <CountryLabel code={i.country} short />
              <ScoreValue score={i.preliminary_score} provisional />
              <span className="text-[12px] text-muted"><DateText value={i.automated_completed_at} withTime /></span>
              <Button size="sm" variant="primary" asChild><Link href={`/review/${i.audit_id}`}>{t("review.reviewAudit")}</Link></Button>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
