// Fails when English and Turkish message catalogs differ in keys or contain empty strings.
import { readFileSync } from "node:fs";

const load = (l) => JSON.parse(readFileSync(new URL(`../messages/${l}.json`, import.meta.url), "utf8"));
const flatten = (obj, prefix = "") =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? flatten(v, `${prefix}${k}.`) : [[`${prefix}${k}`, v]]));

const en = new Map(flatten(load("en")));
const tr = new Map(flatten(load("tr")));
const problems = [];
for (const k of en.keys()) if (!tr.has(k)) problems.push(`missing in tr: ${k}`);
for (const k of tr.keys()) if (!en.has(k)) problems.push(`missing in en: ${k}`);
for (const [lang, map] of [["en", en], ["tr", tr]]) for (const [k, v] of map) if (typeof v !== "string" || !v.trim()) problems.push(`empty ${lang}: ${k}`);
// Argument names only ("{count}" or "{count, plural, …}"), not the words inside plural branches.
const placeholders = (s) => [...new Set([...String(s).matchAll(/\{\s*(\w+)\s*[,}]/g)].map((m) => m[1]))].sort().join(",");
for (const [k, v] of en) if (tr.has(k) && placeholders(v) !== placeholders(tr.get(k))) problems.push(`placeholder mismatch: ${k}`);
// Every message must be valid ICU syntax (literal braces must be quoted, e.g. '{query}').
// intl-messageformat ships with next-intl; the check is skipped if it cannot be loaded.
try {
  const { IntlMessageFormat } = await import("intl-messageformat");
  for (const [lang, map] of [["en", en], ["tr", tr]]) {
    for (const [k, v] of map) {
      try {
        new IntlMessageFormat(v, lang);
      } catch (e) {
        problems.push(`invalid ICU message ${lang}: ${k} (${e.message})`);
      }
    }
  }
} catch {
  console.warn("intl-messageformat not available; ICU syntax check skipped");
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`i18n OK: ${en.size} keys in en and tr`);
