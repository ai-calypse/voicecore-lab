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
		"gateway_tokens_issued_total 1", `gateway_rejected_total{reason="draining"} 1`, "# TYPE gateway_sessions gauge"} {
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
