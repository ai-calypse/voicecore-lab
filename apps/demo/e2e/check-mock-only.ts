// Playwright globalSetup guard (Step 09): e2e must never talk to an orchestrator with live (paid) providers.
// A dev's live orchestrator once sat on the port the e2e stack used; reusing it would have spent money.
const NO_SPEND = new Set(["mock", "mock-billed"]);

export async function checkMockOnly(orchestrator: string, timeoutMs = 5000): Promise<void> {
  let health: { providers?: string };
  let res: Response;
  try {
    res = await fetch(`${orchestrator}/healthz`, { signal: AbortSignal.timeout(timeoutMs) });
  } catch {
    throw new Error(`no orchestrator at ${orchestrator}`);
  }
  if (!res.ok) throw new Error(`no orchestrator at ${orchestrator} (HTTP ${res.status})`);
  try {
    health = await res.json();
  } catch {
    throw new Error(`no orchestrator at ${orchestrator} (not JSON)`);
  }
  if (!NO_SPEND.has(health.providers ?? "")) throw new Error(`refusing to run e2e against live providers (${orchestrator} says ${health.providers})`);
}
