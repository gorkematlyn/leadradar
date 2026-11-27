"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, Pencil, Play, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/app/bits";
import { MultiSelect } from "@/components/app/multi-select";
import { SettingsForm } from "@/components/app/settings-form";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge, Callout, Card, CardHeader, InfoTip, Switch, Tooltip } from "@/components/ui/misc";
import { ConfirmDialog, Dialog, Tabs } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useIndustries, useLocalizedName, useSortByName } from "@/hooks/use-catalog";
import { api } from "@/lib/api";
import { SERVICES, type Industry } from "@/lib/types";

const FEATURES = ["booking", "reservation", "contact_form", "tel_link", "whatsapp", "quote_form", "ecommerce", "checkout"];

function IndustriesTab() {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const name = useLocalizedName();
  const sortByName = useSortByName();
  const locale = useLocale();
  const { data } = useIndustries();
  const { data: profiles } = useApi<{ id: string; name_en: string; name_tr: string }[]>(["scoring-profiles"], "/scoring/profiles");
  const { data: templates } = useApi<{ id: string; name_en: string }[]>(["review-templates"], "/review-templates");
  const [edit, setEdit] = useState<Partial<Industry> | null>(null);
  const [rule, setRule] = useState<{ industryId: string; id?: string; key: string; description: string; conditions: string; classification: string; enabled: boolean } | null>(null);
  const [test, setTest] = useState("name=Smile Dental\namenity=dentist");
  const [matches, setMatches] = useState<{ industry_key: string; rule_key: string; classification: string }[] | null>(null);
  const [deleteRule, setDeleteRule] = useState<{ industryId: string; id: string; key: string } | null>(null);
  const removeRule = async (industryId: string, id: string) => {
    try {
      await api(`/industries/${industryId}/rules/${id}`, { method: "DELETE" });
      refresh();
    } catch (e) {
      toast.error(err(e));
    }
  };
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
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="grid min-w-0 content-start gap-3">
        <Callout>
          <p>{t("dataSources.industriesHelp")}</p>
          <p className="mt-1">{t("dataSources.rulesOptional")}</p>
        </Callout>
        <div><Button size="sm" variant="primary" onClick={() => setEdit({ key: "", name_en: "", name_tr: "", enabled: true, priority: 5, relevant_services: [], relevant_features: [] })}><Plus />{t("dataSources.addIndustry")}</Button></div>
        {sortByName(data).map((i) => (
          <Card key={i.id} className="min-w-0">
            <CardHeader title={<span className="flex flex-wrap items-center gap-2">{name(i)} <span className="num text-[11px] font-normal text-muted">{i.key}</span>{i.is_priority ? <Badge>{t("discovery.priority")}</Badge> : null}
              {!i.rules.length ? <Tooltip content={t("dataSources.manualInfo")}><span><Badge tone="warning">{t("dataSources.manualBadge")}</Badge></span></Tooltip> : null}</span>}
              description={locale === "tr" ? i.description_tr : i.description_en}
              actions={<>
                <Switch checked={i.enabled} label={t("common.enabled")} onCheckedChange={async (v) => { await api(`/industries/${i.id}`, { method: "PATCH", body: { enabled: v } }); refresh(); }} />
                <Button size="sm" onClick={() => setEdit(i)}>{t("common.edit")}</Button>
                <Button size="sm" onClick={() => setRule({ industryId: i.id, key: "", description: "", conditions: '{\n  "all": [{"key": "name", "op": "exists"}, {"key": "shop", "op": "eq", "value": "beauty"}]\n}', classification: "confident", enabled: true })}><Plus />{t("dataSources.addRule")}</Button>
              </>} />
            <p className="flex items-center gap-1 border-b border-border px-4 py-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">
              {t("dataSources.rulesTitle")}<InfoTip>{t("dataSources.rulesInfo")}</InfoTip>
            </p>
            <ul className="divide-y divide-border">
              {i.rules.map((r) => (
                <li key={r.id} className="grid gap-1.5 px-4 py-2 text-[12px] md:grid-cols-[minmax(8rem,12rem)_minmax(0,1fr)_auto] md:items-start md:gap-3">
                  <span className="num break-all font-medium">{r.key}</span>
                  <code className="num min-w-0 whitespace-pre-wrap break-all text-muted">{JSON.stringify(r.conditions)}</code>
                  <span className="flex flex-wrap items-center gap-1 md:justify-end">
                    <Badge tone={r.classification === "confident" ? "solid" : "warning"}>{r.classification === "confident" ? t("dataSources.confident") : t("dataSources.reviewCandidate")}</Badge>
                    {!r.enabled ? <Badge>{t("common.disabled")}</Badge> : null}
                    <Button size="sm" variant="ghost" onClick={() => setRule({ industryId: i.id, id: r.id, key: r.key, description: r.description, conditions: JSON.stringify(r.conditions, null, 2), classification: r.classification, enabled: r.enabled })}>{t("common.edit")}</Button>
                    <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={() => setDeleteRule({ industryId: i.id, id: r.id, key: r.key })}><Trash2 /></Button>
                  </span>
                </li>
              ))}
              {!i.rules.length ? <li className="px-4 py-2 text-[12px] text-muted">{t("dataSources.manualInfo")}</li> : null}
            </ul>
          </Card>
        ))}
      </div>
      <Card className="h-fit min-w-0 xl:sticky xl:top-16">
        <CardHeader title={<span className="flex items-center gap-1">{t("dataSources.testMatch")}<InfoTip>{t("dataSources.testMatchInfo")}</InfoTip></span>} />
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
            {!edit.id ? <Field label={t("dataSources.key")} info={t("dataSources.keyInfo")}><Input className="num" value={edit.key ?? ""} onChange={(e) => setEdit({ ...edit, key: e.target.value })} /></Field> : null}
            <Field label={t("dataSources.priority")} info={t("dataSources.priorityInfo")}><Input type="number" min={0} max={100} value={edit.priority ?? 0} onChange={(e) => setEdit({ ...edit, priority: Number(e.target.value) })} /></Field>
            <Field label={t("dataSources.nameEn")}><Input value={edit.name_en ?? ""} onChange={(e) => setEdit({ ...edit, name_en: e.target.value })} /></Field>
            <Field label={t("dataSources.nameTr")}><Input value={edit.name_tr ?? ""} onChange={(e) => setEdit({ ...edit, name_tr: e.target.value })} /></Field>
            <Field label={t("dataSources.descriptionEn")}><Textarea value={edit.description_en ?? ""} onChange={(e) => setEdit({ ...edit, description_en: e.target.value })} /></Field>
            <Field label={t("dataSources.descriptionTr")}><Textarea value={edit.description_tr ?? ""} onChange={(e) => setEdit({ ...edit, description_tr: e.target.value })} /></Field>
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              <MultiSelect label={t("dataSources.relevantServices")} value={edit.relevant_services ?? []} onChange={(v) => setEdit({ ...edit, relevant_services: v })} options={SERVICES.map((s) => ({ value: s, label: t(`services.${s}`) }))} />
              <MultiSelect label={t("dataSources.relevantFeatures")} value={edit.relevant_features ?? []} onChange={(v) => setEdit({ ...edit, relevant_features: v })} options={FEATURES.map((s) => ({ value: s, label: s }))} />
            </div>
            <Field label={t("dataSources.scoringProfile")} info={t("dataSources.scoringProfileInfo")}>
              <NativeSelect value={edit.scoring_profile_id ?? ""} onChange={(e) => setEdit({ ...edit, scoring_profile_id: e.target.value || null })}>
                <option value="">—</option>
                {profiles?.map((p) => <option key={p.id} value={p.id}>{locale === "tr" ? p.name_tr : p.name_en}</option>)}
              </NativeSelect>
            </Field>
            <Field label={t("dataSources.reviewTemplate")} info={t("dataSources.reviewTemplateInfo")}>
              <NativeSelect value={edit.review_template_id ?? ""} onChange={(e) => setEdit({ ...edit, review_template_id: e.target.value || null })}>
                <option value="">—</option>
                {templates?.map((p) => <option key={p.id} value={p.id}>{p.name_en}</option>)}
              </NativeSelect>
            </Field>
            <label className="flex items-center gap-2 text-[13px]"><Switch checked={!!edit.is_priority} onCheckedChange={(v) => setEdit({ ...edit, is_priority: v })} label={t("dataSources.isPriority")} />{t("dataSources.isPriority")}<InfoTip>{t("dataSources.isPriorityInfo")}</InfoTip></label>
            <p className="text-[12px] text-muted sm:col-span-2">{t("dataSources.relevantServices")}: {t("dataSources.relevantServicesInfo")} {t("dataSources.relevantFeatures")}: {t("dataSources.relevantFeaturesInfo")}</p>
          </div>
        ) : null}
      </Dialog>
      <Dialog open={rule !== null} onOpenChange={(v) => !v && setRule(null)} title={t("dataSources.osmRules")} wide
        footer={<><Button onClick={() => setRule(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={saveRule}>{t("common.save")}</Button></>}>
        {rule ? (
          <div className="grid gap-3">
            <Callout>
              <p>{t("dataSources.rulesInfo")}</p>
              <p className="mt-1">{t("dataSources.ruleWhy")}</p>
              <p className="mt-1">{t("dataSources.rulesOptional")}</p>
            </Callout>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("dataSources.key")} info={t("dataSources.ruleKeyInfo")}><Input className="num" value={rule.key} disabled={!!rule.id} placeholder="dentist_amenity" onChange={(e) => setRule({ ...rule, key: e.target.value })} /></Field>
              <Field label={t("dataSources.classification")} info={t("dataSources.classificationInfo")}>
                <NativeSelect value={rule.classification} onChange={(e) => setRule({ ...rule, classification: e.target.value })}>
                  <option value="confident">{t("dataSources.confident")}</option>
                  <option value="review">{t("dataSources.reviewCandidate")}</option>
                </NativeSelect>
              </Field>
            </div>
            <Field label={t("common.description")} info={t("dataSources.ruleDescriptionInfo")}><Input value={rule.description} onChange={(e) => setRule({ ...rule, description: e.target.value })} /></Field>
            <Field label={t("dataSources.conditions")} info={t("dataSources.conditionsInfo")} hint="all · any · exclude — eq · in · exists · regex"><Textarea className="num" rows={8} value={rule.conditions} onChange={(e) => setRule({ ...rule, conditions: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-[13px]"><Switch checked={rule.enabled} onCheckedChange={(v) => setRule({ ...rule, enabled: v })} label={t("common.enabled")} />{t("common.enabled")}</label>
          </div>
        ) : null}
      </Dialog>
      <ConfirmDialog open={deleteRule !== null} onOpenChange={(v) => !v && setDeleteRule(null)} title={t("common.delete")} danger
        message={`${deleteRule?.key ?? ""} — ${t("common.areYouSure")}`} confirmLabel={t("common.delete")} cancelLabel={t("common.cancel")}
        onConfirm={() => deleteRule && removeRule(deleteRule.industryId, deleteRule.id)} />
    </div>
  );
}

interface Provider { key: string; name: string; enabled: boolean; automation_status: string; automation_supported: boolean; credentials_configured: boolean; note_en: string; note_tr: string; official_source_url: string | null; manual_search_url_template: string | null; config: Record<string, string>; rate_limit_per_minute: number; recheck_days: number }

function ProvidersTab() {
  const t = useTranslations();
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useApi<Provider[]>(["ad-providers"], "/ad-providers");
  const [token, setToken] = useState<Record<string, string>>({});
  const [urls, setUrls] = useState<{ key: string; name: string; official: string; template: string } | null>(null);
  const patch = async (key: string, body: Record<string, unknown>, msg: string = t("common.saved")) => {
    try {
      await api(`/ad-providers/${key}`, { method: "PATCH", body });
      toast.success(msg);
      qc.invalidateQueries({ queryKey: ["ad-providers"] });
      return true;
    } catch (e) {
      toast.error(err(e));
      return false;
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
          <div className="grid gap-3 px-4 py-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="flex min-w-0 items-center gap-2 sm:col-span-2 lg:col-span-4">
              {p.official_source_url ? (
                <a href={p.official_source_url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex min-w-0 items-center gap-1 text-[12px] text-muted hover:text-foreground hover:underline">
                  <span className="truncate">{p.official_source_url}</span><ExternalLink className="size-3 shrink-0" />
                </a>
              ) : <span className="text-[12px] text-muted">—</span>}
              <Tooltip content={t("common.edit")}>
                <Button size="icon-sm" variant="ghost" className="ml-1 shrink-0" aria-label={t("dataSources.editUrls")}
                  onClick={() => setUrls({ key: p.key, name: p.name, official: p.official_source_url ?? "", template: p.manual_search_url_template ?? "" })}><Pencil /></Button>
              </Tooltip>
            </div>
            <Field label={t("dataSources.rateLimit")} info={t("dataSources.rateLimitInfo")}><Input type="number" min={1} max={60} defaultValue={p.rate_limit_per_minute} onBlur={(e) => Number(e.target.value) !== p.rate_limit_per_minute && patch(p.key, { rate_limit_per_minute: Number(e.target.value) })} /></Field>
            <Field label={t("dataSources.recheckDays")} info={t("dataSources.recheckInfo")}><Input type="number" min={1} max={365} defaultValue={p.recheck_days} onBlur={(e) => Number(e.target.value) !== p.recheck_days && patch(p.key, { recheck_days: Number(e.target.value) })} /></Field>
            {p.automation_supported ? (
              <>
                <Field label={t("dataSources.apiVersion")} info={t("dataSources.apiVersionInfo")}><Input className="num" defaultValue={p.config.api_version ?? "v23.0"} onBlur={(e) => e.target.value !== (p.config.api_version ?? "v23.0") && patch(p.key, { config: { ...p.config, api_version: e.target.value } })} /></Field>
                <Field label={t("dataSources.accessToken")} info={t("dataSources.accessTokenInfo")} hint={p.credentials_configured ? t("dataSources.apifyTokenSet") : undefined}>
                  <div className="flex gap-2">
                    <Input type="password" autoComplete="off" value={token[p.key] ?? ""} onChange={(e) => setToken({ ...token, [p.key]: e.target.value })} />
                    <Button size="sm" disabled={!token[p.key]} onClick={() => patch(p.key, { credentials: { access_token: token[p.key] ?? "" } })}>{t("common.save")}</Button>
                  </div>
                </Field>
              </>
            ) : null}
          </div>
        </Card>
      ))}
      <Dialog open={urls !== null} onOpenChange={(v) => !v && setUrls(null)} title={`${t("dataSources.editUrls")}${urls ? ` — ${urls.name}` : ""}`} wide
        footer={<><Button onClick={() => setUrls(null)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!urls?.official.trim()} onClick={async () => {
          if (urls && await patch(urls.key, { official_source_url: urls.official.trim(), manual_search_url_template: urls.template.trim() }, t("dataSources.urlsSaved"))) setUrls(null);
        }}>{t("common.save")}</Button></>}>
        {urls ? (
          <div className="grid gap-3">
            <Field label={t("dataSources.officialUrl")} info={t("dataSources.officialUrlInfo")}><Input className="num" type="url" inputMode="url" value={urls.official} onChange={(e) => setUrls({ ...urls, official: e.target.value })} /></Field>
            <Field label={t("dataSources.searchTemplate")} info={t("dataSources.searchTemplateInfo")} hint="{query} · {domain} · {country}">
              <Input className="num" value={urls.template} onChange={(e) => setUrls({ ...urls, template: e.target.value })} />
            </Field>
          </div>
        ) : null}
      </Dialog>
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
      <Callout title={t("dataSources.apifyGuideTitle")}><p className="whitespace-pre-line">{t("dataSources.apifyGuide")}</p></Callout>
      <Card>
        <CardHeader title={t("dataSources.actors")} actions={<Button size="sm" onClick={() => setEdit({ id: "", name: "", actor_id: "", purpose: "discovery", input_template: "{}", field_mapping: '{"name": "title", "website": "website", "phone": "phone"}', allowed_input_keys: "", max_items: 100, max_cost_usd: 1, enabled: false })}><Plus />{t("dataSources.addActor")}</Button>} />
        <ul className="divide-y divide-border">
          {data?.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-[13px]">
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
      <Dialog open={edit !== null} onOpenChange={(v) => !v && setEdit(null)} title={edit?.id ? t("common.edit") : t("dataSources.addActor")} wide
        footer={<><Button onClick={() => setEdit(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={save}>{t("common.save")}</Button></>}>
        {edit ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("common.name")}><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label={t("dataSources.actorId")} info={t("dataSources.actorIdInfo")}><Input placeholder="apify/google-maps-scraper" className="num" value={edit.actor_id} onChange={(e) => setEdit({ ...edit, actor_id: e.target.value })} /></Field>
            <Field label={t("dataSources.purpose")} info={t("dataSources.purposeInfo")}>
              <NativeSelect value={edit.purpose} onChange={(e) => setEdit({ ...edit, purpose: e.target.value })}><option value="discovery">discovery</option><option value="advertising">advertising</option></NativeSelect>
            </Field>
            <Field label={t("dataSources.maxItems")} info={t("dataSources.maxItemsInfo")}><Input type="number" value={edit.max_items} onChange={(e) => setEdit({ ...edit, max_items: Number(e.target.value) })} /></Field>
            <Field label={t("dataSources.maxCost")} info={t("dataSources.maxCostInfo")}><Input type="number" step="0.1" value={edit.max_cost_usd} onChange={(e) => setEdit({ ...edit, max_cost_usd: Number(e.target.value) })} /></Field>
            <Field label={t("dataSources.allowedKeys")} info={t("dataSources.allowedKeysInfo")}><Input placeholder="searchStringsArray, locationQuery" className="num" value={edit.allowed_input_keys} onChange={(e) => setEdit({ ...edit, allowed_input_keys: e.target.value })} /></Field>
            <Field label={t("dataSources.inputTemplate")} info={t("dataSources.inputTemplateInfo")}><Textarea className="num" rows={6} value={edit.input_template} onChange={(e) => setEdit({ ...edit, input_template: e.target.value })} /></Field>
            <Field label={t("dataSources.fieldMapping")} info={t("dataSources.fieldMappingInfo")}><Textarea className="num" rows={6} value={edit.field_mapping} onChange={(e) => setEdit({ ...edit, field_mapping: e.target.value })} /></Field>
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
