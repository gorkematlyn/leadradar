"use client";

import { useLocale, useTranslations } from "next-intl";
import { Badge, Tooltip } from "@/components/ui/misc";
import { useCountries, useCrmStatuses, useIndustries, useLocalizedName } from "@/hooks/use-catalog";
import { cn } from "@/lib/utils";

export function Flag({ code, className }: { code: string | null | undefined; className?: string }) {
  if (!code) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={`/flags/${code.toLowerCase()}.svg`} alt="" width={16} height={12} className={cn("inline-block h-3 w-4 shrink-0 rounded-[2px] border border-border object-cover", className)} />
  );
}

export function CountryLabel({ code, short }: { code: string | null | undefined; short?: boolean }) {
  const { data } = useCountries();
  const name = useLocalizedName();
  if (!code) return <span className="text-muted">—</span>;
  const c = data?.find((x) => x.iso2 === code);
  return (
    <span className="inline-flex items-center gap-1.5">
      <Flag code={c?.flag ?? code} />
      <span>{short ? code : name(c) ?? code}</span>
    </span>
  );
}

export function IndustryLabel({ industryKey }: { industryKey: string | null | undefined }) {
  const { data } = useIndustries();
  const name = useLocalizedName();
  if (!industryKey) return <span className="text-muted">—</span>;
  const i = data?.find((x) => x.key === industryKey);
  return <span>{i ? name(i) : industryKey}</span>;
}

export function ScoreValue({ score, provisional, size = "md" }: { score: number | null | undefined; provisional?: boolean; size?: "md" | "lg" }) {
  if (score === null || score === undefined) return <span className="text-muted">—</span>;
  const tone = score >= 80 ? "text-foreground font-semibold" : score >= 60 ? "text-foreground" : "text-muted";
  return (
    <span className={cn("num inline-flex items-baseline gap-1", tone, size === "lg" && "text-[28px] leading-none")}>
      {score}
      {provisional ? <span className="text-[10px] font-normal text-muted">*</span> : null}
    </span>
  );
}

export function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div className="h-full rounded-full bg-foreground/70" style={{ width: `${Math.min(100, (value / max) * 100)}%` }} />
    </div>
  );
}

const ANALYSIS_TONE: Record<string, string> = {
  not_analyzed: "neutral", queued: "info", running: "info", action_required: "warning", completed: "success", failed: "danger", cancelled: "neutral",
};

export function AnalysisBadge({ status }: { status: string }) {
  const t = useTranslations("analysisStatus");
  return <Badge tone={ANALYSIS_TONE[status] ?? "neutral"}>{t.has(status) ? t(status) : status}</Badge>;
}

export function CrmBadge({ status }: { status: string }) {
  const { data } = useCrmStatuses();
  const name = useLocalizedName();
  const s = data?.find((x) => x.key === status);
  const tone = status === "won" ? "success" : status === "lost" || status === "do_not_contact" ? "danger" : status === "new" ? "neutral" : "solid";
  return <Badge tone={tone}>{s ? name(s) : status}</Badge>;
}

export function WebsiteStatusBadge({ status }: { status: string }) {
  const t = useTranslations("websiteStatus");
  const tone = status === "verified" ? "success" : status === "verified_absent" ? "warning" : "neutral";
  return <Badge tone={tone}>{t(status)}</Badge>;
}

export function ResultBadge({ result }: { result: string }) {
  const t = useTranslations("result");
  const tone = result === "passed" || result === "detected" ? "success" : result === "failed" ? "danger" : result === "blocked" || result === "error" ? "warning" : "neutral";
  return <Badge tone={tone}>{t.has(result) ? t(result) : result}</Badge>;
}

export function ClassificationBadge({ value }: { value: string | null | undefined }) {
  const t = useTranslations("score.classification");
  if (!value) return null;
  const tone = value === "high_priority" ? "accent" : value === "strong_potential" ? "solid" : value === "excluded" ? "danger" : "neutral";
  return <Badge tone={tone}>{t(value)}</Badge>;
}

export function JobStatusBadge({ status }: { status: string }) {
  const t = useTranslations("jobs.status");
  const tone = status === "completed" ? "success" : status === "running" ? "info" : status === "failed" || status === "dead" ? "danger" : status === "waiting_review" ? "warning" : "neutral";
  return <Badge tone={tone}>{t.has(status) ? t(status) : status}</Badge>;
}

const TAG_COLORS: Record<string, string> = {
  neutral: "border-border text-foreground",
  lime: "border-[#7c9a2e]/50 text-[#4d6315] dark:text-[#c5f35c]",
  blue: "border-info/40 text-info",
  amber: "border-warning/40 text-warning",
  red: "border-danger/40 text-danger",
  violet: "border-[#7a5ba8]/40 text-[#6b4c9a] dark:text-[#c4a8ee]",
  teal: "border-[#2d7f7a]/40 text-[#22706b] dark:text-[#7fd1ca]",
};

/** Tag label in the active language. Tags are identified by ID; the name is only for display. */
export function TagChip({ tag }: { tag: { name_en: string; name_tr: string; color: string } }) {
  const locale = useLocale();
  const name = (locale === "tr" ? tag.name_tr : tag.name_en) || tag.name_en || tag.name_tr || "…";
  return <span className={cn("inline-flex h-5 items-center rounded-sm border px-1.5 text-[11px]", TAG_COLORS[tag.color] ?? TAG_COLORS.neutral)}>{name}</span>;
}

export function PlatformChips({ platforms }: { platforms: string[] }) {
  const t = useTranslations("ads.platforms");
  if (!platforms.length) return <span className="text-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {platforms.map((p) => (
        <Badge key={p} tone="solid">{t.has(p) ? t(p) : p}</Badge>
      ))}
    </span>
  );
}

export function DateText({ value, withTime }: { value: string | null | undefined; withTime?: boolean }) {
  const locale = useLocale();
  if (!value) return <span className="text-muted">—</span>;
  const d = new Date(value);
  const text = new Intl.DateTimeFormat(locale === "tr" ? "tr-TR" : "en-GB", { dateStyle: "medium", ...(withTime ? { timeStyle: "short" } : {}) }).format(d);
  return (
    <Tooltip content={d.toISOString()}>
      <span className="num whitespace-nowrap text-[12px]">{text}</span>
    </Tooltip>
  );
}

export function PageHeader({ title, description, actions }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-[18px] font-semibold tracking-tight">{title}</h1>
        {description ? <p className="mt-0.5 text-[13px] text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function KeyValue({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3 border-t border-border py-2 text-[13px] first:border-t-0">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}
