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
const placeholders = (s) => [...String(s).matchAll(/\{(\w+)/g)].map((m) => m[1]).sort().join(",");
for (const [k, v] of en) if (tr.has(k) && placeholders(v) !== placeholders(tr.get(k))) problems.push(`placeholder mismatch: ${k}`);
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`i18n OK: ${en.size} keys in en and tr`);
