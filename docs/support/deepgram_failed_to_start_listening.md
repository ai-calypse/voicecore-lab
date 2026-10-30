# Draft ticket for Deepgram support (not sent)

Sending this is an outward action, so the user sends it from their Deepgram account.

---

**Subject:** Voice Agent API: intermittent `FAILED_TO_START_LISTENING` right after `Welcome`

Hello,

Using the Voice Agent API (`wss://agent.deepgram.com/v1/agent/converse`), 3 of 7 sessions on 2026-10-29 failed during setup with:

```json
{"type": "Error", "code": "FAILED_TO_START_LISTENING", "description": "Failed to start listening. Please check your `listen` settings."}
```

The same `Settings` message worked in the other sessions (listen `deepgram nova-3`, think `open_ai gpt-4o-mini`, speak `deepgram v2 flux-kit-en`, input linear16 16 kHz, output linear16 24 kHz). The failures came 0.7–1.4 s after `Welcome`, in back-to-back sessions (one test also had a 5 s gap between sessions).

Request IDs of the failed sessions:

- `01a188d7-f7fe-71b3-9d07-e160da3423b7` (2026-10-29 18:06 UTC)
- `01a188d7-facc-7d33-a76e-e645e6895634` (2026-10-29 18:06 UTC)
- `01a188d9-7364-7251-bc72-2685eb2d0bfd` (2026-10-29 18:07 UTC)

For comparison, 10 back-to-back plain `/v1/listen` (nova-3) sessions on 2026-10-30 all succeeded, as did a later Voice Agent session (`01a18a5d-3b46-76b0-8be6-579f12bdd54c`). Could you tell us what made listening fail to start for those three sessions, and whether a client-side retry is the recommended handling?

Thank you.
