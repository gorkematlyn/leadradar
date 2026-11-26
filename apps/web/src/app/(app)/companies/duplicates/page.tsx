"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { PageHeader } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Badge, Card, EmptyState } from "@/components/ui/misc";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";

interface Side { id: string; name: string; city: string | null; address: string | null; website: string | null; phone: string | null; country: string | null }
interface Dup { id: string; score: number; reasons: string[]; a: Side; b: Side }

function SideView({ s }: { s: Side }) {
  return (
    <div className="min-w-0 text-[13px]">
      <Link href={`/companies/${s.id}`} className="font-medium hover:underline">{s.name}</Link>
      <p className="truncate text-[12px] text-muted">{[s.address, s.city, s.country].filter(Boolean).join(", ") || "—"}</p>
      <p className="num truncate text-[11px] text-muted">{s.website ?? "—"} · {s.phone ?? "—"}</p>
    </div>
  );
}

export default function DuplicatesPage() {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useApi<Dup[]>(["duplicates"], "/companies/duplicates/pending");
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      qc.invalidateQueries({ queryKey: ["duplicates"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <>
      <PageHeader title={t("companies.duplicates")} description={t("companies.duplicatesHint")} />
      <Card>
        {!data?.length ? <EmptyState title={t("common.noResults")} /> : null}
        <ul className="divide-y divide-border">
          {data?.map((d) => (
            <li key={d.id} className="grid gap-3 px-4 py-3 lg:grid-cols-[1fr_1fr_auto] lg:items-center">
              <SideView s={d.a} />
              <SideView s={d.b} />
              <div className="flex flex-wrap items-center gap-2">
                <span className="num text-[12px] text-muted">{Math.round(d.score * 100)}%</span>
                {d.reasons.slice(0, 3).map((r) => <Badge key={r}>{r}</Badge>)}
                <Button size="sm" onClick={() => act(() => api(`/companies/${d.a.id}/merge`, { body: { source_id: d.b.id } }))}>← {t("companies.mergeInto")}</Button>
                <Button size="sm" onClick={() => act(() => api(`/companies/${d.b.id}/merge`, { body: { source_id: d.a.id } }))}>{t("companies.mergeInto")} →</Button>
                <Button size="sm" variant="ghost" onClick={() => act(() => api(`/companies/duplicates/${d.id}/dismiss`, { body: {} }))}>{t("companies.dismiss")}</Button>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
