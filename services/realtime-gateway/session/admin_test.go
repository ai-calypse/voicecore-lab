package session

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func get(t *testing.T, h http.Handler, method, path string) (int, string) {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	req.Host = "localhost"
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	b, _ := io.ReadAll(w.Result().Body)
	return w.Code, string(b)
}

func TestAdminHandlerServesMetricsAndCounters(t *testing.T) {
	s := New(Defaults([]byte("k"), "ws://x"))
	pub, admin := s.Handler(), s.AdminHandler()
	if code, _ := get(t, pub, "POST", "/v1/session"); code != 200 {
		t.Fatalf("token: %d", code)
	}
	s.BeginDrain()
	if code, _ := get(t, pub, "POST", "/v1/session"); code != 503 {
		t.Fatalf("token while draining: %d", code)
	}
	code, body := get(t, admin, "GET", "/metrics")
	for _, want := range []string{"# TYPE gateway_drops_total counter", `gateway_drops_total{reason="fenced"} 0`,
		"gateway_tokens_issued_total 1", `gateway_rejected_total{reason="draining"} 1`, "# TYPE gateway_sessions gauge",
		`gateway_breaker_state{provider="upstream"} 0`} {
		if code != 200 || !strings.Contains(body, want) {
			t.Errorf("/metrics %d lacks %q", code, want)
		}
	}
	_, body = get(t, admin, "GET", "/debug/counters")
	var c map[string]int64
	if json.Unmarshal([]byte(body), &c) != nil || c["tokens_issued"] != 1 || c["rejected_draining"] != 1 {
		t.Fatalf("/debug/counters %s", body)
	}
}

func TestTwoServersDoNotCollide(t *testing.T) { // each Server has its own registry, never the global one
	a, b := New(Defaults([]byte("k"), "ws://x")), New(Defaults([]byte("k"), "ws://x"))
	for _, s := range []*Server{a, b} {
		if code, _ := get(t, s.AdminHandler(), "GET", "/metrics"); code != 200 {
			t.Fatalf("metrics %d", code)
		}
	}
}

func TestHelloRefusalsAreCounted(t *testing.T) {
	runCfg(t, false, func(c *Config) { c.MaxSessions = 1 }, func(t *testing.T, r *rig) {
		welcomeOf(r.connect(nil, nil))
		r.upstream()
		_ = r.connect(nil, nil).closeStatus()                              // busy: 1013
		_ = r.connect(map[string]any{"token": "1.2.3"}, nil).closeStatus() // bad token: 4001
		tok := r.token()
		r.gw.BeginDrain()
		_ = r.connect(map[string]any{"token": tok}, nil).closeStatus() // draining: 1013
		c := r.counters()
		if c["rejected_busy"] != 1 || c["rejected_token"] != 1 || c["rejected_draining"] != 1 {
			t.Fatalf("counters %v", c)
		}
	})
}
