"use client";

import { useLocale } from "next-intl";
import { useApi } from "@/hooks/use-api";
import type { Country, Industry, Tag } from "@/lib/types";

export function useCountries() {
  return useApi<Country[]>(["countries"], "/countries");
}

export function useRegions() {
  return useApi<{ code: string; name_en: string; name_tr: string }[]>(["regions"], "/regions");
}

export function useIndustries() {
  return useApi<Industry[]>(["industries"], "/industries");
}

export interface CrmStatusItem { key: string; name_en: string; name_tr: string; sort_order: number; is_terminal: boolean; show_in_pipeline: boolean; is_system: boolean; count: number }

/** CRM statuses as configured by the administrator (Settings → CRM statuses), in pipeline order. */
export function useCrmStatuses() {
  return useApi<CrmStatusItem[]>(["crm-statuses"], "/crm/statuses");
}

/** Options for status pickers: every status except "Do not contact" (set through its own action). */
export function useCrmStatusOptions() {
  const { data } = useCrmStatuses();
  const name = useLocalizedName();
  return (data ?? []).filter((s) => s.key !== "do_not_contact").map((s) => ({ value: s.key, label: name(s) }));
}

export interface Facet { value: string; count: number }
export type Facets = Record<"countries" | "regions" | "industries" | "crm_status" | "website_status" | "analysis_status" | "classifications" | "tags" | "ad_platforms", Facet[]>;

/** Values that occur in the company list (with counts), so filters only offer useful options. */
export function useCompanyFacets() {
  return useApi<Facets>(["company-facets"], "/companies/facets", { refetchInterval: 60_000 });
}

export function useTags() {
  return useApi<Tag[]>(["tags"], "/tags");
}

/** Sorts items alphabetically by their name in the active language (Turkish collation for "tr"). */
export function useSortByName() {
  const locale = useLocale();
  return <T extends { name_en: string; name_tr: string }>(items: T[] | undefined): T[] => {
    const key = locale === "tr" ? "name_tr" : "name_en";
    return [...(items ?? [])].sort((a, b) => a[key].localeCompare(b[key], locale, { sensitivity: "base" }));
  };
}

export function useLocalizedName() {
  const locale = useLocale();
  return (item: { name_en: string; name_tr: string } | null | undefined) => (item ? (locale === "tr" ? item.name_tr : item.name_en) : "—");
}
