"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { DateText } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge, Card, CardHeader, Checkbox } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";

interface AdsData {
  platforms: { key: string; name: string; enabled: boolean; automation_status: string; manual_url: string | null; note_en: string; note_tr: string;
    latest: { id: string; status: string; method: string; researched_at: string | null; active_ads_verified: boolean; result_count: number; notes: string | null; error: string | null; source_url: string | null; search_scope: Record<string, unknown> } | null }[];
  advertisers: { id: string; platform: string; name: string; match_status: string; match_confidence: number; source_url: string | null }[];
  ads: { id: string; platform: string; advertiser_id: string | null; format: string | null; text: string | null; landing_page_url: string | null; status: string | null; start_date: string | null; end_date: string | null; source_url: string | null; approved_for_reports: boolean; last_observed_at: string | null }[];
}

const STATUS_TONE: Record<string, string> = { found: "success", no_results: "neutral", match_required: "warning", unsupported: "neutral", error: "danger", blocked: "warning", rate_limited: "warning", not_checked: "neutral" };

export function AdsPanel({ companyId }: { companyId: string }) {
  const t = useTranslations("ads");
  const tc = useTranslations("common");
  const ta = useTranslations("audit");
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useApi<AdsData>(["ads", companyId], `/companies/${companyId}/advertising`, { refetchInterval: 15_000 });
  const [manual, setManual] = useState<string | null>(null);
  const [form, setForm] = useState({ status: "found", active_ads_verified: true, advertiser_name: "", advertiser_id: "", source_url: "", notes: "", ad_text: "", ad_status: "active", landing: "", start: "" });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ads", companyId] });
    qc.invalidateQueries({ queryKey: ["company", companyId] });
  };
  const research = async (platforms?: string[]) => {
    try {
      await api(`/companies/${companyId}/ad-research`, { body: { platforms: platforms ?? null } });
      toast.success(t("queued"));
      refresh();
    } catch (e) {
      toast.error(err(e));
    }
  };
  const confirm = async (id: string, ok: boolean) => {
    await api(`/companies/${companyId}/advertisers/${id}/confirm`, { body: { confirm: ok } }).catch((e) => toast.error(err(e)));
    refresh();
  };
  const saveManual = async () => {
    if (!manual) return;
    try {
      await api(`/companies/${companyId}/ad-research/manual`, {
        body: {
          platform: manual, status: form.status, active_ads_verified: form.status === "found" && form.active_ads_verified,
          advertiser_name: form.advertiser_name || null, advertiser_id: form.advertiser_id || null, source_url: form.source_url || null,
          notes: form.notes || null,
          ads: form.status === "found" && form.ad_text ? [{ text: form.ad_text, status: form.ad_status, landing_page_url: form.landing || null, start_date: form.start || null, source_url: form.source_url || null }] : [],
        },
      });
      toast.success(tc("saved"));
      setManual(null);
      refresh();
    } catch (e) {
      toast.error(err(e));
    }
  };
  const approveAd = async (id: string, approved: boolean) => {
    await api(`/ads/${id}/approve`, { body: { approved } });
    refresh();
  };
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader title={t("title")} description={`${t("noResultsNote")} ${t("noSpend")}`} actions={<Button size="sm" variant="primary" onClick={() => research()}><Search />{t("researchAll")}</Button>} />
        <ul className="divide-y divide-border">
          {data?.platforms.map((p) => (
            <li key={p.key} className="grid gap-2 px-4 py-3 text-[13px] lg:grid-cols-[180px_1fr_auto] lg:items-start">
              <div>
                <p className="font-medium">{p.name}</p>
                <p className="text-[11px] text-muted">{t(`automation.${p.automation_status}`)}</p>
              </div>
              <div className="min-w-0">
                {p.latest ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={STATUS_TONE[p.latest.status] ?? "neutral"}>{t(`status.${p.latest.status}`)}</Badge>
                    <span className="text-[12px] text-muted">{t(`method.${p.latest.method}`)}</span>
                    {p.latest.active_ads_verified ? <Badge tone="success">{t("activeVerified")}</Badge> : null}
                    {p.latest.researched_at ? <DateText value={p.latest.researched_at} withTime /> : null}
                  </div>
                ) : <Badge>{t("status.not_checked")}</Badge>}
                <p className="mt-1 text-[12px] text-muted">{p.latest?.notes ?? (locale === "tr" ? p.note_tr : p.note_en)}</p>
                {p.latest?.error ? <p className="mt-1 text-[12px] text-danger">{p.latest.error}</p> : null}
              </div>
              <div className="flex flex-wrap gap-2">
                {p.manual_url ? <Button size="sm" asChild><a href={p.manual_url} target="_blank" rel="noopener noreferrer nofollow"><ExternalLink />{t("manualResearch")}</a></Button> : null}
                <Button size="sm" onClick={() => setManual(p.key)}>{t("recordManual")}</Button>
                {p.automation_status === "automated" ? <Button size="sm" onClick={() => research([p.key])}>{t("research")}</Button> : null}
              </div>
            </li>
          ))}
        </ul>
      </Card>
      {data?.advertisers.length ? (
        <Card>
          <CardHeader title={t("advertisers")} />
          <ul className="divide-y divide-border">
            {data.advertisers.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-[13px]">
                <Badge tone="solid">{t(`platforms.${a.platform}`)}</Badge>
                <span className="font-medium">{a.name}</span>
                <span className="num text-[12px] text-muted">{t("matchConfidence")}: {Math.round(a.match_confidence * 100)}%</span>
                <Badge tone={a.match_status === "confirmed" ? "success" : a.match_status === "rejected" ? "danger" : "warning"}>{a.match_status}</Badge>
                {a.source_url ? <a href={a.source_url} target="_blank" rel="noopener noreferrer nofollow" className="text-[12px] text-muted hover:underline">source</a> : null}
                <span className="ml-auto flex gap-2">
                  {a.match_status !== "confirmed" ? <Button size="sm" onClick={() => confirm(a.id, true)}>{t("confirmMatch")}</Button> : null}
                  {a.match_status !== "rejected" ? <Button size="sm" variant="ghost" onClick={() => confirm(a.id, false)}>{t("rejectMatch")}</Button> : null}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      {data?.ads.length ? (
        <Card>
          <CardHeader title={t("ads")} />
          <ul className="divide-y divide-border">
            {data.ads.map((ad) => (
              <li key={ad.id} className="grid gap-1 px-4 py-2 text-[13px]">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="solid">{t(`platforms.${ad.platform}`)}</Badge>
                  <Badge tone={ad.status === "active" ? "success" : "neutral"}>{t(`adStatus.${ad.status ?? "unknown"}`)}</Badge>
                  {ad.start_date ? <span className="num text-[12px] text-muted">{ad.start_date}{ad.end_date ? ` → ${ad.end_date}` : ""}</span> : null}
                  {ad.source_url ? <a href={ad.source_url} target="_blank" rel="noopener noreferrer nofollow" className="text-[12px] text-muted hover:underline">source</a> : null}
                  <label className="ml-auto flex items-center gap-1.5 text-[12px] text-muted">
                    <Checkbox label="approve" checked={ad.approved_for_reports} onCheckedChange={(v) => approveAd(ad.id, v)} />
                    {ta("approveForReports")}
                  </label>
                </div>
                {ad.text ? <p className="text-[12px]">{ad.text}</p> : null}
                {ad.landing_page_url ? <p className="num text-[11px] text-muted">{ad.landing_page_url}</p> : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <Dialog open={manual !== null} onOpenChange={(v) => !v && setManual(null)} title={t("manualTitle")} description={t("manualHint")} wide
        footer={<><Button onClick={() => setManual(null)}>{tc("cancel")}</Button><Button variant="primary" onClick={saveManual}>{tc("save")}</Button></>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={tc("status")}>
            <NativeSelect value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {["found", "no_results", "blocked", "unsupported"].map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
            </NativeSelect>
          </Field>
          <label className="flex items-end gap-2 pb-1.5 text-[13px]">
            <Checkbox label={t("activeVerified")} checked={form.active_ads_verified} onCheckedChange={(v) => setForm({ ...form, active_ads_verified: v })} />
            {t("activeVerified")}
          </label>
          <Field label={t("advertiserName")}><Input value={form.advertiser_name} onChange={(e) => setForm({ ...form, advertiser_name: e.target.value })} /></Field>
          <Field label={t("advertiserId")}><Input value={form.advertiser_id} onChange={(e) => setForm({ ...form, advertiser_id: e.target.value })} /></Field>
          <Field label={t("sourceUrl")} className="sm:col-span-2"><Input value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} /></Field>
          <Field label={t("adText")} className="sm:col-span-2"><Textarea value={form.ad_text} onChange={(e) => setForm({ ...form, ad_text: e.target.value })} /></Field>
          <Field label={t("landingPage")}><Input value={form.landing} onChange={(e) => setForm({ ...form, landing: e.target.value })} /></Field>
          <Field label={t("startDate")}><Input type="date" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></Field>
          <Field label={tc("notes")} className="sm:col-span-2"><Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
        </div>
      </Dialog>
    </div>
  );
}
