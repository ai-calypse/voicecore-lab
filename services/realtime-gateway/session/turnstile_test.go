package session

import (
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"strings"
	"testing"
	"time"
)

// fakeSiteverify answers like Cloudflare's siteverify: mode "pass", "fail" or "slow" (3 s, past our 2 s limit).
func fakeSiteverify(r *rig, mode *string) (stop func()) {
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		_ = req.ParseForm()
		if req.PostForm.Get("secret") != "test-turnstile-secret" || req.PostForm.Get("response") == "" {
			w.WriteHeader(400)
			return
		}
		if *mode == "slow" {
			time.Sleep(3 * time.Second)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": *mode == "pass"})
	})}
	ln := r.net.Listen("cf:80")
	go func() { _ = srv.Serve(ln) }()
	return func() { _ = srv.Close() } // inside the bubble: synctest fails on goroutines left behind
}

func postSession(r *rig, body string) (int, string) {
	resp, err := r.http.Post("http://gw:80/v1/session", "application/x-www-form-urlencoded", strings.NewReader(body))
	if err != nil {
		r.t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(b)
}

func TestTurnstile(t *testing.T) {
	runCfg(t, false, func(c *Config) {
		c.TurnstileSecret, c.TurnstileURL = "test-turnstile-secret", "http://cf:80/siteverify"
	}, func(t *testing.T, r *rig) {
		mode := "pass"
		defer fakeSiteverify(r, &mode)()
		form := url.Values{"cf-turnstile-response": {"widget-token"}}.Encode()
		if code, _ := postSession(r, ""); code != 403 {
			t.Fatalf("no Turnstile field: %d, want 403", code)
		}
		mode = "fail"
		if code, _ := postSession(r, form); code != 403 {
			t.Fatalf("siteverify said no: %d, want 403", code)
		}
		mode = "pass"
		if code, body := postSession(r, form); code != 200 || !strings.Contains(body, `"token"`) {
			t.Fatalf("siteverify said yes: %d %s", code, body)
		}
		mode = "slow"
		if code, _ := postSession(r, form); code != 503 {
			t.Fatalf("siteverify slower than 2 s: %d, want 503", code)
		}
		time.Sleep(2 * time.Second) // let the slow fake finish before the bubble ends
		if code, _ := postSession(r, "cf-turnstile-response="+strings.Repeat("a", 5000)); code != 413 {
			t.Fatalf("body over 4 KiB: %d, want 413", code)
		}
		time.Sleep(time.Second) // net/http lingers 500 ms after refusing a body
		if c := r.counters(); c["rejected_turnstile"] != 2 {
			t.Fatalf("rejected_turnstile %d, want 2", c["rejected_turnstile"])
		}
	})
}

func TestResumeNeedsNoTurnstile(t *testing.T) { // a resume proves itself with resume_key, not a new challenge
	runCfg(t, false, func(c *Config) {
		c.TurnstileSecret, c.TurnstileURL = "test-turnstile-secret", "http://cf:80/siteverify"
	}, func(t *testing.T, r *rig) {
		mode := "pass"
		defer fakeSiteverify(r, &mode)()
		_, body := postSession(r, url.Values{"cf-turnstile-response": {"w"}}.Encode())
		var tok struct{ Token string }
		_ = json.Unmarshal([]byte(body), &tok)
		c := r.connect(map[string]any{"token": tok.Token}, nil)
		id, key, _ := welcomeOf(c)
		r.upstream()
		_ = c.ws.CloseNow()
		time.Sleep(2 * time.Second)
		mode = "fail" // Cloudflare would now say no: the resume must not ask
		if id2, _, resumed := welcomeOf(r.connect(map[string]any{"token": tok.Token, "session_id": id, "resume_key": key}, nil)); id2 != id || !resumed {
			t.Fatalf("resume: %s %v", id2, resumed)
		}
	})
}

func TestTurnstileTokenInMultipartForm(t *testing.T) { // fetch(url, {method: "POST", body: new FormData()}) sends multipart
	runCfg(t, false, func(c *Config) {
		c.TurnstileSecret, c.TurnstileURL = "test-turnstile-secret", "http://cf:80/siteverify"
	}, func(t *testing.T, r *rig) {
		mode := "pass"
		defer fakeSiteverify(r, &mode)()
		var body strings.Builder
		mw := multipart.NewWriter(&body)
		_ = mw.WriteField("cf-turnstile-response", "widget-token")
		_ = mw.Close()
		resp, err := r.http.Post("http://gw:80/v1/session", mw.FormDataContentType(), strings.NewReader(body.String()))
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != 200 {
			t.Fatalf("multipart: %d, want 200", resp.StatusCode)
		}
	})
}

func TestFailedHumanChecksDoNotSpendTheDailyQuota(t *testing.T) {
	runCfg(t, false, func(c *Config) {
		c.TurnstileSecret, c.TurnstileURL, c.SessionsPerIPPerDay, c.TokensPerMinute = "test-turnstile-secret", "http://cf:80/siteverify", 1, 0
	}, func(t *testing.T, r *rig) {
		mode := "fail"
		defer fakeSiteverify(r, &mode)()
		form := url.Values{"cf-turnstile-response": {"w"}}.Encode()
		for i := 0; i < 3; i++ {
			if code, _ := postSession(r, form); code != 403 {
				t.Fatalf("failed check %d: %d", i, code)
			}
		}
		mode = "pass"
		if code, _ := postSession(r, form); code != 200 {
			t.Fatalf("first passed check of the day: %d, want 200 (the quota is 1)", code)
		}
	})
}
