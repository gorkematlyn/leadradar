"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Filter, Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { DateText, PageHeader } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Badge, Card, EmptyState } from "@/components/ui/misc";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { CompanyFilter } from "@/lib/types";

export default function SavedFiltersPage() {
  const t = useTranslations();
  const qc = useQueryClient();
  const { data } = useApi<{ id: string; name: string; description: string | null; filters: CompanyFilter; is_pinned: boolean; updated_at: string }[]>(["saved-filters"], "/saved-filters");
  const remove = async (id: string) => {
    await api(`/saved-filters/${id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["saved-filters"] });
  };
  const summary = (f: CompanyFilter) =>
    Object.entries(f).filter(([, v]) => (Array.isArray(v) ? v.length : v !== null && v !== undefined && v !== "" && v !== "exclude" && v !== "any"))
      .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ");
  return (
    <>
      <PageHeader title={t("savedFilters.title")} description={t("savedFilters.subtitle")} />
      <Card>
        {data && !data.length ? <EmptyState icon={<Filter />} title={t("savedFilters.empty")} description={t("savedFilters.emptyHint")} /> : null}
        <ul className="divide-y divide-border">
          {data?.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-[13px]">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{f.name} {f.is_pinned ? <Badge>{t("savedFilters.pinned")}</Badge> : null}</p>
                <p className="num truncate text-[11px] text-muted">{summary(f.filters) || "—"}</p>
              </div>
              <DateText value={f.updated_at} />
              <Button size="sm" asChild><Link href={`/companies?saved=${f.id}`}>{t("savedFilters.apply")}</Link></Button>
              <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={() => remove(f.id)}><Trash2 /></Button>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
