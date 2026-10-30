import { startPlayout, VoiceClient } from "@voicecore/web-sdk";

// Exposed for end-to-end tests and manual poking from the console.
(window as unknown as { voicecore: unknown }).voicecore = { VoiceClient, startPlayout };
