"use client";

import { AlertTriangle, ClipboardCheck, ListChecks, Radar, Trophy } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ClassificationBadge, CountryLabel, PageHeader, ScoreValue } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, EmptyState, Skeleton, Stat } from "@/components/ui/misc";
import { useApi } from "@/hooks/use-api";
import { fmtNumber, relativeTime } from "@/lib/utils";

interface Dashboard {
  metrics: Record<string, number>;
  top_opportunities: { id: string; name: string; score: number; confidence: number | null; country: string | null; classification: string | null }[];
  recent_activity: { company: string; company_id: string; kind: string; title: string | null; occurred_at: string }[];
  warnings: { kind: string; message_key: string; params: Record<string, string | number>; severity: string; link: string | null }[];
}

export default function OverviewPage() {
  const t = useTranslations();
  const locale = useLocale();
  const { data, isLoading } = useApi<Dashboard>(["dashboard"], "/dashboard", { refetchInterval: 30_000 });
  const m = data?.metrics ?? {};
  const n = (k: string) => (isLoading ? <Skeleton className="h-6 w-12" /> : fmtNumber(m[k] ?? 0, locale));
  return (
    <>
      <PageHeader
        title={t("overview.title")}
        description={t("overview.subtitle")}
        actions={
          <>
            <Button asChild size="sm"><Link href="/discovery"><Radar />{t("overview.newDiscovery")}</Link></Button>
            <Button asChild size="sm"><Link href="/review"><ClipboardCheck />{t("nav.review")}</Link></Button>
            <Button asChild size="sm"><Link href="/jobs"><ListChecks />{t("nav.jobs")}</Link></Button>
          </>
        }
      />
      <Card className="mb-4 grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
        <Stat label={t("overview.totalCompanies")} value={n("total_companies")} />
        <Stat label={t("overview.qualifiedLeads")} value={n("qualified_leads")} />
        <Stat label={t("overview.highPriority")} value={n("high_priority")} />
        <Stat label={t("overview.requiresReview")} value={n("requires_review")} />
        <Stat label={t("overview.completedAudits")} value={n("completed_audits")} />
        <Stat label={t("overview.runningJobs")} value={n("running_jobs")} hint={t("overview.queuedJobs", { count: m.queued_jobs ?? 0 })} />
      </Card>
      {data?.warnings.length || m.failed_jobs_24h ? (
        <Card className="mb-4">
          <CardHeader title={t("overview.warnings")} />
          <ul className="divide-y divide-border">
            {m.failed_jobs_24h ? (
              <li className="flex items-center gap-2 px-4 py-2 text-[13px]">
                <AlertTriangle className="size-4 text-danger" />
                <Link href="/jobs?status=failed" className="hover:underline">{t("overview.failedJobs")}: <span className="num">{m.failed_jobs_24h}</span></Link>
              </li>
            ) : null}
            {data?.warnings.map((w, i) => (
              <li key={i} className="flex items-center gap-2 px-4 py-2 text-[13px]">
                <AlertTriangle className={w.severity === "error" ? "size-4 text-danger" : "size-4 text-warning"} />
                {w.link ? <Link href={w.link} className="hover:underline">{t(w.message_key, w.params)}</Link> : t(w.message_key, w.params)}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader title={t("overview.topOpportunities")} actions={<Button asChild size="sm" variant="ghost"><Link href="/companies">{t("nav.companies")}</Link></Button>} />
          {data && !data.top_opportunities.length ? (
            <EmptyState icon={<Trophy />} title={t("overview.noOpportunities")} description={t("overview.noOpportunitiesHint")} />
          ) : (
            <table className="w-full text-[13px]">
              <tbody>
                {data?.top_opportunities.map((c) => (
                  <tr key={c.id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2"><Link href={`/companies/${c.id}`} className="font-medium hover:underline">{c.name}</Link></td>
                    <td className="px-2 py-2"><CountryLabel code={c.country} short /></td>
                    <td className="px-2 py-2"><ClassificationBadge value={c.classification} /></td>
                    <td className="px-4 py-2 text-right"><ScoreValue score={c.score} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card>
          <CardHeader title={t("overview.recentActivity")} />
          {data && !data.recent_activity.length ? <EmptyState title={t("overview.noActivity")} /> : null}
          <ul className="divide-y divide-border">
            {data?.recent_activity.map((a, i) => (
              <li key={i} className="flex items-start justify-between gap-3 px-4 py-2 text-[13px]">
                <div className="min-w-0">
                  <Link href={`/companies/${a.company_id}?tab=activity`} className="font-medium hover:underline">{a.company}</Link>
                  <p className="truncate text-[12px] text-muted">{t.has(`crm.activity.${a.kind}`) ? t(`crm.activity.${a.kind}`) : a.kind}{a.title ? ` · ${a.title}` : ""}</p>
                </div>
                <span className="shrink-0 text-[11px] text-muted">{relativeTime(a.occurred_at, locale)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
