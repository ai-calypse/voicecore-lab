import { expect, test } from "@playwright/test";

// Seam 13: the ?lab=1 panel on a committed sample trace (one interrupted and one completed generation).
test("fixture trace shows 5 stage bars and marks the interrupted generation", async ({ page }) => {
  await page.goto("/?lab=1&trace=/lab/sample-timeline.json");
  await expect(page.getByRole("heading", { name: "Session timeline" })).toBeVisible();
  const stages = page.locator("[data-stage]");
  await expect(stages).toHaveCount(5);
  for (const s of ["endpoint", "stt", "llm", "tts", "playout"]) {
    await expect(page.locator(`[data-stage="${s}"] .bar[data-gen="2"]`)).toHaveCount(1);
  }
  await expect(page.locator('.seg.agent[data-gen="1"]')).toHaveAttribute("data-interrupted", "true");
  await expect(page.locator('.seg.agent[data-gen="2"]')).toHaveAttribute("data-interrupted", "false");
  await expect(page.getByText("gen 1 · interrupted")).toBeVisible();
  await page.getByRole("button", { name: "gateway" }).click();
  await expect(page.locator("td.proc.gateway")).toHaveCount(0);
});

test("loading a file that is not a timeline shows an error and keeps the current trace", async ({ page }) => {
  await page.goto("/?lab=1&trace=/lab/sample-timeline.json");
  await expect(page.locator("[data-stage]")).toHaveCount(5);
  await page.locator('.lab-load input[type="file"]').setInputFiles({ name: "notes.json", mimeType: "application/json", buffer: Buffer.from('{"hello": 1}') });
  await expect(page.getByRole("alert")).toContainText("Could not show notes.json");
  await expect(page.locator("[data-stage]")).toHaveCount(5);
});
