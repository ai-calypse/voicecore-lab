package session

import (
	"encoding/json"
	"net/http"
	"testing"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/internal/memnet"
	"github.com/coder/websocket"
)

func getJSON(t *testing.T, c *http.Client, url string) (int, map[string]any) {
	t.Helper()
	resp, err := c.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var body map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&body)
	return resp.StatusCode, body
}

func TestHealthzAndReadyz(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		if code, body := getJSON(t, r.http, "http://gw:80/healthz"); code != 200 || body["status"] != "ok" || body["version"] != "dev" {
			t.Fatalf("healthz %d %v", code, body)
		}
		if code, body := getJSON(t, r.http, "http://gw:80/readyz"); code != 200 || body["ready"] != true {
			t.Fatalf("readyz %d %v", code, body)
		}
		r.gw.BeginDrain()
		if code, body := getJSON(t, r.http, "http://gw:80/readyz"); code != 503 || body["draining"] != true {
			t.Fatalf("readyz while draining %d %v", code, body)
		}
	})
}

func TestPostSessionWhileDrainingIs503(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		r.gw.BeginDrain()
		resp, err := r.http.Post("http://gw:80/v1/session", "", nil)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != 503 {
			t.Fatalf("POST /v1/session while draining = %d, want 503", resp.StatusCode)
		}
	})
}

func TestHelloDuringDrainClosesWith1013(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		tok := r.token() // minted before the drain
		r.gw.BeginDrain()
		c := r.connect(map[string]any{"token": tok}, nil)
		if s := c.closeStatus(); s != websocket.StatusTryAgainLater {
			t.Fatalf("close %d, want 1013", s)
		}
	})
}

func TestDrainEndsSessionsWithShutdownAfterTimeout(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		done := make(chan struct{})
		go func() { r.gw.Drain(25 * time.Second); close(done) }()
		// Pings every 4 s keep the heartbeat alive and never coincide with the 25 s drain end (next() skips other events).
		for i := 0; ; i++ {
			select {
			case <-done:
			case <-time.After(4 * time.Second):
				c.send("ping", map[string]any{"t_client_us": 1})
				c.next("pong")
				if i == 4 { // 20 s into a 25 s drain
					if n := r.counters()["sessions"]; n != 1 {
						t.Fatalf("sessions during drain = %d, want 1", n)
					}
				}
				continue
			}
			break
		}
		var reason string
		_ = c.next("session.ended").Get("reason", &reason)
		if reason != "shutdown" {
			t.Fatalf("reason %q, want shutdown", reason)
		}
		if n := r.counters()["sessions"]; n != 0 {
			t.Fatalf("sessions after drain = %d, want 0", n)
		}
	})
}

func TestProbeExitCodes(t *testing.T) {
	n := memnet.New()
	l := n.Listen("svc:1")
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/down" {
			w.WriteHeader(503)
		}
	})}
	go func() { _ = srv.Serve(l) }()
	defer srv.Close()
	c := n.HTTPClient()
	for url, want := range map[string]int{"http://svc:1/healthz": 0, "http://svc:1/down": 1, "http://nobody:1/healthz": 1} {
		if got := ProbeWith(c, url); got != want {
			t.Fatalf("ProbeWith(%s) = %d, want %d", url, got, want)
		}
	}
}
