"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  AnalysisBadge, ClassificationBadge, CountryLabel, DateText, IndustryLabel, KeyValue, ScoreValue, TagChip, WebsiteStatusBadge,
} from "@/components/app/bits";
import type { CompanyDetail } from "@/components/company/types";
import { Button } from "@/components/ui/button";
import { Input, NativeSelect } from "@/components/ui/input";
import { Badge, Skeleton } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useCrmStatusOptions } from "@/hooks/use-catalog";
import { api } from "@/lib/api";

/** Company summary in a dialog, used by the CRM pipeline (status and follow-up are editable). */
export function CompanyQuickView({ id, onOpenChange }: { id: string | null; onOpenChange: (v: boolean) => void }) {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const statusOptions = useCrmStatusOptions();
  const { data: c } = useApi<CompanyDetail>(["company", id], id ? `/companies/${id}` : null);
  const patch = async (body: Record<string, unknown>) => {
    try {
      await api(`/companies/${id}`, { method: "PATCH", body });
      ["company", "pipeline", "pipeline-table", "crm-statuses", "companies"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast.success(t("common.saved"));
    } catch (e) {
      toast.error(err(e));
    }
  };
  const services = [...(c?.service_scores_detail ?? [])].filter((v) => v.score >= 30).sort((a, b) => b.score - a.score);
  return (
    <Dialog open={id !== null} onOpenChange={onOpenChange} wide title={c?.name ?? "…"}
      description={c ? <span className="inline-flex flex-wrap items-center gap-2"><CountryLabel code={c.country} /> · <IndustryLabel industryKey={c.industry} /></span> : undefined}
      footer={<>
        <Button onClick={() => onOpenChange(false)}>{t("common.close")}</Button>
        {c ? <Button variant="primary" asChild><Link href={`/companies/${c.id}`}>{t("crm.openCompany")}</Link></Button> : null}
      </>}>
      {!c ? <Skeleton className="h-48 w-full" /> : (
        <div className="grid gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <ScoreValue score={c.lead_score} size="lg" provisional={c.final_score === null && c.lead_score !== null} />
            <ClassificationBadge value={c.classification} />
            <span className="text-[12px] text-muted">{t("score.confidence")} <span className="num">{c.confidence ?? "—"}</span></span>
            <WebsiteStatusBadge status={c.website_status} />
            <AnalysisBadge status={c.analysis_status} />
            {c.tags.map((x) => <TagChip key={x.id} tag={x} />)}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1 text-[12px] text-muted">{t("companies.col.crmStatus")}
              <NativeSelect value={c.crm_status} disabled={c.do_not_contact} onChange={(e) => patch({ crm_status: e.target.value })}>
                {c.do_not_contact ? <option value="do_not_contact">{t("companies.f.dncOnly")}</option> : null}
                {statusOptions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </NativeSelect>
            </label>
            <label className="grid gap-1 text-[12px] text-muted">{t("company.followUp")}
              <Input type="date" value={c.follow_up_at?.slice(0, 10) ?? ""} onChange={(e) => patch({ follow_up_at: e.target.value ? `${e.target.value}T09:00:00Z` : null })} />
            </label>
          </div>
          {services.length ? (
            <div>
              <p className="mb-1.5 text-[12px] font-medium text-muted">{t("crm.opportunities")}</p>
              <div className="flex flex-wrap gap-1.5">
                {services.map((v) => <Badge key={v.service} tone="solid">{t(`services.${v.service}`)} <span className="num ml-1 text-muted">{v.score}</span></Badge>)}
              </div>
            </div>
          ) : null}
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            <KeyValue label={t("company.website")}>
              {c.website ? <a href={c.website} target="_blank" rel="noopener noreferrer nofollow" className="num inline-flex items-center gap-1 hover:underline">{c.domain ?? c.website}<ExternalLink className="size-3" /></a> : "—"}
            </KeyValue>
            <KeyValue label={t("company.phone")}>{c.phone ?? "—"}</KeyValue>
            <KeyValue label={t("company.email")}>{c.email ?? "—"}</KeyValue>
            <KeyValue label={t("company.address")}>{[c.address, c.postal_code, c.city].filter(Boolean).join(", ") || "—"}</KeyValue>
            <KeyValue label={t("company.discovered")}><DateText value={c.discovered_at} /></KeyValue>
            <KeyValue label={t("companies.col.lastAudit")}><DateText value={c.last_audit_at} /></KeyValue>
          </dl>
          {c.notes ? <p className="line-clamp-4 whitespace-pre-line rounded-md bg-surface-2 px-3 py-2 text-[12px]">{c.notes}</p> : null}
        </div>
      )}
    </Dialog>
  );
}
