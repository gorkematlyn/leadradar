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
