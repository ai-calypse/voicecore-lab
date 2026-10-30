import { expect, test } from "@playwright/test";

// What the widget does when an answer cites a section: dispatch "voicecore:navigate". The site (src/theme/Root.jsx)
// must open the page without a reload (the voice session lives in the page) and highlight the cited section.
test("a navigate event opens the cited section without a reload and highlights it", async ({ page }) => {
  const html = await (await page.request.get("/concepts/endpointing")).text();
  const ids = [...html.matchAll(/<h2[^>]*\bid="([^"]+)"/g)].map((m) => m[1]);
  const id = ids[1] ?? ids[0]; // not the first: the page must scroll
  await page.goto("/");
  await page.evaluate(() => { (window as unknown as { marker: number }).marker = 1; });
  const handled = await page.evaluate((url) =>
    !dispatchEvent(new CustomEvent("voicecore:navigate", { detail: { url, title: "t" }, cancelable: true })), `${new URL(page.url()).origin}/concepts/endpointing#${id}`);
  expect(handled).toBe(true);
  await expect(page).toHaveURL(new RegExp(`/concepts/endpointing#${id}$`));
  await expect(page.locator(`[id="${id}"]`)).toHaveClass(/vc-cited/);
  await expect(page.locator(".vc-cited").last()).toBeInViewport();
  expect(await page.evaluate(() => (window as unknown as { marker?: number }).marker)).toBe(1); // same document
});

test("a link to another site is left to the widget", async ({ page }) => {
  await page.goto("/");
  const handled = await page.evaluate(() =>
    !dispatchEvent(new CustomEvent("voicecore:navigate", { detail: { url: "https://example.com/x#y", title: "t" }, cancelable: true })));
  expect(handled).toBe(false);
});
