"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Copy, Play, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/app/bits";
import { MultiSelect } from "@/components/app/multi-select";
import { SettingsForm } from "@/components/app/settings-form";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge, Card, CardHeader, Switch } from "@/components/ui/misc";
import { Dialog, Tabs } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useIndustries, useLocalizedName } from "@/hooks/use-catalog";
import { api } from "@/lib/api";
import { SERVICES, type Industry } from "@/lib/types";

const FEATURES = ["booking", "reservation", "contact_form", "tel_link", "whatsapp", "quote_form", "ecommerce", "checkout"];

function IndustriesTab() {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const name = useLocalizedName();
  const locale = useLocale();
  const { data } = useIndustries();
  const { data: profiles } = useApi<{ id: string; name_en: string; name_tr: string }[]>(["scoring-profiles"], "/scoring/profiles");
  const { data: templates } = useApi<{ id: string; name_en: string }[]>(["review-templates"], "/review-templates");
  const [edit, setEdit] = useState<Partial<Industry> | null>(null);
  const [rule, setRule] = useState<{ industryId: string; id?: string; key: string; description: string; conditions: string; classification: string; enabled: boolean } | null>(null);
  const [test, setTest] = useState("name=Smile Dental\namenity=dentist");
  const [matches, setMatches] = useState<{ industry_key: string; rule_key: string; classification: string }[] | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["industries"] });
  const save = async () => {
    if (!edit) return;
    const body = { ...edit } as Record<string, unknown>;
    delete body.rules;
    delete body.id;
    try {
      if (edit.id) await api(`/industries/${edit.id}`, { method: "PATCH", body: { ...body, key: undefined } });
      else await api("/industries", { body });
      setEdit(null);
      refresh();
    } catch (e) {
      toast.error(err(e));
    }
  };
  const saveRule = async () => {
    if (!rule) return;
    let conditions: unknown;
    try { conditions = JSON.parse(rule.conditions); } catch { return toast.error(t("errors.validation_error")); }
    const body = { key: rule.key, description: rule.description, conditions, classification: rule.classification, enabled: rule.enabled };
    try {
      if (rule.id) await api(`/industries/${rule.industryId}/rules/${rule.id}`, { method: "PATCH", body });
      else await api(`/industries/${rule.industryId}/rules`, { body });
      setRule(null);
      refresh();
    } catch (e) {
      toast.error(err(e));
    }
  };
  const runTest = async () => {
    const tags = Object.fromEntries(test.split("\n").map((l) => l.split("=")).filter((p) => p.length >= 2).map(([k, ...v]) => [k.trim(), v.join("=").trim()]));
    setMatches(await api("/industries/test-match", { body: { tags } }));
  };
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
      <div className="grid content-start gap-3">
        <div><Button size="sm" variant="primary" onClick={() => setEdit({ key: "", name_en: "", name_tr: "", enabled: true, priority: 5, relevant_services: [], relevant_features: [] })}><Plus />{t("dataSources.addIndustry")}</Button></div>
        {data?.map((i) => (
          <Card key={i.id}>
            <CardHeader title={<span className="flex items-center gap-2">{name(i)} <span className="num text-[11px] font-normal text-muted">{i.key}</span>{i.is_priority ? <Badge>{t("discovery.priority")}</Badge> : null}</span>}
              description={locale === "tr" ? i.description_tr : i.description_en}
              actions={<>
                <Switch checked={i.enabled} label={t("common.enabled")} onCheckedChange={async (v) => { await api(`/industries/${i.id}`, { method: "PATCH", body: { enabled: v } }); refresh(); }} />
                <Button size="sm" onClick={() => setEdit(i)}>{t("common.edit")}</Button>
                <Button size="sm" onClick={() => setRule({ industryId: i.id, key: "", description: "", conditions: '{\n  "all": [{"key": "name", "op": "exists"}, {"key": "shop", "op": "eq", "value": "beauty"}]\n}', classification: "confident", enabled: true })}><Plus />{t("dataSources.addRule")}</Button>
              </>} />
            <ul className="divide-y divide-border">
              {i.rules.map((r) => (
                <li key={r.id} className="flex items-center gap-3 px-4 py-2 text-[12px]">
                  <span className="num w-48 shrink-0 truncate">{r.key}</span>
                  <code className="num flex-1 truncate text-muted">{JSON.stringify(r.conditions)}</code>
                  <Badge tone={r.classification === "confident" ? "solid" : "warning"}>{r.classification === "confident" ? t("dataSources.confident") : t("dataSources.reviewCandidate")}</Badge>
                  {!r.enabled ? <Badge>{t("common.disabled")}</Badge> : null}
                  <Button size="sm" variant="ghost" onClick={() => setRule({ industryId: i.id, id: r.id, key: r.key, description: r.description, conditions: JSON.stringify(r.conditions, null, 2), classification: r.classification, enabled: r.enabled })}>{t("common.edit")}</Button>
                  <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={async () => { await api(`/industries/${i.id}/rules/${r.id}`, { method: "DELETE" }); refresh(); }}><Trash2 /></Button>
                </li>
              ))}
              {!i.rules.length ? <li className="px-4 py-2 text-[12px] text-muted">—</li> : null}
            </ul>
          </Card>
        ))}
      </div>
      <Card className="h-fit">
        <CardHeader title={t("dataSources.testMatch")} />
        <div className="grid gap-2 p-4">
          <Field label={t("dataSources.testTags")}><Textarea className="num" rows={5} value={test} onChange={(e) => setTest(e.target.value)} /></Field>
          <Button size="sm" onClick={runTest}>{t("dataSources.testMatch")}</Button>
          {matches ? (
            <ul className="grid gap-1 text-[12px]">
              {matches.length ? matches.map((m) => <li key={m.industry_key} className="flex justify-between"><span>{m.industry_key}</span><Badge>{m.classification}</Badge></li>) : <li className="text-muted">{t("common.noResults")}</li>}
            </ul>
          ) : null}
        </div>
      </Card>
      <Dialog open={edit !== null} onOpenChange={(v) => !v && setEdit(null)} title={edit?.id ? t("common.edit") : t("dataSources.addIndustry")} wide
        footer={<><Button onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={save}>{t("common.save")}</Button></>}>
        {edit ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {!edit.id ? <Field label={t("dataSources.key")}><Input className="num" value={edit.key ?? ""} onChange={(e) => setEdit({ ...edit, key: e.target.value })} /></Field> : null}
            <Field label={t("dataSources.priority")}><Input type="number" min={0} max={100} value={edit.priority ?? 0} onChange={(e) => setEdit({ ...edit, priority: Number(e.target.value) })} /></Field>
            <Field label={t("dataSources.nameEn")}><Input value={edit.name_en ?? ""} onChange={(e) => setEdit({ ...edit, name_en: e.target.value })} /></Field>
            <Field label={t("dataSources.nameTr")}><Input value={edit.name_tr ?? ""} onChange={(e) => setEdit({ ...edit, name_tr: e.target.value })} /></Field>
            <Field label={t("dataSources.descriptionEn")}><Textarea value={edit.description_en ?? ""} onChange={(e) => setEdit({ ...edit, description_en: e.target.value })} /></Field>
            <Field label={t("dataSources.descriptionTr")}><Textarea value={edit.description_tr ?? ""} onChange={(e) => setEdit({ ...edit, description_tr: e.target.value })} /></Field>
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              <MultiSelect label={t("dataSources.relevantServices")} value={edit.relevant_services ?? []} onChange={(v) => setEdit({ ...edit, relevant_services: v })} options={SERVICES.map((s) => ({ value: s, label: t(`services.${s}`) }))} />
              <MultiSelect label={t("dataSources.relevantFeatures")} value={edit.relevant_features ?? []} onChange={(v) => setEdit({ ...edit, relevant_features: v })} options={FEATURES.map((s) => ({ value: s, label: s }))} />
            </div>
            <Field label={t("dataSources.scoringProfile")}>
              <NativeSelect value={edit.scoring_profile_id ?? ""} onChange={(e) => setEdit({ ...edit, scoring_profile_id: e.target.value || null })}>
                <option value="">—</option>
                {profiles?.map((p) => <option key={p.id} value={p.id}>{p.name_en}</option>)}
              </NativeSelect>
            </Field>
            <Field label={t("dataSources.reviewTemplate")}>
              <NativeSelect value={edit.review_template_id ?? ""} onChange={(e) => setEdit({ ...edit, review_template_id: e.target.value || null })}>
                <option value="">—</option>
                {templates?.map((p) => <option key={p.id} value={p.id}>{p.name_en}</option>)}
              </NativeSelect>
            </Field>
            <label className="flex items-center gap-2 text-[13px]"><Switch checked={!!edit.is_priority} onCheckedChange={(v) => setEdit({ ...edit, is_priority: v })} label={t("dataSources.isPriority")} />{t("dataSources.isPriority")}</label>
          </div>
        ) : null}
      </Dialog>
      <Dialog open={rule !== null} onOpenChange={(v) => !v && setRule(null)} title={t("dataSources.osmRules")} wide
        footer={<><Button onClick={() => setRule(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={saveRule}>{t("common.save")}</Button></>}>
        {rule ? (
          <div className="grid gap-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("dataSources.key")}><Input className="num" value={rule.key} disabled={!!rule.id} onChange={(e) => setRule({ ...rule, key: e.target.value })} /></Field>
              <Field label={t("dataSources.classification")}>
                <NativeSelect value={rule.classification} onChange={(e) => setRule({ ...rule, classification: e.target.value })}>
                  <option value="confident">{t("dataSources.confident")}</option>
                  <option value="review">{t("dataSources.reviewCandidate")}</option>
                </NativeSelect>
              </Field>
            </div>
            <Field label={t("common.description")}><Input value={rule.description} onChange={(e) => setRule({ ...rule, description: e.target.value })} /></Field>
            <Field label={t("dataSources.conditions")} hint='ops: eq, in, exists, regex · groups: all, any, exclude'><Textarea className="num" rows={8} value={rule.conditions} onChange={(e) => setRule({ ...rule, conditions: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-[13px]"><Switch checked={rule.enabled} onCheckedChange={(v) => setRule({ ...rule, enabled: v })} label={t("common.enabled")} />{t("common.enabled")}</label>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}

interface Provider { key: string; name: string; enabled: boolean; automation_status: string; automation_supported: boolean; credentials_configured: boolean; note_en: string; note_tr: string; official_source_url: string | null; config: Record<string, string>; rate_limit_per_minute: number; recheck_days: number }

function ProvidersTab() {
  const t = useTranslations();
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useApi<Provider[]>(["ad-providers"], "/ad-providers");
  const [token, setToken] = useState<Record<string, string>>({});
  const patch = async (key: string, body: Record<string, unknown>) => {
    try {
      await api(`/ad-providers/${key}`, { method: "PATCH", body });
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["ad-providers"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <div className="grid gap-3">
      {data?.map((p) => (
        <Card key={p.key}>
          <CardHeader title={p.name} description={locale === "tr" ? p.note_tr : p.note_en} actions={<>
            <Badge tone={p.automation_status === "automated" ? "success" : p.automation_status === "unsupported" ? "neutral" : "solid"}>{t(`ads.automation.${p.automation_status}`)}</Badge>
            <Switch checked={p.enabled} label={t("common.enabled")} onCheckedChange={(v) => patch(p.key, { enabled: v })} />
          </>} />
          <div className="grid gap-3 px-4 py-3 sm:grid-cols-4">
            {p.official_source_url ? <a href={p.official_source_url} target="_blank" rel="noopener noreferrer nofollow" className="text-[12px] text-muted hover:underline sm:col-span-4">{p.official_source_url}</a> : null}
            <Field label={t("dataSources.rateLimit")}><Input type="number" defaultValue={p.rate_limit_per_minute} onBlur={(e) => Number(e.target.value) !== p.rate_limit_per_minute && patch(p.key, { rate_limit_per_minute: Number(e.target.value) })} /></Field>
            <Field label={t("dataSources.recheckDays")}><Input type="number" defaultValue={p.recheck_days} onBlur={(e) => Number(e.target.value) !== p.recheck_days && patch(p.key, { recheck_days: Number(e.target.value) })} /></Field>
            {p.automation_supported ? (
              <>
                <Field label={t("dataSources.apiVersion")}><Input className="num" defaultValue={p.config.api_version ?? "v23.0"} onBlur={(e) => patch(p.key, { config: { ...p.config, api_version: e.target.value } })} /></Field>
                <Field label={t("dataSources.accessToken")} hint={p.credentials_configured ? t("dataSources.apifyTokenSet") : undefined}>
                  <div className="flex gap-2">
                    <Input type="password" autoComplete="off" value={token[p.key] ?? ""} onChange={(e) => setToken({ ...token, [p.key]: e.target.value })} />
                    <Button size="sm" onClick={() => patch(p.key, { credentials: { access_token: token[p.key] ?? "" } })}>{t("common.save")}</Button>
                  </div>
                </Field>
              </>
            ) : null}
          </div>
        </Card>
      ))}
    </div>
  );
}

interface Actor { id: string; name: string; actor_id: string; purpose: string; input_template: Record<string, unknown>; allowed_input_keys: string[]; field_mapping: Record<string, string>; max_items: number; max_cost_usd: number; enabled: boolean }

function ApifyTab() {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useApi<Actor[]>(["apify-actors"], "/apify/actors");
  const [edit, setEdit] = useState<(Omit<Actor, "input_template" | "field_mapping" | "allowed_input_keys"> & { input_template: string; field_mapping: string; allowed_input_keys: string }) | null>(null);
  const save = async () => {
    if (!edit) return;
    try {
      const body = { ...edit, input_template: JSON.parse(edit.input_template || "{}"), field_mapping: JSON.parse(edit.field_mapping || "{}"), allowed_input_keys: edit.allowed_input_keys.split(",").map((s) => s.trim()).filter(Boolean) };
      if (edit.id) await api(`/apify/actors/${edit.id}`, { method: "PUT", body });
      else await api("/apify/actors", { body });
      setEdit(null);
      qc.invalidateQueries({ queryKey: ["apify-actors"] });
    } catch (e) {
      toast.error(e instanceof SyntaxError ? t("errors.validation_error") : err(e));
    }
  };
  const run = async (id: string) => {
    try {
      await api(`/apify/actors/${id}/run`, { body: {} });
      toast.success(t("campaigns.runQueued"));
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader title={t("dataSources.apify")} description={t("dataSources.apifyHint")} />
        <div className="p-4">
          <SettingsForm keys={["apify.enabled", "apify.token", "apify.daily_budget_usd", "apify.monthly_budget_usd", "apify.max_cost_per_task_usd", "apify.alert_percent"]}
            labels={{ "apify.token": t("dataSources.apifyToken") }} />
        </div>
      </Card>
      <Card>
        <CardHeader title={t("dataSources.actors")} actions={<Button size="sm" onClick={() => setEdit({ id: "", name: "", actor_id: "", purpose: "discovery", input_template: "{}", field_mapping: '{"name": "title", "website": "website", "phone": "phone"}', allowed_input_keys: "", max_items: 100, max_cost_usd: 1, enabled: false })}><Plus />{t("dataSources.addActor")}</Button>} />
        <ul className="divide-y divide-border">
          {data?.map((a) => (
            <li key={a.id} className="flex items-center gap-3 px-4 py-2 text-[13px]">
              <span className="font-medium">{a.name}</span><span className="num text-[12px] text-muted">{a.actor_id}</span>
              <Badge>{a.purpose}</Badge>{!a.enabled ? <Badge>{t("common.disabled")}</Badge> : null}
              <span className="ml-auto flex gap-2">
                <Button size="sm" onClick={() => setEdit({ ...a, input_template: JSON.stringify(a.input_template, null, 2), field_mapping: JSON.stringify(a.field_mapping, null, 2), allowed_input_keys: a.allowed_input_keys.join(", ") })}>{t("common.edit")}</Button>
                <Button size="sm" disabled={!a.enabled} onClick={() => run(a.id)}><Play />{t("dataSources.run")}</Button>
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Dialog open={edit !== null} onOpenChange={(v) => !v && setEdit(null)} title={t("dataSources.addActor")} wide
        footer={<><Button onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={save}>{t("common.save")}</Button></>}>
        {edit ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("common.name")}><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label={t("dataSources.actorId")}><Input className="num" value={edit.actor_id} onChange={(e) => setEdit({ ...edit, actor_id: e.target.value })} /></Field>
            <Field label={t("dataSources.purpose")}>
              <NativeSelect value={edit.purpose} onChange={(e) => setEdit({ ...edit, purpose: e.target.value })}><option value="discovery">discovery</option><option value="advertising">advertising</option></NativeSelect>
            </Field>
            <Field label={t("dataSources.maxItems")}><Input type="number" value={edit.max_items} onChange={(e) => setEdit({ ...edit, max_items: Number(e.target.value) })} /></Field>
            <Field label={t("dataSources.maxCost")}><Input type="number" step="0.1" value={edit.max_cost_usd} onChange={(e) => setEdit({ ...edit, max_cost_usd: Number(e.target.value) })} /></Field>
            <Field label={t("dataSources.allowedKeys")}><Input className="num" value={edit.allowed_input_keys} onChange={(e) => setEdit({ ...edit, allowed_input_keys: e.target.value })} /></Field>
            <Field label={t("dataSources.inputTemplate")}><Textarea className="num" rows={6} value={edit.input_template} onChange={(e) => setEdit({ ...edit, input_template: e.target.value })} /></Field>
            <Field label={t("dataSources.fieldMapping")}><Textarea className="num" rows={6} value={edit.field_mapping} onChange={(e) => setEdit({ ...edit, field_mapping: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-[13px]"><Switch checked={edit.enabled} onCheckedChange={(v) => setEdit({ ...edit, enabled: v })} label={t("common.enabled")} />{t("common.enabled")}</label>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}

export default function DataSourcesPage() {
  const t = useTranslations();
  const [tab, setTab] = useState("industries");
  return (
    <>
      <PageHeader title={t("dataSources.title")} description={t("dataSources.subtitle")} actions={<Button size="sm" asChild><Link href="/companies/duplicates"><Copy />{t("dataSources.duplicates")}</Link></Button>} />
      <Tabs value={tab} onValueChange={setTab} tabs={[
        { value: "industries", label: t("dataSources.industries") },
        { value: "providers", label: t("dataSources.adProviders") },
        { value: "apify", label: t("dataSources.apify") },
      ]} />
      <div className="mt-4">
        {tab === "industries" ? <IndustriesTab /> : null}
        {tab === "providers" ? <ProvidersTab /> : null}
        {tab === "apify" ? <ApifyTab /> : null}
      </div>
    </>
  );
}
