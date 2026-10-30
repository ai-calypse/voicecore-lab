// Playwright globalSetup guard (Step 09): e2e must never talk to an orchestrator with live (paid) providers.
// A dev's live orchestrator once sat on the port the e2e stack uses; reusing it would have spent money.
const NO_SPEND = new Set(["mock", "mock-billed"]);

export async function checkMockOnly(orchestrator: string): Promise<void> {
  let health: { providers?: string };
  try {
    health = await (await fetch(`${orchestrator}/healthz`)).json();
  } catch {
    throw new Error(`no orchestrator at ${orchestrator}`);
  }
  if (!NO_SPEND.has(health.providers ?? "")) throw new Error(`refusing to run e2e against live providers (${orchestrator} says ${health.providers})`);
}
