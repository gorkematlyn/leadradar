// Browser end-to-end smoke test against a running stack (web + api + database).
// Usage: BASE_URL=http://127.0.0.1:3000 E2E_EMAIL=... E2E_PASSWORD=... node tests/e2e/smoke.mjs
// Requires the `playwright` package and Chromium. Never point this at production data you care about:
// it creates a company, a tag and switches language/theme.
import { chromium } from "playwright";
import assert from "node:assert/strict";

const base = process.env.BASE_URL ?? "http://127.0.0.1:3000";
const email = process.env.E2E_EMAIL;
const password = process.env.E2E_PASSWORD;
assert.ok(email && password, "set E2E_EMAIL and E2E_PASSWORD");

const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
const page = await (await browser.newContext({ viewport: { width: 1366, height: 900 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
const step = async (name, fn) => { await fn(); console.log(`ok - ${name}`); };

await step("unauthenticated users are redirected to login", async () => {
  await page.goto(`${base}/companies`);
  await page.waitForURL(/\/login/);
});
await step("robots.txt disallows crawling", async () => {
  const res = await page.request.get(`${base}/robots.txt`);
  assert.match(await res.text(), /Disallow: \//);
  assert.match(res.headers()["x-robots-tag"] ?? "", /noindex/);
});
await step("administrator login", async () => {
  await page.goto(`${base}/login`);
  await page.fill("input[type=email]", email);
  await page.fill("input[type=password]", password);
  await page.click("button[type=submit]");
  await page.waitForURL(`${base}/`);
});
const name = `E2E Company ${Date.now()}`;
await step("create company manually", async () => {
  await page.goto(`${base}/companies`);
  await page.click("text=Add company");
  await page.fill("form#new-company input >> nth=0", name);
  await page.click("button[form=new-company]");
  await page.waitForURL(/\/companies\/[0-9a-f-]{36}/);
  await page.getByRole("heading", { name }).waitFor();
});
await step("company appears in the server-side table and search", async () => {
  await page.goto(`${base}/companies`);
  await page.fill("input[aria-label=Search]", name);
  await page.getByText(name).first().waitFor();
});
await step("create tag", async () => {
  await page.goto(`${base}/tags`);
  await page.click("text=New tag");
  await page.fill("[role=dialog] input >> nth=0", `e2e-${Date.now()}`);
  await page.click("[role=dialog] >> text=Save");
});
await step("language switch to Turkish persists", async () => {
  await page.click("button[aria-label=Language]");
  await page.click("text=Türkçe");
  await page.getByText("Şirketler").first().waitFor();
  await page.reload();
  await page.getByText("Şirketler").first().waitFor();
  await page.click("button[aria-label=Dil]");
  await page.click("text=English");
  await page.getByText("Companies").first().waitFor();
});
await step("theme switch to dark", async () => {
  await page.click("button[aria-label=Theme]");
  await page.click("text=Dark");
  assert.ok(await page.evaluate(() => document.documentElement.classList.contains("dark")));
});
await step("key pages render", async () => {
  for (const p of ["/", "/discovery", "/pipeline", "/review", "/reports", "/jobs", "/data-sources", "/saved-filters", "/campaigns", "/usage", "/settings"]) {
    await page.goto(base + p);
    await page.locator("main h1").first().waitFor();
  }
});
await browser.close();
assert.deepEqual(errors, [], `page errors: ${errors.join("; ")}`);
console.log("e2e smoke passed");
