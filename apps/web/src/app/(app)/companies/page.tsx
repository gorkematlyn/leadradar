"use client";

import { useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, RowSelectionState } from "@tanstack/react-table";
import { Copy, Download, FileUp, Filter as FilterIcon, Plus, Save, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  AnalysisBadge, CountryLabel, CrmBadge, DateText, IndustryLabel, PageHeader, PlatformChips, ScoreValue, TagChip, WebsiteStatusBadge,
} from "@/components/app/bits";
import { activeFilterCount, CompanyFilters } from "@/components/app/company-filters";
import { CsvImportDialog, NewCompanyDialog } from "@/components/app/company-dialogs";
import { DataTable } from "@/components/app/data-table";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Badge, Card, EmptyState } from "@/components/ui/misc";
import { Dialog, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useTags } from "@/hooks/use-catalog";
import { api, download } from "@/lib/api";
import { CRM_STATUSES, type CompanyFilter, type CompanyRow } from "@/lib/types";

const PAGE_SIZE = 50;

function CompaniesView() {
  const t = useTranslations();
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const errorMessage = useErrorMessage();
  const { data: tags } = useTags();
  const [filter, setFilter] = useState<CompanyFilter>({});
  const [q, setQ] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ id: "score", desc: true });
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [newOpen, setNewOpen] = useState(false);
  const [csvOpen, setCsvOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [bulk, setBulk] = useState<{ action: string; tag?: string; status?: string } | null>(null);

  // Load a saved filter (?saved=<id>) or a pre-set filter (?filter=<json>).
  const savedId = params.get("saved");
  const { data: saved } = useApi<{ id: string; filters: CompanyFilter }[]>(["saved-filters"], savedId ? "/saved-filters" : null);
  useEffect(() => {
    const preset = params.get("filter");
    if (preset) {
      try { setFilter(JSON.parse(preset)); } catch { /* ignore malformed */ }
    }
  }, [params]);
  useEffect(() => {
    const s = saved?.find((x) => x.id === savedId);
    if (s) {
      setFilter(s.filters);
      setQ(s.filters.q ?? "");
    }
  }, [saved, savedId]);
  useEffect(() => {
    const h = setTimeout(() => { setFilter((f) => ({ ...f, q: q || undefined })); setPage(1); }, 300);
    return () => clearTimeout(h);
  }, [q]);

  const body = useMemo(() => ({ filter, sort: sort.id, direction: sort.desc ? "desc" : "asc", page, page_size: PAGE_SIZE }), [filter, sort, page]);
  const { data, isLoading, isFetching } = useApi<{ total: number; items: CompanyRow[] }>(["companies", body], "/companies/query", { body, method: "POST" });
  const selectedIds = Object.keys(selection).filter((k) => selection[k]);

  const columns = useMemo<ColumnDef<CompanyRow, unknown>[]>(() => [
    {
      id: "name", header: t("companies.col.company"), size: 240,
      cell: ({ row }) => (
        <div className="flex min-w-0 items-center gap-2">
          <Link href={`/companies/${row.original.id}`} className="truncate font-medium hover:underline" onClick={(e) => e.stopPropagation()}>{row.original.name}</Link>
          {row.original.do_not_contact ? <Badge tone="danger">DNC</Badge> : null}
          {row.original.industry_confidence === "review" ? <Badge>?</Badge> : null}
        </div>
      ),
    },
    { id: "website", header: t("companies.col.website"), size: 180, cell: ({ row }) => row.original.domain ? <span className="num text-[12px] text-muted">{row.original.domain}</span> : <span className="text-muted">—</span> },
    { id: "country", header: t("companies.col.country"), size: 140, cell: ({ row }) => <CountryLabel code={row.original.country} /> },
    { id: "city", header: t("companies.col.city"), size: 120, cell: ({ row }) => row.original.city ?? <span className="text-muted">—</span> },
    { id: "industry", header: t("companies.col.industry"), size: 150, cell: ({ row }) => <IndustryLabel industryKey={row.original.industry} /> },
    { id: "score", header: t("companies.col.leadScore"), size: 90, cell: ({ row }) => <ScoreValue score={row.original.lead_score} provisional={row.original.final_score === null && row.original.lead_score !== null} /> },
    { id: "confidence", header: t("companies.col.confidence"), size: 90, cell: ({ row }) => <span className="num text-muted">{row.original.confidence ?? "—"}</span> },
    { id: "website_status", header: t("companies.col.websiteStatus"), size: 150, cell: ({ row }) => <WebsiteStatusBadge status={row.original.website_status} /> },
    { id: "advertising", header: t("companies.col.advertising"), size: 140, cell: ({ row }) => <PlatformChips platforms={row.original.advertising_platforms} /> },
    {
      id: "services", header: t("companies.col.services"), size: 200,
      cell: ({ row }) => row.original.services.length ? (
        <span className="flex flex-wrap gap-1">{row.original.services.map((s) => <Badge key={s.key}>{t(`services.${s.key}`)}{s.provisional ? "*" : ""}</Badge>)}</span>
      ) : <span className="text-muted">—</span>,
    },
    { id: "tags", header: t("companies.col.tags"), size: 160, cell: ({ row }) => <span className="flex flex-wrap gap-1">{row.original.tags.map((x) => <TagChip key={x.id} name={x.name} color={x.color} />)}</span> },
    { id: "crm_status", header: t("companies.col.crmStatus"), size: 130, cell: ({ row }) => <CrmBadge status={row.original.crm_status} /> },
    { id: "analysis_status", header: t("companies.col.analysisStatus"), size: 130, cell: ({ row }) => <AnalysisBadge status={row.original.analysis_status} /> },
    { id: "last_audit", header: t("companies.col.lastAudit"), size: 120, cell: ({ row }) => <DateText value={row.original.last_audit_at} /> },
  ], [t]);

  const runBulk = async () => {
    if (!bulk) return;
    const payload: Record<string, unknown> = { ids: selectedIds, action: bulk.action };
    if (bulk.action === "add_tags" || bulk.action === "remove_tags") payload.tag_ids = bulk.tag ? [bulk.tag] : [];
    if (bulk.action === "set_status") payload.status = bulk.status;
    try {
      const res = await api<{ affected: number }>("/companies/bulk", { body: payload });
      toast.success(t("companies.bulk.done", { count: res.affected }));
      setBulk(null);
      setSelection({});
      qc.invalidateQueries({ queryKey: ["companies"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const saveFilter = async () => {
    try {
      await api("/saved-filters", { body: { name: saveName, filters: { ...filter, q: q || undefined } } });
      toast.success(t("common.saved"));
      setSaveOpen(false);
      setSaveName("");
      qc.invalidateQueries({ queryKey: ["saved-filters"] });
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const count = activeFilterCount(filter);
  return (
    <>
      <PageHeader
        title={t("companies.title")}
        description={t("companies.subtitle")}
        actions={
          <>
            <Button size="sm" asChild><Link href="/companies/duplicates"><Copy />{t("companies.duplicates")}</Link></Button>
            <Button size="sm" onClick={() => setCsvOpen(true)}><FileUp />{t("companies.importCsv")}</Button>
            <Menu>
              <MenuTrigger asChild><Button size="sm"><Download />{t("companies.export")}</Button></MenuTrigger>
              <MenuContent>
                <MenuItem onSelect={() => download("/companies/export", body, "leadradar-contacts.csv", { purpose: "contact" }).catch((e) => toast.error(errorMessage(e)))}>{t("companies.exportContacts")}</MenuItem>
                <MenuItem onSelect={() => download("/companies/export", body, "leadradar-analysis.csv", { purpose: "analysis" }).catch((e) => toast.error(errorMessage(e)))}>{t("companies.exportAnalysis")}</MenuItem>
              </MenuContent>
            </Menu>
            <Button size="sm" variant="primary" onClick={() => setNewOpen(true)}><Plus />{t("companies.addCompany")}</Button>
          </>
        }
      />
      {showFilters ? (
        <Card className="mb-3 p-3">
          <CompanyFilters value={filter} onChange={(f) => { setFilter(f); setPage(1); }} />
        </Card>
      ) : null}
      <DataTable<CompanyRow>
        id="companies"
        columns={columns}
        data={data?.items ?? []}
        total={data?.total ?? 0}
        page={page}
        pageSize={PAGE_SIZE}
        onPageChange={setPage}
        sort={sort}
        onSortChange={(s) => { setSort(s); setPage(1); }}
        sortable={["name", "score", "confidence", "last_audit", "country", "city", "crm_status", "analysis_status"]}
        loading={isLoading || isFetching}
        selectable
        selection={selection}
        onSelectionChange={setSelection}
        getRowId={(r) => r.id}
        onRowClick={(r) => router.push(`/companies/${r.id}`)}
        empty={<EmptyState title={t("companies.empty")} description={t("companies.emptyHint")} />}
        toolbar={
          <>
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute left-2 top-2 size-4 text-muted" />
              <Input className="pl-8" placeholder={t("companies.searchPlaceholder")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("common.search")} />
            </div>
            <Button size="sm" variant={showFilters ? "primary" : "secondary"} onClick={() => setShowFilters(!showFilters)}>
              <FilterIcon />{t("common.filters")}{count ? <span className="num">({count})</span> : null}
            </Button>
            {count ? <Button size="sm" variant="ghost" onClick={() => { setFilter({}); setQ(""); }}>{t("common.clear")}</Button> : null}
            <Button size="sm" variant="ghost" onClick={() => setSaveOpen(true)}><Save />{t("companies.saveFilter")}</Button>
            {selectedIds.length ? (
              <Menu>
                <MenuTrigger asChild><Button size="sm">{t("companies.applyToSelection", { count: selectedIds.length })}</Button></MenuTrigger>
                <MenuContent align="start">
                  <MenuItem onSelect={() => setBulk({ action: "add_tags" })}>{t("companies.bulk.addTags")}</MenuItem>
                  <MenuItem onSelect={() => setBulk({ action: "remove_tags" })}>{t("companies.bulk.removeTags")}</MenuItem>
                  <MenuItem onSelect={() => setBulk({ action: "set_status", status: "qualified" })}>{t("companies.bulk.setStatus")}</MenuItem>
                  <MenuSeparator />
                  <MenuItem onSelect={() => setBulk({ action: "audit_quick" })}>{t("companies.bulk.auditQuick")}</MenuItem>
                  <MenuItem onSelect={() => setBulk({ action: "audit_full" })}>{t("companies.bulk.auditFull")}</MenuItem>
                  <MenuItem onSelect={() => setBulk({ action: "research_ads" })}>{t("companies.bulk.researchAds")}</MenuItem>
                  <MenuItem onSelect={() => setBulk({ action: "recalculate" })}>{t("companies.bulk.recalculate")}</MenuItem>
                  <MenuSeparator />
                  <MenuItem onSelect={() => setBulk({ action: "watch" })}>{t("companies.bulk.watch")}</MenuItem>
                  <MenuItem onSelect={() => setBulk({ action: "unwatch" })}>{t("companies.bulk.unwatch")}</MenuItem>
                  <MenuItem onSelect={() => setBulk({ action: "archive" })}>{t("companies.bulk.archive")}</MenuItem>
                  <MenuItem onSelect={() => setBulk({ action: "unarchive" })}>{t("companies.bulk.unarchive")}</MenuItem>
                  <MenuItem danger onSelect={() => setBulk({ action: "do_not_contact" })}>{t("companies.bulk.dnc")}</MenuItem>
                </MenuContent>
              </Menu>
            ) : null}
          </>
        }
      />
      <Dialog
        open={bulk !== null}
        onOpenChange={(v) => !v && setBulk(null)}
        title={bulk ? t(`companies.bulk.${{ add_tags: "addTags", remove_tags: "removeTags", set_status: "setStatus", audit_quick: "auditQuick", audit_full: "auditFull", research_ads: "researchAds", recalculate: "recalculate", watch: "watch", unwatch: "unwatch", archive: "archive", unarchive: "unarchive", do_not_contact: "dnc" }[bulk.action] ?? "addTags"}`) : ""}
        description={t("common.selected", { count: selectedIds.length })}
        footer={<><Button onClick={() => setBulk(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={runBulk}>{t("common.apply")}</Button></>}
      >
        {bulk?.action === "add_tags" || bulk?.action === "remove_tags" ? (
          <Field label={t("nav.tags")}>
            <NativeSelect value={bulk.tag ?? ""} onChange={(e) => setBulk({ ...bulk, tag: e.target.value })}>
              <option value="">—</option>
              {tags?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </NativeSelect>
          </Field>
        ) : bulk?.action === "set_status" ? (
          <Field label={t("companies.col.crmStatus")}>
            <NativeSelect value={bulk.status} onChange={(e) => setBulk({ ...bulk, status: e.target.value })}>
              {CRM_STATUSES.filter((s) => s !== "do_not_contact").map((s) => <option key={s} value={s}>{t(`crm.status.${s}`)}</option>)}
            </NativeSelect>
          </Field>
        ) : bulk?.action === "do_not_contact" ? (
          <p className="text-[13px] text-muted">{t("company.dncHint")}</p>
        ) : (
          <p className="text-[13px] text-muted">{t("common.areYouSure")}</p>
        )}
      </Dialog>
      <Dialog open={saveOpen} onOpenChange={setSaveOpen} title={t("companies.saveFilter")}
        footer={<><Button onClick={() => setSaveOpen(false)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!saveName} onClick={saveFilter}>{t("common.save")}</Button></>}>
        <Field label={t("savedFilters.name")}><Input autoFocus value={saveName} onChange={(e) => setSaveName(e.target.value)} /></Field>
      </Dialog>
      <NewCompanyDialog open={newOpen} onOpenChange={setNewOpen} />
      <CsvImportDialog open={csvOpen} onOpenChange={setCsvOpen} />
    </>
  );
}

export default function CompaniesPage() {
  return (
    <Suspense>
      <CompaniesView />
    </Suspense>
  );
}
