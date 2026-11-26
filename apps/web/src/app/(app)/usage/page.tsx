"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { DateText, PageHeader } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, Card, CardHeader, EmptyState, Stat } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { fmtNumber } from "@/lib/utils";

interface Usage {
  note: string; apify: { spent_24h: number; spent_month: number };
  month_by_provider: { provider: string; estimated_usd: number; confirmed_usd: number; entries: number }[];
  items: { id: string; provider: string; kind: string; description: string | null; reference: string | null; estimated_usd: number | null; actual_usd: number | null; confirmed: boolean; status: string | null; occurred_at: string }[];
}

export default function UsagePage() {
  const t = useTranslations();
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useApi<Usage>(["usage"], "/usage");
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ provider: "infrastructure", description: "", amount: "" });
  const usd = (v: number | null | undefined) => (v === null || v === undefined ? "—" : fmtNumber(v, locale, { style: "currency", currency: "USD", maximumFractionDigits: 4 }));
  const save = async () => {
    try {
      await api("/usage/expenses", { body: { provider: f.provider, description: f.description, amount_usd: f.amount } });
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["usage"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <>
      <PageHeader title={t("usage.title")} description={t("usage.subtitle")} actions={<Button size="sm" onClick={() => setOpen(true)}><Plus />{t("usage.addExpense")}</Button>} />
      <Card className="mb-4 grid grid-cols-2 divide-x divide-border">
        <Stat label={t("usage.apifySpent24h")} value={usd(data?.apify.spent_24h)} />
        <Stat label={t("usage.apifySpentMonth")} value={usd(data?.apify.spent_month)} />
      </Card>
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card className="h-fit">
          <CardHeader title={t("usage.byProvider")} />
          <ul className="divide-y divide-border">
            {data?.month_by_provider.map((p) => (
              <li key={p.provider} className="grid grid-cols-[1fr_auto] gap-1 px-4 py-2 text-[13px]">
                <span>{p.provider}</span><span className="num">{usd(p.confirmed_usd || p.estimated_usd)}</span>
                <span className="text-[11px] text-muted">{t("usage.estimated")} {usd(p.estimated_usd)} · {t("usage.confirmed")} {usd(p.confirmed_usd)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          {!data?.items.length ? <EmptyState title={t("usage.empty")} /> : null}
          <ul className="divide-y divide-border">
            {data?.items.map((u) => (
              <li key={u.id} className="grid items-center gap-2 px-4 py-2 text-[13px] sm:grid-cols-[120px_1fr_120px_120px_100px_32px]">
                <span className="font-medium">{u.provider}</span>
                <span className="truncate text-muted">{u.description}{u.reference ? ` · ${u.reference}` : ""}</span>
                <span className="num text-[12px]">{t("usage.estimated")}: {usd(u.estimated_usd)}</span>
                <span className="num text-[12px]">{u.confirmed ? <Badge tone="success">{usd(u.actual_usd)}</Badge> : "—"}</span>
                <DateText value={u.occurred_at} />
                {u.kind === "manual_expense" ? <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={async () => { await api(`/usage/${u.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["usage"] }); }}><Trash2 /></Button> : <span />}
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <Dialog open={open} onOpenChange={setOpen} title={t("usage.addExpense")}
        footer={<><Button onClick={() => setOpen(false)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!f.description || !f.amount} onClick={save}>{t("common.save")}</Button></>}>
        <div className="grid gap-3">
          <Field label={t("usage.provider")}><Input value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })} /></Field>
          <Field label={t("common.description")}><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <Field label={t("usage.amount")}><Input type="number" min={0} step="0.01" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        </div>
      </Dialog>
    </>
  );
}
