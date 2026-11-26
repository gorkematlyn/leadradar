"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileSearch } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { AnalysisBadge, DateText, ResultBadge } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { Badge, Card, CardHeader, Checkbox, EmptyState, Skeleton } from "@/components/ui/misc";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { fmtNumber } from "@/lib/utils";
import type { AuditDetail, AuditFindingView } from "./types";

interface AuditSummary { id: string; mode: string; status: string; created_at: string; automated_completed_at: string | null; reused_from: string | null }

export function useLatestAudit(companyId: string) {
  const list = useApi<AuditSummary[]>(["audits", companyId], `/companies/${companyId}/audits`, { refetchInterval: 15_000 });
  return list;
}

export function FindingList({ findings, showPassed, onValidate }: { findings: AuditFindingView[]; showPassed: boolean; onValidate?: (id: number, v: boolean | null) => void }) {
  const t = useTranslations();
  const locale = useLocale();
  const groups = useMemo(() => {
    const g: Record<string, AuditFindingView[]> = {};
    for (const f of findings) {
      if (!showPassed && ["passed", "not_applicable", "detected"].includes(f.result)) continue;
      (g[f.category ?? "other"] ??= []).push(f);
    }
    return g;
  }, [findings, showPassed]);
  const order = ["availability", "technical", "performance", "visual", "accessibility", "seo", "conversion", "tracking", "other"];
  return (
    <div className="grid gap-3">
      {order.filter((c) => groups[c]?.length).map((cat) => (
        <Card key={cat}>
          <CardHeader title={t.has(`audit.categories.${cat}`) ? t(`audit.categories.${cat}`) : cat} />
          <ul className="divide-y divide-border">
            {groups[cat].map((f) => (
              <li key={f.id} className="grid gap-1 px-4 py-2.5 text-[13px] sm:grid-cols-[100px_1fr_auto] sm:items-start sm:gap-3">
                <div><ResultBadge result={f.result} /></div>
                <div className="min-w-0">
                  <p className="font-medium">{locale === "tr" ? f.title_tr : f.title_en}
                    {f.severity && f.result === "failed" ? <span className="ml-2 text-[11px] font-normal text-muted">{t(`audit.severity.${f.severity}`)}</span> : null}
                    {f.heuristic ? <Badge className="ml-2">{t("audit.heuristic")}</Badge> : null}
                  </p>
                  <p className="text-[12px] text-muted">{locale === "tr" ? f.description_tr : f.description_en}</p>
                  {f.result === "failed" && (locale === "tr" ? f.recommendation_tr : f.recommendation_en) && (locale === "tr" ? f.recommendation_tr : f.recommendation_en) !== "—" ? (
                    <p className="mt-1 text-[12px]">→ {locale === "tr" ? f.recommendation_tr : f.recommendation_en}</p>
                  ) : null}
                  <FindingValue value={f.value} />
                </div>
                <div className="flex items-center gap-2 text-[11px] text-muted">
                  <span className="num">{Math.round(f.confidence * 100)}%</span>
                  {f.evidence_count ? <Badge>{f.evidence_count}</Badge> : null}
                  {onValidate && f.heuristic && f.result === "failed" ? (
                    <NativeSelect className="h-6 w-auto text-[11px]" value={f.admin_validated === null ? "" : String(f.admin_validated)}
                      onChange={(e) => onValidate(f.id, e.target.value === "" ? null : e.target.value === "true")}>
                      <option value="">—</option>
                      <option value="true">{t("audit.validate")}</option>
                      <option value="false">{t("audit.invalidate")}</option>
                    </NativeSelect>
                  ) : f.admin_validated !== null ? <Badge tone={f.admin_validated ? "success" : "neutral"}>{f.admin_validated ? t("audit.validate") : t("audit.invalidate")}</Badge> : null}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

function FindingValue({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value ?? {}).filter(([k, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length) && k !== "limitations");
  if (!entries.length) return null;
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-[11px] text-muted">{entries.map(([k]) => k).slice(0, 4).join(" · ")}</summary>
      <pre className="num mt-1 max-h-48 overflow-auto rounded-md border border-border bg-surface-2 p-2 text-[11px] leading-snug">{JSON.stringify(Object.fromEntries(entries), null, 2).slice(0, 4000)}</pre>
    </details>
  );
}

export function LighthouseCard({ audit }: { audit: AuditDetail }) {
  const t = useTranslations("audit");
  const locale = useLocale();
  const lh = audit.metrics.lighthouse;
  if (!lh?.scores) return null;
  const m = lh.metrics ?? {};
  const sec = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${fmtNumber(v / 1000, locale, { maximumFractionDigits: 1 })} s`);
  return (
    <Card>
      <CardHeader title={t("lighthouse")} description={t("lighthouseNote")} />
      <div className="grid grid-cols-2 divide-x divide-border border-b border-border sm:grid-cols-4">
        {(["performance", "accessibility", "best_practices", "seo"] as const).map((k) => (
          <div key={k} className="px-4 py-3">
            <p className="text-[12px] text-muted">{t(k === "best_practices" ? "bestPractices" : k)}</p>
            <p className="num text-[20px]">{lh.scores[k] ?? "—"}</p>
          </div>
        ))}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 px-4 py-3 text-[13px] sm:grid-cols-5">
        <div><dt className="text-[12px] text-muted">FCP</dt><dd className="num">{sec(m.fcp_ms)}</dd></div>
        <div><dt className="text-[12px] text-muted">LCP</dt><dd className="num">{sec(m.lcp_ms)}</dd></div>
        <div><dt className="text-[12px] text-muted">CLS</dt><dd className="num">{m.cls ?? "—"}</dd></div>
        <div><dt className="text-[12px] text-muted">TBT</dt><dd className="num">{m.tbt_ms === null || m.tbt_ms === undefined ? "—" : `${Math.round(m.tbt_ms)} ms`}</dd></div>
        <div><dt className="text-[12px] text-muted">{t("speedIndex")}</dt><dd className="num">{sec(m.speed_index_ms)}</dd></div>
      </dl>
      {audit.context.lighthouse ? (
        <p className="border-t border-border px-4 py-2 text-[11px] text-muted">
          {t("testConditions")}: {String(audit.context.lighthouse.form_factor ?? "")} · {String(audit.context.lighthouse.throttling_method ?? "")} · Lighthouse {String(audit.context.lighthouse.lighthouse_version ?? "")} · {String(audit.context.lighthouse.fetch_time ?? "")}
        </p>
      ) : null}
    </Card>
  );
}

export function Screenshots({ audit, selectable, selected, onToggle }: { audit: AuditDetail; selectable?: boolean; selected?: string[]; onToggle?: (id: string) => void }) {
  const t = useTranslations("audit");
  const qc = useQueryClient();
  if (!audit.screenshots.length) return null;
  const approve = async (id: string, approved: boolean) => {
    await api(`/evidence/${id}/approve`, { body: { approved } });
    qc.invalidateQueries({ queryKey: ["audit", audit.id] });
  };
  return (
    <Card>
      <CardHeader title={t("screenshots")} />
      <div className="grid gap-4 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        {audit.screenshots.map((s) => (
          <figure key={s.id} className="grid gap-2">
            {/* Screenshots are served as images from our own API; external pages are never embedded. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/api/blobs/${s.blob_id}`} alt={s.label} className="w-full rounded-md border border-border" loading="lazy" />
            <figcaption className="flex items-center justify-between gap-2 text-[12px] text-muted">
              <span>{s.label}</span>
              {selectable ? (
                <label className="flex items-center gap-1.5">
                  <Checkbox label={t("approveForReports")} checked={selected?.includes(s.id) ?? false} onCheckedChange={() => onToggle?.(s.id)} />
                  {t("approveForReports")}
                </label>
              ) : (
                <Button size="sm" variant={s.approved_for_reports ? "secondary" : "ghost"} onClick={() => approve(s.id, !s.approved_for_reports)}>
                  {s.approved_for_reports ? t("approved") : t("approveForReports")}
                </Button>
              )}
            </figcaption>
          </figure>
        ))}
      </div>
    </Card>
  );
}

export function TrackingTable({ audit }: { audit: AuditDetail }) {
  const t = useTranslations("tracking");
  const tr = useTranslations();
  const byTech = useMemo(() => {
    const m: Record<string, AuditDetail["tracking"]> = {};
    audit.tracking.forEach((x) => (m[x.technology] ??= []).push(x));
    return m;
  }, [audit.tracking]);
  if (!audit.tracking.length) return <EmptyState title={tr("result.not_checked")} />;
  const states = Array.from(new Set(audit.tracking.map((x) => x.consent_state)));
  return (
    <Card>
      <CardHeader title={t("title")} description={t("note")} />
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-border text-left text-[12px] text-muted">
              <th className="px-4 py-2 font-medium">{tr("common.name")}</th>
              {states.map((s) => <th key={s} className="px-3 py-2 font-medium">{t(`consentState.${s}`)}</th>)}
              <th className="px-3 py-2 font-medium">{t("methods")}</th>
              <th className="px-3 py-2 font-medium">{t("identifiers")}</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(byTech).map(([tech, rows]) => {
              const any = rows.find((r) => r.status === "detected") ?? rows[0];
              return (
                <tr key={tech} className="border-b border-border last:border-0">
                  <td className="px-4 py-2">{t.has(`tech.${tech}`) ? t(`tech.${tech}`) : tech}</td>
                  {states.map((s) => {
                    const r = rows.find((x) => x.consent_state === s);
                    return <td key={s} className="px-3 py-2">{r ? <ResultBadge result={r.status} /> : "—"}</td>;
                  })}
                  <td className="num px-3 py-2 text-[11px] text-muted">{any.methods.join(", ") || "—"}</td>
                  <td className="num px-3 py-2 text-[11px] text-muted">{any.identifiers.join(", ") || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {audit.context.consent_test ? <p className="border-t border-border px-4 py-2 text-[11px] text-muted">{audit.context.consent_test.note} ({audit.context.consent_test.clicked_selector})</p> : null}
    </Card>
  );
}

export function AuditPanel({ companyId, hasWebsite }: { companyId: string; hasWebsite: boolean }) {
  const t = useTranslations();
  const { data: audits, isLoading } = useLatestAudit(companyId);
  const [selected, setSelected] = useState<string | null>(null);
  const [showPassed, setShowPassed] = useState(false);
  const current = selected ?? audits?.[0]?.id ?? null;
  const { data: audit } = useApi<AuditDetail>(["audit", current], current ? `/audits/${current}` : null, { refetchInterval: 15_000 });
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (!audits?.length) return <EmptyState icon={<FileSearch />} title={t("audit.noAudit")} description={hasWebsite ? t("audit.noAuditHint") : t("company.noWebsiteNote")} />;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect className="h-8 w-auto" value={current ?? ""} onChange={(e) => setSelected(e.target.value)} aria-label={t("audit.history")}>
          {audits.map((a) => <option key={a.id} value={a.id}>{new Date(a.created_at).toISOString().slice(0, 16).replace("T", " ")} · {t(`audit.mode.${a.mode}`)} · {t(`analysisStatus.${a.status}`)}</option>)}
        </NativeSelect>
        {audit ? <AnalysisBadge status={audit.status} /> : null}
        {audit?.status === "action_required" ? <Button size="sm" variant="primary" asChild><Link href={`/review/${audit.id}`}>{t("company.actions.review")}</Link></Button> : null}
        {audit?.reused_from ? <Badge>{t("audit.reused")}</Badge> : null}
        <label className="ml-auto flex items-center gap-2 text-[12px] text-muted">
          <Checkbox label={t("audit.showPassed")} checked={showPassed} onCheckedChange={setShowPassed} />{t("audit.showPassed")}
        </label>
      </div>
      {audit ? (
        <>
          <Card className="grid gap-x-6 gap-y-1 px-4 py-3 text-[12px] sm:grid-cols-3">
            <span className="text-muted">{t("audit.pages")}: <span className="text-foreground">{audit.pages_audited.length}</span></span>
            <span className="text-muted">HTTP: <span className="num text-foreground">{audit.metrics.http?.status ?? "—"} · {audit.metrics.http?.elapsed_ms ?? "—"} ms</span></span>
            <span className="text-muted">{t("audit.browser")}: <span className="text-foreground">{audit.context.browser?.version ?? "—"}</span></span>
            {audit.final_url ? <a href={audit.final_url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 truncate text-foreground hover:underline sm:col-span-3"><ExternalLink className="size-3" />{audit.final_url}</a> : null}
            {audit.technologies.length ? <span className="text-muted sm:col-span-3">{t("audit.technologies")}: {audit.technologies.map((x) => x.name).join(", ")}</span> : null}
            <span className="text-muted sm:col-span-3">{t("common.created")}: <DateText value={audit.created_at} withTime /></span>
          </Card>
          <LighthouseCard audit={audit} />
          <Screenshots audit={audit} />
          <FindingList findings={audit.findings} showPassed={showPassed} />
        </>
      ) : <Skeleton className="h-40 w-full" />}
    </div>
  );
}

export function TrackingPanel({ companyId }: { companyId: string }) {
  const t = useTranslations();
  const { data: audits } = useLatestAudit(companyId);
  const current = audits?.[0]?.id ?? null;
  const { data: audit } = useApi<AuditDetail>(["audit", current], current ? `/audits/${current}` : null);
  if (!audit) return <EmptyState title={t("audit.noAudit")} />;
  return <TrackingTable audit={audit} />;
}
