---
title: Embed the voice widget
sidebar_label: Embed the widget
description: Add the VoiceCore voice widget to a page with one script tag, and see how it gets a session, uses the microphone, opens cited sections and stays isolated from your styles.
---

## Add the widget with one script tag

The widget is one classic script, `voicecore.js`. Add it to any page:

```html
<script src="https://docs.example.com/embed/voicecore.js"
        data-endpoint="https://gateway.example.com"
        data-title="Ask the docs"></script>
```

Build the script with `pnpm --filter @voicecore/demo build:widget`. It lands in `apps/demo/public/embed/voicecore.js`. This docs site copies it to `static/embed/` when it starts or builds.

The script mounts as soon as the page has a body, or on `DOMContentLoaded` if it loads in the head. It adds a launcher button in the bottom-right corner. Opening the launcher connects to the gateway; nothing connects on page load. The widget reads its attributes from its own script tag, so keep the `data-` attributes on that tag and load it as a classic script, not as a module.

## Widget attributes

The script tag takes two attributes:

| Attribute | What it sets | Default |
|---|---|---|
| `data-endpoint` | the gateway's base URL; a trailing slash is removed | the page's own origin |
| `data-title` | the label on the launcher button | "Ask the docs" |
| `data-name` | the assistant's name, shown at the top of the open panel and used as the dialog's accessible name | "Docs assistant" |

The widget derives both gateway addresses from `data-endpoint`:

- the token request goes to `<endpoint>/v1/session`;
- the WebSocket opens at the same URL with `http` replaced by `ws`, plus `/v1/ws`. An `https` endpoint therefore gives a `wss` WebSocket.

Leave `data-endpoint` out only when the gateway serves the same origin as the page. This docs site sets it from `VOICECORE_GATEWAY`, default `http://localhost:8080`. The demo app sets it from `VITE_GATEWAY`, with the same default.

## How the widget gets a session token

The widget never holds a provider key. It starts a session in four steps:

1. **Token.** When you open the panel, it sends `POST /v1/session` to the gateway. The reply is `{"token": "..."}`: an expiry time signed with HMAC-SHA256, valid for 60 s.
2. **Hello.** It opens the WebSocket and sends `hello` with the token, protocol version 1, 16 kHz mic audio in 20 ms frames, and 24 kHz playout. The gateway closes the socket if `hello` does not arrive within 5 s.
3. **Welcome.** The gateway checks the token and the audio format, dials the orchestrator, and replies `welcome` with the session ID and a 10 s resume window.
4. **Heartbeat.** The client sends `ping` every 2 s. The gateway closes the session after 10 s without any message.

The gateway issues at most 10 tokens per minute per client IP; beyond that the token request fails with HTTP 429. Closing the panel ends the session, and so does leaving the page.

## Microphone permission and the text fallback

The widget asks for the microphone only when you tap the mic button, never when the page loads. It requests mono audio with the browser's echo cancellation, noise suppression and automatic gain control turned on.

If the browser refuses, the widget switches to text:

- the mic button is disabled and labelled "Microphone blocked";
- the status line says "Microphone access was blocked. You can still type your question below.";
- focus moves to the text field.

Typed questions get the same answers and citations as spoken ones, with a limit of 500 characters. Tapping the mic button again while it is on stops the microphone and sends `mic.revoked`. The session stays open for text, and a half-spoken turn is dropped. The mic button stays disabled after a refusal until the page reloads.

## Open cited sections with the navigation event

When an answer cites a docs section, the widget dispatches a `voicecore:navigate` event on `window`. It is a `CustomEvent` whose `detail` is `{ url, title }`: the cited section's URL and heading.

A host page that wants to show the section itself handles the event, calls `event.preventDefault()`, and navigates:

```js
window.addEventListener("voicecore:navigate", (event) => {
  event.preventDefault();               // the page navigates, not the widget
  const { url, title } = event.detail;  // the cited section and its heading
  router.push(url);                     // your client-side router: no reload, so the voice session keeps running
});
```

This docs site handles it in `src/theme/Root.jsx`. It changes the route without a page reload, so the voice session keeps running. It then scrolls to the cited heading and highlights that section.

On a page that does not handle the event, nothing else changes. The citation links in the answer open in a new tab.

## Keep the widget isolated from page styles

The widget renders inside a Shadow DOM. It appends one host element, a `div` with a `data-voicecore` attribute, to the end of `body`, and attaches an open shadow root to it. The widget's stylesheet is placed inside that shadow root.

Two things follow from this:

- **Your page's CSS cannot reach the widget.** Selectors in the host page do not match elements inside the shadow root, so a global `button` or `input` rule does not restyle the launcher or the text field.
- **The widget's CSS cannot leak out.** Its rules apply only inside its own shadow root.

The panel is a labelled dialog. The launcher reports whether the panel is open with `aria-expanded`, and the status line is a polite live region, so screen readers announce "Listening", "Thinking" and "Speaking" as the state changes.

## Allow the origin of your site on the gateway

The gateway accepts a browser WebSocket only from allowed origins. Its `-origins` flag takes a comma-separated list of host patterns, default `localhost:*,127.0.0.1:*`. A page served from the gateway's own host is always allowed. Any other origin is refused with HTTP 403 when the WebSocket upgrade is attempted.

A second check guards against DNS rebinding. The `-hosts` flag lists the `Host` header names the gateway answers to, default `localhost,127.0.0.1,::1`. A request for any other host name gets HTTP 421. An empty value allows any host.

For a site at `docs.example.com` talking to a gateway at `gateway.example.com`:

```bash
cd services/realtime-gateway
go run ./cmd/gateway -addr 0.0.0.0:8080 -origins "docs.example.com" -hosts "gateway.example.com"
```

The token endpoint answers any origin, so a wrong `-origins` value shows up only when the WebSocket fails to open.
