"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, MoreHorizontal, Play, Search } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  AnalysisBadge, ClassificationBadge, CountryLabel, CrmBadge, DateText, IndustryLabel, KeyValue, ScoreValue, TagChip, WebsiteStatusBadge,
} from "@/components/app/bits";
import { AdsPanel } from "@/components/company/ads-panel";
import { AuditPanel, TrackingPanel } from "@/components/company/audit-panel";
import { ActivityPanel, EvidencePanel, HistoryPanel, ReportsPanel } from "@/components/company/other-panels";
import { ScorePanel, ServicesPanel } from "@/components/company/score-panel";
import type { CompanyDetail } from "@/components/company/types";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge, Card, CardHeader, Checkbox, Skeleton } from "@/components/ui/misc";
import { Dialog, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Tabs } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useCountries, useIndustries, useLocalizedName, useTags } from "@/hooks/use-catalog";
import { api } from "@/lib/api";
import { CRM_STATUSES } from "@/lib/types";

type DialogKind = "edit" | "override" | "tags" | "merge" | "dnc" | "delete" | null;

function CompanyView() {
  const t = useTranslations();
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const nameOf = useLocalizedName();
  const [tab, setTab] = useState(params.get("tab") ?? "overview");
  const [dialog, setDialog] = useState<DialogKind>(null);
  const { data: c, isLoading } = useApi<CompanyDetail>(["company", id], `/companies/${id}`, { refetchInterval: 20_000 });
  const { data: tags } = useTags();
  const { data: countries } = useCountries();
  const { data: industries } = useIndustries();
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [override, setOverride] = useState({ score: "", reason: "" });
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [mergeQ, setMergeQ] = useState("");
  const [mergeHits, setMergeHits] = useState<{ id: string; name: string; city: string | null }[]>([]);
  const [text, setText] = useState("");

  useEffect(() => {
    if (c) {
      setEdit({ name: c.name, legal_name: c.legal_name ?? "", website: c.website ?? "", country: c.country ?? "", industry: c.industry ?? "",
        city: c.city ?? "", region: c.region ?? "", address: c.address ?? "", postal_code: c.postal_code ?? "", email: c.email ?? "",
        phone: c.phone ?? "", notes: c.notes ?? "" });
      setTagIds(c.tags.map((x) => x.id));
    }
  }, [c]);
  useEffect(() => {
    if (dialog !== "merge" || mergeQ.length < 2) return;
    const h = setTimeout(async () => {
      const res = await api<{ items: { id: string; name: string; city: string | null }[] }>("/companies/query", { body: { filter: { q: mergeQ, dnc: "include" }, page_size: 10 } });
      setMergeHits(res.items.filter((x) => x.id !== id));
    }, 250);
    return () => clearTimeout(h);
  }, [mergeQ, dialog, id]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["company", id] });
    qc.invalidateQueries({ queryKey: ["audits", id] });
    qc.invalidateQueries({ queryKey: ["companies"] });
  };
  const act = async (fn: () => Promise<unknown>, success?: string) => {
    try {
      await fn();
      if (success) toast.success(success);
      refresh();
      return true;
    } catch (e) {
      toast.error(err(e));
      return false;
    }
  };
  const patch = (body: Record<string, unknown>) => act(() => api(`/companies/${id}`, { method: "PATCH", body }), t("common.saved"));

  if (isLoading || !c) return <Skeleton className="h-64 w-full" />;
  const latestAuditPending = c.analysis_status === "action_required";
  return (
    <>
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-[12px] text-muted">
            <Link href="/companies" className="hover:underline">{t("nav.companies")}</Link>
            <span>/</span>
          </div>
          <h1 className="text-[20px] font-semibold tracking-tight">{c.name}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[13px]">
            <CountryLabel code={c.country} />
            <span className="text-muted">·</span>
            <IndustryLabel industryKey={c.industry} />
            {c.industry_confidence === "review" ? <Badge tone="warning">{t("company.industryReview")}</Badge> : null}
            {c.website ? <a href={c.website} target="_blank" rel="noopener noreferrer nofollow" className="num inline-flex items-center gap-1 text-[12px] text-muted hover:underline"><ExternalLink className="size-3" />{c.domain ?? c.website}</a> : null}
            <WebsiteStatusBadge status={c.website_status} />
            <CrmBadge status={c.crm_status} />
            <AnalysisBadge status={c.analysis_status} />
            {c.tags.map((x) => <TagChip key={x.id} name={x.name} color={x.color} />)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="mr-2 flex items-baseline gap-2">
            <ScoreValue score={c.lead_score} size="lg" provisional={c.final_score === null && c.lead_score !== null} />
            <div className="grid text-[11px] text-muted">
              <ClassificationBadge value={c.classification} />
              <span>{t("score.confidence")} <span className="num">{c.confidence ?? "—"}</span></span>
            </div>
          </div>
          {latestAuditPending ? <Button size="sm" variant="primary" onClick={() => setTab("audit")}>{t("company.actions.review")}</Button> : null}
          <Button size="sm" disabled={!c.website} onClick={() => act(() => api(`/companies/${id}/audits`, { body: { mode: "full" } }), t("quickAudit.started"))}><Play />{t("company.actions.runAudit")}</Button>
          <Button size="sm" onClick={() => act(() => api(`/companies/${id}/ad-research`, { body: {} }), t("ads.queued"))}><Search />{t("company.actions.researchAds")}</Button>
          <Menu>
            <MenuTrigger asChild><Button size="icon" aria-label={t("common.more")}><MoreHorizontal /></Button></MenuTrigger>
            <MenuContent>
              <MenuItem disabled={!c.website} onSelect={() => act(() => api(`/companies/${id}/audits`, { body: { mode: "quick" } }), t("quickAudit.started"))}>{t("company.actions.runQuick")}</MenuItem>
              <MenuItem onSelect={() => act(() => api(`/companies/${id}/run-all`, { body: {} }), t("quickAudit.started"))}>{t("company.actions.runAll")}</MenuItem>
              <MenuItem onSelect={() => act(() => api(`/companies/${id}/recalculate`, { body: {} }), t("company.recalculated"))}>{t("company.actions.recalculate")}</MenuItem>
              <MenuItem onSelect={() => setDialog("override")}>{t("company.actions.override")}</MenuItem>
              <MenuSeparator />
              <MenuItem onSelect={() => setDialog("edit")}>{t("common.edit")}</MenuItem>
              <MenuItem onSelect={() => setDialog("tags")}>{t("company.actions.manageTags")}</MenuItem>
              <MenuItem onSelect={() => setTab("activity")}>{t("company.actions.addNote")}</MenuItem>
              <MenuItem onSelect={() => setTab("reports")}>{t("company.actions.createReport")}</MenuItem>
              <MenuItem onSelect={() => patch({ watchlisted: !c.watchlisted })}>{c.watchlisted ? t("company.actions.unwatch") : t("company.actions.watch")}</MenuItem>
              {!c.website ? <MenuItem onSelect={() => act(() => api(`/companies/${id}/verify-website`, { body: { absent: true } }), t("common.saved"))}>{t("company.actions.verifyNoWebsite")}</MenuItem> : null}
              {c.website_status === "verified_absent" ? <MenuItem onSelect={() => act(() => api(`/companies/${id}/verify-website`, { body: { absent: false } }), t("common.saved"))}>{t("company.actions.verifyHasWebsite")}</MenuItem> : null}
              <MenuSeparator />
              <MenuItem onSelect={() => setDialog("merge")}>{t("company.actions.merge")}</MenuItem>
              <MenuItem onSelect={() => patch({ archived: !c.archived })}>{c.archived ? t("company.actions.unarchive") : t("company.actions.archive")}</MenuItem>
              {!c.do_not_contact ? <MenuItem danger onSelect={() => setDialog("dnc")}>{t("company.actions.dnc")}</MenuItem> : null}
              <MenuItem danger onSelect={() => setDialog("delete")}>{t("company.actions.delete")}</MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </div>

      {c.do_not_contact ? (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-danger/40 px-3 py-2 text-[13px] text-danger"><AlertTriangle className="size-4" />{t("company.dncBanner")}</div>
      ) : null}
      {c.website_status === "not_found" ? (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2 text-[13px] text-muted">
          {t("company.noWebsiteNote")}
          <Button size="sm" onClick={() => act(() => api(`/companies/${id}/verify-website`, { body: { absent: true } }), t("common.saved"))}>{t("company.actions.verifyNoWebsite")}</Button>
        </div>
      ) : null}

      <Tabs
        value={tab}
        onValueChange={(v) => { setTab(v); router.replace(`/companies/${id}?tab=${v}`, { scroll: false }); }}
        tabs={["overview", "score", "services", "audit", "tracking", "advertising", "evidence", "activity", "history", "reports"].map((v) => ({ value: v, label: t(`company.tabs.${v}`) }))}
      />
      <div className="mt-4">
        {tab === "overview" ? (
          <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
            <Card>
              <CardHeader title={t("company.info")} actions={<Button size="sm" variant="ghost" onClick={() => setDialog("edit")}>{t("common.edit")}</Button>} />
              <dl className="px-4 py-2">
                <KeyValue label={t("company.legalName")}>{c.legal_name ?? "—"}</KeyValue>
                <KeyValue label={t("company.address")}>{[c.address, c.postal_code, c.city, c.region].filter(Boolean).join(", ") || "—"}</KeyValue>
                <KeyValue label={t("company.email")}>{c.email ? <span>{c.email} {c.email_verified ? <Badge tone="success">{t("company.emailVerified")}</Badge> : null}</span> : "—"}</KeyValue>
                <KeyValue label={t("company.phone")}>{c.phone ?? "—"}</KeyValue>
                <KeyValue label={t("company.social")}>
                  <span className="flex flex-wrap gap-2">{c.social_profiles.length ? c.social_profiles.map((s) => (
                    <a key={s.id} href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="hover:underline">{s.platform}/{s.handle}{s.verified ? " ✓" : ""}</a>
                  )) : "—"}</span>
                </KeyValue>
                <KeyValue label={t("company.discovered")}><DateText value={c.discovered_at} /></KeyValue>
                <KeyValue label={t("company.lastVerified")}><DateText value={c.last_verified_at} /></KeyValue>
                <KeyValue label={t("company.chain")}>{c.is_chain === null ? t("common.unknown") : c.is_chain ? t("common.yes") : t("common.no")}</KeyValue>
                <KeyValue label={t("company.sources")}>
                  <ul className="grid gap-1">{c.sources.map((s) => (
                    <li key={s.source + s.source_key} className="text-[12px]">
                      <Badge>{s.source}</Badge>{" "}
                      {s.source_url ? <a href={s.source_url} target="_blank" rel="noopener noreferrer nofollow" className="num hover:underline">{s.source_key}</a> : <span className="num">{s.source_key}</span>}
                    </li>
                  ))}</ul>
                </KeyValue>
              </dl>
            </Card>
            <div className="grid content-start gap-4">
              <Card className="p-4">
                <div className="grid gap-3">
                  <Field label={t("companies.col.crmStatus")}>
                    <NativeSelect value={c.crm_status} disabled={c.do_not_contact} onChange={(e) => patch({ crm_status: e.target.value })}>
                      {CRM_STATUSES.filter((s) => s !== "do_not_contact" || c.do_not_contact).map((s) => <option key={s} value={s}>{t(`crm.status.${s}`)}</option>)}
                    </NativeSelect>
                  </Field>
                  <Field label={t("company.followUp")}>
                    <Input type="date" value={c.follow_up_at?.slice(0, 10) ?? ""} onChange={(e) => patch({ follow_up_at: e.target.value ? `${e.target.value}T09:00:00Z` : null })} />
                  </Field>
                  <label className="flex items-center gap-2 text-[13px]"><Checkbox label="chain" checked={!!c.is_chain} onCheckedChange={(v) => patch({ is_chain: v })} />{t("company.chain")}</label>
                  <label className="flex items-center gap-2 text-[13px]"><Checkbox label="closed" checked={c.permanently_closed} onCheckedChange={(v) => patch({ permanently_closed: v })} />{t("company.closed")}</label>
                  <label className="flex items-center gap-2 text-[13px]"><Checkbox label="rejected" checked={c.rejected} onCheckedChange={(v) => patch({ rejected: v })} />{t("company.rejected")}</label>
                </div>
              </Card>
              <Card>
                <CardHeader title={t("company.internalNotes")} />
                <div className="grid gap-2 p-4">
                  <Textarea defaultValue={c.notes ?? ""} onBlur={(e) => e.target.value !== (c.notes ?? "") && patch({ notes: e.target.value })} rows={6} />
                </div>
              </Card>
              {c.override ? (
                <Card className="p-4 text-[13px]">
                  <p>{t("company.overrideActive", { score: c.override.score, original: c.override.original ?? "—" })}</p>
                  <p className="mt-1 text-[12px] text-muted">{c.override.reason}</p>
                  <Button size="sm" className="mt-2" onClick={() => act(() => api(`/companies/${id}/score-override`, { method: "DELETE" }), t("common.saved"))}>{t("company.clearOverride")}</Button>
                </Card>
              ) : null}
            </div>
          </div>
        ) : null}
        {tab === "score" ? <ScorePanel company={c} /> : null}
        {tab === "services" ? <ServicesPanel company={c} /> : null}
        {tab === "audit" ? <AuditPanel companyId={id} hasWebsite={!!c.website} /> : null}
        {tab === "tracking" ? <TrackingPanel companyId={id} /> : null}
        {tab === "advertising" ? <AdsPanel companyId={id} /> : null}
        {tab === "evidence" ? <EvidencePanel companyId={id} /> : null}
        {tab === "activity" ? <ActivityPanel companyId={id} /> : null}
        {tab === "history" ? <HistoryPanel companyId={id} /> : null}
        {tab === "reports" ? <ReportsPanel companyId={id} companyName={c.name} /> : null}
      </div>

      <Dialog open={dialog === "edit"} onOpenChange={(v) => !v && setDialog(null)} title={t("common.edit")} wide
        footer={<><Button onClick={() => setDialog(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={async () => {
          const body: Record<string, unknown> = {};
          for (const [k, v] of Object.entries(edit)) body[k] = v === "" ? null : v;
          if (await patch(body)) setDialog(null);
        }}>{t("common.save")}</Button></>}>
        <div className="grid gap-3 sm:grid-cols-2">
          {(["name", "legal_name", "website", "city", "region", "address", "postal_code", "email", "phone"] as const).map((k) => (
            <Field key={k} label={t(k === "name" ? "common.name" : k === "legal_name" ? "company.legalName" : k === "postal_code" ? "company.postalCode" : `company.${k}`)}>
              <Input value={edit[k] ?? ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />
            </Field>
          ))}
          <Field label={t("companies.col.country")}>
            <NativeSelect value={edit.country ?? ""} onChange={(e) => setEdit({ ...edit, country: e.target.value })}>
              <option value="">—</option>
              {countries?.map((x) => <option key={x.iso2} value={x.iso2}>{nameOf(x)}</option>)}
            </NativeSelect>
          </Field>
          <Field label={t("companies.col.industry")}>
            <NativeSelect value={edit.industry ?? ""} onChange={(e) => setEdit({ ...edit, industry: e.target.value })}>
              <option value="">—</option>
              {industries?.map((x) => <option key={x.key} value={x.key}>{nameOf(x)}</option>)}
            </NativeSelect>
          </Field>
        </div>
      </Dialog>

      <Dialog open={dialog === "override"} onOpenChange={(v) => !v && setDialog(null)} title={t("company.overrideTitle")} description={t("company.overrideHint")}
        footer={<><Button onClick={() => setDialog(null)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!override.reason || override.score === ""} onClick={async () => {
          if (await act(() => api(`/companies/${id}/score-override`, { body: { score: Number(override.score), reason: override.reason } }), t("common.saved"))) setDialog(null);
        }}>{t("common.save")}</Button></>}>
        <div className="grid gap-3">
          <Field label={t("score.leadScore")}><Input type="number" min={0} max={100} value={override.score} onChange={(e) => setOverride({ ...override, score: e.target.value })} /></Field>
          <Field label={t("common.reason")}><Textarea value={override.reason} onChange={(e) => setOverride({ ...override, reason: e.target.value })} /></Field>
        </div>
      </Dialog>

      <Dialog open={dialog === "tags"} onOpenChange={(v) => !v && setDialog(null)} title={t("company.actions.manageTags")}
        footer={<><Button onClick={() => setDialog(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={async () => {
          if (await act(() => api(`/companies/${id}/tags`, { method: "PUT", body: { tag_ids: tagIds } }), t("common.saved"))) {
            qc.invalidateQueries({ queryKey: ["tags"] });
            setDialog(null);
          }
        }}>{t("common.save")}</Button></>}>
        <ul className="grid gap-1.5">
          {tags?.map((x) => (
            <li key={x.id}>
              <label className="flex items-center gap-2 text-[13px]">
                <Checkbox label={x.name} checked={tagIds.includes(x.id)} onCheckedChange={(v) => setTagIds(v ? [...tagIds, x.id] : tagIds.filter((y) => y !== x.id))} />
                <TagChip name={x.name} color={x.color} />
              </label>
            </li>
          ))}
          {!tags?.length ? <li className="text-[12px] text-muted"><Link href="/tags" className="underline">{t("tags.new")}</Link></li> : null}
        </ul>
      </Dialog>

      <Dialog open={dialog === "merge"} onOpenChange={(v) => !v && setDialog(null)} title={t("company.mergeTitle")} description={t("company.mergeHint")}>
        <div className="grid gap-2">
          <Input autoFocus placeholder={t("company.mergeSearch")} value={mergeQ} onChange={(e) => setMergeQ(e.target.value)} />
          <ul className="divide-y divide-border rounded-md border border-border">
            {mergeHits.map((h) => (
              <li key={h.id} className="flex items-center justify-between px-3 py-2 text-[13px]">
                <span>{h.name} <span className="text-muted">{h.city}</span></span>
                <Button size="sm" onClick={async () => {
                  if (await act(() => api(`/companies/${id}/merge`, { body: { source_id: h.id } }), t("common.saved"))) setDialog(null);
                }}>{t("companies.mergeInto")}</Button>
              </li>
            ))}
          </ul>
        </div>
      </Dialog>

      <Dialog open={dialog === "dnc"} onOpenChange={(v) => !v && setDialog(null)} title={t("company.dncTitle")} description={t("company.dncHint")}
        footer={<><Button onClick={() => setDialog(null)}>{t("common.cancel")}</Button><Button variant="danger" onClick={async () => {
          if (await act(() => api(`/companies/${id}/do-not-contact`, { body: { reason: text || null } }), t("common.saved"))) { setDialog(null); setText(""); }
        }}>{t("common.confirm")}</Button></>}>
        <Field label={t("common.reason")}><Input value={text} onChange={(e) => setText(e.target.value)} /></Field>
      </Dialog>

      <Dialog open={dialog === "delete"} onOpenChange={(v) => !v && setDialog(null)} title={t("company.deleteTitle")} description={t("company.deleteHint")}
        footer={<><Button onClick={() => setDialog(null)}>{t("common.cancel")}</Button><Button variant="danger" disabled={text !== c.name} onClick={async () => {
          try {
            await api(`/companies/${id}`, { method: "DELETE", query: { confirm: text } });
            qc.invalidateQueries({ queryKey: ["companies"] });
            router.push("/companies");
          } catch (e) {
            toast.error(err(e));
          }
        }}>{t("common.delete")}</Button></>}>
        <Field label={c.name}><Input value={text} onChange={(e) => setText(e.target.value)} /></Field>
      </Dialog>
    </>
  );
}

export default function CompanyPage() {
  return (
    <Suspense>
      <CompanyView />
    </Suspense>
  );
}
