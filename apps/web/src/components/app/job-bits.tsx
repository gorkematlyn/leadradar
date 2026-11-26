"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Pause, Play, RotateCcw, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/misc";
import { useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import { fmtNumber } from "@/lib/utils";

export function JobProgress({ job }: { job: Job }) {
  const t = useTranslations("jobs");
  const locale = useLocale();
  if (job.status !== "running" && !job.processed) return <span className="text-[12px] text-muted">—</span>;
  return (
    <div className="flex items-center gap-2">
      {job.status === "running" ? <Progress value={job.processed} total={job.total} /> : null}
      <span className="num text-[11px] text-muted">
        {job.total ? t("processedOf", { done: fmtNumber(job.processed, locale), total: fmtNumber(job.total, locale) }) : t("processed", { count: fmtNumber(job.processed, locale) })}
      </span>
    </div>
  );
}

export function JobActions({ job }: { job: Job }) {
  const t = useTranslations("jobs");
  const qc = useQueryClient();
  const err = useErrorMessage();
  const run = async (action: string) => {
    try {
      await api(`/jobs/${job.id}/action`, { body: { action } });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["job", job.id] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <div className="flex justify-end gap-1">
      {["queued", "running", "paused"].includes(job.status) && !job.cancel_requested ? <Button size="sm" variant="ghost" onClick={() => run("cancel")}><X />{t("cancel")}</Button> : null}
      {job.status === "queued" ? <Button size="sm" variant="ghost" onClick={() => run("pause")}><Pause />{t("pause")}</Button> : null}
      {job.status === "paused" ? <Button size="sm" variant="ghost" onClick={() => run("resume")}><Play />{t("resume")}</Button> : null}
      {["failed", "dead", "cancelled"].includes(job.status) ? <Button size="sm" variant="ghost" onClick={() => run("retry")}><RotateCcw />{t("retry")}</Button> : null}
    </div>
  );
}
