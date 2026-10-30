---
title: Telephony extension design
sidebar_label: Telephony
description: The design for putting phone calls in front of VoiceCore with a Twilio Media Streams adapter, including the SIP call flow and codec conversion; it is a design only, not built or tested.
---

:::warning Design only
Telephony is not built and not tested. VoiceCore makes no SIP or PSTN claim. This page describes what a phone path would need and where it would plug in. The source is `docs/telephony_extension.md` (task S07-T04, design review).
:::

## Telephony is a design, not a shipped feature

VoiceCore has no phone support today. There is no telephony adapter in the repository, no SIP stack, no G.711 codec and no test for any of them. If you need to answer a phone call with VoiceCore, you would have to build the adapter described on this page first.

The project keeps it that way on purpose. ADR 0001 lists telephone carrier certification as a non-goal and says SIP and telephony stay a design document unless a real integration is built and tested. The point of the design is to show that a phone path fits in front of the existing system without changing it: the wire protocol, the Go gateway, the orchestrator, turn-taking and the generation runtime stay the same. Only a thin translator is new.

Everything below is a plan. None of it has been measured.

## Where a phone call would enter VoiceCore

In the design, a phone call reaches VoiceCore through Twilio and a new telephony adapter written in Go. The adapter speaks Twilio's protocol on one side and the VoiceCore wire protocol on the other.

```text
Caller on the PSTN
  -> Carrier or Twilio
       SIP INVITE, RTP G.711 mu-law 8 kHz          (terminated by Twilio)
  -> Twilio Media Streams: WebSocket, base64 mu-law 8 kHz, 20 ms messages
  -> Telephony adapter (Go, not built)
  -> VoiceCore protocol: hello, then 20 ms PCM16 16 kHz mic frames
  -> Go gateway -> Python orchestrator
Agent audio returns the same way, converted to mu-law 8 kHz media messages.
```

To the gateway, the adapter looks like any other client. It sends `hello`, mic frames and control events, and it receives agent frames and events such as `agent.cancel`.

## Why Twilio Media Streams instead of a direct SIP trunk

The design picks Twilio Media Streams because it is the cheapest real path to a phone call. Twilio terminates SIP and RTP itself and sends the call audio over a WebSocket. The adapter then only translates messages and audio formats, which is a small, testable piece of code.

A direct SIP trunk would mean owning much more:

- a SIP stack: registration, NAT traversal, re-INVITEs and session timers;
- media anchoring for the RTP streams;
- carrier certification.

That extra work is the reason for the telephony non-goal in ADR 0001. The direct-trunk call flow is still written down, so the trade-off is visible, but it was not chosen.

## SIP call flow for a direct trunk

This is the call flow a direct SIP trunk would need. It is documented for comparison; the design does not use it.

1. The carrier sends an `INVITE` with an SDP offer, usually PCMU at 8000 Hz, often PCMA, maybe Opus. VoiceCore would answer `100 Trying`, `180 Ringing`, then `200 OK` with its own SDP choosing PCMU.
2. The carrier sends `ACK`. RTP then flows both ways: 20 ms G.711 packets of 160 bytes. RTCP sender and receiver reports arrive about every 5 s.
3. Touch-tone digits arrive as RFC 4733 telephone-event RTP packets, or as SIP INFO.
4. On barge-in, VoiceCore stops sending RTP for the cancelled generation.
5. Either side hangs up with `BYE`, answered by `200 OK`. The adapter then sends `session.ended` with reason `client` upstream.

On the receive side, packet jitter would be absorbed by the RTP jitter buffer from the `experiments/rtp` experiment.

## How barge-in would work on a phone call

In the browser, barge-in ends with the client flushing its playout buffer. On a phone call there is no VoiceCore playout to flush. The carrier plays whatever audio it has received, so the generation fence must act before audio leaves the adapter.

The design applies the same fence rule as every other queue owner in VoiceCore:

- When the adapter receives `agent.cancel` for generation `g`, it raises its fence to at least `g` and drops every queued agent frame with a generation id at or below the fence.
- With Twilio, it also sends a `clear` message. `clear` flushes the audio Twilio has buffered but not yet played.
- With a direct SIP trunk, it would simply stop sending RTP for that generation.

Without the `clear` message, the caller would still hear whatever audio of the cancelled answer Twilio had already buffered, even though VoiceCore had stopped sending it.

## Twilio Media Streams adapter mapping

The planned telephony adapter maps each Twilio Media Streams message to a VoiceCore protocol message, and back. The adapter is not built; this table is the whole design of the translator. Each row is one concern of a call: starting the session, audio in each direction, barge-in, playout progress, touch tones and hanging up. The right-hand column is the work the adapter itself would do.

