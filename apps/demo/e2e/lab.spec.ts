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
