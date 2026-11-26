"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Play, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { DateText, PageHeader } from "@/components/app/bits";
import { MultiSelect } from "@/components/app/multi-select";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Badge, Card, CardHeader, Checkbox, EmptyState, Switch } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useCountries, useIndustries, useLocalizedName, useRegions } from "@/hooks/use-catalog";
import { api } from "@/lib/api";
import { AD_PLATFORMS } from "@/lib/types";

interface Campaign {
  id: string; name: string; regions: string[]; countries: string[]; industries: string[]; cities: string[];
  discovery_sources: string[]; actions: { import?: boolean; audit?: string; ads?: boolean; ad_platforms?: string[] };
  record_limit: number; schedule_interval_hours: number | null; enabled: boolean; last_run_at: string | null; next_run_at: string | null;
  runs: { id: string; status: string; trigger: string; stats: Record<string, unknown>; created_at: string }[];
}

const empty = { name: "", regions: [] as string[], countries: [] as string[], industries: [] as string[], cities: [] as string[], discovery_sources: ["geofabrik"], actions: { import: false, audit: "", ads: false, ad_platforms: [] as string[] }, record_limit: 50, schedule_interval_hours: "" as string | number, enabled: true };

export default function CampaignsPage() {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const name = useLocalizedName();
  const { data } = useApi<Campaign[]>(["campaigns"], "/campaigns", { refetchInterval: 20_000 });
  const { data: regions } = useRegions();
  const { data: countries } = useCountries();
  const { data: industries } = useIndustries();
  const [edit, setEdit] = useState<(typeof empty & { id?: string }) | null>(null);
  const save = async () => {
    if (!edit) return;
    const body = { ...edit, schedule_interval_hours: edit.schedule_interval_hours === "" ? null : Number(edit.schedule_interval_hours), actions: { ...edit.actions, audit: edit.actions.audit || undefined } };
    try {
      if (edit.id) await api(`/campaigns/${edit.id}`, { method: "PUT", body });
      else await api("/campaigns", { body });
      setEdit(null);
      qc.invalidateQueries({ queryKey: ["campaigns"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  const run = async (id: string) => {
    try {
      await api(`/campaigns/${id}/run`, { body: {} });
      toast.success(t("campaigns.runQueued"));
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <>
      <PageHeader title={t("campaigns.title")} description={t("campaigns.subtitle")} actions={<Button size="sm" variant="primary" onClick={() => setEdit({ ...empty })}><Plus />{t("campaigns.new")}</Button>} />
      {data && !data.length ? <Card><EmptyState title={t("campaigns.empty")} description={t("campaigns.emptyHint")} /></Card> : null}
      <div className="grid gap-3">
        {data?.map((c) => (
          <Card key={c.id}>
            <CardHeader title={c.name} description={`${c.countries.join(", ") || c.regions.join(", ") || "—"} · ${c.industries.length || t("common.all")}`}
              actions={<>
                {!c.enabled ? <Badge>{t("common.disabled")}</Badge> : null}
                <Button size="sm" onClick={() => setEdit({ ...empty, ...c, schedule_interval_hours: c.schedule_interval_hours ?? "", actions: { import: !!c.actions.import, audit: c.actions.audit ?? "", ads: !!c.actions.ads, ad_platforms: c.actions.ad_platforms ?? [] } })}>{t("common.edit")}</Button>
                <Button size="sm" variant="primary" onClick={() => run(c.id)}><Play />{t("campaigns.runNow")}</Button>
                <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={async () => { await api(`/campaigns/${c.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["campaigns"] }); }}><Trash2 /></Button>
              </>} />
            <div className="grid gap-3 px-4 py-3 text-[12px] sm:grid-cols-4">
              <div><p className="text-muted">{t("campaigns.actions")}</p><p>{[c.actions.import && t("campaigns.actionImport"), c.actions.audit && `${t("campaigns.actionAudit")} (${c.actions.audit})`, c.actions.ads && t("campaigns.actionAds")].filter(Boolean).join(" · ") || "—"}</p></div>
              <div><p className="text-muted">{t("campaigns.lastRun")}</p><DateText value={c.last_run_at} withTime /></div>
              <div><p className="text-muted">{t("campaigns.nextRun")}</p><DateText value={c.next_run_at} withTime /></div>
              <div><p className="text-muted">{t("campaigns.history")}</p><p className="num">{c.runs.slice(0, 3).map((r) => `${r.status}`).join(", ") || "—"}</p></div>
            </div>
          </Card>
        ))}
      </div>
      <Dialog open={edit !== null} onOpenChange={(v) => !v && setEdit(null)} title={edit?.id ? t("common.edit") : t("campaigns.new")} wide
        footer={<><Button onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!edit?.name} onClick={save}>{t("common.save")}</Button></>}>
        {edit ? (
          <div className="grid gap-3">
            <Field label={t("common.name")}><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <div className="flex flex-wrap gap-2">
              <MultiSelect label={t("discovery.regions")} value={edit.regions} onChange={(v) => setEdit({ ...edit, regions: v })} options={(regions ?? []).map((r) => ({ value: r.code, label: name(r) }))} />
              <MultiSelect label={t("discovery.countries")} searchable value={edit.countries} onChange={(v) => setEdit({ ...edit, countries: v })} options={(countries ?? []).map((c) => ({ value: c.iso2, label: name(c) }))} />
              <MultiSelect label={t("discovery.industries")} value={edit.industries} onChange={(v) => setEdit({ ...edit, industries: v })} options={(industries ?? []).map((i) => ({ value: i.key, label: name(i) }))} />
            </div>
            <Field label={t("companies.f.cities")}><Input value={edit.cities.join(", ")} onChange={(e) => setEdit({ ...edit, cities: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
            <div className="grid gap-2 rounded-md border border-border p-3">
              <p className="text-[12px] font-medium text-muted">{t("campaigns.actions")}</p>
              <label className="flex items-center gap-2 text-[13px]"><Checkbox label="import" checked={edit.actions.import} onCheckedChange={(v) => setEdit({ ...edit, actions: { ...edit.actions, import: v } })} />{t("campaigns.actionImport")}</label>
              <label className="flex items-center gap-2 text-[13px]">
                <span className="w-40">{t("campaigns.actionAudit")}</span>
                <NativeSelect className="w-48" value={edit.actions.audit} onChange={(e) => setEdit({ ...edit, actions: { ...edit.actions, audit: e.target.value } })}>
                  <option value="">{t("campaigns.auditNone")}</option>
                  <option value="quick">{t("audit.mode.quick")}</option>
                  <option value="full">{t("audit.mode.full")}</option>
                </NativeSelect>
              </label>
              <label className="flex items-center gap-2 text-[13px]"><Checkbox label="ads" checked={edit.actions.ads} onCheckedChange={(v) => setEdit({ ...edit, actions: { ...edit.actions, ads: v } })} />{t("campaigns.actionAds")}</label>
              {edit.actions.ads ? <MultiSelect label={t("companies.f.adPlatforms")} value={edit.actions.ad_platforms} onChange={(v) => setEdit({ ...edit, actions: { ...edit.actions, ad_platforms: v } })} options={AD_PLATFORMS.map((p) => ({ value: p, label: t(`ads.platforms.${p}`) }))} /> : null}
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={t("campaigns.recordLimit")}><Input type="number" min={1} max={500} value={edit.record_limit} onChange={(e) => setEdit({ ...edit, record_limit: Number(e.target.value) })} /></Field>
              <Field label={t("campaigns.schedule")}><Input type="number" min={6} value={edit.schedule_interval_hours} onChange={(e) => setEdit({ ...edit, schedule_interval_hours: e.target.value })} /></Field>
              <label className="flex items-end gap-2 pb-1.5 text-[13px]"><Switch checked={edit.enabled} onCheckedChange={(v) => setEdit({ ...edit, enabled: v })} label={t("common.enabled")} />{t("common.enabled")}</label>
            </div>
          </div>
        ) : null}
      </Dialog>
    </>
  );
}
