import { expect, test } from "@playwright/test";

// Step 10 (seam 13): the console's one-line snippet. The gateway serves the widget, the widget names its agent,
// and the free orchestrator answers from that agent's published bundle (fixtures/agents/acme-docs).
test("the snippet's script names its agent and talks to the gateway that served it", async ({ page }) => {
  const token = page.waitForRequest((r) => r.url() === "http://127.0.0.1:18083/v1/session" && r.method() === "POST");
  await page.goto("/embed-agent.html");
  await page.getByRole("button", { name: "Ask the docs" }).click();
  expect((await token).postData()).toBe("agent=acme-docs");
  await expect(page.locator("li.agent").first()).toHaveText("Text answers from your docs. Voice turns on once provider keys are set.", { timeout: 15_000 });
  await page.getByRole("textbox", { name: "Your question" }).fill("how do refunds work");
  await page.getByRole("button", { name: "Send" }).click();
  const answer = page.locator("li.agent").nth(1);
  await expect(answer).toContainText("Closest section: Refunds > How refunds work.", { timeout: 15_000 });
  await expect(answer.locator(".sources a")).toHaveCount(1); // the bundle's passages link to docs.acme.test
});
