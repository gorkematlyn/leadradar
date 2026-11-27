"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/misc";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useCountries, useIndustries, useLocalizedName } from "@/hooks/use-catalog";
import { api } from "@/lib/api";

export function NewCompanyDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useTranslations();
  const router = useRouter();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const name = useLocalizedName();
  const { data: countries } = useCountries();
  const { data: industries } = useIndustries();
  const empty = { name: "", website: "", country: "", industry: "", city: "", address: "", email: "", phone: "", notes: "", quick_audit: false };
  const [f, setF] = useState(empty);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v === "" ? null : v]));
      const res = await api<{ id: string; action: string }>("/companies", { body });
      toast.success(res.action === "matched" ? t("companies.new.duplicate") : t("companies.new.created"));
      qc.invalidateQueries({ queryKey: ["companies"] });
      onOpenChange(false);
      setF(empty);
      router.push(`/companies/${res.id}`);
    } catch (e2) {
      toast.error(err(e2));
    } finally {
      setBusy(false);
    }
  };
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("companies.new.title")} wide
      footer={<><Button onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button><Button variant="primary" type="submit" form="new-company" disabled={busy || !f.name}>{t("common.create")}</Button></>}>
      <form id="new-company" onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <Field label={t("common.name")} className="sm:col-span-2"><Input required autoFocus value={f.name} onChange={set("name")} /></Field>
        <Field label={t("company.website")}><Input inputMode="url" placeholder="https://" value={f.website} onChange={set("website")} /></Field>
        <Field label={t("companies.col.country")}>
          <NativeSelect value={f.country} onChange={set("country")}>
            <option value="">—</option>
            {countries?.map((c) => <option key={c.iso2} value={c.iso2}>{name(c)}</option>)}
          </NativeSelect>
        </Field>
        <Field label={t("companies.col.industry")}>
          <NativeSelect value={f.industry} onChange={set("industry")}>
            <option value="">—</option>
            {industries?.map((i) => <option key={i.key} value={i.key}>{name(i)}</option>)}
          </NativeSelect>
        </Field>
        <Field label={t("company.city")}><Input value={f.city} onChange={set("city")} /></Field>
        <Field label={t("company.address")} className="sm:col-span-2"><Input value={f.address} onChange={set("address")} /></Field>
        <Field label={t("company.email")}><Input type="email" value={f.email} onChange={set("email")} /></Field>
        <Field label={t("company.phone")}><Input value={f.phone} onChange={set("phone")} /></Field>
        <Field label={t("company.internalNotes")} className="sm:col-span-2"><Textarea value={f.notes} onChange={set("notes")} /></Field>
        <label className="flex items-center gap-2 text-[13px] sm:col-span-2">
          <Checkbox label={t("companies.new.fromUrl")} checked={f.quick_audit} onCheckedChange={(v) => setF({ ...f, quick_audit: v })} />
          {t("companies.new.fromUrl")}
        </label>
      </form>
    </Dialog>
  );
}

const CSV_FIELDS = ["name", "website", "email", "phone", "address", "city", "region", "postal_code", "country", "industry",
  "latitude", "longitude", "legal_name", "facebook", "instagram", "linkedin"] as const;

