"use client";

import { FileText } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { DateText, PageHeader } from "@/components/app/bits";
import { Badge, Card, EmptyState } from "@/components/ui/misc";
import { useApi } from "@/hooks/use-api";

interface ReportRow { id: string; title: string; status: string; mode: string; language: string; company: { id: string; name: string } | null; updated_at: string; links: { revoked_at: string | null }[] }

export default function ReportsPage() {
  const t = useTranslations();
  const { data } = useApi<ReportRow[]>(["reports"], "/reports");
  return (
    <>
      <PageHeader title={t("reports.title")} description={t("reports.subtitle")} />
      <Card>
        {data && !data.length ? <EmptyState icon={<FileText />} title={t("reports.empty")} description={t("reports.emptyHint")} /> : null}
        <ul className="divide-y divide-border">
          {data?.map((r) => (
            <li key={r.id} className="grid items-center gap-2 px-4 py-2.5 text-[13px] sm:grid-cols-[1fr_200px_100px_100px_120px]">
              <Link href={`/reports/${r.id}`} className="font-medium hover:underline">{r.title}</Link>
              {r.company ? <Link href={`/companies/${r.company.id}`} className="truncate text-muted hover:underline">{r.company.name}</Link> : <span />}
              <Badge tone={r.status === "published" ? "success" : r.status === "revoked" ? "danger" : "neutral"}>{t(`reports.status.${r.status}`)}</Badge>
              <span className="text-[12px] text-muted">{r.mode === "live" ? "Live" : "Snapshot"} · {r.language.toUpperCase()}</span>
              <DateText value={r.updated_at} />
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
