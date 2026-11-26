"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Download, Save, Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { DateText, Flag, PageHeader } from "@/components/app/bits";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, Card, CardHeader, Checkbox, Switch } from "@/components/ui/misc";
import { Dialog } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { useCountries, useIndustries, useLocalizedName, useRegions } from "@/hooks/use-catalog";
import { api } from "@/lib/api";
import { fmtBytes, fmtNumber } from "@/lib/utils";

interface ImportRun { id: string; source: string; country: string | null; extract_id: string | null; status: string; file_size: number | null; stats: Record<string, number>; error: string | null; created_at: string; finished_at: string | null; job_id: string | null }
interface GeoSel { id: string; name: string; regions: string[]; countries: string[]; industries: string[] }

export default function DiscoveryPage() {
  const t = useTranslations();
  const locale = useLocale();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const name = useLocalizedName();
  const { data: regions } = useRegions();
  const { data: countries } = useCountries();
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

  const visible = useMemo(() => (countries ?? []).filter((c) =>
    (!region.length || region.includes(c.region)) && (!enabledOnly || c.enabled) &&
    (!q || name(c).toLowerCase().includes(q.toLowerCase()) || c.iso2.toLowerCase() === q.toLowerCase())), [countries, region, enabledOnly, q, name]);

  const toggleCountry = async (iso2: string, enabled: boolean) => {
    try {
      await api(`/countries/${iso2}`, { method: "PATCH", body: { enabled } });
      qc.invalidateQueries({ queryKey: ["countries"] });
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
      qc.invalidateQueries({ queryKey: ["countries"] });
      qc.invalidateQueries({ queryKey: ["imports"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  const saveSel = async () => {
    await api("/geo-selections", { body: { name: saveName, regions: region, countries: selected, industries: inds } });
    setSaveOpen(false);
    qc.invalidateQueries({ queryKey: ["geo-selections"] });
  };

  return (
    <>
      <PageHeader title={t("discovery.title")} description={t("discovery.subtitle")}
        actions={<><Button size="sm" onClick={() => setSaveOpen(true)}><Save />{t("discovery.saveSelection")}</Button><Button size="sm" variant="primary" onClick={start}><Download />{t("discovery.startImport")}</Button></>} />
      <p className="mb-4 max-w-4xl text-[12px] text-muted">{t("discovery.coverageNote")}</p>
      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card>
          <CardHeader title={t("discovery.countries")} actions={
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-2 text-[12px] text-muted"><Switch checked={enabledOnly} onCheckedChange={setEnabledOnly} label={t("discovery.enabledOnly")} />{t("discovery.enabledOnly")}</label>
            </div>
          } />
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
            {regions?.map((r) => (
              <Button key={r.code} size="sm" variant={region.includes(r.code) ? "primary" : "secondary"}
                onClick={() => setRegion(region.includes(r.code) ? region.filter((x) => x !== r.code) : [...region, r.code])}>{name(r)}</Button>
            ))}
            <div className="relative ml-auto w-56">
              <Search className="pointer-events-none absolute left-2 top-2 size-4 text-muted" />
              <Input className="pl-8" placeholder={t("discovery.searchCountries")} value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <Button size="sm" variant="ghost" onClick={() => setSelected(Array.from(new Set([...selected, ...visible.map((c) => c.iso2)])))}>{t("common.selectAll")}</Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected([])}>{t("common.deselectAll")}</Button>
          </div>
          <div className="max-h-[60vh] overflow-auto">
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-border text-left text-[12px] text-muted">
                  <th className="w-10 px-4 py-2" />
                  <th className="px-2 py-2 font-medium">{t("discovery.countries")}</th>
                  <th className="px-2 py-2 font-medium">{t("common.enabled")}</th>
                  <th className="px-2 py-2 font-medium">{t("discovery.importStatus")}</th>
                  <th className="px-2 py-2 font-medium">{t("discovery.lastImport")}</th>
                  <th className="px-2 py-2 font-medium">{t("discovery.sourceDate")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("discovery.companies")}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((c) => (
                  <tr key={c.iso2} className="border-b border-border last:border-0">
                    <td className="px-4 py-1.5"><Checkbox label={c.iso2} checked={selected.includes(c.iso2)} onCheckedChange={(v) => setSelected(v ? [...selected, c.iso2] : selected.filter((x) => x !== c.iso2))} /></td>
                    <td className="px-2 py-1.5"><span className="inline-flex items-center gap-2"><Flag code={c.flag} />{name(c)} <span className="num text-[11px] text-muted">{c.iso2}</span>{c.is_priority ? <Badge>{t("discovery.priority")}</Badge> : null}</span></td>
                    <td className="px-2 py-1.5"><Switch checked={c.enabled} onCheckedChange={(v) => toggleCountry(c.iso2, v)} label={c.enabled ? t("discovery.disableCountry") : t("discovery.enableCountry")} /></td>
                    <td className="px-2 py-1.5"><Badge tone={c.import_status === "completed" ? "success" : c.import_status === "failed" ? "danger" : ["running", "queued", "planning"].includes(c.import_status) ? "info" : "neutral"}>{c.import_status}</Badge></td>
                    <td className="px-2 py-1.5"><DateText value={c.last_import_at} /></td>
                    <td className="px-2 py-1.5"><DateText value={c.last_source_timestamp} /></td>
                    <td className="num px-4 py-1.5 text-right">{fmtNumber(c.companies, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-border px-4 py-2 text-[11px] text-muted">{t("discovery.disableHint")}</p>
        </Card>
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader title={t("discovery.industries")} actions={<span className="num text-[12px] text-muted">{inds.length || t("common.all")}</span>} />
            <ul className="grid gap-1 p-3">
              {industries?.filter((i) => i.enabled).map((i) => (
                <li key={i.key}>
                  <label className="flex items-center gap-2 text-[13px]">
                    <Checkbox label={i.key} checked={inds.includes(i.key)} onCheckedChange={(v) => setInds(v ? [...inds, i.key] : inds.filter((x) => x !== i.key))} />
                    <span className="flex-1">{name(i)}</span>
                    {!i.rules.length ? <Badge>manual</Badge> : null}
                  </label>
                </li>
              ))}
            </ul>
            <label className="flex items-center gap-2 border-t border-border px-3 py-2 text-[12px] text-muted"><Checkbox label="force" checked={force} onCheckedChange={setForce} />{t("discovery.forceReimport")}</label>
          </Card>
          {selections?.length ? (
            <Card>
              <CardHeader title={t("discovery.savedSelections")} />
              <ul className="divide-y divide-border">
                {selections.map((s) => (
                  <li key={s.id} className="flex items-center justify-between px-3 py-2 text-[13px]">
                    <button type="button" className="hover:underline" onClick={() => { setRegion(s.regions); setSelected(s.countries); setInds(s.industries); }}>{s.name}</button>
                    <span className="num text-[11px] text-muted">{s.countries.length}</span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      </div>
      <Card className="mt-4">
        <CardHeader title={t("discovery.imports")} />
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead><tr className="border-b border-border text-left text-[12px] text-muted">
              <th className="px-4 py-2 font-medium">{t("discovery.extract")}</th><th className="px-2 py-2 font-medium">{t("common.status")}</th>
              <th className="px-2 py-2 font-medium">{t("discovery.size")}</th><th className="px-2 py-2 font-medium">{t("discovery.stats")}</th>
              <th className="px-4 py-2 font-medium">{t("common.updated")}</th>
            </tr></thead>
            <tbody>
              {runs?.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-1.5"><span className="inline-flex items-center gap-2"><Flag code={r.country} /><span className="num text-[12px]">{r.extract_id ?? r.source}</span></span></td>
                  <td className="px-2 py-1.5"><Badge tone={r.status === "completed" ? "success" : r.status === "failed" ? "danger" : "neutral"}>{r.status}</Badge></td>
                  <td className="num px-2 py-1.5 text-[12px]">{fmtBytes(r.file_size, locale)}</td>
                  <td className="num px-2 py-1.5 text-[12px] text-muted">{r.stats?.created !== undefined ? `${r.stats.created} ${t("discovery.created")} · ${r.stats.updated ?? 0} ${t("discovery.updatedCount")} · ${r.stats.matched_existing ?? 0} ${t("discovery.matched")}` : r.error ?? "—"}</td>
                  <td className="px-4 py-1.5"><DateText value={r.finished_at ?? r.created_at} withTime /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Dialog open={saveOpen} onOpenChange={setSaveOpen} title={t("discovery.saveSelection")}
        footer={<><Button onClick={() => setSaveOpen(false)}>{t("common.cancel")}</Button><Button variant="primary" disabled={!saveName} onClick={saveSel}>{t("common.save")}</Button></>}>
        <Field label={t("discovery.selectionName")}><Input value={saveName} onChange={(e) => setSaveName(e.target.value)} /></Field>
      </Dialog>
    </>
  );
}
