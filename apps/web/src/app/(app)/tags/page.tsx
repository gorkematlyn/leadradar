"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader, TagChip } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Card, EmptyState, InfoTip } from "@/components/ui/misc";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { useErrorMessage } from "@/hooks/use-api";
import { useSortByName, useTags } from "@/hooks/use-catalog";
import { api } from "@/lib/api";
import type { Tag } from "@/lib/types";

const COLORS = ["neutral", "lime", "blue", "amber", "red", "violet", "teal"];
const EXAMPLES: [string, string][] = [
  ["High Priority", "Yüksek Öncelik"], ["Website Redesign", "Web Sitesi Yenileme"], ["Tracking Gap", "İzleme Eksiği"],
  ["Active Advertiser", "Aktif Reklamveren"], ["White-label Opportunity", "Beyaz Etiket Fırsatı"], ["E-commerce", "E-ticaret"],
  ["Needs Review", "İnceleme Gerekli"], ["Follow Up", "Takip Edilecek"], ["Existing Agency", "Mevcut Ajans"],
  ["Potential Retainer", "Potansiyel Sürekli Müşteri"],
];

interface EditState { id?: string; name_en: string; name_tr: string; description_en: string; description_tr: string; color: string }
const EMPTY: EditState = { name_en: "", name_tr: "", description_en: "", description_tr: "", color: "neutral" };

export default function TagsPage() {
  const t = useTranslations();
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const sortByName = useSortByName();
  const { data } = useTags();
  const [edit, setEdit] = useState<EditState | null>(null);
  const [remove, setRemove] = useState<Tag | null>(null);
  const valid = !!edit && !!edit.name_en.trim() && !!edit.name_tr.trim();
  const save = async () => {
    if (!edit || !valid) return toast.error(t("tags.bothRequired"));
    try {
      const body = { name_en: edit.name_en, name_tr: edit.name_tr, description_en: edit.description_en || null,
        description_tr: edit.description_tr || null, color: edit.color };
      if (edit.id) await api(`/tags/${edit.id}`, { method: "PATCH", body });
      else await api("/tags", { body });
      setEdit(null);
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["tags"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  const doRemove = async (id: string) => {
    try {
      await api(`/tags/${id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["tags"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  const desc = (x: Tag) => (locale === "tr" ? x.description_tr : x.description_en) ?? "";
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-1.5">{t("tags.title")}<InfoTip>{t("tags.bilingualInfo")}</InfoTip></span>}
        description={t("tags.subtitle")}
        actions={<Button size="sm" variant="primary" onClick={() => setEdit({ ...EMPTY })}><Plus />{t("tags.new")}</Button>} />
      <Card>
        {data && !data.length ? (
          <EmptyState title={t("tags.empty")} action={
            <div className="flex max-w-lg flex-wrap justify-center gap-1.5">
              {EXAMPLES.map(([en, tr]) => (
                <Button key={en} size="sm" variant="ghost" onClick={() => setEdit({ ...EMPTY, name_en: en, name_tr: tr })}>+ {locale === "tr" ? tr : en}</Button>
              ))}
            </div>
          } />
        ) : null}
        <ul className="divide-y divide-border">
          {sortByName(data).map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-[13px]">
              <button type="button" onClick={() => setEdit({ id: x.id, name_en: x.name_en, name_tr: x.name_tr, description_en: x.description_en ?? "",
                description_tr: x.description_tr ?? "", color: x.color })}><TagChip tag={x} /></button>
              <span className="min-w-0 flex-1 truncate text-[12px] text-muted">{desc(x)}</span>
              <Link href={`/companies?filter=${encodeURIComponent(JSON.stringify({ tags_any: [x.id] }))}`} className="num text-[12px] hover:underline">{x.count} {t("tags.companies").toLowerCase()}</Link>
              <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={() => setRemove(x)}><Trash2 /></Button>
            </li>
          ))}
        </ul>
      </Card>
      <Dialog open={edit !== null} onOpenChange={(v) => !v && setEdit(null)} title={edit?.id ? t("common.edit") : t("tags.new")} wide
        footer={<><Button onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!valid} onClick={save}>{t("common.save")}</Button></>}>
        {edit ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={`${t("tags.nameEn")} *`}><Input value={edit.name_en} maxLength={64} onChange={(e) => setEdit({ ...edit, name_en: e.target.value })} /></Field>
            <Field label={`${t("tags.nameTr")} *`}><Input value={edit.name_tr} maxLength={64} onChange={(e) => setEdit({ ...edit, name_tr: e.target.value })} /></Field>
            <Field label={t("tags.descriptionEn")}><Input value={edit.description_en} maxLength={300} onChange={(e) => setEdit({ ...edit, description_en: e.target.value })} /></Field>
            <Field label={t("tags.descriptionTr")}><Input value={edit.description_tr} maxLength={300} onChange={(e) => setEdit({ ...edit, description_tr: e.target.value })} /></Field>
            <Field label={t("tags.color")}>
              <NativeSelect value={edit.color} onChange={(e) => setEdit({ ...edit, color: e.target.value })}>
                {COLORS.map((c) => <option key={c} value={c}>{t(`tags.colors.${c}`)}</option>)}
              </NativeSelect>
            </Field>
            <div className="flex items-end gap-2 pb-1.5">
              <TagChip tag={{ name_en: edit.name_en, name_tr: edit.name_tr, color: edit.color }} />
            </div>
            <p className="text-[12px] text-muted sm:col-span-2">{t("tags.bilingualInfo")}</p>
          </div>
        ) : null}
      </Dialog>
      <ConfirmDialog open={remove !== null} onOpenChange={(v) => !v && setRemove(null)} title={t("common.delete")} danger
        message={remove ? `${locale === "tr" ? remove.name_tr : remove.name_en} — ${t("common.areYouSure")}` : null}
        confirmLabel={t("common.delete")} cancelLabel={t("common.cancel")} onConfirm={() => remove && doRemove(remove.id)} />
    </>
  );
}
