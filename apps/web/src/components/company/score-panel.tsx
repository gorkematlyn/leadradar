"use client";

import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { ClassificationBadge, DateText, ScoreBar, ScoreValue } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { Badge, Card, CardHeader, EmptyState } from "@/components/ui/misc";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { CompanyDetail, ScoreBreakdown, ScoreRuleView } from "./types";

function RuleRow({ r }: { r: ScoreRuleView }) {
  const locale = useLocale();
  return (
    <li className="flex items-start justify-between gap-3 py-1.5 text-[13px]">
      <div className="min-w-0">
        <p>{locale === "tr" ? r.title_tr : r.title_en}</p>
        <p className="num text-[11px] text-muted">{r.signal}{r.evidence.length ? ` · ${r.evidence.slice(0, 3).join(", ")}` : ""}</p>
      </div>
      <span className={`num shrink-0 ${r.points < 0 ? "text-danger" : ""}`}>{r.points > 0 ? "+" : ""}{r.points}</span>
    </li>
  );
}

export function Breakdown({ b }: { b: ScoreBreakdown }) {
  const t = useTranslations("score");
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-2">
        {Object.entries(b.categories).map(([cat, c]) => (
          <Card key={cat} className="p-3">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-[13px] font-medium">{t(`category.${cat}`)}</span>
              <span className="num text-[13px]">{c.score} <span className="text-muted">/ {c.limit}</span>{c.capped ? <Badge className="ml-2">{t("capped")} ({c.raw})</Badge> : null}</span>
            </div>
            <ScoreBar value={c.score} max={c.limit || 1} />
            <ul className="mt-2 divide-y divide-border">{c.rules.map((r) => <RuleRow key={r.key} r={r} />)}</ul>
          </Card>
        ))}
      </div>
      {b.penalties.length ? (
        <Card className="p-3">
          <p className="mb-1 text-[13px] font-medium">{t("penalties")} <span className="num text-danger">−{b.penalty_total}</span></p>
          <ul className="divide-y divide-border">{b.penalties.map((r) => <RuleRow key={r.key} r={r} />)}</ul>
        </Card>
      ) : null}
      {b.exclusions.length ? (
        <Card className="border-danger/40 p-3">
          <p className="mb-1 text-[13px] font-medium text-danger">{t("exclusions")}</p>
          <ul className="divide-y divide-border">{b.exclusions.map((r) => <RuleRow key={r.key} r={r} />)}</ul>
        </Card>
      ) : null}
      {b.suppressed_overlaps.length ? (
        <p className="text-[12px] text-muted">{t("suppressed")}: {b.suppressed_overlaps.map((s) => s.key).join(", ")}</p>
      ) : null}
      <p className="num text-[11px] text-muted">{t("formula")}: {b.formula}</p>
    </div>
  );
}

export function Confidence({ b }: { b: ScoreBreakdown }) {
  const t = useTranslations("score");
  return (
    <Card className="p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[13px] font-medium">{t("confidence")}</span>
        <span className="num text-[16px]">{b.confidence.score}</span>
      </div>
      <ul className="grid gap-2">
        {Object.entries(b.confidence.components).map(([k, v]) => (
          <li key={k} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 text-[12px]">
            <span className="text-muted">{t(`components.${k}`)}</span>
            <span className="num">{Math.round(v.value * 100)}% · w{v.weight}</span>
            <div className="col-span-2"><ScoreBar value={v.value * 100} /></div>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[12px] text-muted">{t("confidenceNote")}</p>
    </Card>
  );
}

export function ScorePanel({ company }: { company: CompanyDetail }) {
  const t = useTranslations();
  const locale = useLocale();
  const { data: profiles } = useApi<{ key: string; name_en: string; name_tr: string }[]>(["scoring-profiles"], "/scoring/profiles");
  const [compare, setCompare] = useState("");
  const [preview, setPreview] = useState<{ score: number; classification: string; breakdown: ScoreBreakdown } | null>(null);
  const s = company.score;
  if (!s) return <EmptyState title={t("score.noScore")} description={t("score.noScoreHint")} />;
  const runCompare = async (key: string) => {
    setCompare(key);
    setPreview(key ? await api(`/companies/${company.id}/preview-score`, { body: { profile_key: key } }) : null);
  };
  const shown = preview?.breakdown ?? s.breakdown;
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader
          title={t("score.leadScore")}
          description={`${t(s.stage === "final" ? "score.final" : "score.preliminary")} · ${t("score.ruleVersion", { version: s.profile_version })}`}
          actions={
            <NativeSelect className="h-7 w-auto" value={compare} onChange={(e) => runCompare(e.target.value)} aria-label={t("company.compareProfile")}>
              <option value="">{t("company.compareProfile")}</option>
              {profiles?.map((p) => <option key={p.key} value={p.key}>{locale === "tr" ? p.name_tr : p.name_en}</option>)}
            </NativeSelect>
          }
        />
        <div className="flex flex-wrap items-center gap-6 px-4 py-4">
          <div className="flex items-baseline gap-2"><ScoreValue score={preview?.score ?? s.score} size="lg" /><span className="text-muted">/ 100</span></div>
          <ClassificationBadge value={preview?.classification ?? s.classification} />
          {company.override ? <Badge tone="warning">{t("company.overrideActive", { score: company.override.score, original: company.override.original ?? "—" })}</Badge> : null}
          <span className="text-[12px] text-muted">{t("score.calculatedAt", { date: "" })}<DateText value={s.calculated_at} withTime /></span>
          {preview ? <Button size="sm" variant="ghost" onClick={() => runCompare("")}>{t("common.reset")}</Button> : null}
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Breakdown b={shown} />
        <div className="grid content-start gap-4">
          <Confidence b={shown} />
          <p className="text-[12px] text-muted">{t("score.adsNote")}</p>
          <p className="text-[12px] text-muted">{t("score.contactabilityNote")}</p>
        </div>
      </div>
    </div>
  );
}

export function ServicesPanel({ company }: { company: CompanyDetail }) {
  const t = useTranslations();
  const locale = useLocale();
  const recs = company.score?.breakdown.recommendations ?? [];
  if (!company.service_scores_detail.length) return <EmptyState title={t("services.noOpportunities")} />;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title={t("company.tabs.services")} description={t("services.provisionalNote")} />
        <ul className="divide-y divide-border">
          {company.service_scores_detail.map((s) => (
            <li key={s.service} className="grid grid-cols-[1fr_120px_40px] items-center gap-3 px-4 py-2 text-[13px]">
              <span>{t(`services.${s.service}`)} {s.provisional ? <Badge className="ml-1">{t("common.provisional")}</Badge> : null}</span>
              <ScoreBar value={s.score} />
              <span className="num text-right">{s.score}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHeader title={t("services.recommendations")} />
        <ul className="divide-y divide-border">
          {recs.map((r) => (
            <li key={r.rule} className="px-4 py-2 text-[13px]">
              <p>{locale === "tr" ? r.text_tr : r.text_en}</p>
              <p className="text-[11px] text-muted">{t(`services.${r.service}`)} · +{r.points}{r.provisional ? ` · ${t("common.provisional")}` : ""}</p>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
