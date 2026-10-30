package session

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http/httptest"
	"net/netip"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
)

func welcomeOf(c *client) (id, key string, resumed bool) {
	w := c.next("welcome")
	_ = w.Get("session_id", &id)
	_ = w.Get("resume_key", &key)
	_ = w.Get("resumed", &resumed)
	return
}

func TestResumeWithRightKeyResumes(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		id, key, _ := welcomeOf(c)
		if len(key) != 64 {
			t.Fatalf("resume_key %q, want 64 hex chars", key)
		}
		r.upstream()
		_ = c.ws.CloseNow()
		time.Sleep(2 * time.Second)
		id2, _, resumed := welcomeOf(r.connect(map[string]any{"session_id": id, "resume_key": key}, nil))
		if id2 != id || !resumed {
			t.Fatalf("resume with the right key: id %s resumed %v", id2, resumed)
		}
	})
}

func TestResumeWithWrongKeyStartsNewSession(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		id, _, _ := welcomeOf(c)
		r.upstream()
		_ = c.ws.CloseNow()
		time.Sleep(2 * time.Second)
		id2, _, resumed := welcomeOf(r.connect(map[string]any{"session_id": id, "resume_key": "x"}, nil))
		if id2 == id || resumed {
			t.Fatalf("a wrong key took over session %s", id)
		}
	})
}

func TestTokenIsSingleUse(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		tok := r.token()
		welcomeOf(r.connect(map[string]any{"token": tok}, nil))
		if s := r.connect(map[string]any{"token": tok}, nil).closeStatus(); s != statusBadToken {
			t.Fatalf("second use of a token: close %d, want 4001", s)
		}
	})
}

func TestSpentTokenPlusRightResumeKeyResumes(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		tok := r.token()
		c := r.connect(map[string]any{"token": tok}, nil)
		id, key, _ := welcomeOf(c)
		r.upstream()
		_ = c.ws.CloseNow()
		time.Sleep(2 * time.Second)
		id2, _, resumed := welcomeOf(r.connect(map[string]any{"token": tok, "session_id": id, "resume_key": key}, nil))
		if id2 != id || !resumed {
			t.Fatalf("reconnect with the spent token and the right key: id %s resumed %v", id2, resumed)
		}
	})
}

// A dropped network often closes nothing: the old socket still looks attached until the heartbeat (10 s) notices.
// The key proves ownership, so the resume takes the session over instead of starting a new one.
func TestResumeTakesOverAConnectionThatStillLooksAttached(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		tok := r.token()
		c := r.connect(map[string]any{"token": tok}, nil)
		id, key, _ := welcomeOf(c)
		r.upstream()
		id2, _, resumed := welcomeOf(r.connect(map[string]any{"token": tok, "session_id": id, "resume_key": key}, nil))
		if id2 != id || !resumed {
			t.Fatalf("resume while the old socket is still attached: id %s resumed %v", id2, resumed)
		}
		_ = c.ws.CloseNow()
	})
}

func TestTokenBoundToClientIP(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		alice, mallory := r.net.HTTPClientFrom("198.51.100.7:5000"), r.net.HTTPClientFrom("203.0.113.5:6000")
		tok := r.tokenVia(alice)
		if s := r.connectVia(mallory, map[string]any{"token": tok}, nil).closeStatus(); s != statusBadToken {
			t.Fatalf("token used from another IP: close %d, want 4001", s)
		}
		welcomeOf(r.connectVia(alice, map[string]any{"token": tok}, nil)) // the owner can still use it once
	})
}

func TestXFFOnlyFromTrustedProxy(t *testing.T) {
	s := New(Config{TrustedProxies: []netip.Prefix{netip.MustParsePrefix("10.0.0.0/8")}})
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("X-Forwarded-For", "1.2.3.4")
	req.RemoteAddr = "203.0.113.5:4000"
	if got := s.clientIP(req); got != "203.0.113.5" {
		t.Fatalf("untrusted peer: client %q, want 203.0.113.5", got)
	}
	req.RemoteAddr = "10.1.2.3:4000"
	req.Header.Set("X-Forwarded-For", "9.9.9.9, 1.2.3.4, 10.0.0.7") // spoofed left part, then a trusted hop
	if got := s.clientIP(req); got != "1.2.3.4" {
		t.Fatalf("trusted proxy: client %q, want 1.2.3.4 (rightmost untrusted)", got)
	}
}

