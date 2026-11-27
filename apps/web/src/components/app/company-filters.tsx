"use client";

import { useTranslations } from "next-intl";
import { Flag } from "@/components/app/bits";
import { MultiSelect } from "@/components/app/multi-select";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import type { Option } from "@/components/app/multi-select";
import { type Facet, useCompanyFacets, useCountries, useCrmStatuses, useIndustries, useLocalizedName, useRegions, useSortByName, useTags } from "@/hooks/use-catalog";
import {
  AD_PLATFORMS, ANALYSIS_STATUSES, CLASSIFICATIONS, SERVICES, TRACKING_TECH, WEBSITE_STATUSES,
  type CompanyFilter,
} from "@/lib/types";

/** Keeps only options that occur in the data (plus ones already selected) and adds their counts. */
function present(options: Option[], facet: Facet[] | undefined, selected: string[] | undefined): Option[] {
  if (!facet) return options;
  const counts = new Map(facet.map((f) => [f.value, f.count]));
  return options.filter((o) => counts.has(o.value) || selected?.includes(o.value)).map((o) => ({ ...o, count: counts.get(o.value) ?? 0 }));
}

export function CompanyFilters({ value, onChange }: { value: CompanyFilter; onChange: (f: CompanyFilter) => void }) {
  const t = useTranslations();
  const name = useLocalizedName();
  const sortByName = useSortByName();
  const { data: countries } = useCountries();
  const { data: regions } = useRegions();
  const { data: industries } = useIndustries();
  const { data: tags } = useTags();
  const { data: statuses } = useCrmStatuses();
  const { data: facets } = useCompanyFacets();
  const set = <K extends keyof CompanyFilter>(k: K, v: CompanyFilter[K]) => onChange({ ...value, [k]: v });
  const num = (v: string) => (v === "" ? null : Math.max(0, Math.min(100, Number(v))));
  const tagOptions = sortByName(tags).map((x) => ({ value: x.id, label: name(x) }));
  const f = facets;
  const tagsPresent = (sel: string[] | undefined) => present(tagOptions, f?.tags, sel);
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-2">
        <MultiSelect label={t("companies.f.regions")} value={value.regions ?? []} onChange={(v) => set("regions", v)}
          options={present((regions ?? []).map((r) => ({ value: r.code, label: name(r) })), f?.regions, value.regions)} />
        <MultiSelect label={t("companies.f.countries")} searchable value={value.countries ?? []} onChange={(v) => set("countries", v)}
          options={present(sortByName(countries).map((c) => ({ value: c.iso2, label: name(c), icon: <Flag code={c.flag} /> })), f?.countries, value.countries)} />
        <MultiSelect label={t("companies.f.industries")} value={value.industries ?? []} onChange={(v) => set("industries", v)}
          options={present(sortByName(industries).map((i) => ({ value: i.key, label: name(i) })), f?.industries, value.industries)} />
        <MultiSelect label={t("companies.f.classification")} value={value.classifications ?? []} onChange={(v) => set("classifications", v)}
          options={present(CLASSIFICATIONS.map((c) => ({ value: c, label: t(`score.classification.${c}`) })), f?.classifications, value.classifications)} />
        <MultiSelect label={t("companies.f.crmStatus")} value={value.crm_status ?? []} onChange={(v) => set("crm_status", v)}
          options={present((statuses ?? []).map((s) => ({ value: s.key, label: name(s) })), f?.crm_status, value.crm_status)} />
        <MultiSelect label={t("companies.f.analysisStatus")} value={value.analysis_status ?? []} onChange={(v) => set("analysis_status", v)}
          options={present(ANALYSIS_STATUSES.map((s) => ({ value: s, label: t(`analysisStatus.${s}`) })), f?.analysis_status, value.analysis_status)} />
        <MultiSelect label={t("companies.f.websiteStatus")} value={value.website_status ?? []} onChange={(v) => set("website_status", v)}
          options={present(WEBSITE_STATUSES.map((s) => ({ value: s, label: t(`websiteStatus.${s}`) })), f?.website_status, value.website_status)} />
        <MultiSelect label={t("companies.f.adPlatforms")} value={value.ad_platforms ?? []} onChange={(v) => set("ad_platforms", v)}
          options={present(AD_PLATFORMS.map((p) => ({ value: p, label: t(`ads.platforms.${p}`) })), f?.ad_platforms, value.ad_platforms)} />
        <MultiSelect label={t("companies.f.services")} value={value.services ?? []} onChange={(v) => set("services", v)}
          options={SERVICES.map((s) => ({ value: s, label: t(`services.${s}`) }))} />
        <MultiSelect label={t("companies.f.trackingDetected")} value={value.tracking_detected ?? []} onChange={(v) => set("tracking_detected", v)}
          options={TRACKING_TECH.map((x) => ({ value: x, label: t(`tracking.tech.${x}`) }))} />
        <MultiSelect label={t("companies.f.trackingNotDetected")} value={value.tracking_not_detected ?? []} onChange={(v) => set("tracking_not_detected", v)}
          options={TRACKING_TECH.map((x) => ({ value: x, label: t(`tracking.tech.${x}`) }))} />
        <MultiSelect label={t("companies.f.tagsAny")} value={value.tags_any ?? []} onChange={(v) => set("tags_any", v)} options={tagsPresent(value.tags_any)} searchable />
        <MultiSelect label={t("companies.f.tagsAll")} value={value.tags_all ?? []} onChange={(v) => set("tags_all", v)} options={tagsPresent(value.tags_all)} searchable />
        <MultiSelect label={t("companies.f.tagsExclude")} value={value.tags_exclude ?? []} onChange={(v) => set("tags_exclude", v)} options={tagsPresent(value.tags_exclude)} searchable />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <Field label={`${t("companies.f.score")} ${t("companies.f.min")}`}>
          <Input type="number" min={0} max={100} value={value.score_min ?? ""} onChange={(e) => set("score_min", num(e.target.value))} />
        </Field>
        <Field label={`${t("companies.f.score")} ${t("companies.f.max")}`}>
          <Input type="number" min={0} max={100} value={value.score_max ?? ""} onChange={(e) => set("score_max", num(e.target.value))} />
        </Field>
        <Field label={`${t("companies.f.confidence")} ${t("companies.f.min")}`}>
          <Input type="number" min={0} max={100} value={value.confidence_min ?? ""} onChange={(e) => set("confidence_min", num(e.target.value))} />
        </Field>
        <Field label={`${t("companies.f.auditDate")} ${t("companies.f.from")}`}>
          <Input type="date" value={value.audit_from?.slice(0, 10) ?? ""} onChange={(e) => set("audit_from", e.target.value ? `${e.target.value}T00:00:00Z` : null)} />
        </Field>
        <Field label={`${t("companies.f.auditDate")} ${t("companies.f.to")}`}>
          <Input type="date" value={value.audit_to?.slice(0, 10) ?? ""} onChange={(e) => set("audit_to", e.target.value ? `${e.target.value}T23:59:59Z` : null)} />
        </Field>
        <Field label={t("companies.f.dnc")}>
          <NativeSelect value={value.dnc ?? "exclude"} onChange={(e) => set("dnc", e.target.value as CompanyFilter["dnc"])}>
            <option value="exclude">{t("companies.f.dncExclude")}</option>
            <option value="include">{t("companies.f.dncInclude")}</option>
            <option value="only">{t("companies.f.dncOnly")}</option>
          </NativeSelect>
        </Field>
        <Field label={t("companies.f.archived")}>
          <NativeSelect value={value.archived ?? "exclude"} onChange={(e) => set("archived", e.target.value as CompanyFilter["archived"])}>
            <option value="exclude">{t("companies.f.dncExclude")}</option>
            <option value="include">{t("companies.f.dncInclude")}</option>
            <option value="only">{t("companies.f.dncOnly")}</option>
          </NativeSelect>
        </Field>
        <Field label={t("companies.f.industryConfidence")}>
          <NativeSelect value={value.industry_confidence ?? ""} onChange={(e) => set("industry_confidence", (e.target.value || null) as CompanyFilter["industry_confidence"])}>
            <option value="">{t("common.all")}</option>
            <option value="confident">{t("dataSources.confident")}</option>
            <option value="review">{t("dataSources.reviewCandidate")}</option>
          </NativeSelect>
        </Field>
      </div>
      <div className="flex flex-wrap gap-4 text-[13px]">
        <label className="flex items-center gap-2">
          <NativeSelect className="h-7 w-auto" value={value.ad_mode ?? "any"} onChange={(e) => set("ad_mode", e.target.value as "any" | "all")}>
            <option value="any">{t("companies.f.adModeAny")}</option>
            <option value="all">{t("companies.f.adModeAll")}</option>
          </NativeSelect>
          <span className="text-muted">{t("companies.f.adPlatforms")}</span>
        </label>
        <label className="flex items-center gap-2">
          <NativeSelect className="h-7 w-auto" value={value.has_website === null || value.has_website === undefined ? "" : String(value.has_website)}
            onChange={(e) => set("has_website", e.target.value === "" ? null : e.target.value === "true")}>
            <option value="">{t("common.all")}</option>
            <option value="true">{t("common.yes")}</option>
            <option value="false">{t("common.no")}</option>
          </NativeSelect>
          <span className="text-muted">{t("companies.f.hasWebsite")}</span>
        </label>
        <label className="flex items-center gap-2">
          <NativeSelect className="h-7 w-auto" value={value.watchlisted === null || value.watchlisted === undefined ? "" : String(value.watchlisted)}
            onChange={(e) => set("watchlisted", e.target.value === "" ? null : e.target.value === "true")}>
            <option value="">{t("common.all")}</option>
            <option value="true">{t("common.yes")}</option>
            <option value="false">{t("common.no")}</option>
          </NativeSelect>
          <span className="text-muted">{t("companies.f.watchlisted")}</span>
        </label>
      </div>
    </div>
  );
}

export function activeFilterCount(f: CompanyFilter): number {
  let n = 0;
  for (const [k, v] of Object.entries(f)) {
    if (k === "q" || k === "ad_mode" || k === "service_min") continue;
    if (k === "dnc" || k === "archived") {
      if (v && v !== "exclude") n++;
      continue;
    }
    if (Array.isArray(v) ? v.length : v !== null && v !== undefined && v !== "") n++;
  }
  return n;
}
