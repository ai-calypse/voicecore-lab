---
title: WebSocket vs WebRTC
description: What the RTP media lab and the Pion WebRTC spike measured, how the jitter buffer and RFC 3550 jitter work, and why the product path stays on WebSocket.
---

## What the media lab is for

VoiceCore's product path sends audio over one WebSocket per hop. The media lab in `experiments/` shows what that choice gives up and what the alternative would cost. It has two parts, and the product path uses neither:

- **The RTP lab**, `experiments/rtp`, is a Go package with a fixed-delay jitter buffer and the RFC 3550 interarrival jitter estimate. Its unit tests pin the packet arithmetic.
- **The WebRTC spike**, `experiments/cmd/pion-peer`, is a Go peer built on Pion that receives the browser microphone as Opus over RTP, logs each negotiation step, and runs every packet through the jitter buffer. It also accepts the SDK's WebSocket mic stream, so one process can time both transports on one clock.

The lab answers two questions. What does a jitter buffer have to do when packets can arrive late, out of order, twice or never? And does WebRTC beat the WebSocket path on a local machine?

## Why the WebSocket path has no jitter buffer

A WebSocket runs over one TCP connection, so frames arrive in order or not at all. A lost segment is retransmitted and everything behind it waits, which is head-of-line blocking. Frames cannot be reordered, so the gateway only counts duplicates, stale frames and gaps across reconnects, and the browser playout counts underruns by time rather than by sequence.

The transport benchmark shows what network jitter turns into on TCP. A user-space proxy added delay and jitter to each direction of one stream. The proxy rows are simulated; the first row is the plain gateway (fake-provider, loopback, n = 500 frames each):

| Proxy delay each way | RTT p50 | Interarrival p50 / p95 |
|---|---:|---|
| none | 0.43 ms | 19.96 / 21.49 ms |
| 50 ± 20 ms | 104.71 ms | 18.28 / 55.51 ms |
| 150 ± 50 ms | 326.44 ms | 0.04 / 86.15 ms |

At 150 ± 50 ms the median gap between frames collapses to 0.04 ms. A delayed chunk holds back everything behind it, so frames arrive in clumps. On TCP, jitter becomes bursts and stalls, not reordering. ADR 0001 therefore moved the reorder and sequence-wrap buffer out of the WebSocket path and into the RTP lab, where packets really do reorder.

## How the RTP jitter buffer plays packets

`rtp.Buffer` is a fixed-delay jitter buffer. It plays packet n at the first packet's arrival time, plus a fixed delay, plus 20 ms times n, counting n from the first packet. Every packet is judged against its own play time:

- a packet that arrives before its play time waits, so packets reordered inside the window come out in order;
- a packet that arrives after its play time, or after the buffer has moved past it, is counted late and dropped;
- a second copy of a waiting packet is counted as a duplicate;
- a play time with no packet is counted lost, which is where packet-loss concealment would go.

`Pop(now)` returns every packet whose play time has come, in sequence order. It counts losses only up to the highest sequence seen, so the end of a stream is not mistaken for loss. A test pins the behaviour with a 40 ms delay: packets 10, 12 and 11 come out as 10, 11, 12, and packet 13, arriving 5 ms after its play time, is counted late while its slot is counted lost. The Pion spike uses a 60 ms delay.

## How sequence numbers are unwrapped across 65535

RTP sequence numbers are 16 bits, so they wrap from 65535 to 0 every 65,536 packets, about 22 minutes at 20 ms per packet. Without care, packet 0 after 65535 looks like a packet from the distant past.

`rtp.Buffer` extends every sequence number to 64 bits, in the style of RFC 3550 appendix A.1. It takes the highest extended sequence seen so far and puts the new 16-bit value in its low bits. If the result is more than 32,768 away from the highest seen, it moves the result one wrap up or down, whichever lands closest.

The test `TestSequence65535Then0IsInOrder` sends 65534, 0, 65535 and 1, with 0 arriving before 65535. The buffer plays 65534, 65535, 0, 1, with nothing late or lost. The gateway's 32-bit mic sequence numbers have no such logic, because at 20 ms per frame they would wrap only after 2.7 years.

## How RFC 3550 interarrival jitter is computed

`rtp.Jitter` implements the interarrival jitter estimate defined in RFC 3550 section 6.4.1. For each packet, transit is the arrival time minus the RTP timestamp, both in the stream's clock units. D is the change in transit from the previous packet, and the estimate moves one sixteenth of the way towards the absolute value of D:

```text
J = J + (|D| - J) / 16
```

The unit test works an example by hand. Four 20 ms packets of 8 kHz audio have RTP timestamps 0, 160, 320 and 480, and arrive at 1000, 1170, 1310 and 1500. Transit is 1000, 1010, 990 and 1020, so |D| is 10, 20 and 30, and J becomes 0.625, then 1.8359375, then 3.59619140625. The test checks that value exactly.

Differences are taken modulo 2^32, so a timestamp wrapping past 0xFFFFFFFF does not look like a jump of four billion; a second test checks that a wrapped stream gives the same J. The lab computes this estimate but does not send or parse RTCP packets. The Pion peer converts J to milliseconds by dividing by the codec's clock rate.

## The Pion WebRTC spike

`experiments/cmd/pion-peer` is a Go program on Pion WebRTC v4 that listens on `127.0.0.1:8090`. Its page captures the microphone with `getUserMedia`, adds the track to an `RTCPeerConnection`, waits for ICE gathering to complete, and posts the offer to `/offer`. The peer applies it, creates an answer, waits for its own gathering to finish, and returns the answer. That is one signalling round trip with no trickle ICE, and no STUN or TURN server, because the spike runs on loopback only.

