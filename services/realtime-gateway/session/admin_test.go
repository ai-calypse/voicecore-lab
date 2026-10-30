package session

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
	"time"
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
		`gateway_breaker_state{provider="upstream",target="ws://x"} 0`} {
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

func TestCORSEchoesOnlyAllowedOrigin(t *testing.T) {
	cfg := Defaults([]byte("k"), "ws://x")
	cfg.Origins = []string{"localhost:*", "127.0.0.1:*"} // the gateway's -origins default
	s := New(cfg)
	h := s.Handler()
	post := func(origin string) *httptest.ResponseRecorder {
		req := httptest.NewRequest("POST", "/v1/session", nil)
		req.Host = "localhost"
		if origin != "" {
			req.Header.Set("Origin", origin)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, req)
		return w
	}
	if w := post("http://localhost:5173"); w.Code != 200 || w.Header().Get("Access-Control-Allow-Origin") != "http://localhost:5173" ||
		w.Header().Get("Vary") != "Origin" {
		t.Fatalf("allowed origin: %d %q", w.Code, w.Header())
	}
	if w := post("https://evil.example"); w.Code != 403 || w.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatalf("foreign origin: %d %q", w.Code, w.Header())
	}
	if w := post(""); w.Code != 200 || w.Header().Get("Access-Control-Allow-Origin") != "" { // curl, the harness
		t.Fatalf("no origin: %d %q", w.Code, w.Header())
	}
	if s.Snapshot()["rejected_origin"] != 1 {
		t.Fatalf("rejected_origin %d", s.Snapshot()["rejected_origin"])
	}
}

func TestValidateProd(t *testing.T) {
	bad := Defaults([]byte("short"), "ws://x")
	bad.Origins, bad.Hosts = []string{"localhost:*", "voicecore.example"}, []string{"127.0.0.1"}
	err := bad.ValidateProd()
	for _, want := range []string{"GATEWAY_SECRET", "TURNSTILE_SECRET", "-origins", "-hosts", "-trusted-proxies"} {
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("ValidateProd() = %v, want it to name %s", err, want)
		}
	}
	good := Defaults([]byte(strings.Repeat("k", 32)), "ws://x")
	good.TurnstileSecret, good.Origins, good.Hosts = "ts", []string{"voicecore.example"}, []string{"voicecore.example"}
	good.TrustedProxies = []netip.Prefix{netip.MustParsePrefix("172.16.0.0/12")}
	if err := good.ValidateProd(); err != nil {
		t.Fatalf("a complete prod config: %v", err)
	}
	good.Origins = []string{"*"} // any site could mint tokens from its visitors' browsers
	if err := good.ValidateProd(); err == nil || !strings.Contains(err.Error(), "-origins") {
		t.Fatalf("-origins * passed: %v", err)
	}
}

func TestDebugCountersNotOnPublicMux(t *testing.T) {
	s := New(Defaults([]byte("k"), "ws://x"))
	if code, _ := get(t, s.Handler(), "GET", "/debug/counters"); code != 404 {
		t.Fatalf("public /debug/counters: %d, want 404 (admin listener only)", code)
	}
	if code, _ := get(t, s.AdminHandler(), "GET", "/debug/counters"); code != 200 {
		t.Fatalf("admin /debug/counters: %d", code)
	}
}

func TestTokenOriginCheckMatchesTheWebSocketRules(t *testing.T) {
	cfg := Defaults([]byte("k"), "ws://x")
	cfg.Origins, cfg.Hosts = []string{"https://voicecore.example"}, nil // a pattern with a scheme, like coder/websocket allows
	h := New(cfg).Handler()
	post := func(host, origin string) int {
		req := httptest.NewRequest("POST", "/v1/session", nil)
		req.Host, req.Header["Origin"] = host, []string{origin}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, req)
		return w.Code
	}
	if c := post("gw.example", "https://voicecore.example"); c != 200 {
		t.Errorf("scheme pattern: %d, want 200", c)
	}
	if c := post("gw.example", "http://voicecore.example"); c != 403 {
		t.Errorf("wrong scheme: %d, want 403", c)
	}
	if c := post("docs.example", "https://docs.example"); c != 200 {
		t.Errorf("same origin as the gateway: %d, want 200", c)
	}
}

func TestValidateProdRejectsBroadAndLocalPatterns(t *testing.T) {
	for _, origins := range [][]string{{"*.*"}, {"**"}, {"?*"}, {"http://localhost:*"}, {"voicecore.example", " localhost:*"}, {"0.0.0.0:*"}} {
		c := Defaults([]byte(strings.Repeat("k", 32)), "ws://x")
		c.TurnstileSecret, c.Hosts, c.Origins = "ts", []string{"voicecore.example"}, origins
		c.TrustedProxies = []netip.Prefix{netip.MustParsePrefix("172.16.0.0/12")}
		if err := c.ValidateProd(); err == nil || !strings.Contains(err.Error(), "-origins") {
			t.Errorf("-origins %q passed: %v", origins, err)
		}
	}
}

func TestPerIPDailyQuota(t *testing.T) {
	runCfg(t, false, func(c *Config) { c.TokensPerMinute, c.SessionsPerIPPerDay = 0, 20 }, func(t *testing.T, r *rig) {
		post := func() int {
			resp, err := r.http.Post("http://gw:80/v1/session", "application/json", nil)
			if err != nil {
				t.Fatal(err)
			}
			resp.Body.Close()
			return resp.StatusCode
		}
		for i := 0; i < 20; i++ {
			if c := post(); c != 200 {
				t.Fatalf("token %d: %d", i+1, c)
			}
		}
		if c := post(); c != 429 {
			t.Fatalf("21st token today: %d, want 429", c)
		}
		time.Sleep(24 * time.Hour) // a new UTC day
		if c := post(); c != 200 {
			t.Fatalf("next day: %d, want 200", c)
		}
		if n := r.counters()["rejected_quota"]; n != 1 {
			t.Fatalf("rejected_quota %d, want 1", n)
		}
	})
}
