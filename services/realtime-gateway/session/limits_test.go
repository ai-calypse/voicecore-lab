package session

import (
	"context"
	"net/http"
	"strings"
	"testing"
	"testing/synctest"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
)

// Abuse limits from the 2026-10-30 security review.

func TestUnknownHostIsRefused(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		r.gw.cfg.Hosts = []string{"gw"}
		req, _ := http.NewRequest("POST", "http://gw:80/v1/session", nil)
		req.Host = "rebind.attacker.example"
		resp, err := r.http.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusMisdirectedRequest {
			t.Fatalf("status %d", resp.StatusCode)
		}
		if r.token() == "" {
			t.Fatal("the allowed host got no token")
		}
	})
}

func TestTokenIssuanceIsRateLimitedPerIP(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		codes := []int{}
		for range 11 {
			resp, err := r.http.Post("http://gw:80/v1/session", "application/json", nil)
			if err != nil {
				t.Fatal(err)
			}
			resp.Body.Close()
			codes = append(codes, resp.StatusCode)
		}
		if codes[9] != 200 || codes[10] != http.StatusTooManyRequests {
			t.Fatalf("codes %v", codes)
		}
		time.Sleep(6 * time.Second) // one more token per 6 s
		if r.token() == "" {
			t.Fatal("no token after waiting")
		}
	})
}

func TestSessionsAboveThePerIPCapCloseWith1013(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		r.gw.cfg.MaxSessionsPerIP = 2
		for range 2 {
			r.connect(nil, nil).next("welcome")
		}
		if s := r.connect(nil, nil).closeStatus(); s != websocket.StatusTryAgainLater {
			t.Fatalf("close %d", s)
		}
	})
}

func TestSessionEndsAtMaxAge(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		for range 15*60/5 - 1 { // keep the heartbeat alive until just before 15 minutes
			time.Sleep(5 * time.Second)
			c.send("ping", map[string]any{"t_client_us": 1})
			c.next("pong")
		}
		var reason string
		_ = c.next("session.ended").Get("reason", &reason)
		if reason != "expired" {
			t.Fatalf("reason %q", reason)
		}
	})
}

func TestTextInputMustBeAShortString(t *testing.T) {
	for name, text := range map[string]any{"content parts": []map[string]any{{"type": "image_url"}}, "too long": strings.Repeat("a", 501)} {
		t.Run(name, func(t *testing.T) {
			run(t, false, func(t *testing.T, r *rig) {
				c := r.connect(nil, nil)
				c.next("welcome")
				oc := r.upstream()
				c.send("text.input", map[string]any{"text": text})
				if s := c.closeStatus(); s != 1008 {
					t.Fatalf("close %d", s)
				}
				if got := upEvents(oc); len(got) != 0 {
					t.Fatalf("upstream got %v", got)
				}
			})
		})
	}
}

func TestMicFramesFasterThanRealTimeAreDroppedAndCounted(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		oc := r.upstream()
		for s := range uint32(150) { // 3 s of audio at once: the 2 s burst passes, the rest is dropped
			c.mic(1, s)
		}
		if got := len(seqs(oc)); got != 100 {
			t.Fatalf("forwarded %d", got)
		}
		if n := r.counters()["drops_ratelimit"]; n != 50 {
			t.Fatalf("drops_ratelimit %d", n)
		}
		_ = c.ws.Write(context.Background(), websocket.MessageBinary, (protocol.Frame{Kind: protocol.KindMic, StreamID: 1, Sequence: 150, Payload: make([]int16, 320)}).Encode())
		synctest.Wait()
	})
}