When the track arrives, the peer reads every RTP packet. It records the arrival, updates the RFC 3550 jitter, and pushes the packet through a jitter buffer with a 60 ms delay. `GET /stats` returns the negotiation steps, packet counts, jitter, interarrival percentiles, and the buffer's played, late, lost and duplicate counts.

`GET /ws` accepts the SDK's `hello` and mic frames in the same protocol the gateway speaks, and times them the same way. It uses each frame's capture time, in 16 kHz units, as its RTP timestamp.

## Negotiation steps the spike records

The peer logs each ICE, DTLS and connection state change with a timestamp. The Playwright test `apps/demo/e2e/webrtc.spec.ts` opens the spike page in Chromium, waits for more than 100 packets, and checks that the steps include `offer applied`, `answer sent`, `ice connected`, `dtls connected` and `connection connected`. It also checks that the codec is `audio/opus`, that more than 50 packets were played out of the jitter buffer, and that the median interarrival is between 15 and 25 ms.

In the recorded benchmark run the steps came in this order: offer applied, ICE checking, connection connecting, answer sent, ICE connected, DTLS connecting, DTLS connected, connection connected, and then the Opus track. ICE checking begins before the answer is sent, and DTLS starts only once ICE has connected. A new offer replaces and closes the previous call. Because the spike runs on loopback without STUN or TURN, NAT traversal is not exercised.

## WebSocket and WebRTC measured on loopback

The comparison sends Chromium's fake microphone to one Pion process over both transports and timestamps every arrival on one clock (measured, local loopback, 2026-10-30, raw data in `benchmarks/raw/webrtc_vs_ws_20261030T024016Z.json`). Run it with `BENCH=1 pnpm --filter @voicecore/demo exec playwright test e2e/webrtc.spec.ts -g compare`.

| Transport | Payload | Packets | Interarrival p50 / p95 / p99 / max | RFC 3550 jitter | Late / lost |
|---|---|---:|---|---:|---:|
| WebRTC | Opus, Chrome's RTP sender | 1,002 | 20.06 / 20.41 / 20.61 / 21.2 ms | 0.26 ms | 0 / 0 |
| WebSocket (VoiceCore SDK) | PCM16 16 kHz, 28-byte header | 500 | 19.86 / 29.53 / 30.10 / 30.2 ms | 4.84 ms | 0 / 0 |

On loopback neither transport lost a packet or delivered one too late for the 60 ms buffer. Both medians sit at 20 ms. The difference is in the tail: the SDK's frames have a p95 interarrival of 29.53 ms, and 4.84 ms of jitter against 0.26 ms for WebRTC. The WebRTC call stays open while the WebSocket run happens, which is why it collected about twice as many packets.

## Why the SDK frames leave in bursts

The jitter in the WebSocket row comes from the browser, not the network. WebRTC paces packets from Chrome's media thread. The SDK's capture AudioWorklet instead posts 128-sample blocks to the main thread, where 20 ms frames are cut and sent. Frames therefore leave in small bursts, and every few frames one waits for the next block. That gives the 29.53 ms p95 interarrival (measured, loopback, n = 500 frames).

The WebSocket timestamps come from the SDK's capture clock, derived from the sample count. So the RFC 3550 jitter of that stream measures send-time jitter, not network jitter.

A possible fix has not been done: cut and send frames inside the worklet, or send on a 20 ms timer. Either would move framing off the main thread's schedule. The [browser SDK](browser-sdk.md) page describes the capture path as it is today.

## Confounds in the WebSocket and WebRTC comparison

The comparison is not a controlled transport test, and these confounds are recorded with it:

- **The codecs differ.** WebRTC sends Opus in 20 ms frames; the SDK sends raw PCM16.
- **Audio processing.** Chrome applies its echo cancellation, noise suppression and automatic gain control to both paths, but only the WebRTC path can adapt its bitrate.
- **Different timestamps.** The WebSocket timestamp is the SDK's capture clock from the sample count, so its jitter reflects send-time jitter. The WebRTC timestamp is the RTP sender's.
- **Different durations.** The WebRTC call runs through both 10 s windows, so it has 1,002 packets against 500.
- **Not run: shaped networks.** The same comparison under dummynet delay and loss needs `sudo`, which was not available. That is where UDP's late and lost packets and TCP's head-of-line stalls would separate, and it is the open item of this step.

So the result says only this: on a quiet loopback both transports deliver everything, and the SDK's send pacing is the bigger source of jitter.

## Why the product path uses WebSocket

VoiceCore keeps WebSocket for the product path, for reasons the repository records:

- **One protocol for both hops.** The same binary frames and JSON events run browser to gateway and gateway to orchestrator, with golden vectors in three languages. The gateway forwards them without translating.
- **TCP removes a class of work.** Frames cannot reorder, so the gateway needs bounded queues and counters rather than a jitter buffer, and the playout counts underruns by time.
- **The cost is small where it was measured.** The gateway adds 0.19 ms median for both passes (fake-provider, loopback, n = 500 frames), and on loopback the WebSocket path lost nothing.
- **WebRTC brings infrastructure.** The Pion spike shows the server side is small, but real networks need ICE and TURN servers.

The trade-off is lossy networks. WebRTC's jitter buffer, NACK and FEC exist for exactly the loss that TCP turns into stalls. `docs/media_internals.md` lists what a production media path would change: Opus over the WebSocket, about 10 times less bandwidth than PCM16, once transport becomes the bottleneck; playback position events for the echo reference; WebRTC for lossy networks; and telephony through an adapter. See [telephony](../guides/telephony.md).
