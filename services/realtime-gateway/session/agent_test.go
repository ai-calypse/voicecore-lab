package session

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
)

// Step 10 (ADR 0005): the widget names an agent; the gateway signs it into the token and passes it upstream.

func agentsDir(t *testing.T, ids ...string) string {
	t.Helper()
	d := t.TempDir()
	for _, id := range ids {
		if err := os.MkdirAll(filepath.Join(d, id), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(d, id, "current"), []byte("e72764ddb031\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return d
}

// postAgent asks for a token for an agent and returns the status, body and token.
func (r *rig) postAgent(agent string) (int, string, string) {
	resp, err := r.http.PostForm("http://gw:80/v1/session", url.Values{"agent": {agent}})
	if err != nil {
		r.t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var body struct{ Token string }
	_ = json.Unmarshal(b, &body)
	return resp.StatusCode, string(b), body.Token
}

func TestTokenForAgent(t *testing.T) {
	gw := New(Defaults([]byte("test-secret"), "ws://orch:80"))
	parts := strings.Split(gw.TokenFor("198.51.100.7", "acme-docs"), ".")
	if len(parts) != 4 || parts[2] != "acme-docs" {
		t.Fatalf("parts = %q", parts)
	}
}

func TestNoAgentTokenUnchanged(t *testing.T) {
	gw := New(Defaults([]byte("test-secret"), "ws://orch:80"))
	if n := len(strings.Split(gw.TokenFor("198.51.100.7", ""), ".")); n != 3 {
		t.Fatalf("parts = %d, want 3", n)
	}
}

func TestUnknownAgent404(t *testing.T) {
	dir := agentsDir(t, "acme-docs")
	runCfg(t, false, func(c *Config) { c.AgentsDir = dir }, func(t *testing.T, r *rig) {
		if code, body, _ := r.postAgent("nope"); code != 404 || body != "unknown agent\n" {
			t.Fatalf("got %d %q", code, body)
		}
	})
}

func TestBadAgentID400(t *testing.T) {
	dir := agentsDir(t, "acme-docs")
	runCfg(t, false, func(c *Config) { c.AgentsDir = dir }, func(t *testing.T, r *rig) {
		if code, body, _ := r.postAgent("../x"); code != 400 || body != "bad agent id\n" {
			t.Fatalf("got %d %q", code, body)
		}
	})
}

func TestAgentHeaderUpstream(t *testing.T) {
	dir := agentsDir(t, "acme-docs")
	runCfg(t, false, func(c *Config) { c.AgentsDir = dir }, func(t *testing.T, r *rig) {
		_, _, tok := r.postAgent("acme-docs")
		c := r.connect(map[string]any{"token": tok}, nil)
		c.next("welcome")
		if up := r.upstream(); up.Agent != "acme-docs" {
			t.Fatalf("upstream agent = %q", up.Agent)
		}
		plain := r.connect(nil, nil) // a token without an agent: no header, the orchestrator's default agent
		plain.next("welcome")
		if up := r.upstream(); up.Agent != "" {
			t.Fatalf("upstream agent = %q, want none", up.Agent)
		}
	})
}

func TestTamperedAgentToken(t *testing.T) {
	dir := agentsDir(t, "acme-docs", "other")
	runCfg(t, false, func(c *Config) { c.AgentsDir = dir }, func(t *testing.T, r *rig) {
		_, _, tok := r.postAgent("acme-docs")
		parts := strings.Split(tok, ".")
		parts[2] = "other" // someone else's agent (and budget) with this token's signature
		c := r.connect(map[string]any{"token": strings.Join(parts, ".")}, nil)
		if s := c.closeStatus(); s != statusBadToken {
			t.Fatalf("close status = %d, want %d", s, statusBadToken)
		}
	})
}

func TestWidgetJS(t *testing.T) {
	js := filepath.Join(t.TempDir(), "voicecore.js")
	if err := os.WriteFile(js, []byte("console.log('widget')\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	runCfg(t, false, func(c *Config) { c.Widget = js }, func(t *testing.T, r *rig) {
		resp, err := r.http.Get("http://gw:80/widget.js")
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		if resp.StatusCode != http.StatusOK || resp.Header.Get("Cache-Control") != "public, max-age=300" || string(b) != "console.log('widget')\n" {
			t.Fatalf("got %d %q %q", resp.StatusCode, resp.Header.Get("Cache-Control"), b)
		}
		if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/javascript") {
			t.Fatalf("content type %q", ct)
		}
	})
}

// writeOrigins publishes the console's "Websites allowed to embed" list, as the console does.
func writeOrigins(t *testing.T, dir string, origins ...string) {
	t.Helper()
	b, _ := json.Marshal(map[string]any{"origins": origins})
	if err := os.MkdirAll(filepath.Join(dir, "_site"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "_site", "origins.json"), b, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestOriginsFileReload(t *testing.T) {
	dir := agentsDir(t, "acme-docs")
	runCfg(t, false, func(c *Config) { c.AgentsDir = dir }, func(t *testing.T, r *rig) {
		post := func() int {
			req, _ := http.NewRequest("POST", "http://gw:80/v1/session", nil)
			req.Header.Set("Origin", "https://acme.com")
			resp, err := r.http.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			resp.Body.Close()
			return resp.StatusCode
		}
		if code := post(); code != 403 {
			t.Fatalf("before: %d, want 403", code)
		}
		writeOrigins(t, dir, "acme.com")
		time.Sleep(1100 * time.Millisecond) // the file is looked at again at most once a second
		if code := post(); code != 200 {
			t.Fatalf("after: %d, want 200", code)
		}
	})
}

func TestWSAcceptUsesReloadedOrigins(t *testing.T) {
	dir := agentsDir(t, "acme-docs")
	runCfg(t, false, func(c *Config) { c.AgentsDir = dir }, func(t *testing.T, r *rig) {
		dial := func() error {
			ws, _, err := websocket.Dial(context.Background(), "ws://gw:80/v1/ws",
				&websocket.DialOptions{HTTPClient: r.http, HTTPHeader: http.Header{"Origin": {"https://acme.com"}}})
			if err == nil {
				ws.CloseNow()
			}
			return err
		}
		if dial() == nil {
			t.Fatal("upgrade from an unlisted site was accepted")
		}
		writeOrigins(t, dir, "acme.com")
		time.Sleep(1100 * time.Millisecond)
		if err := dial(); err != nil {
			t.Fatalf("upgrade from a listed site refused: %v", err)
		}
	})
}

// TestConsoleBehindGateway: one host for voice and the dashboard. Every path the gateway does not serve goes to the
// console, which sees the real client and scheme, never the ones a visitor claims.
func TestConsoleBehindGateway(t *testing.T) {
	console, _ := url.Parse("http://console:80")
	runCfg(t, false, func(c *Config) { c.Console = console }, func(t *testing.T, r *rig) {
		seen := make(chan *http.Request, 1)
		srv, ln := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			seen <- req.Clone(context.Background())
			_, _ = io.WriteString(w, "console")
		})}, r.net.Listen("console:80")
		go func() { _ = srv.Serve(ln) }()
		defer srv.Close()

		req, _ := http.NewRequest("POST", "http://gw:80/api/login?next=1", strings.NewReader("{}"))
		req.Header.Set("X-Forwarded-For", "6.6.6.6") // a visitor's claim: not believed (no trusted proxies)
		req.Header.Set("X-Forwarded-Proto", "https")
		resp, err := r.http.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		b, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		got := <-seen
		if string(b) != "console" || got.URL.RequestURI() != "/api/login?next=1" || got.Host != "gw:80" {
			t.Fatalf("got %q %s host %q", b, got.URL.RequestURI(), got.Host)
		}
		if xff, proto := got.Header.Get("X-Forwarded-For"), got.Header.Get("X-Forwarded-Proto"); xff == "" || xff == "6.6.6.6" || proto != "http" {
			t.Fatalf("forwarded for %q proto %q", xff, proto)
		}
		resp, err = r.http.Get("http://gw:80/healthz") // the gateway's own paths stay its own
		if err != nil {
			t.Fatal(err)
		}
		b, _ = io.ReadAll(resp.Body)
		resp.Body.Close()
		if !strings.Contains(string(b), `"status":"ok"`) {
			t.Fatalf("healthz went elsewhere: %q", b)
		}
		r.http.CloseIdleConnections()
	})
}

func TestNoConsoleNoProxy(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		resp, err := r.http.Get("http://gw:80/")
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusNotFound {
			t.Fatalf("status %d", resp.StatusCode)
		}
	})
}
