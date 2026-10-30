import { expect, test } from "@playwright/test";

// S08-T01 (seam 13): the one-script widget on an unrelated page with hostile CSS, against the real gateway and
// orchestrator (mock providers). Playwright locators pierce the widget's open Shadow DOM.
test.describe.configure({ mode: "serial" }); // one mock orchestrator behind one gateway

test("an unrelated page embeds the widget with one script tag and its CSS does not leak in", async ({ page }) => {
  await page.goto("/embed-test.html");
  const launcher = page.getByRole("button", { name: "Ask the uv docs" });
  await expect(launcher).toBeVisible();
  const font = await launcher.evaluate((el) => getComputedStyle(el).fontFamily);
  expect(font).not.toContain("Comic Sans");
  await launcher.click();
  await expect(page.getByRole("dialog", { name: "uv docs voice assistant" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Ready", { timeout: 10_000 });
});

test("a typed question gets an answer that links to the docs it cites", async ({ page }) => {
  await page.goto("/embed-test.html");
  await page.getByRole("button", { name: "Ask the uv docs" }).click();
  await page.getByRole("textbox", { name: "Your question" }).fill("How do I install uv?");
  await page.getByRole("button", { name: "Send" }).click();
  const answer = page.locator("li.agent").first();
  await expect(answer).toContainText("standalone installer", { timeout: 15_000 });
  const cite = answer.locator("a.cite").first();
  await expect(cite).toHaveAttribute("href", /^https:\/\/docs\.astral\.sh\/uv\//);
});

test("a spoken question round-trips: transcript, cited answer and playback", async ({ page }) => {
  await page.goto("/embed-test.html");
  await page.getByRole("button", { name: "Ask the uv docs" }).click();
  await expect(page.getByRole("status")).toContainText("Ready", { timeout: 10_000 });
  await page.getByRole("button", { name: "Start talking" }).click();
  await expect(page.locator("li.user").first()).toHaveText("how do I install uv?", { timeout: 20_000 });
  await expect(page.locator("li.agent").first()).toContainText("installer", { timeout: 10_000 });
  await expect(page.getByRole("status")).toContainText("Speaking", { timeout: 10_000 });
  await page.getByRole("button", { name: "Close and end the session" }).click();
  await expect(page.getByRole("button", { name: "Ask the uv docs" })).toBeFocused();
});

test("with the microphone blocked the widget says so and text still works", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
  });
  await page.goto("/embed-test.html");
  await page.getByRole("button", { name: "Ask the uv docs" }).click();
  await page.getByRole("button", { name: "Start talking" }).click();
  await expect(page.getByRole("status")).toContainText("Microphone access was blocked");
  await expect(page.getByRole("button", { name: "Microphone blocked" })).toBeDisabled();
  await page.getByRole("textbox", { name: "Your question" }).fill("How do I install uv?");
  await page.keyboard.press("Enter");
  await expect(page.locator("li.agent").first()).toContainText("installer", { timeout: 15_000 });
});