| Concern | Twilio side | VoiceCore side | Adapter work |
|---|---|---|---|
| Session start | `start` message with `streamSid`, `callSid` | `hello` and a dev token | mint a token server-side; map `streamSid` to `session_id` |
| Inbound audio | `media` messages, base64 μ-law 8 kHz, 20 ms | binary mic frames, PCM16 LE 16 kHz, 320 samples | μ-law decode, 8 to 16 kHz upsample, frame numbering, `capture_us` from Twilio's `timestamp` |
| Outbound audio | `media` messages to Twilio, μ-law 8 kHz | agent frames, PCM16 24 kHz, with `generation_id` | 24 to 8 kHz downsample with a low-pass filter, μ-law encode, 20 ms chunks |
| Barge-in | `clear` flushes Twilio's buffered audio | `agent.cancel` with `gen` | send `clear`, drop queued frames at or below `gen` |
| Playout progress | `mark` messages, echoed back when the audio has played | `playout.started`, `playout.stopped` | send a `mark` after the first and last chunk of a generation; turn the echoes into playout events |
| Touch tones | `dtmf` messages | none | map to `text.input` (for example "0" for an operator) or ignore |
| End | `stop` | `session.ended` | close both sides |

## Codec and sample rate conversion for phone audio

Phone audio is G.711 μ-law at 8 kHz. VoiceCore expects 16 kHz PCM16 from the caller and produces 24 kHz PCM16 for the agent. The adapter would convert in both directions.

**Inbound, caller to VoiceCore:**

1. Base64-decode each Twilio `media` payload. One 20 ms message at 8 kHz is 160 μ-law bytes.
2. Decode μ-law to linear PCM16 with the G.711 table.
3. Upsample 8 kHz to 16 kHz, giving the 320 samples of one VoiceCore mic frame.
4. Number the frames and set `capture_us` from Twilio's `timestamp`.

**Outbound, VoiceCore to caller:**

1. Downsample the 24 kHz agent audio to 8 kHz. This step needs a low-pass filter first, or frequencies above 4 kHz fold back as distortion. The design ports the `Resampler` approach from the browser SDK (`packages/web-sdk/src/capture/resample.ts`).
2. Encode to μ-law and send 20 ms chunks as `media` messages.

Upsampling from 8 kHz adds no information above 4 kHz. Turn-taking would hear telephone-band audio, which is why endpointing needs a re-run at 8 kHz.

## Playout progress from Twilio mark messages

VoiceCore's echo gate needs to know what the caller is hearing right now. In the browser, the playout reports `playout.started` and `playout.stopped`. On a phone call, the adapter would build those events from Twilio `mark` messages.

The design: after the first and the last audio chunk of a generation, the adapter sends Twilio a `mark`. Twilio echoes a mark back when the audio before it has actually played. The adapter turns the first echo into `playout.started` and the last into `playout.stopped`, and sends them upstream like a browser would.

This has a side benefit. The browser path assumes playback runs in real time from `playout.started`, and the barge-in report notes that an underrun shifts real playback away from that model. Mark echoes would give the echo gate a real playback position from the carrier instead of an assumption.

## What would change in the core for telephony

The design changes nothing in the protocol, the gateway or the generation runtime. The adapter is a client of the gateway like the browser SDK.

Two things would need new measurements, though:

- **Echo gate calibration.** Phone echo comes from the handset and the carrier network, not from laptop speakers into a laptop microphone. The echo gate thresholds were set and tested with laptop playback and a simulated room, so they need a phone calibration.
- **Endpointing at 8 kHz.** The endpoint policy was chosen with sweeps on wideband audio (ADR 0002). Telephone-band audio would need that sweep re-run before the policy is trusted on calls.

Until both are measured, any claim about barge-in or turn-taking quality on phone calls would be unsupported.

## Tests required before any telephony claim

The design lists the tests an adapter would need before VoiceCore could claim phone support. None of them exist.

1. **G.711 golden vectors:** a fixed set of encode and decode cases, in the same spirit as the wire protocol's golden vectors.
2. **Resampler tests at 8 kHz:** both the 8 to 16 kHz upsample and the 24 to 8 kHz downsample with its low-pass filter.
3. **A recorded Media Streams session replayed through the adapter:** an in-process, repeatable test through the existing harness seam (seam 9a), like the fake-time runner used for the CI gate.
4. **One real call, recorded with consent:** the only test that proves the whole path works with a carrier.

Until these exist, treat this page as an architecture exercise. It shows where telephony would plug in, not that it works.
