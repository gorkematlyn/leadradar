"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { CountryLabel, DateText, PageHeader, ScoreValue } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { Card } from "@/components/ui/misc";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { CRM_STATUSES } from "@/lib/types";

interface Card_ { id: string; name: string; score: number | null; country: string | null; follow_up_at: string | null }

export default function PipelinePage() {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const [view, setView] = useState<"kanban" | "table">("kanban");
  const { data: statuses } = useApi<{ key: string; show_in_pipeline: boolean; count: number }[]>(["crm-statuses"], "/crm/statuses");
  const { data } = useApi<{ columns: Record<string, Card_[]> }>(["pipeline"], "/crm/pipeline");
  const [dragging, setDragging] = useState<string | null>(null);
  const move = async (id: string, status: string) => {
    try {
      await api(`/companies/${id}`, { method: "PATCH", body: { crm_status: status } });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["crm-statuses"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  const cols = Object.keys(data?.columns ?? {});
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
                <span className="font-medium">{t(`crm.status.${col}`)}</span>
                <span className="num text-muted">{statuses?.find((s) => s.key === col)?.count ?? 0}</span>
              </div>
              <div className="grid min-h-24 gap-2 rounded-lg border border-dashed border-border p-2">
                {data?.columns[col].map((c) => (
                  <Card key={c.id} draggable onDragStart={() => setDragging(c.id)} onDragEnd={() => setDragging(null)} className="cursor-grab p-2.5 active:cursor-grabbing">
                    <Link href={`/companies/${c.id}?tab=activity`} className="block truncate text-[13px] font-medium hover:underline">{c.name}</Link>
                    <div className="mt-1 flex items-center justify-between text-[12px]">
                      <CountryLabel code={c.country} short />
                      <ScoreValue score={c.score} />
                    </div>
                    {c.follow_up_at ? <p className="mt-1 text-[11px] text-muted">{t("crm.followUps")}: <DateText value={c.follow_up_at} /></p> : null}
                    <NativeSelect className="mt-2 h-6 text-[11px]" value={col} onChange={(e) => move(c.id, e.target.value)} aria-label={t("crm.moveTo")}>
                      {CRM_STATUSES.filter((s) => s !== "do_not_contact").map((s) => <option key={s} value={s}>{t(`crm.status.${s}`)}</option>)}
                    </NativeSelect>
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Card>
          <table className="w-full text-[13px]">
            <tbody>
              {cols.flatMap((col) => (data?.columns[col] ?? []).map((c) => (
                <tr key={c.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-2"><Link href={`/companies/${c.id}`} className="font-medium hover:underline">{c.name}</Link></td>
                  <td className="px-2 py-2"><CountryLabel code={c.country} short /></td>
                  <td className="px-2 py-2"><ScoreValue score={c.score} /></td>
                  <td className="px-2 py-2"><DateText value={c.follow_up_at} /></td>
                  <td className="px-4 py-2">
                    <NativeSelect className="h-7 w-44" value={col} onChange={(e) => move(c.id, e.target.value)} aria-label={t("crm.moveTo")}>
                      {CRM_STATUSES.filter((s) => s !== "do_not_contact").map((s) => <option key={s} value={s}>{t(`crm.status.${s}`)}</option>)}
                    </NativeSelect>
                  </td>
                </tr>
              )))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
