import { expect, test, type Page } from "@playwright/test";

// Step 09 Phase 7 (seam 13): against the compose stack's nginx images, which send the security headers. The CI
// docker job runs it (playwright.compose.config.ts); locally DOCS_URL and DEMO_URL point at a running stack.
const DOCS = process.env.DOCS_URL ?? "http://localhost:3000";
const DEMO = process.env.DEMO_URL ?? "http://localhost:5173";

async function watch(page: Page) {
  const refused: string[] = [];
  page.on("console", (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) refused.push(m.text()); });
  await page.addInitScript(() => document.addEventListener("securitypolicyviolation", (e) => {
    const w = window as unknown as { csp?: string[] };
    w.csp = [...(w.csp ?? []), `${e.violatedDirective} ${e.blockedURI}`];
  }));
  return async () => [...refused, ...(await page.evaluate(() => (window as unknown as { csp?: string[] }).csp ?? []))];
}

function expectHeaders(headers: Record<string, string>) {
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(headers["content-security-policy"]).not.toContain("script-src 'self' 'unsafe-inline'");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
}

test("the docs site sends the headers, and a mock turn through the widget breaks no CSP rule", async ({ page }) => {
  const violations = await watch(page);
  expectHeaders((await page.goto(`${DOCS}/concepts/endpointing`))!.headers());
  await page.getByRole("button", { name: "Ask the docs" }).click();
  await page.getByRole("textbox", { name: "Your question" }).fill("How does eager endpointing work?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator("li.agent").first()).toContainText("speech recognizer", { timeout: 20_000 });
  expect(await violations()).toEqual([]);
});

for (const path of ["/", "/?lab=1"]) {
  test(`the demo page ${path} sends the headers and breaks no CSP rule`, async ({ page }) => {
    const violations = await watch(page);
    expectHeaders((await page.goto(`${DEMO}${path}`))!.headers());
    await page.waitForLoadState("networkidle");
    expect(await violations()).toEqual([]);
  });
}

test("an injected inline script is blocked and reported (the policy is enforced, and the checks above can see it)", async ({ page }) => {
  const violations = await watch(page);
  await page.goto(`${DOCS}/`);
  await page.evaluate(() => {
    const s = document.createElement("script");
    s.textContent = "window.injected = 1";
    document.head.appendChild(s);
  });
  await expect.poll(violations).toContainEqual(expect.stringContaining("script-src"));
  expect(await page.evaluate(() => (window as unknown as { injected?: number }).injected)).toBeUndefined();
});
