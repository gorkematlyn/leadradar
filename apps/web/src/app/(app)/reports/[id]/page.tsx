"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Copy, Eye, FileDown, Link2, RefreshCw, ShieldOff } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { DateText, PageHeader } from "@/components/app/bits";
import type { AuditDetail } from "@/components/company/types";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge, Card, CardHeader, Checkbox, Skeleton } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";

const SECTIONS = ["summary", "performance", "mobile", "seo", "accessibility", "tracking", "screenshots", "advertising", "recommendations", "services", "methodology", "notes"];

interface Report {
  id: string; title: string; mode: string; language: string; sections: string[]; status: string; company: { id: string; name: string } | null;
  selected_evidence_ids: string[]; selected_ad_ids: string[]; public_notes: string | null; branding: Record<string, string>;
  published_version_id: string | null;
  versions: { id: string; version: number; status: string; created_at: string; approved_at: string | null; pdf: { en: boolean; tr: boolean } }[];
  links: { id: string; hint: string; pinned_version_id: string | null; expires_at: string | null; revoked_at: string | null; password_protected: boolean; view_count: number; last_viewed_at: string | null; allow_pdf: boolean; created_at: string }[];
}

export default function ReportPage() {
  const t = useTranslations();
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data: r } = useApi<Report>(["report", id], `/reports/${id}`, { refetchInterval: 10_000 });
  const { data: audits } = useApi<{ id: string; status: string }[]>(["audits", r?.company?.id], r?.company ? `/companies/${r.company.id}/audits` : null);
  const completed = audits?.find((a) => a.status === "completed")?.id ?? null;
  const { data: audit } = useApi<AuditDetail>(["audit", completed], completed ? `/audits/${completed}` : null);
  const { data: ads } = useApi<{ ads: { id: string; platform: string; text: string | null; status: string | null }[] }>(["ads", r?.company?.id], r?.company ? `/companies/${r.company.id}/advertising` : null);
  const [form, setForm] = useState<Partial<Report>>({});
  const [publishOpen, setPublishOpen] = useState(false);
  const [pub, setPub] = useState({ expires: "", password: "", allow_pdf: true });
  const [created, setCreated] = useState<string | null>(null);

  useEffect(() => {
    if (r) setForm({ title: r.title, mode: r.mode, language: r.language, sections: r.sections, selected_evidence_ids: r.selected_evidence_ids, selected_ad_ids: r.selected_ad_ids, public_notes: r.public_notes ?? "", branding: r.branding });
  }, [r]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["report", id] });
  const act = async <T,>(fn: () => Promise<T>, msg?: string): Promise<T | null> => {
    try {
      const res = await fn();
      if (msg) toast.success(msg);
      refresh();
      return res;
    } catch (e) {
      toast.error(err(e));
      return null;
    }
  };
  const save = () => act(() => api(`/reports/${id}`, { method: "PATCH", body: form }), t("common.saved"));
  const publish = async () => {
    const res = await act(() => api<{ url: string }>(`/reports/${id}/publish`, {
      body: { expires_in_days: pub.expires ? Number(pub.expires) : null, password: pub.password || null, allow_pdf: pub.allow_pdf },
    }), t("reports.linkCreated"));
    if (res) { setCreated(res.url); setPublishOpen(false); }
  };
  if (!r) return <Skeleton className="h-64 w-full" />;
  const toggle = (key: "sections" | "selected_evidence_ids" | "selected_ad_ids", v: string) => {
    const cur = (form[key] as string[]) ?? [];
    setForm({ ...form, [key]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] });
  };
  return (
    <>
      <PageHeader title={r.title} description={r.company ? <Link href={`/companies/${r.company.id}?tab=reports`} className="hover:underline">{r.company.name}</Link> : null}
        actions={
          <>
            <Button size="sm" onClick={save}>{t("common.save")}</Button>
            <Button size="sm" onClick={async () => { await save(); await act(() => api(`/reports/${id}/versions`, { body: {} })); }}><RefreshCw />{t("reports.newVersion")}</Button>
            <Button size="sm" variant="primary" disabled={!r.published_version_id} onClick={() => setPublishOpen(true)}><Link2 />{t("reports.publish")}</Button>
          </>
        } />
      <p className="mb-4 text-[12px] text-muted">{t("reports.neverExposed")}</p>
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <div className="grid content-start gap-4">
          <Card className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label={t("reports.titleLabel")} className="sm:col-span-2"><Input value={form.title ?? ""} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
            <Field label={t("reports.mode")}>
              <NativeSelect value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
                <option value="snapshot">{t("reports.modeSnapshot")}</option>
                <option value="live">{t("reports.modeLive")}</option>
              </NativeSelect>
            </Field>
            <Field label={t("reports.language")}>
              <NativeSelect value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                <option value="en">{t("common.english")}</option>
                <option value="tr">{t("common.turkish")}</option>
              </NativeSelect>
            </Field>
            <Field label={t("reports.brandName")}><Input value={form.branding?.name ?? ""} onChange={(e) => setForm({ ...form, branding: { ...form.branding, name: e.target.value } })} /></Field>
            <Field label={t("reports.brandContact")}><Input value={form.branding?.contact ?? ""} onChange={(e) => setForm({ ...form, branding: { ...form.branding, contact: e.target.value } })} /></Field>
            <Field label={t("reports.publicNotes")} className="sm:col-span-2"><Textarea value={form.public_notes ?? ""} onChange={(e) => setForm({ ...form, public_notes: e.target.value })} /></Field>
          </Card>
          <Card>
            <CardHeader title={t("reports.sections")} />
            <div className="grid gap-1.5 p-4 sm:grid-cols-2">
              {SECTIONS.map((s) => (
                <label key={s} className="flex items-center gap-2 text-[13px]"><Checkbox label={s} checked={form.sections?.includes(s) ?? false} onCheckedChange={() => toggle("sections", s)} />{t(`reports.section.${s}`)}</label>
              ))}
            </div>
          </Card>
          {audit?.screenshots.length ? (
            <Card>
              <CardHeader title={t("reports.selectEvidence")} />
              <div className="grid gap-3 p-4 sm:grid-cols-3">
                {audit.screenshots.filter((s) => s.approved_for_reports).map((s) => (
                  <label key={s.id} className="grid gap-1 text-[12px]">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/api/blobs/${s.blob_id}`} alt={s.label} className="rounded-md border border-border" />
                    <span className="flex items-center gap-1.5"><Checkbox label={s.label} checked={form.selected_evidence_ids?.includes(s.id) ?? false} onCheckedChange={() => toggle("selected_evidence_ids", s.id)} />{s.label}</span>
                  </label>
                ))}
              </div>
            </Card>
          ) : null}
          {ads?.ads.filter((a) => true).length ? (
            <Card>
              <CardHeader title={t("reports.selectAds")} />
              <ul className="grid gap-1.5 p-4">
                {ads.ads.map((a) => (
                  <li key={a.id}><label className="flex items-center gap-2 text-[13px]"><Checkbox label={a.id} checked={form.selected_ad_ids?.includes(a.id) ?? false} onCheckedChange={() => toggle("selected_ad_ids", a.id)} />{t(`ads.platforms.${a.platform}`)} · {(a.text ?? "").slice(0, 80)}</label></li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader title={t("reports.versions")} />
            <ul className="divide-y divide-border">
              {r.versions.map((v) => (
                <li key={v.id} className="grid gap-1.5 px-4 py-2.5 text-[13px]">
                  <div className="flex items-center gap-2">
                    <span className="num font-medium">v{v.version}</span>
                    <Badge tone={v.status === "approved" ? "success" : "neutral"}>{v.status === "approved" ? t("reports.approved") : t("reports.draft")}</Badge>
                    {r.published_version_id === v.id ? <Badge tone="accent">live</Badge> : null}
                    <span className="ml-auto"><DateText value={v.created_at} withTime /></span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" asChild><a href={`/api/reports/${id}/versions/${v.id}/preview?lang=${r.language}`} target="_blank" rel="noopener"><Eye />{t("reports.preview")}</a></Button>
                    {v.status !== "approved" ? <Button size="sm" variant="primary" onClick={() => act(() => api(`/reports/${id}/versions/${v.id}/approve`, { body: {} }), t("reports.approved"))}>{t("reports.approve")}</Button> : null}
                    {(["en", "tr"] as const).map((l) => v.pdf[l] ? (
                      <Button key={l} size="sm" asChild><a href={`/api/reports/${id}/versions/${v.id}/pdf?lang=${l}`}><FileDown />PDF {l.toUpperCase()}</a></Button>
                    ) : v.status === "approved" ? <Badge key={l}>{t("reports.pdfPending")} ({l})</Badge> : null)}
                  </div>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader title={t("reports.links")} actions={r.links.some((l) => !l.revoked_at) ? <Button size="sm" variant="danger" onClick={() => act(() => api(`/reports/${id}/unpublish`, { body: {} }))}><ShieldOff />{t("reports.unpublish")}</Button> : null} />
            {!r.published_version_id ? <p className="px-4 py-3 text-[12px] text-muted">{t("reports.approveFirst")}</p> : null}
            <ul className="divide-y divide-border">
              {r.links.map((l) => (
                <li key={l.id} className="grid gap-1 px-4 py-2.5 text-[13px]">
                  <div className="flex items-center gap-2">
                    <span className="num">/r/{l.hint}…</span>
                    {l.revoked_at ? <Badge tone="danger">{t("reports.revoked")}</Badge> : <Badge tone="success">{t("reports.status.published")}</Badge>}
                    {l.password_protected ? <Badge>🔒</Badge> : null}
                    {l.pinned_version_id ? <Badge>snapshot</Badge> : <Badge>live</Badge>}
                    <span className="ml-auto text-[11px] text-muted">{t("reports.views", { count: l.view_count })}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
                    <DateText value={l.created_at} />{l.expires_at ? <> → <DateText value={l.expires_at} /></> : null}
                    {!l.revoked_at ? (
                      <>
                        <Button size="sm" variant="ghost" onClick={async () => { const res = await act(() => api<{ url: string }>(`/reports/${id}/links/${l.id}/rotate`, { body: {} })); if (res) setCreated(res.url); }}>{t("reports.rotate")}</Button>
                        <Button size="sm" variant="ghost" onClick={() => act(() => api(`/reports/${id}/links/${l.id}/revoke`, { body: {} }))}>{t("reports.revoke")}</Button>
                      </>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
            <p className="border-t border-border px-4 py-2 text-[11px] text-muted">{t("reports.domainNote")}</p>
          </Card>
        </div>
      </div>
      <Dialog open={publishOpen} onOpenChange={setPublishOpen} title={t("reports.publish")} description={t("reports.publishHint")}
        footer={<><Button onClick={() => setPublishOpen(false)}>{t("common.cancel")}</Button><Button variant="primary" onClick={publish}>{t("common.create")}</Button></>}>
        <div className="grid gap-3">
          <Field label={t("reports.expires")}><Input type="number" min={1} value={pub.expires} onChange={(e) => setPub({ ...pub, expires: e.target.value })} /></Field>
          <Field label={t("reports.password")}><Input type="password" autoComplete="new-password" value={pub.password} onChange={(e) => setPub({ ...pub, password: e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-[13px]"><Checkbox label="pdf" checked={pub.allow_pdf} onCheckedChange={(v) => setPub({ ...pub, allow_pdf: v })} />{t("reports.allowPdf")}</label>
        </div>
      </Dialog>
      <Dialog open={created !== null} onOpenChange={(v) => !v && setCreated(null)} title={t("reports.linkCreated")} description={t("reports.linkOnce")}>
        <div className="flex gap-2">
          <Input readOnly value={created ?? ""} className="num" onFocus={(e) => e.target.select()} />
          <Button onClick={() => { navigator.clipboard.writeText(created ?? ""); toast.success(t("common.copied")); }}><Copy />{t("reports.copyLink")}</Button>
        </div>
      </Dialog>
    </>
  );
}
