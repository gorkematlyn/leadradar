"use client";

import { useTranslations } from "next-intl";
import { useCountries, useLocalizedName } from "@/hooks/use-catalog";

/** Renders a stored notification (translation key + params) in the active language.
 * Country codes in the params are shown as localized country names. */
export function useNotificationText() {
  const t = useTranslations("notifications");
  const name = useLocalizedName();
  const { data: countries } = useCountries();
  return (messageKey: string, params: Record<string, string | number>) => {
    const key = messageKey.replace(/^notifications\./, "");
    const p = { ...params };
    if (typeof p.country === "string") {
      const c = countries?.find((x) => x.iso2 === String(p.country).toUpperCase());
      if (c) p.country = name(c);
    }
    try {
      return t.has(key) ? t(key, p) : messageKey;
    } catch {
      return messageKey;
    }
  };
}