func TestXFFAcrossHeaderLinesAndHopForms(t *testing.T) {
	s := New(Config{TrustedProxies: []netip.Prefix{netip.MustParsePrefix("10.0.0.0/8")}})
	req := httptest.NewRequest("GET", "/", nil)
	req.RemoteAddr = "10.1.2.3:4000"
	req.Header.Add("X-Forwarded-For", "6.6.6.6") // the client's own line
	req.Header.Add("X-Forwarded-For", "1.2.3.4") // the proxy added a second line instead of appending
	if got := s.clientIP(req); got != "1.2.3.4" {
		t.Fatalf("two XFF lines: client %q, want 1.2.3.4", got)
	}
	for hop, want := range map[string]string{
		"1.2.3.4:51000":         "1.2.3.4",
		"[2001:db8::1]:443":     "2001:db8::1",
		"::ffff:1.2.3.4":        "1.2.3.4",
		"not-an-ip":             "10.1.2.3", // garbage: fall back to the proxy, never a made-up key
		"1.2.3.4, 10.0.0.7:443": "1.2.3.4",  // a trusted hop with a port is still skipped
	} {
		req.Header.Set("X-Forwarded-For", hop)
		if got := s.clientIP(req); got != want {
			t.Errorf("hop %q: client %q, want %q", hop, got, want)
		}
	}
}

func TestRefusedHelloDoesNotSpendToken(t *testing.T) {
	runCfg(t, false, func(c *Config) { c.MaxSessions = 1 }, func(t *testing.T, r *rig) {
		first := r.connect(nil, nil)
		welcomeOf(first)
		r.upstream()
		tok := r.token()
		if s := r.connect(map[string]any{"token": tok}, nil).closeStatus(); s != websocket.StatusTryAgainLater {
			t.Fatalf("over the session cap: close %d, want 1013", s)
		}
		_ = first.ws.Close(websocket.StatusNormalClosure, "")
		time.Sleep(time.Second)
		welcomeOf(r.connect(map[string]any{"token": tok}, nil)) // "try again later" must work with the same token
	})
}

func TestSessionIDCarriesCopyID(t *testing.T) {
	runCfg(t, false, func(c *Config) { c.CopyID = "gw1" }, func(t *testing.T, r *rig) {
		id, _, _ := welcomeOf(r.connect(nil, nil))
		if !regexp.MustCompile(`^s-gw1-[0-9a-f]{16}$`).MatchString(id) {
			t.Fatalf("session id %q", id)
		}
	})
}

// syncBuf is a bytes.Buffer safe to read while server goroutines write to it.
type syncBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuf) Write(p []byte) (int, error) { s.mu.Lock(); defer s.mu.Unlock(); return s.b.Write(p) }
func (s *syncBuf) String() string              { s.mu.Lock(); defer s.mu.Unlock(); return s.b.String() }

func TestResumeKeyNeverLoggedOrTraced(t *testing.T) {
	var logs, trace syncBuf
	runCfg(t, false, func(c *Config) {
		c.Log = slog.New(slog.NewJSONHandler(&logs, nil))
		c.Trace = &trace
	}, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		_, key, _ := welcomeOf(c)
		r.upstream()
		_ = c.ws.CloseNow()
		time.Sleep(11 * time.Second) // the resume window ends the session: logs and trace are written
		if strings.Contains(logs.String(), key) || strings.Contains(trace.String(), key) {
			t.Fatal("resume_key appears in logs or trace")
		}
		if !strings.Contains(trace.String(), "session_ended") {
			t.Fatal("trace was not written; the check above proves nothing")
		}
	})
}

func TestSessionEndLogLine(t *testing.T) {
	var logs syncBuf
	runCfg(t, false, func(c *Config) { c.Log = slog.New(slog.NewJSONHandler(&logs, nil)) }, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		id, key, _ := welcomeOf(c)
		r.upstream()
		time.Sleep(1500 * time.Millisecond)
		_ = c.ws.Close(websocket.StatusNormalClosure, "")
		time.Sleep(time.Second)
		var ended map[string]any
		for _, l := range strings.Split(strings.TrimSpace(logs.String()), "\n") {
			var m map[string]any
			if json.Unmarshal([]byte(l), &m) == nil && m["msg"] == "session ended" {
				ended = m
			}
		}
		if ended["session_id"] != id || ended["reason"] != "client" || ended["duration_ms"] != float64(1500) {
			t.Fatalf("session ended line %v (logs %s)", ended, logs.String())
		}
		if strings.Contains(logs.String(), key) {
			t.Fatal("resume_key in logs")
		}
	})
}
