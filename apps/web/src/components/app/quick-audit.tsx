"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Dialog } from "@/components/ui/overlay";
import { useAction } from "@/hooks/use-api";
import { useCountries, useIndustries, useLocalizedName } from "@/hooks/use-catalog";
import { api } from "@/lib/api";

export function QuickAuditDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useTranslations();
  const router = useRouter();
  const name = useLocalizedName();
  const { data: countries } = useCountries();
  const { data: industries } = useIndustries();
  const [form, setForm] = useState({ url: "", name: "", country: "", industry: "", mode: "full" });
  const action = useAction(
    () => api<{ company_id: string }>("/companies/quick-audit", {
      body: { url: form.url, name: form.name || null, country: form.country || null, industry: form.industry || null, mode: form.mode },
    }),
    {
      success: t("quickAudit.started"),
      invalidate: [["jobs"]],
    },
  );
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const res = await action.mutateAsync(undefined as never).catch(() => null);
    if (res) {
      onOpenChange(false);
      router.push(`/companies/${res.company_id}?tab=audit`);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("quickAudit.title")}
      description={t("quickAudit.description")}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
          <Button variant="primary" type="submit" form="quick-audit" disabled={!form.url || action.isPending}>{t("quickAudit.start")}</Button>
        </>
      }
    >
      <form id="quick-audit" onSubmit={submit} className="grid gap-3">
        <Field label={t("quickAudit.url")}>
          <Input required autoFocus inputMode="url" placeholder="https://" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
        </Field>
        <Field label={`${t("quickAudit.companyName")} (${t("common.optional")})`}>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("companies.col.country")}>
            <NativeSelect value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}>
              <option value="">—</option>
              {countries?.map((c) => <option key={c.iso2} value={c.iso2}>{name(c)}</option>)}
            </NativeSelect>
          </Field>
          <Field label={t("discovery.industries")}>
            <NativeSelect value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })}>
              <option value="">—</option>
              {industries?.map((i) => <option key={i.key} value={i.key}>{name(i)}</option>)}
            </NativeSelect>
          </Field>
        </div>
        <Field label={t("quickAudit.mode")}>
          <NativeSelect value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
            <option value="full">{t("quickAudit.modeFull")}</option>
            <option value="quick">{t("quickAudit.modeQuick")}</option>
          </NativeSelect>
        </Field>
      </form>
    </Dialog>
  );
}