export function CsvImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useTranslations();
  const router = useRouter();
  const err = useErrorMessage();
  const name = useLocalizedName();
  const { data: countries } = useCountries();
  const { data: industries } = useIndustries();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<{ delimiter: string; columns: string[]; sample: string[][] } | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [defaults, setDefaults] = useState({ country: "", industry: "" });

  const onFile = async (f: File | null) => {
    setFile(f);
    setPreview(null);
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    try {
      const p = await api<{ delimiter: string; columns: string[]; sample: string[][] }>("/companies/import/preview", { form });
      setPreview(p);
      const guess: Record<string, string> = {};
      for (const field of CSV_FIELDS) {
        const col = p.columns.find((c) => c.trim().toLowerCase().replace(/[\s-]+/g, "_") === field || c.toLowerCase() === field);
        if (col) guess[field] = col;
      }
      setMapping(guess);
    } catch (e) {
      toast.error(err(e));
    }
  };

  const start = async () => {
    if (!file || !preview) return;
    if (!mapping.name) {
      toast.error(t("companies.csv.nameRequired"));
      return;
    }
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api<{ job_id: string }>("/companies/import", {
        form,
        query: { mapping: JSON.stringify(mapping), delimiter: preview.delimiter, default_country: defaults.country || undefined, default_industry: defaults.industry || undefined },
      });
      toast.success(t("companies.csv.queued"));
      onOpenChange(false);
      router.push(`/jobs/${res.job_id}`);
    } catch (e) {
      toast.error(err(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("companies.csv.title")} description={t("companies.csv.step1")} wide
      footer={<><Button onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!preview} onClick={start}>{t("companies.csv.start")}</Button></>}>
      <div className="grid gap-4">
        <Input type="file" accept=".csv,text/csv" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        {preview ? (
          <>
            <div>
              <h4 className="mb-2 text-[13px] font-semibold">{t("companies.csv.mapping")}</h4>
              <div className="grid gap-2 sm:grid-cols-2">
                {CSV_FIELDS.map((field) => (
                  <label key={field} className="grid grid-cols-[110px_1fr] items-center gap-2 text-[13px]">
                    <span className="num text-[12px] text-muted">{field}{field === "name" ? " *" : ""}</span>
                    <NativeSelect value={mapping[field] ?? ""} onChange={(e) => setMapping((m) => {
                      const next = { ...m };
                      if (e.target.value) next[field] = e.target.value;
                      else delete next[field];
                      return next;
                    })}>
                      <option value="">{t("companies.csv.ignore")}</option>
                      {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                    </NativeSelect>
                  </label>
                ))}
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("companies.csv.defaultCountry")}>
                <NativeSelect value={defaults.country} onChange={(e) => setDefaults({ ...defaults, country: e.target.value })}>
                  <option value="">—</option>
                  {countries?.map((c) => <option key={c.iso2} value={c.iso2}>{name(c)}</option>)}
                </NativeSelect>
              </Field>
              <Field label={t("companies.csv.defaultIndustry")}>
                <NativeSelect value={defaults.industry} onChange={(e) => setDefaults({ ...defaults, industry: e.target.value })}>
                  <option value="">—</option>
                  {industries?.map((i) => <option key={i.key} value={i.key}>{name(i)}</option>)}
                </NativeSelect>
              </Field>
            </div>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-[12px]">
                <thead><tr className="border-b border-border text-muted">{preview.columns.map((c) => <th key={c} className="px-2 py-1 text-left font-medium">{c}</th>)}</tr></thead>
                <tbody>{preview.sample.map((r, i) => <tr key={i} className="border-b border-border last:border-0">{r.map((v, j) => <td key={j} className="max-w-40 truncate px-2 py-1">{v}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </>
        ) : null}
      </div>
    </Dialog>
  );
}

interface TrashItem { id: string; name: string; country: string | null; city: string | null; domain: string | null; deleted_at: string; purge_at: string; days_left: number }

/** Trash: companies deleted in the last 30 days. Restore them or delete them permanently. */
export function TrashDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useApi<{ days: number; items: TrashItem[] }>(["companies-trash"], open ? "/companies/trash/items" : null);
  const [confirm, setConfirm] = useState<{ ids: string[] | null; label: string } | null>(null);
  const refresh = () => ["companies-trash", "companies", "company-facets", "dashboard", "pipeline", "pipeline-table", "crm-statuses"]
    .forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const restore = async (ids: string[]) => {
    try {
      const r = await api<{ restored: number }>("/companies/trash/restore", { body: { ids } });
      toast.success(t("companies.trash.restored", { count: r.restored }));
      refresh();
    } catch (e) {
      toast.error(err(e));
    }
  };
  const purge = async (ids: string[] | null) => {
    try {
      const r = await api<{ deleted: number }>("/companies/trash/purge", { body: { ids } });
      toast.success(t("companies.trash.purged", { count: r.deleted }));
      refresh();
    } catch (e) {
      toast.error(err(e));
    }
  };
  const items = data?.items ?? [];
  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange} wide title={t("companies.trash.title")} description={t("companies.trash.hint", { days: data?.days ?? 30 })}
        footer={<>
          {items.length ? <Button variant="danger" className="mr-auto" onClick={() => setConfirm({ ids: null, label: t("companies.trash.empty") })}>{t("companies.trash.empty")}</Button> : null}
          {items.length ? <Button onClick={() => restore(items.map((i) => i.id))}>{t("companies.trash.restoreAll")}</Button> : null}
          <Button variant="primary" onClick={() => onOpenChange(false)}>{t("common.close")}</Button>
        </>}>
        {!items.length ? <p className="py-6 text-center text-[13px] text-muted">{t("companies.trash.isEmpty")}</p> : (
          <ul className="divide-y divide-border">
            {items.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{i.name}</span>
                  <span className="block text-[11px] text-muted">{[i.country, i.city, i.domain].filter(Boolean).join(" · ")}</span>
                </span>
                <span className="num text-[11px] text-muted">{t("companies.trash.daysLeft", { days: i.days_left })}</span>
                <Button size="sm" variant="ghost" onClick={() => restore([i.id])}>{t("companies.trash.restore")}</Button>
                <Button size="sm" variant="ghost" className="text-danger" onClick={() => setConfirm({ ids: [i.id], label: i.name })}>{t("companies.trash.deleteForever")}</Button>
              </li>
            ))}
          </ul>
        )}
      </Dialog>
      <ConfirmDialog open={confirm !== null} onOpenChange={(v) => !v && setConfirm(null)} danger title={t("companies.trash.deleteForever")}
        message={confirm ? t("companies.trash.purgeConfirm", { name: confirm.label, count: confirm.ids?.length ?? items.length }) : null}
        confirmLabel={t("companies.trash.deleteForever")} cancelLabel={t("common.cancel")} onConfirm={() => confirm && purge(confirm.ids)} />
    </>
  );
}
