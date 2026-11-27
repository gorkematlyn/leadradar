"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Pause, Play, X } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Flag } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader, InfoTip, Progress, Tooltip } from "@/components/ui/misc";
import { ConfirmDialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useLocalizedName, useRegions, useSortByName } from "@/hooks/use-catalog";
import { api } from "@/lib/api";
import type { ImportProgress } from "@/lib/types";
import { fmtBytes } from "@/lib/utils";

export const ACTIVE_IMPORT = ["queued", "planning", "running", "paused"];

export function importTone(status: string): string {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "partial") return "warning";
  if (["running", "queued", "planning"].includes(status)) return "info";
  return "neutral";
}

export function ImportStatusBadge({ status }: { status: string }) {
  const t = useTranslations("discovery.importStatuses");
  return <Badge tone={importTone(status)}>{t.has(status) ? t(status) : status}</Badge>;
}

/** "3/10 regions" + byte progress bar + what is happening right now. */
export function ImportProgressLine({ progress, compact }: { progress: ImportProgress; compact?: boolean }) {
  const t = useTranslations("discovery");
  const locale = useLocale();
  const p = progress;
  const active = ACTIVE_IMPORT.includes(p.status);
  if (!p.regions_total) {
    return active ? <span className="text-[11px] text-muted">{t("planningRegions")}</span> : null;
  }
  const cur = p.current;
  return (
    <div className="grid min-w-0 gap-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted">
        <span className="num text-foreground">{t("regionsProgress", { done: p.regions_done, total: p.regions_total })}</span>
        {p.regions_failed ? <span className="text-danger">{t("regionsFailed", { count: p.regions_failed })}</span> : null}
        {p.bytes_total ? <span className="num">{fmtBytes(p.bytes_done ?? 0, locale)} / {fmtBytes(p.bytes_total, locale)}</span> : null}
      </div>
      <Progress className={compact ? "w-full max-w-48" : "w-full"} value={p.bytes_total ? p.bytes_done ?? 0 : p.regions_done} total={p.bytes_total || p.regions_total}
        tone={p.status === "failed" ? "danger" : p.status === "paused" || p.status === "cancelled" ? "muted" : undefined} />
      {cur && !compact ? (
        <span className="truncate text-[11px] text-muted">
          {cur.stage === "download" ? t("downloading", { name: cur.name ?? "" }) : t("processing", { name: cur.name ?? "" })}
        </span>
      ) : null}
    </div>
  );
}

/** Cancel / pause / resume all jobs of a country's current import. */
export function CountryImportActions({ iso2, countryName, status }: { iso2: string; countryName: string; status: string }) {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const [confirm, setConfirm] = useState(false);
  const run = async (action: "cancel" | "pause" | "resume") => {
    try {
      await api(`/discovery/countries/${iso2}/action`, { body: { action } });
      ["countries", "discovery-progress", "imports", "jobs"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    } catch (e) {
      toast.error(err(e));
    }
  };
  if (!ACTIVE_IMPORT.includes(status)) return null;
  return (
    <span className="inline-flex items-center gap-0.5">
      {status === "paused" ? (
        <Tooltip content={t("discovery.resumeImport")}><Button size="icon-sm" variant="ghost" aria-label={t("discovery.resumeImport")} onClick={() => run("resume")}><Play /></Button></Tooltip>
      ) : (
        <Tooltip content={`${t("discovery.pauseImport")} — ${t("discovery.pauseInfo")}`}><Button size="icon-sm" variant="ghost" aria-label={t("discovery.pauseImport")} onClick={() => run("pause")}><Pause /></Button></Tooltip>
      )}
      <Tooltip content={t("discovery.cancelImport")}><Button size="icon-sm" variant="ghost" aria-label={t("discovery.cancelImport")} onClick={() => setConfirm(true)}><X /></Button></Tooltip>
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title={t("discovery.cancelImport")} danger
        message={t("discovery.cancelCountryConfirm", { country: countryName })}
        confirmLabel={t("discovery.cancelImport")} cancelLabel={t("common.close")} onConfirm={() => run("cancel")} />
    </span>
  );
}

interface ProgressRow extends ImportProgress { iso2: string; name_en: string; name_tr: string; region: string; flag: string }

/** Import progress grouped by continent: one box per continent, one bar per country. */
export function ImportProgressPanel({ onlyActive, className }: { onlyActive?: boolean; className?: string }) {
  const t = useTranslations();
  const name = useLocalizedName();
  const sortByName = useSortByName();
  const { data: regions } = useRegions();
  const { data } = useApi<ProgressRow[]>(["discovery-progress"], "/discovery/progress", {
    refetchInterval: (d) => (d?.some((r) => ACTIVE_IMPORT.includes(r.status)) ? 5_000 : 30_000),
  });
  const rows = (data ?? []).filter((r) => !onlyActive || ACTIVE_IMPORT.includes(r.status));
  if (!rows.length) return null;
  const groups = (regions ?? []).map((r) => ({ region: r, items: sortByName(rows.filter((x) => x.region === r.code)) })).filter((g) => g.items.length);
  const other = rows.filter((x) => !(regions ?? []).some((r) => r.code === x.region));
  return (
    <Card className={className}>
      <CardHeader title={<span className="flex items-center gap-1">{t("discovery.progressTitle")}<InfoTip>{t("discovery.progressInfo")}</InfoTip></span>}
        actions={<Button asChild size="sm" variant="ghost"><Link href="/discovery">{t("nav.discovery")}</Link></Button>} />
      <div className="grid gap-3 p-3 md:grid-cols-2 xl:grid-cols-3">
        {[...groups, ...(other.length ? [{ region: { code: "other", name_en: "Other", name_tr: "Diğer" }, items: other }] : [])].map((g) => (
          <div key={g.region.code} className="rounded-md border border-border">
            <p className="border-b border-border px-3 py-1.5 text-[12px] font-medium">{name(g.region)} <span className="num text-muted">({g.items.length})</span></p>
            <ul className="divide-y divide-border">
              {g.items.map((r) => (
                <li key={r.iso2} className="grid gap-1 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2 text-[13px]">
                    <Flag code={r.flag} />
                    <span className="min-w-0 flex-1 truncate">{name(r)}</span>
                    <ImportStatusBadge status={r.status} />
                    <CountryImportActions iso2={r.iso2} countryName={name(r)} status={r.status} />
                  </div>
                  <ImportProgressLine progress={r} />
                  {r.error && ["failed", "partial"].includes(r.status) ? (
                    <Link href={`/jobs/${r.job_id}`} className="truncate text-[11px] text-danger hover:underline" title={r.error}>{r.error}</Link>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  );
}
