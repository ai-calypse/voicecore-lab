import { expect, test } from "@playwright/test";

// Step 10 (P9): the read-only console demo the docs site serves at /console/ (snapshots of the real API).
test("the console demo shows the published VoiceCore docs agent and refuses changes", async ({ page }) => {
  await page.goto("/console/");
  await expect(page.getByText("Read-only demo. Install it to try: npx create-voicecore")).toBeVisible();
  await expect(page.getByRole("link", { name: /VoiceCore docs/ })).toContainText("363 sections from 32 pages");
  await page.getByRole("link", { name: /VoiceCore docs/ }).click();
  await expect(page.getByRole("heading", { name: "VoiceCore docs", exact: true })).toBeVisible();
  await expect(page.locator(".live-summary")).toHaveText("363 sections from 32 pages");
  await expect(page.getByText(/^Version [0-9a-f]{12}$/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish changes" })).toBeDisabled();
});
