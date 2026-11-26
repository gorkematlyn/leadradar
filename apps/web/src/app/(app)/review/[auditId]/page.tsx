"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader, ScoreValue } from "@/components/app/bits";
import { FindingList, LighthouseCard, Screenshots, TrackingTable } from "@/components/company/audit-panel";
import { Breakdown } from "@/components/company/score-panel";
import type { AuditDetail, CompanyDetail } from "@/components/company/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, Skeleton } from "@/components/ui/misc";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const ANSWERS = ["yes", "no", "unknown", "not_applicable"] as const;

export default function ReviewPage() {
  const t = useTranslations();
  const locale = useLocale();
  const { auditId } = useParams<{ auditId: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data: audit } = useApi<AuditDetail>(["audit", auditId], `/audits/${auditId}`);
  const { data: company } = useApi<CompanyDetail>(["company", audit?.company?.id], audit?.company ? `/companies/${audit.company.id}` : null);
  const [answers, setAnswers] = useState<Record<string, { answer: string; note: string }>>({});
  const [validations, setValidations] = useState<Record<number, boolean | null>>({});
  const [approved, setApproved] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (audit) {
      setAnswers(Object.fromEntries(Object.entries(audit.responses).map(([k, v]) => [k, { answer: v.answer, note: v.note ?? "" }])));
      setApproved(audit.screenshots.filter((s) => s.approved_for_reports).map((s) => s.id));
      setValidations(Object.fromEntries(audit.findings.filter((f) => f.admin_validated !== null).map((f) => [f.id, f.admin_validated])));
    }
  }, [audit]);

  const submit = async (finalize: boolean) => {
    if (!audit) return;
    setBusy(true);
    try {
      await api(`/audits/${auditId}/review`, {
        body: {
          answers: Object.entries(answers).filter(([, v]) => v.answer).map(([k, v]) => ({ question_key: k, answer: v.answer, note: v.note || null })),
          finding_validations: validations,
          approve_evidence: approved,
          finalize,
        },
      });
      toast.success(finalize ? t("review.completed") : t("common.saved"));
      qc.invalidateQueries({ queryKey: ["audit", auditId] });
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      if (finalize && audit.company) router.push(`/companies/${audit.company.id}?tab=score`);
    } catch (e) {
      toast.error(err(e));
    } finally {
      setBusy(false);
    }
  };

  if (!audit) return <Skeleton className="h-64 w-full" />;
  return (
    <>
      <PageHeader
        title={`${t("review.reviewAudit")}: ${audit.company?.name ?? ""}`}
        description={t("review.subjectiveNote")}
        actions={
          <>
            {audit.company ? <Button size="sm" asChild><Link href={`/companies/${audit.company.id}`}>{t("nav.companies")}</Link></Button> : null}
            <Button size="sm" disabled={busy} onClick={() => submit(false)}>{t("review.saveDraft")}</Button>
            <Button size="sm" variant="primary" disabled={busy || audit.status === "completed"} onClick={() => submit(true)}>{t("review.complete")}</Button>
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="grid content-start gap-4">
          <Screenshots audit={audit} selectable selected={approved} onToggle={(id) => setApproved(approved.includes(id) ? approved.filter((x) => x !== id) : [...approved, id])} />
          <LighthouseCard audit={audit} />
          <div>
            <p className="mb-2 text-[13px] font-semibold">{t("review.validateFindings")}</p>
            <FindingList findings={audit.findings.map((f) => ({ ...f, admin_validated: f.id in validations ? validations[f.id] : f.admin_validated }))} showPassed={false}
              onValidate={(id, v) => setValidations({ ...validations, [id]: v })} />
          </div>
          <TrackingTable audit={audit} />
        </div>
        <div className="grid content-start gap-4 xl:sticky xl:top-16">
          <Card>
            <CardHeader title={t("review.questions")} />
            <ol className="divide-y divide-border">
              {audit.questions.map((q) => (
                <li key={q.key} className="grid gap-2 px-4 py-3">
                  <p className="text-[13px]">{locale === "tr" ? q.text_tr : q.text_en}</p>
                  <div className="flex gap-1" role="radiogroup" aria-label={q.key}>
                    {ANSWERS.map((a) => (
                      <button key={a} type="button" role="radio" aria-checked={answers[q.key]?.answer === a}
                        onClick={() => setAnswers({ ...answers, [q.key]: { answer: a, note: answers[q.key]?.note ?? "" } })}
                        className={cn("h-7 rounded-md border border-border px-2.5 text-[12px]", answers[q.key]?.answer === a ? "border-accent bg-accent text-accent-foreground" : "hover:bg-surface-2")}>
                        {t(`review.answers.${a}`)}
                      </button>
                    ))}
                  </div>
                  <Input placeholder={t("review.note")} value={answers[q.key]?.note ?? ""} onChange={(e) => setAnswers({ ...answers, [q.key]: { answer: answers[q.key]?.answer ?? "", note: e.target.value } })} />
                </li>
              ))}
            </ol>
          </Card>
          {company?.score ? (
            <Card>
              <CardHeader title={t("review.preliminaryScore")} actions={<ScoreValue score={company.score.score} provisional />} />
              <div className="p-3"><Breakdown b={company.score.breakdown} /></div>
            </Card>
          ) : null}
          {company?.score?.breakdown.recommendations.length ? (
            <Card>
              <CardHeader title={t("review.preliminaryRecommendations")} />
              <ul className="divide-y divide-border">
                {company.score.breakdown.recommendations.slice(0, 10).map((r) => (
                  <li key={r.rule} className="px-4 py-2 text-[12px]">{locale === "tr" ? r.text_tr : r.text_en}</li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}
