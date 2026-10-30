// Runs after Playwright's webServers are up: refuse to test against an orchestrator with live (paid) providers.
import { checkMockOnly } from "./check-mock-only.ts";

export default async function globalSetup() {
  await checkMockOnly("http://127.0.0.1:18766");
}
