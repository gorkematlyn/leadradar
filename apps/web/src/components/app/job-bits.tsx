"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Pause, Play, RotateCcw, Trash2, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/misc";
import { ConfirmDialog } from "@/components/ui/overlay";
import { useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import { fmtBytes, fmtNumber } from "@/lib/utils";

/** Stage names reported by workers (e.g. "download", "extract:nodes") in the active language. */
export function JobStage({ stage }: { stage: string | null }) {
  const t = useTranslations("jobs.stages");
  if (!stage) return <>—</>;
  const base = stage.split(":")[0];
  return <>{t.has(base) ? t(base) : stage}</>;
}

export function JobProgress({ job }: { job: Job }) {
  const t = useTranslations("jobs");
  const locale = useLocale();
  if (job.status !== "running" && !job.processed) return <span className="text-[12px] text-muted">—</span>;
  return (
    <div className="flex items-center gap-2">
      {job.status === "running" ? <Progress value={job.processed} total={job.total} /> : null}
      <span className="num text-[11px] text-muted">
        {job.stage === "download"
          ? `${fmtBytes(job.processed, locale)}${job.total ? ` / ${fmtBytes(job.total, locale)}` : ""}`
          : job.total ? t("processedOf", { done: fmtNumber(job.processed, locale), total: fmtNumber(job.total, locale) }) : t("processed", { count: fmtNumber(job.processed, locale) })}
      </span>
    </div>
  );
}

const RELATED = ["jobs", "dashboard", "notifications", "countries", "discovery-progress", "imports"];

export function JobActions({ job, onDeleted }: { job: Job; onDeleted?: () => void }) {
  const t = useTranslations("jobs");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const err = useErrorMessage();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const run = async (action: string) => {
    try {
      await api(`/jobs/${job.id}/action`, { body: { action } });
      RELATED.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      qc.invalidateQueries({ queryKey: ["job", job.id] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  const remove = async () => {
    try {
      await api("/jobs/delete", { body: { ids: [job.id] } });
      RELATED.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      onDeleted?.();
    } catch (e) {
      toast.error(err(e));
    }
  };
  const finished = ["completed", "failed", "dead", "cancelled"].includes(job.status);
  return (
    <div className="flex justify-end gap-1">
      {["queued", "running", "paused"].includes(job.status) && !job.cancel_requested ? <Button size="sm" variant="ghost" onClick={() => run("cancel")}><X />{t("cancel")}</Button> : null}
      {job.status === "queued" ? <Button size="sm" variant="ghost" onClick={() => run("pause")}><Pause />{t("pause")}</Button> : null}
      {job.status === "paused" ? <Button size="sm" variant="ghost" onClick={() => run("resume")}><Play />{t("resume")}</Button> : null}
      {["failed", "dead", "cancelled"].includes(job.status) ? <Button size="sm" variant="ghost" onClick={() => run("retry")}><RotateCcw />{t("retry")}</Button> : null}
      {finished ? <Button size="sm" variant="ghost" aria-label={t("deleteJob")} onClick={() => setConfirmDelete(true)}><Trash2 /><span className="sr-only sm:not-sr-only">{t("deleteJob")}</span></Button> : null}
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={t("deleteJob")} danger message={`${job.name} — ${tc("areYouSure")}`}
        confirmLabel={t("deleteJob")} cancelLabel={tc("cancel")} onConfirm={remove} />
    </div>
  );
}
