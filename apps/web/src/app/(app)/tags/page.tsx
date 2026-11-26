"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader, TagChip } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Card, EmptyState } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/overlay";
import { useErrorMessage } from "@/hooks/use-api";
import { useTags } from "@/hooks/use-catalog";
import { api } from "@/lib/api";

const COLORS = ["neutral", "lime", "blue", "amber", "red", "violet", "teal"];
const EXAMPLES = ["High Priority", "Website Redesign", "Tracking Gap", "Active Advertiser", "White-label Opportunity", "E-commerce", "Needs Review", "Follow Up", "Existing Agency", "Potential Retainer"];

export default function TagsPage() {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useTags();
  const [edit, setEdit] = useState<{ id?: string; name: string; description: string; color: string } | null>(null);
  const save = async () => {
    if (!edit) return;
    try {
      const body = { name: edit.name, description: edit.description || null, color: edit.color };
      if (edit.id) await api(`/tags/${edit.id}`, { method: "PATCH", body });
      else await api("/tags", { body });
      setEdit(null);
      qc.invalidateQueries({ queryKey: ["tags"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  const remove = async (id: string) => {
    await api(`/tags/${id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["tags"] });
  };
  return (
    <>
      <PageHeader title={t("tags.title")} description={t("tags.subtitle")} actions={<Button size="sm" variant="primary" onClick={() => setEdit({ name: "", description: "", color: "neutral" })}><Plus />{t("tags.new")}</Button>} />
      <Card>
        {data && !data.length ? (
          <EmptyState title={t("tags.empty")} action={
            <div className="flex max-w-lg flex-wrap justify-center gap-1.5">
              {EXAMPLES.map((n) => <Button key={n} size="sm" variant="ghost" onClick={() => setEdit({ name: n, description: "", color: "neutral" })}>+ {n}</Button>)}
            </div>
          } />
        ) : null}
        <ul className="divide-y divide-border">
          {data?.map((x) => (
            <li key={x.id} className="flex items-center gap-3 px-4 py-2 text-[13px]">
              <button type="button" onClick={() => setEdit({ id: x.id, name: x.name, description: x.description ?? "", color: x.color })}><TagChip name={x.name} color={x.color} /></button>
              <span className="flex-1 truncate text-[12px] text-muted">{x.description}</span>
              <Link href={`/companies?filter=${encodeURIComponent(JSON.stringify({ tags_any: [x.name] }))}`} className="num text-[12px] hover:underline">{x.count} {t("tags.companies").toLowerCase()}</Link>
              <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={() => remove(x.id)}><Trash2 /></Button>
            </li>
          ))}
        </ul>
      </Card>
      <Dialog open={edit !== null} onOpenChange={(v) => !v && setEdit(null)} title={edit?.id ? t("common.edit") : t("tags.new")}
        footer={<><Button onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!edit?.name} onClick={save}>{t("common.save")}</Button></>}>
        {edit ? (
          <div className="grid gap-3">
            <Field label={t("common.name")}><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label={t("common.description")}><Input value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
            <Field label={t("tags.color")}>
              <NativeSelect value={edit.color} onChange={(e) => setEdit({ ...edit, color: e.target.value })}>
                {COLORS.map((c) => <option key={c} value={c}>{t(`tags.colors.${c}`)}</option>)}
              </NativeSelect>
            </Field>
            <TagChip name={edit.name || "…"} color={edit.color} />
          </div>
        ) : null}
      </Dialog>
    </>
  );
}
