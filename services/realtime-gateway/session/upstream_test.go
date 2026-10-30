package session

import (
	"testing"
	"time"

	"github.com/coder/websocket"
)

func TestUpstreamDialRetriesOnlyOnRefusedBeforeUpgrade(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		r.orchLn.RefuseNext(1)
		welcomeOf(r.connect(nil, nil)) // refused once, then the retry 300 ms later connects
		if n := r.orchLn.Dials(); n != 2 {
			t.Fatalf("dials %d, want 2", n)
		}
	})
	runCfg(t, false, func(c *Config) { c.Upstream = "ws://slow:80" }, func(t *testing.T, r *rig) {
		ln := r.net.Listen("slow:80") // accepts nothing: the dial times out
		defer ln.Close()
		start := time.Now()
		if s := r.connect(nil, nil).closeStatus(); s != websocket.StatusInternalError {
			t.Fatalf("close %d, want 1011", s)
		}
		if n, took := ln.Dials(), time.Since(start); n != 1 || took > 6*time.Second { // a retry could reserve budget twice
			t.Fatalf("dials %d after %v, want 1 within 6 s", n, took)
		}
	})
}

func TestUpstreamBreakerFailsFastAndReadyz503(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		r.orchLn.RefuseNext(1000)
		for i := 0; i < 5; i++ {
			if s := r.connect(nil, nil).closeStatus(); s != websocket.StatusInternalError {
				t.Fatalf("session %d: close %d, want 1011", i, s)
			}
		}
		dials := r.orchLn.Dials()
		if s := r.connect(nil, nil).closeStatus(); s != websocket.StatusInternalError || r.orchLn.Dials() != dials {
			t.Fatalf("breaker open: close %d, dials %d -> %d (want 1011 and no dial)", s, dials, r.orchLn.Dials())
		}
		if code, body := getJSON(t, r.http, "http://gw:80/readyz"); code != 503 || body["upstream"] != "open" {
			t.Fatalf("readyz while open: %d %v", code, body)
		}
		time.Sleep(30 * time.Second)
		r.orchLn.RefuseNext(0)
		if code, _ := getJSON(t, r.http, "http://gw:80/readyz"); code != 200 {
			t.Fatalf("readyz after 30 s: %d, want 200 (a probe may go out)", code)
		}
		welcomeOf(r.connect(nil, nil)) // the probe connects and closes the breaker
		welcomeOf(r.connect(nil, nil))
	})
}
