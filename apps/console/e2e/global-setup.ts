// Runs once the servers are up: refuse to test against an orchestrator with paid providers.
import { checkMockOnly } from "../../demo/e2e/check-mock-only.ts";

export default async function globalSetup() {
  await checkMockOnly("http://127.0.0.1:18767");
}
