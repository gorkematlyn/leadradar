"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { DateText } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge, Card, CardHeader, EmptyState } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";

interface EvidenceItem {
  id: string; kind: string; label: string; source_url: string | null; selector: string | null; data: Record<string, unknown>;
  blob_id: string | null; detection_method: string | null; rule_version: number | null; confidence: number | null;
  limitations: string | null; viewport: string | null; created_at: string; finding_id: number | null;
}

export function EvidencePanel({ companyId }: { companyId: string }) {
  const t = useTranslations("evidence");
  const { data } = useApi<EvidenceItem[]>(["evidence", companyId], `/evidence?company_id=${companyId}`);
  if (!data?.length) return <EmptyState title={t("noEvidence")} />;
  return (
    <Card>
      <CardHeader title={t("title")} description={t("sanitized")} />
      <ul className="divide-y divide-border">
        {data.map((e) => (
          <li key={e.id} className="grid gap-1 px-4 py-3 text-[13px]">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="solid">{t.has(`kind.${e.kind}`) ? t(`kind.${e.kind}`) : e.kind}</Badge>
              <span className="font-medium">{e.label}</span>
              {e.viewport ? <Badge>{e.viewport}</Badge> : null}
              <span className="ml-auto"><DateText value={e.created_at} withTime /></span>
            </div>
            <div className="flex flex-wrap gap-x-4 text-[11px] text-muted">
              {e.detection_method ? <span>{t("method")}: {e.detection_method}</span> : null}
              {e.rule_version ? <span>{t("ruleVersion")}: v{e.rule_version}</span> : null}
              {e.selector ? <span className="num">{t("selector")}: {e.selector}</span> : null}
              {e.source_url ? <a href={e.source_url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 hover:underline"><ExternalLink className="size-3" />{e.source_url.slice(0, 80)}</a> : null}
            </div>
            {e.limitations ? <p className="text-[11px] text-warning">{t("limitations")}: {e.limitations}</p> : null}
            {e.blob_id && e.kind === "screenshot" ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={`/api/blobs/${e.blob_id}`} alt={e.label} className="mt-1 max-h-64 w-auto rounded-md border border-border" loading="lazy" />
            ) : null}
            {Object.keys(e.data).length ? (
              <pre className="num mt-1 max-h-48 overflow-auto rounded-md border border-border bg-surface-2 p-2 text-[11px] leading-snug">{JSON.stringify(e.data, null, 2).slice(0, 4000)}</pre>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

interface Activity { id: string; kind: string; title: string | null; body: string | null; data: Record<string, unknown>; occurred_at: string; due_at: string | null; completed: boolean }

export function ActivityPanel({ companyId }: { companyId: string }) {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useApi<Activity[]>(["activities", companyId], `/companies/${companyId}/activities`);
  const [form, setForm] = useState({ kind: "note", title: "", body: "", due_at: "" });
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api(`/companies/${companyId}/activities`, {
        body: { kind: form.kind, title: form.title || null, body: form.body || null, due_at: form.due_at ? new Date(form.due_at).toISOString() : null },
      });
      setForm({ kind: "note", title: "", body: "", due_at: "" });
      qc.invalidateQueries({ queryKey: ["activities", companyId] });
      qc.invalidateQueries({ queryKey: ["company", companyId] });
    } catch (e2) {
      toast.error(err(e2));
    }
  };
  const toggle = async (id: string) => {
    await api(`/companies/${companyId}/activities/${id}`, { method: "PATCH", body: {} });
    qc.invalidateQueries({ queryKey: ["activities", companyId] });
  };
  return (
    <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <Card className="h-fit">
        <CardHeader title={t("crm.addActivity")} />
        <form onSubmit={add} className="grid gap-3 p-4">
          <Field label={t("crm.activityType")}>
            <NativeSelect value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {["note", "call", "email", "meeting", "proposal", "follow_up", "won", "lost"].map((k) => <option key={k} value={k}>{t(`crm.activity.${k}`)}</option>)}
            </NativeSelect>
          </Field>
          <Field label={t("crm.title2")}><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label={t("crm.body")}><Textarea value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></Field>
          <Field label={t("crm.dueAt")}><Input type="datetime-local" value={form.due_at} onChange={(e) => setForm({ ...form, due_at: e.target.value })} /></Field>
          <Button variant="primary" type="submit"><Plus />{t("common.add")}</Button>
        </form>
      </Card>
      <Card>
        <CardHeader title={t("crm.timeline")} />
        {!data?.length ? <EmptyState title={t("crm.noActivity")} /> : null}
        <ol className="divide-y divide-border">
          {data?.map((a) => (
            <li key={a.id} className="grid gap-0.5 px-4 py-2.5 text-[13px]">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={a.kind === "won" ? "success" : a.kind === "lost" ? "danger" : "solid"}>{t.has(`crm.activity.${a.kind}`) ? t(`crm.activity.${a.kind}`) : a.kind}</Badge>
                <span className="font-medium">{a.title}</span>
                <span className="ml-auto"><DateText value={a.occurred_at} withTime /></span>
              </div>
              {a.body ? <p className="whitespace-pre-wrap text-[12px] text-muted">{a.body}</p> : null}
              {a.due_at ? (
                <div className="flex items-center gap-2 text-[12px]">
                  <span className="text-muted">{t("crm.dueAt")}:</span><DateText value={a.due_at} withTime />
                  <Button size="sm" variant={a.completed ? "secondary" : "ghost"} onClick={() => toggle(a.id)}><Check />{t("crm.markDone")}</Button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

interface History {
  field_changes: { field: string; old: unknown; new: unknown; source: string; at: string }[];
  change_events: { id: string; category: string; field: string; before: unknown; after: unknown; significance: string; at: string }[];
  scores: { id: string; stage: string; score: number; confidence: number; classification: string; at: string; profile_version: number }[];
  merges: { merged_company_id: string; name: string; at: string }[];
}

const show = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

export function HistoryPanel({ companyId }: { companyId: string }) {
  const t = useTranslations();
  const { data } = useApi<History>(["history", companyId], `/companies/${companyId}/history`);
  if (!data) return null;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title={t("changes.title")} />
        {!data.change_events.length ? <EmptyState title={t("changes.empty")} /> : null}
        <ul className="divide-y divide-border">
          {data.change_events.map((e) => (
            <li key={e.id} className="grid gap-0.5 px-4 py-2 text-[13px]">
              <div className="flex items-center gap-2">
                <Badge tone={e.significance === "major" ? "warning" : "neutral"}>{t(`changes.significance.${e.significance}`)}</Badge>
                <span>{e.category} · {e.field}</span>
                <span className="ml-auto"><DateText value={e.at} /></span>
              </div>
              <p className="num text-[11px] text-muted">{t("changes.before")}: {show(e.before)} → {t("changes.after")}: {show(e.after)}</p>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHeader title={t("changes.scores")} />
        <ul className="divide-y divide-border">
          {data.scores.map((s) => (
            <li key={s.id} className="flex items-center gap-3 px-4 py-2 text-[13px]">
              <span className="num w-10">{s.score}</span>
              <span className="text-muted">{t(s.stage === "final" ? "score.final" : "score.preliminary")}</span>
              <span className="num text-[12px] text-muted">{t("score.confidence")} {s.confidence}</span>
              <span className="ml-auto"><DateText value={s.at} withTime /></span>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHeader title={t("changes.fieldChanges")} />
        <ul className="divide-y divide-border">
          {data.field_changes.map((c, i) => (
            <li key={i} className="px-4 py-2 text-[12px]">
              <span className="font-medium">{c.field}</span> <span className="text-muted">({c.source})</span>
              <p className="num text-[11px] text-muted">{show(c.old)} → {show(c.new)} · <DateText value={c.at} /></p>
            </li>
          ))}
        </ul>
      </Card>
      {data.merges.length ? (
        <Card>
          <CardHeader title={t("changes.merges")} />
          <ul className="divide-y divide-border">
            {data.merges.map((m) => <li key={m.merged_company_id} className="flex justify-between px-4 py-2 text-[13px]"><span>{m.name}</span><DateText value={m.at} /></li>)}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

export function ReportsPanel({ companyId, companyName }: { companyId: string; companyName: string }) {
  const t = useTranslations();
  const router = useRouter();
  const err = useErrorMessage();
  const { data } = useApi<{ id: string; title: string; status: string; mode: string; updated_at: string }[]>(["reports", companyId], `/reports?company_id=${companyId}`);
  const { data: templates } = useApi<{ id: string; key: string; name_en: string; name_tr: string; is_default: boolean }[]>(["report-templates"], "/report-templates");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: `${companyName} — Digital audit`, template_id: "", mode: "snapshot", language: "en" });
  const create = async () => {
    try {
      const r = await api<{ id: string }>("/reports", { body: { company_id: companyId, title: form.title, template_id: form.template_id || null, mode: form.mode, language: form.language } });
      router.push(`/reports/${r.id}`);
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <Card>
      <CardHeader title={t("reports.title")} actions={<Button size="sm" variant="primary" onClick={() => setOpen(true)}><Plus />{t("reports.new")}</Button>} />
      {!data?.length ? <EmptyState title={t("reports.empty")} description={t("reports.emptyHint")} /> : null}
      <ul className="divide-y divide-border">
        {data?.map((r) => (
          <li key={r.id} className="flex items-center gap-3 px-4 py-2 text-[13px]">
            <Link href={`/reports/${r.id}`} className="font-medium hover:underline">{r.title}</Link>
            <Badge>{t(`reports.status.${r.status}`)}</Badge>
            <span className="ml-auto"><DateText value={r.updated_at} /></span>
          </li>
        ))}
      </ul>
      <Dialog open={open} onOpenChange={setOpen} title={t("reports.new")}
        footer={<><Button onClick={() => setOpen(false)}>{t("common.cancel")}</Button><Button variant="primary" onClick={create}>{t("common.create")}</Button></>}>
        <div className="grid gap-3">
          <Field label={t("reports.titleLabel")}><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label={t("reports.template")}>
            <NativeSelect value={form.template_id} onChange={(e) => setForm({ ...form, template_id: e.target.value })}>
              <option value="">—</option>
              {templates?.map((x) => <option key={x.id} value={x.id}>{x.name_en}</option>)}
            </NativeSelect>
          </Field>
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
        </div>
      </Dialog>
    </Card>
  );
}
