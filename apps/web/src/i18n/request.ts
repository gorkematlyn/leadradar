import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

export const LOCALES = ["en", "tr"] as const;
export type Locale = (typeof LOCALES)[number];

export default getRequestConfig(async () => {
  const store = await cookies();
  let locale: Locale = "en";
  const cookieLocale = store.get("NEXT_LOCALE")?.value;
  if (cookieLocale === "tr" || cookieLocale === "en") {
    locale = cookieLocale;
  } else {
    const accept = (await headers()).get("accept-language") ?? "";
    if (accept.toLowerCase().startsWith("tr")) locale = "tr";
  }
  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
    timeZone: "UTC",
  };
});
