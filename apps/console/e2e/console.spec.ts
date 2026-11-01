import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

// Step 10, P6 (seam 23): the ten-minute path in the console, on the real stack in free mode.
test.describe.configure({ mode: "serial" }); // one console, set up once
const ACME_ZIP = fileURLToPath(new URL("../../../fixtures/docs/acme.zip", import.meta.url));
const SNIPPET = '<script src="http://127.0.0.1:18082/widget.js" data-agent="acme-docs" async></script>';

test("first run to a cited answer in the Test tab, then the snippet", async ({ page }) => {
  await page.goto("/#/setup?token=e2e-setup");
  await page.getByLabel("Admin password").fill("correct horse battery");
  await page.getByRole("button", { name: "Create admin" }).click();
  await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
  await expect(page.getByText("No agents yet")).toBeVisible();
  await expect(page.getByText("Voice is off.")).toBeVisible(); // free mode

  await page.getByRole("button", { name: "New agent" }).click();
  await page.getByLabel("Agent name").fill("Acme Docs");
  await page.getByRole("button", { name: "Create agent" }).click();
  await expect(page.getByRole("heading", { name: "Acme Docs", exact: true })).toBeVisible();

  await expect(page.getByLabel("Website address")).toBeVisible(); // a website is the first way offered
  await page.getByLabel("Upload files").check();
  await page.getByLabel("Docs files").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: Buffer.from("png") });
  await expect(page.getByRole("alert")).toHaveText("logo.png: not a Markdown, text or zip file: logo.png");
  await page.getByLabel("Docs files").setInputFiles(ACME_ZIP);
  await expect(page.getByText("Added 2 pages from acme.zip.")).toBeVisible();
  await expect(page.locator(".steps li").nth(0)).toHaveClass("done");

  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Live version" })).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(".live-summary")).toHaveText("3 sections from 2 pages");
  await expect(page.getByText(/^Version [0-9a-f]{12}$/)).toBeVisible();
  await expect(page.locator(".steps li").nth(1)).toHaveClass("done");

  await page.getByRole("tab", { name: "Test" }).click();
  await page.locator("iframe.preview").scrollIntoViewIfNeeded(); // the assistant sits in the frame's bottom corner
  const frame = page.frameLocator("iframe.preview");
  await frame.getByRole("button", { name: "Ask the docs" }).click();
  await expect(frame.locator("li.agent").first()).toHaveText("Text answers from your docs. Voice turns on once provider keys are set.", { timeout: 30_000 });
  await frame.getByRole("textbox", { name: "Your question" }).fill("how do refunds work");
  await frame.getByRole("button", { name: "Send" }).click();
  await expect(frame.locator("li.agent").nth(1)).toContainText("Closest section: Refunds > How refunds work.", { timeout: 30_000 });
  await expect(page.locator(".steps li").nth(2)).toHaveClass("done");

  await page.getByRole("tab", { name: "Embed" }).click();
  await expect(page.locator(".snippet code")).toHaveText(SNIPPET);

  await page.getByRole("link", { name: "Agents", exact: true }).first().click();
  await expect(page.getByRole("link", { name: /Acme Docs/ })).toContainText("3 sections from 2 pages");
});

test("spending limits are set on the Voice page", async ({ page }) => {
  await page.goto("/#/voice");
  await page.getByLabel("Admin password").fill("correct horse battery");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Per day, in US dollars").fill("2");
  await page.getByLabel("In total, in US dollars").fill("20");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByText("Saved. The new limits apply from the next conversation.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("In total, in US dollars")).toHaveValue("20");
});

test("a signed-out visitor is asked to sign in", async ({ browser }) => {
  const page = await (await browser.newContext()).newPage();
  await page.goto("http://127.0.0.1:18010/#/agents");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Admin password").fill("wrong password!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Wrong password.");
});
