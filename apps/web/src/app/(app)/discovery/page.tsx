"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Download, Pencil, Save, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { DateText, Flag, PageHeader } from "@/components/app/bits";
import { ACTIVE_IMPORT, CountryImportActions, ImportProgressLine, ImportProgressPanel, ImportStatusBadge } from "@/components/app/import-progress";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, Callout, Card, CardHeader, Checkbox, InfoTip, Switch, Tooltip } from "@/components/ui/misc";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useIndustries, useLocalizedName, useRegions, useSortByName } from "@/hooks/use-catalog";
import { api, ApiError } from "@/lib/api";
import type { Country } from "@/lib/types";
import { fmtBytes, fmtNumber } from "@/lib/utils";

interface ImportRun { id: string; source: string; country: string | null; extract_id: string | null; status: string; file_size: number | null; stats: Record<string, number | string>; error: string | null; created_at: string; finished_at: string | null; job_id: string | null }
interface GeoSel { id: string; name: string; regions: string[]; countries: string[]; industries: string[] }

const RUN_TONE: Record<string, string> = { completed: "success", failed: "danger", running: "info", queued: "info", skipped: "neutral", cancelled: "neutral" };

export default function DiscoveryPage() {
  const t = useTranslations();
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const name = useLocalizedName();
  const sortByName = useSortByName();
  const { data: regions } = useRegions();
  const { data: countries } = useApi<Country[]>(["countries"], "/countries", {
    refetchInterval: (d) => (d?.some((c) => ACTIVE_IMPORT.includes(c.import_status)) ? 5_000 : 30_000),
  });
  const { data: industries } = useIndustries();
  const { data: runs } = useApi<ImportRun[]>(["imports"], "/discovery/imports", { refetchInterval: 10_000 });
  const { data: selections } = useApi<GeoSel[]>(["geo-selections"], "/geo-selections");
  const [region, setRegion] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [inds, setInds] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [enabledOnly, setEnabledOnly] = useState(false);
  const [force, setForce] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [overwrite, setOverwrite] = useState<string | null>(null);
  const [editSel, setEditSel] = useState<(GeoSel & { replace: boolean }) | null>(null);
  const [deleteSel, setDeleteSel] = useState<GeoSel | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const refresh = (...keys: string[]) => keys.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));

  const visible = useMemo(() => sortByName(countries).filter((c) =>
    (!region.length || region.includes(c.region)) && (!enabledOnly || c.enabled) &&
    (!q || name(c).toLocaleLowerCase(locale).includes(q.toLocaleLowerCase(locale)) || c.iso2.toLowerCase() === q.toLowerCase())),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [countries, region, enabledOnly, q, locale]);
  const sortedIndustries = sortByName(industries?.filter((i) => i.enabled));
  const countryName = (iso: string | null) => { const c = countries?.find((x) => x.iso2 === iso); return c ? name(c) : iso ?? "—"; };

  // Enabling a country also selects it for the next import; disabling removes it from the selection.
  const toggleCountry = async (iso2: string, enabled: boolean) => {
    try {
      await api(`/countries/${iso2}`, { method: "PATCH", body: { enabled } });
      setSelected((s) => (enabled ? Array.from(new Set([...s, iso2])) : s.filter((x) => x !== iso2)));
      refresh("countries", "discovery-progress", "imports");
    } catch (e) {
      toast.error(err(e));
    }
  };
  const start = async () => {
    const target = selected.filter((iso) => countries?.find((c) => c.iso2 === iso)?.enabled);
    if (!target.length) return toast.error(t("discovery.noCountriesSelected"));
    try {
      const res = await api<{ jobs: string[] }>("/discovery/imports", { body: { countries: target, industries: inds.length ? inds : null, force } });
      toast.success(t("discovery.importQueued", { count: res.jobs.length }));
      refresh("countries", "imports", "discovery-progress");
    } catch (e) {
      toast.error(err(e));
    }
  };
  const openSave = () => {
    if (!selected.length && !inds.length) return toast.error(t("discovery.selectionEmpty"));
    setSaveName("");
    setSaveOpen(true);
  };
  const saveSel = async (force_overwrite = false) => {
    try {
      await api(`/geo-selections${force_overwrite ? "?overwrite=true" : ""}`, { body: { name: saveName, regions: region, countries: selected, industries: inds } });
      setSaveOpen(false);
      setOverwrite(null);
      toast.success(t("discovery.selectionSaved"));
      refresh("geo-selections");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && !force_overwrite) setOverwrite(saveName.trim());
      else toast.error(err(e));
    }
  };
  const updateSel = async () => {
    if (!editSel) return;
    const body = editSel.replace
      ? { name: editSel.name, regions: region, countries: selected, industries: inds }
      : { name: editSel.name, regions: editSel.regions, countries: editSel.countries, industries: editSel.industries };
    try {
      await api(`/geo-selections/${editSel.id}`, { method: "PUT", body });
      setEditSel(null);
      toast.success(t("common.saved"));
      refresh("geo-selections");
    } catch (e) {
      toast.error(err(e));
    }
  };
  const removeSel = async (id: string) => {
    try {
      await api(`/geo-selections/${id}`, { method: "DELETE" });
      toast.success(t("discovery.selectionDeleted"));
      refresh("geo-selections");
    } catch (e) {
      toast.error(err(e));
    }
  };
  const clearHistory = async () => {
    try {
      const r = await api<{ deleted: number }>("/discovery/imports", { method: "DELETE" });
      toast.success(t("discovery.historyCleared", { count: r.deleted }));
      refresh("imports", "countries", "discovery-progress");
    } catch (e) {
      toast.error(err(e));
    }
  };
  const runStats = (r: ImportRun) => {
    if (r.stats?.created !== undefined) return `${r.stats.created} ${t("discovery.created")} · ${r.stats.updated ?? 0} ${t("discovery.updatedCount")} · ${r.stats.matched_existing ?? 0} ${t("discovery.matched")}`;
    return r.error ?? (typeof r.stats?.reason === "string" ? r.stats.reason : "—");
  };

  return (
    <>
      <PageHeader title={t("discovery.title")} description={t("discovery.subtitle")}
        actions={<><Button size="sm" onClick={openSave}><Save />{t("discovery.saveSelection")}</Button><Button size="sm" variant="primary" onClick={start}><Download />{t("discovery.startImport")}</Button></>} />
      <Callout title={t("discovery.explainTitle")} className="mb-3">
        <ul className="grid gap-0.5">
          <li>• {t("discovery.explainEnabled")}</li>
          <li>• {t("discovery.explainSelect")}</li>
          <li>• {t("discovery.explainIndustries")}</li>
        </ul>
      </Callout>
      <p className="mb-4 max-w-4xl text-[12px] text-muted">{t("discovery.coverageNote")}</p>
      <ImportProgressPanel onlyActive className="mb-4" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="min-w-0">
          <CardHeader title={t("discovery.countries")} actions={
            <label className="flex items-center gap-2 text-[12px] text-muted"><Switch checked={enabledOnly} onCheckedChange={setEnabledOnly} label={t("discovery.enabledOnly")} />{t("discovery.enabledOnly")}</label>
          } />
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
            {regions?.map((r) => (
              <Button key={r.code} size="sm" variant={region.includes(r.code) ? "primary" : "secondary"}
                onClick={() => setRegion(region.includes(r.code) ? region.filter((x) => x !== r.code) : [...region, r.code])}>{name(r)}</Button>
            ))}
            <div className="relative w-full sm:ml-auto sm:w-56">
              <Search className="pointer-events-none absolute left-2 top-2 size-4 text-muted" />
              <Input className="pl-8" placeholder={t("discovery.searchCountries")} value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <Button size="sm" variant="ghost" onClick={() => setSelected(Array.from(new Set([...selected, ...visible.filter((c) => c.enabled).map((c) => c.iso2)])))}>{t("common.selectAll")}</Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected([])}>{t("common.deselectAll")}</Button>
          </div>
          <div className="max-h-[60vh] overflow-auto">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr className="border-b border-border text-left text-[12px] text-muted">
                  <th className="w-10 px-4 py-2"><InfoTip>{t("discovery.selectInfo")}</InfoTip></th>
                  <th className="px-2 py-2 font-medium">{t("discovery.countries")}</th>
                  <th className="px-2 py-2 font-medium"><span className="inline-flex items-center gap-1">{t("common.enabled")}<InfoTip>{t("discovery.enabledInfo")}</InfoTip></span></th>
                  <th className="px-2 py-2 font-medium"><span className="inline-flex items-center gap-1">{t("discovery.importStatus")}<InfoTip>{t("discovery.statusInfo")}</InfoTip></span></th>
                  <th className="px-2 py-2 font-medium">{t("discovery.lastImport")}</th>
                  <th className="px-2 py-2 font-medium">{t("discovery.sourceDate")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("discovery.companies")}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((c) => (
                  <tr key={c.iso2} className="border-b border-border align-top last:border-0">
                    <td className="px-4 py-2"><Checkbox label={c.iso2} disabled={!c.enabled} checked={selected.includes(c.iso2)} onCheckedChange={(v) => setSelected(v ? [...selected, c.iso2] : selected.filter((x) => x !== c.iso2))} /></td>
                    <td className="px-2 py-2">
                      <span className="flex items-start gap-2">
                        <Flag code={c.flag} className="mt-[3px] shrink-0" />
                        <span className="min-w-0">{name(c)} <span className="num text-[11px] text-muted">{c.iso2}</span>{c.is_priority ? <> <Badge>{t("discovery.priority")}</Badge></> : null}</span>
                      </span>
                    </td>
                    <td className="px-2 py-2"><Switch checked={c.enabled} onCheckedChange={(v) => toggleCountry(c.iso2, v)} label={c.enabled ? t("discovery.disableCountry") : t("discovery.enableCountry")} /></td>
                    <td className="w-60 px-2 py-2">
                      <div className="flex items-center gap-1">
                        <ImportStatusBadge status={c.import_status} />
                        <CountryImportActions iso2={c.iso2} countryName={name(c)} status={c.import_status} />
                      </div>
                      {c.progress && c.import_status !== "disabled" ? <div className="mt-1"><ImportProgressLine progress={c.progress} compact /></div> : null}
                    </td>
                    <td className="px-2 py-2"><DateText value={c.last_import_at} /></td>
                    <td className="px-2 py-2"><DateText value={c.last_source_timestamp} /></td>
                    <td className="num px-4 py-2 text-right">{fmtNumber(c.companies, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-border px-4 py-2 text-[11px] text-muted">{t("discovery.disableHint")}</p>
        </Card>
        <div className="grid min-w-0 content-start gap-4">
          <Card>
            <CardHeader title={<span className="flex items-center gap-1">{t("discovery.industries")}<InfoTip>{t("discovery.industriesInfo")}</InfoTip></span>}
              actions={<span className="num text-[12px] text-muted">{inds.length || t("common.all")}</span>} />
            <ul className="grid gap-1 p-3">
              {sortedIndustries.map((i) => (
                <li key={i.key}>
                  <label className="flex items-center gap-2 text-[13px]">
                    <Checkbox label={i.key} checked={inds.includes(i.key)} onCheckedChange={(v) => setInds(v ? [...inds, i.key] : inds.filter((x) => x !== i.key))} />
                    <span className="min-w-0 flex-1">{name(i)}</span>
                    {!i.rules.length ? <Tooltip content={t("dataSources.manualInfo")}><span><Badge>{t("dataSources.manualBadge")}</Badge></span></Tooltip> : null}
                  </label>
                </li>
              ))}
            </ul>
            <label className="flex items-center gap-2 border-t border-border px-3 py-2 text-[12px] text-muted"><Checkbox label="force" checked={force} onCheckedChange={setForce} />{t("discovery.forceReimport")}<InfoTip>{t("discovery.forceInfo")}</InfoTip></label>
          </Card>
          {selections?.length ? (
            <Card>
              <CardHeader title={t("discovery.savedSelections")} />
              <ul className="divide-y divide-border">
                {selections.map((s) => (
                  <li key={s.id} className="flex items-center gap-2 px-3 py-2 text-[13px]">
                    <button type="button" className="min-w-0 flex-1 text-left hover:underline" title={t("common.load")}
                      onClick={() => { setRegion(s.regions); setSelected(s.countries); setInds(s.industries); }}>
                      <span className="block truncate">{s.name}</span>
                      <span className="block text-[11px] text-muted">{t("discovery.selectionContents", { countries: s.countries.length, industries: s.industries.length })}</span>
                    </button>
                    <Tooltip content={t("discovery.editSelection")}><Button size="icon-sm" variant="ghost" aria-label={t("discovery.editSelection")} onClick={() => setEditSel({ ...s, replace: false })}><Pencil /></Button></Tooltip>
                    <Tooltip content={t("common.delete")}><Button size="icon-sm" variant="ghost" aria-label={t("common.delete")} onClick={() => setDeleteSel(s)}><Trash2 /></Button></Tooltip>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      </div>
      <Card className="mt-4">
        <CardHeader title={t("discovery.imports")} actions={runs?.length ? <Button size="sm" variant="ghost" onClick={() => setClearOpen(true)}><Trash2 />{t("discovery.clearHistory")}</Button> : null} />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-[13px]">
            <thead><tr className="border-b border-border text-left text-[12px] text-muted">
              <th className="px-4 py-2 font-medium">{t("discovery.extract")}</th><th className="px-2 py-2 font-medium">{t("common.status")}</th>
              <th className="px-2 py-2 font-medium">{t("discovery.size")}</th><th className="px-2 py-2 font-medium">{t("discovery.stats")}</th>
              <th className="px-4 py-2 font-medium">{t("common.updated")}</th>
            </tr></thead>
            <tbody>
              {runs?.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-1.5">
                    <span className="inline-flex items-center gap-2"><Flag code={r.country} />
                      <span className="text-[12px]">{countryName(r.country)}</span>
                      <span className="num text-[11px] text-muted">{r.extract_id ?? r.source}</span>
                    </span>
                  </td>
                  <td className="px-2 py-1.5"><Badge tone={RUN_TONE[r.status] ?? "neutral"}>{t.has(`discovery.runStatuses.${r.status}`) ? t(`discovery.runStatuses.${r.status}`) : r.status}</Badge></td>
                  <td className="num px-2 py-1.5 text-[12px]">{fmtBytes(r.file_size, locale)}</td>
                  <td className="max-w-96 px-2 py-1.5 text-[12px] text-muted">
                    {r.job_id && r.error ? <Link href={`/jobs/${r.job_id}`} className="block truncate text-danger hover:underline" title={r.error}>{r.error}</Link> : <span className="num block truncate">{runStats(r)}</span>}
                  </td>
                  <td className="px-4 py-1.5"><DateText value={r.finished_at ?? r.created_at} withTime /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen} title={t("discovery.saveSelection")}
        footer={<><Button onClick={() => setSaveOpen(false)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!saveName.trim()} onClick={() => saveSel()}>{t("common.save")}</Button></>}>
        <div className="grid gap-2">
          <Field label={t("discovery.selectionName")}><Input value={saveName} maxLength={120} onChange={(e) => setSaveName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && saveName.trim()) saveSel(); }} /></Field>
          <p className="text-[12px] text-muted">{t("discovery.selectionContents", { countries: selected.length, industries: inds.length })}</p>
        </div>
      </Dialog>
      <ConfirmDialog open={overwrite !== null} onOpenChange={(v) => !v && setOverwrite(null)} title={t("common.overwrite")}
        message={t("discovery.selectionExists", { name: overwrite ?? "" })} confirmLabel={t("common.overwrite")} cancelLabel={t("common.cancel")}
        onConfirm={() => saveSel(true)} />
      <Dialog open={editSel !== null} onOpenChange={(v) => !v && setEditSel(null)} title={t("discovery.editSelection")}
        footer={<><Button onClick={() => setEditSel(null)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!editSel?.name.trim()} onClick={updateSel}>{t("common.save")}</Button></>}>
        {editSel ? (
          <div className="grid gap-3">
            <Field label={t("discovery.selectionName")}><Input value={editSel.name} maxLength={120} onChange={(e) => setEditSel({ ...editSel, name: e.target.value })} /></Field>
            <p className="text-[12px] text-muted">{t("discovery.selectionContents", { countries: editSel.countries.length, industries: editSel.industries.length })}: {editSel.countries.map((c) => countryName(c)).join(", ") || "—"}</p>
            <label className="flex items-center gap-2 text-[13px]">
              <Checkbox label="replace" checked={editSel.replace} onCheckedChange={(v) => setEditSel({ ...editSel, replace: v })} />
              {t("discovery.updateWithCurrent")}<InfoTip>{t("discovery.updateWithCurrentInfo")}</InfoTip>
            </label>
            {editSel.replace ? <p className="text-[12px] text-muted">→ {t("discovery.selectionContents", { countries: selected.length, industries: inds.length })}</p> : null}
          </div>
        ) : null}
      </Dialog>
      <ConfirmDialog open={deleteSel !== null} onOpenChange={(v) => !v && setDeleteSel(null)} title={t("common.delete")} danger
        message={t("discovery.deleteSelectionConfirm", { name: deleteSel?.name ?? "" })} confirmLabel={t("common.delete")} cancelLabel={t("common.cancel")}
        onConfirm={() => deleteSel && removeSel(deleteSel.id)} />
      <ConfirmDialog open={clearOpen} onOpenChange={setClearOpen} title={t("discovery.clearHistory")} danger
        message={t("discovery.clearHistoryConfirm")} confirmLabel={t("discovery.clearHistory")} cancelLabel={t("common.cancel")} onConfirm={clearHistory} />
    </>
  );
}
