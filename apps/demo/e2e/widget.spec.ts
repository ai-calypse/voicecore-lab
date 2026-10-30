import { expect, test } from "@playwright/test";

// S08-T01 (seam 13): the one-script widget on an unrelated page with hostile CSS, against the real gateway and
// orchestrator (mock providers). Playwright locators pierce the widget's open Shadow DOM.
test.describe.configure({ mode: "serial" }); // one mock orchestrator behind one gateway

test("an unrelated page embeds the widget with one script tag and its CSS does not leak in", async ({ page }) => {
  await page.goto("/embed-test.html");
  const launcher = page.getByRole("button", { name: "Ask the docs" });
  await expect(launcher).toBeVisible();
  const font = await launcher.evaluate((el) => getComputedStyle(el).fontFamily);
  expect(font).not.toContain("Comic Sans");
  await launcher.click();
  await expect(page.getByRole("dialog", { name: "Docs assistant" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Ready", { timeout: 10_000 });
});

test("a typed question gets an answer that links to the docs it cites", async ({ page }) => {
  await page.goto("/embed-test.html");
  await page.getByRole("button", { name: "Ask the docs" }).click();
  await page.getByRole("textbox", { name: "Your question" }).fill("How does eager endpointing work?");
  await page.getByRole("button", { name: "Send" }).click();
  const answer = page.locator("li.agent").first();
  await expect(answer).toContainText("speech recognizer", { timeout: 15_000 });
  const cite = answer.locator("a.cite").first();
  await expect(cite).toHaveAttribute("href", /^http:\/\/localhost:3000\//);
});

test("a spoken question round-trips: transcript, cited answer and playback", async ({ page }) => {
  await page.goto("/embed-test.html");
  await page.getByRole("button", { name: "Ask the docs" }).click();
  await expect(page.getByRole("status")).toContainText("Ready", { timeout: 10_000 });
  await page.getByRole("button", { name: "Start talking" }).click();
  await expect(page.locator("li.user").first()).toHaveText("how does eager endpointing work?", { timeout: 20_000 });
  await expect(page.locator("li.agent").first()).toContainText("punctuated final", { timeout: 10_000 });
  await expect(page.getByRole("status")).toContainText("Speaking", { timeout: 10_000 });
  await page.getByRole("button", { name: "Close and end the session" }).click();
  await expect(page.getByRole("button", { name: "Ask the docs" })).toBeFocused();
});

test("with the microphone blocked the widget says so and text still works", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
  });
  await page.goto("/embed-test.html");
  await page.getByRole("button", { name: "Ask the docs" }).click();
  await page.getByRole("button", { name: "Start talking" }).click();
  await expect(page.getByRole("status")).toContainText("Microphone access was blocked");
  await expect(page.getByRole("button", { name: "Microphone blocked" })).toBeDisabled();
  await page.getByRole("textbox", { name: "Your question" }).fill("How does eager endpointing work?");
  await page.keyboard.press("Enter");
  await expect(page.locator("li.agent").first()).toContainText("punctuated final", { timeout: 15_000 });
});

test("a cited answer asks the host page to open the first cited section, and so does a citation click", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { navs: string[] };
    w.navs = [];
    addEventListener("voicecore:navigate", (e) => { w.navs.push((e as CustomEvent).detail.url); e.preventDefault(); });
  });
  await page.goto("/embed-test.html");
  await page.getByRole("button", { name: "Ask the docs" }).click();
  await page.getByRole("textbox", { name: "Your question" }).fill("How does eager endpointing work?");
  await page.keyboard.press("Enter");
  const navs = () => page.evaluate(() => (window as unknown as { navs: string[] }).navs);
  await expect.poll(navs, { timeout: 15_000 }).toEqual([expect.stringMatching(/^http:\/\/localhost:3000\//)]);
  const popup = page.waitForEvent("popup", { timeout: 1_000 }).catch(() => null);
  await page.locator("li.agent a.cite").first().click();
  expect(await popup).toBeNull(); // the host handled it: no new tab
  expect(await navs()).toHaveLength(2);
});

test("a dropped connection says Reconnecting…, resumes the session and keeps answering", async ({ page }) => {
  await page.addInitScript(() => { // keep a handle on the widget's sockets, so the test can cut one
    const W = window.WebSocket;
    const sockets: WebSocket[] = ((window as unknown as { sockets: WebSocket[] }).sockets = []);
    window.WebSocket = class extends W { constructor(u: string | URL, p?: string | string[]) { super(u, p); sockets.push(this); } } as typeof WebSocket;
  });
  await page.goto("/embed-test.html");
  await page.getByRole("button", { name: "Ask the docs" }).click();
  await expect(page.getByRole("status")).toContainText("Ready", { timeout: 10_000 });
  await page.evaluate(() => (window as unknown as { sockets: WebSocket[] }).sockets.at(-1)!.close(4000, "test: network dropped"));
  await expect(page.getByRole("status")).toContainText("Reconnecting");
  await expect(page.getByRole("status")).toContainText("Ready", { timeout: 10_000 });
  expect(await page.evaluate(() => (window as unknown as { sockets: WebSocket[] }).sockets.at(-1)!.url)).toMatch(/\?resume=s-gw-[0-9a-f]{16}$/);
  await page.getByRole("textbox", { name: "Your question" }).fill("How does eager endpointing work?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator("li.agent").first()).toContainText("speech recognizer", { timeout: 15_000 });
});
