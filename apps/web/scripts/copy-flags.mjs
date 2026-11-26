// Copies self-hosted flag SVGs (flag-icons, MIT) into public/flags at install time.
import { cpSync, existsSync, mkdirSync, copyFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
let pkgDir;
try {
  pkgDir = dirname(require.resolve("flag-icons/package.json"));
} catch {
  console.warn("flag-icons not installed; skipping flag copy");
  process.exit(0);
}
const src = join(pkgDir, "flags", "4x3");
const dest = join(process.cwd(), "public", "flags");
if (!existsSync(src)) process.exit(0);
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });
copyFileSync(join(pkgDir, "LICENSE"), join(dest, "LICENSE-flag-icons.txt"));
console.log(`copied flags to ${dest}`);
