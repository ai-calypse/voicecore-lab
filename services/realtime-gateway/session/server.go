// Package session owns the client connection: token, hello, heartbeat, resume window,
// bounded queues with drop/gap counters, and the outbound generation fence (SPEC.md section 4).
package session

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/netip"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
)

type Config struct {
	Secret       []byte
	Upstream     string       // orchestrator base URL(s), comma separated, e.g. ws://orch-1:8765,ws://orch-2:8765
	HTTPClient   *http.Client // dials the orchestrator; nil means http.DefaultClient
	Origins      []string     // allowed browser origins for the WebSocket (coder/websocket patterns)
	TokenTTL     time.Duration
	HelloTimeout time.Duration
	Heartbeat    time.Duration
	ResumeWindow time.Duration
	QueueCap     int // mic frames buffered towards the orchestrator (50 = 1 s)
	OutCap       int // agent frames buffered towards the client (1500 = 30 s)
	Log          *slog.Logger
	Trace        io.Writer // SPEC.md section 5 JSON lines; nil = off
	Version      string    // reported by /healthz
	CopyID       string    // this gateway copy's id, inside every session id (multi-copy routing); default "gw"

	TrustedProxies []netip.Prefix // X-Forwarded-For is believed only from these peers

	// Turnstile (Cloudflare's bot check) on new session tokens. Empty secret = off. Resumes are never challenged.
	TurnstileSecret string
	TurnstileURL    string // siteverify endpoint; Defaults sets Cloudflare's, tests point it at a fake
	HumanCheckOff   bool   // -human-check off: a public install without Turnstile, on purpose (the spend caps still bound it)

	// Abuse limits (security review 2026-10-30). Zero means no limit.
	Hosts            []string      // allowed Host header names (DNS rebinding); empty = any
	MaxSessions      int           // live sessions in total
	MaxSessionsPerIP int           // live sessions per client IP
	MaxSessionAge    time.Duration // a session ends after this long
	TextMaxChars     int           // text.input must be a string of at most this many characters
	MaxQueuedEvents  int           // client events waiting for the orchestrator; more closes with 1008
	TokensPerMinute  float64       // POST /v1/session per client IP (burst of the same size)
	// Session tokens per client IP per UTC day. ponytail: in memory, so a restart resets it; Redis in Phase 10.
	// Turnstile, the token bucket and the dollar caps still bound spend meanwhile.
	SessionsPerIPPerDay int
	Store               Store // shared nonces and daily counts; nil = this process's memory

	// Step 10 (ADR 0005). AgentsDir: the console's published agent bundles (read-only here); a token request may name
	// an agent that has a live version there. Widget: the built voicecore.js, served at /widget.js; "" = not served.
	AgentsDir string
	Widget    string
	// Console: the console's address. Every path the gateway does not serve goes there, so one host carries the voice
	// endpoint and its dashboard (the hosted deploy; a public install does the same with Caddy). nil = not proxied.
	Console *url.URL
}

// AgentHeader carries the token's agent to the orchestrator, which picks that agent's bundle.
const AgentHeader = "X-VoiceCore-Agent"

var agentID = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,39}$`) // same rule as voicecore/agents.py: never a dot or a slash

func Defaults(secret []byte, upstream string) Config {
	return Config{Secret: secret, Upstream: upstream, TokenTTL: 60 * time.Second, HelloTimeout: 5 * time.Second,
		Heartbeat: 10 * time.Second, ResumeWindow: 10 * time.Second, QueueCap: 50, OutCap: 1500, Log: slog.Default(), Version: "dev", CopyID: "gw",
		TurnstileURL: "https://challenges.cloudflare.com/turnstile/v0/siteverify",
		MaxSessions:  50, MaxSessionsPerIP: 4, MaxSessionAge: 15 * time.Minute, TextMaxChars: 500, MaxQueuedEvents: 256,
		TokensPerMinute: 10}
}

// Counters are totals across sessions, exposed at GET /debug/counters on the admin listener (AdminHandler).
type Counters struct {
	DropsDuplicate, DropsStale, DropsOverload, DropsOverloadOut, DropsFenced, DropsRateLimit, Gaps atomic.Int64
	TokensIssued, RejectedRateLimit, RejectedHost, RejectedUpgrade, RejectedDraining               atomic.Int64
	RejectedToken, RejectedBusy, RejectedUpstream                                                  atomic.Int64 // refused at hello
	RejectedTurnstile, RejectedOrigin, RejectedQuota                                               atomic.Int64
}

type Server struct {
	cfg      Config
	start    time.Time
	c        Counters
	wg       sync.WaitGroup
	mu       sync.Mutex
	sessions map[string]*session
	traceMu  sync.Mutex
	perIP    map[string]int     // live and pending sessions per client IP
	pending  int                // sessions being dialled
	tokens   map[string]*bucket // token issuance per client IP
	draining atomic.Bool        // no new sessions; open ones (and their resumes) continue
	ups      []*upstream        // the orchestrators, each with its own breaker

	site site // the console's "Websites allowed to embed", added to cfg.Origins
	rot  int  // rotates the start among upstreams with equal load
}

// bucket is a token bucket: rate per second, up to burst.
type bucket struct {
	tokens float64
	last   time.Time
}

func (b *bucket) take(now time.Time, rate, burst float64) bool {
	if b.last.IsZero() {
		b.tokens = burst
	} else {
		b.tokens = min(burst, b.tokens+now.Sub(b.last).Seconds()*rate)
	}
	b.last = now
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}

func clientIP(remoteAddr string) string {
	if host, _, err := net.SplitHostPort(remoteAddr); err == nil {
		return host
	}
	return remoteAddr
}

// originAllowed applies the WebSocket upgrade's rules (coder/websocket) to an Origin header: same origin as the
// request is allowed; a pattern matches the host, or scheme://host when the pattern names a scheme.
// site is the console's published list of websites allowed to embed (AgentsDir/_site/origins.json, ADR 0005).
type site struct {
	mu      sync.Mutex
	checked time.Time // the file is looked at again at most once a second
	mtime   time.Time
	origins []string
}

// origins is -origins plus the console's list, so adding a website in the console needs no gateway restart.
// A pattern that would match any site is dropped, as ValidateProd refuses it in -origins.
func (s *Server) origins() []string {
	if s.cfg.AgentsDir == "" {
		return s.cfg.Origins
	}
	s.site.mu.Lock()
	defer s.site.mu.Unlock()
	if now := time.Now(); now.Sub(s.site.checked) >= time.Second {
		s.site.checked = now
		path := filepath.Join(s.cfg.AgentsDir, "_site", "origins.json")
		if st, err := os.Stat(path); err != nil {
			s.site.origins, s.site.mtime = nil, time.Time{}
		} else if !st.ModTime().Equal(s.site.mtime) {
			var f struct {
				Origins []string `json:"origins"`
			}
			if b, err := os.ReadFile(path); err == nil && json.Unmarshal(b, &f) == nil {
				s.site.origins = slices.DeleteFunc(f.Origins, func(o string) bool { return broad(strings.ToLower(o)) })
				s.site.mtime = st.ModTime()
			}
		}
	}
	return append(slices.Clone(s.cfg.Origins), s.site.origins...)
}

func (s *Server) originAllowed(r *http.Request, origin string) bool {
	u, err := url.Parse(origin)
	if err != nil || u.Host == "" {
		return false
	}
	if strings.EqualFold(u.Host, r.Host) {
		return true
	}
	for _, pat := range s.origins() {
		target := u.Host
		if strings.Contains(pat, "://") {
			target = u.Scheme + "://" + u.Host
		}
		if ok, _ := path.Match(strings.ToLower(pat), strings.ToLower(target)); ok {
			return true
		}
	}
	return false
}

func (s *Server) hostAllowed(host string) bool {
	if len(s.cfg.Hosts) == 0 {
		return true
	}
	if h, _, err := net.SplitHostPort(host); err == nil {
		host = h
	}
	for _, ok := range s.cfg.Hosts {
		if host == ok {
			return true
		}
	}
	return false
}

// trace writes one SPEC trace event (process "gateway", this server's monotonic clock).
func (s *Server) trace(sid, event string, gen uint32, attrs map[string]any) {
	if s.cfg.Trace == nil {
		return
	}
	e := map[string]any{"trace_id": sid, "span": "gateway", "event": event, "t_mono_us": s.monoUS(), "process": "gateway", "attrs": attrs}
	if gen != 0 {
		e["generation_id"] = gen
	}
	if attrs == nil {
		e["attrs"] = map[string]any{}
	}
	b, _ := json.Marshal(e)
	s.traceMu.Lock()
	_, _ = s.cfg.Trace.Write(append(b, '\n'))
	s.traceMu.Unlock()
}

// upstream is one orchestrator. sessions counts this gateway's live sessions on it (guarded by Server.mu).
type upstream struct {
	url      string
	br       *breaker
	sessions int
}

func New(cfg Config) *Server {
	if cfg.Store == nil {
		cfg.Store = newMemStore()
	}
	if cfg.HTTPClient == nil {
		cfg.HTTPClient = http.DefaultClient
	}
	if cfg.CopyID == "" {
		cfg.CopyID = "gw"
	}
	srv := &Server{cfg: cfg, start: time.Now(), sessions: map[string]*session{}, perIP: map[string]int{}, tokens: map[string]*bucket{}}
	for _, u := range strings.Split(cfg.Upstream, ",") {
		if u = strings.TrimSpace(u); u != "" {
			srv.ups = append(srv.ups, &upstream{url: u, br: newBreaker()})
		}
	}
	return srv
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "version": s.cfg.Version})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if s.draining.Load() {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ready": false, "draining": true})
			return
		}
		if !s.anyUpstreamReady() {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ready": false, "draining": false, "upstream": "open"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"ready": true, "draining": false})
	})
	mux.HandleFunc("POST /v1/session", func(w http.ResponseWriter, r *http.Request) {
		if origin := r.Header.Get("Origin"); origin != "" { // browsers send it; curl and the harness do not
			if !s.originAllowed(r, origin) {
				s.c.RejectedOrigin.Add(1)
				http.Error(w, "origin not allowed", http.StatusForbidden)
				return
			}
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
		}
		if s.draining.Load() {
			s.c.RejectedDraining.Add(1)
			http.Error(w, "draining", http.StatusServiceUnavailable)
			return
		}
		ip := s.clientIP(r)
		s.mu.Lock()
		if len(s.tokens) > 10_000 { // ponytail: crude reset bounds memory; use an LRU if this ever serves the internet
			s.tokens = map[string]*bucket{}
		}
		b := s.tokens[ip]
		if b == nil {
			b = &bucket{}
			s.tokens[ip] = b
		}
		allowed := s.cfg.TokensPerMinute <= 0 || b.take(time.Now(), s.cfg.TokensPerMinute/60, s.cfg.TokensPerMinute)
		s.mu.Unlock()
		if !allowed {
			s.c.RejectedRateLimit.Add(1)
			http.Error(w, "too many session requests", http.StatusTooManyRequests)
			return
		}
		if s.cfg.TurnstileSecret != "" { // after the rate limit, so nobody can make us hammer siteverify
			if code, msg := s.checkTurnstile(w, r, ip); code != 0 {
				http.Error(w, msg, code)
				return
			}
		}
		agent, code, msg := s.requestedAgent(w, r)
		if code != 0 {
			http.Error(w, msg, code)
			return
		}
		quota := s.takeDaily(ip) // only a request that passed every check spends the day's quota
		if !quota {
			s.c.RejectedQuota.Add(1)
			http.Error(w, "daily session limit reached for this address", http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		s.c.TokensIssued.Add(1)
		_ = json.NewEncoder(w).Encode(map[string]string{"token": s.TokenFor(ip, agent)})
	})
	mux.HandleFunc("GET /v1/ws", s.serveWS)
	if s.cfg.Widget != "" {
		mux.HandleFunc("GET /widget.js", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Cache-Control", "public, max-age=300")
			w.Header().Set("Content-Type", "text/javascript; charset=utf-8")
			http.ServeFile(w, r, s.cfg.Widget)
		})
	}
	if s.cfg.Console != nil {
		mux.Handle("/", s.consoleProxy())
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !s.hostAllowed(r.Host) { // a DNS-rebinding page arrives with its own host name
			s.c.RejectedHost.Add(1)
			http.Error(w, "unknown host", http.StatusMisdirectedRequest)
			return
		}
		mux.ServeHTTP(w, r)
	})
}

// consoleProxy passes a request on to the console with the real client and scheme: its login limit then counts per
// visitor, and its session cookie is Secure behind HTTPS. A visitor's own X-Forwarded-* headers are dropped.
func (s *Server) consoleProxy() http.Handler {
	return &httputil.ReverseProxy{Transport: s.cfg.HTTPClient.Transport, Rewrite: func(p *httputil.ProxyRequest) {
		p.SetURL(s.cfg.Console)
		p.Out.Host = p.In.Host // the console compares a request's Origin with its own host
		p.Out.Header.Set("X-Forwarded-For", s.clientIP(p.In))
		proto := "http"
		if p.In.TLS != nil || s.trusted(clientIP(p.In.RemoteAddr)) && p.In.Header.Get("X-Forwarded-Proto") == "https" {
			proto = "https"
		}
		p.Out.Header.Set("X-Forwarded-Proto", proto)
	}}
}

// requestedAgent reads the optional form field "agent": "" (the default agent), or an id with a live version in
// AgentsDir. It returns a status and message when the request names a bad or unknown agent.
func (s *Server) requestedAgent(w http.ResponseWriter, r *http.Request) (string, int, string) {
	r.Body = http.MaxBytesReader(w, r.Body, 4<<10)
	if err := r.ParseForm(); err != nil {
		return "", http.StatusBadRequest, "bad form"
	}
	agent := r.PostForm.Get("agent")
	if agent == "" {
		return "", 0, ""
	}
	if !agentID.MatchString(agent) {
		return "", http.StatusBadRequest, "bad agent id"
	}
	if s.cfg.AgentsDir == "" {
		return "", http.StatusNotFound, "unknown agent"
	}
	if _, err := os.Stat(filepath.Join(s.cfg.AgentsDir, agent, "current")); err != nil {
		return "", http.StatusNotFound, "unknown agent"
	}
	return agent, 0, ""
}

// takeDaily counts one token against this IP's daily quota. A store error lets the request through with a warning:
// Turnstile, the token bucket and the dollar caps still bound spend (fail open).
func (s *Server) takeDaily(ip string) bool {
	if s.cfg.SessionsPerIPPerDay <= 0 {
		return true
	}
	ok, err := s.cfg.Store.TakeDaily(context.Background(), ip, time.Now().UTC().Unix()/86_400, s.cfg.SessionsPerIPPerDay)
	if err != nil {
		s.cfg.Log.Warn("quota store unavailable; allowing", "err", err)
		return true
	}
	return ok
}

func (s *Server) serveCounters(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(s.Snapshot())
}

// Snapshot returns the counters, live sessions and queue depths.
func (s *Server) Snapshot() map[string]int64 {
	s.mu.Lock()
	var depth, out int64
	for _, ss := range s.sessions {
		depth += int64(ss.upq.depth())
		out += int64(ss.outq.depth())
	}
	n := int64(len(s.sessions))
	s.mu.Unlock()
	return map[string]int64{"sessions": n, "depth": depth, "depth_out": out,
		"drops_duplicate": s.c.DropsDuplicate.Load(), "drops_stale": s.c.DropsStale.Load(),
		"drops_overload": s.c.DropsOverload.Load(), "drops_overload_out": s.c.DropsOverloadOut.Load(), "drops_ratelimit": s.c.DropsRateLimit.Load(), "drops_fenced": s.c.DropsFenced.Load(), "gaps": s.c.Gaps.Load(),
		"tokens_issued": s.c.TokensIssued.Load(), "rejected_ratelimit": s.c.RejectedRateLimit.Load(), "rejected_host": s.c.RejectedHost.Load(),
		"rejected_upgrade": s.c.RejectedUpgrade.Load(), "rejected_draining": s.c.RejectedDraining.Load(),
		"rejected_token": s.c.RejectedToken.Load(), "rejected_busy": s.c.RejectedBusy.Load(), "rejected_upstream": s.c.RejectedUpstream.Load(),
		"rejected_turnstile": s.c.RejectedTurnstile.Load(), "rejected_origin": s.c.RejectedOrigin.Load(),
		"rejected_quota": s.c.RejectedQuota.Load()}
}

// Close ends every session and waits for their goroutines.
func (s *Server) Close() {
	s.mu.Lock()
	all := make([]*session, 0, len(s.sessions))
	for _, ss := range s.sessions {
		all = append(all, ss)
	}
	s.mu.Unlock()
	var ended sync.WaitGroup
	for _, ss := range all { // in parallel: each end waits up to 5 s for an upstream close handshake
		ended.Go(func() { ss.end("shutdown") })
	}
	ended.Wait()
	s.wg.Wait()
}

// Token is "<expiry unix s>.<nonce>.<hex HMAC-SHA256 of expiry.nonce.client IP>": it starts one session, from that IP.
func (s *Server) Token(ip string) string { return s.TokenFor(ip, "") }

// TokenFor is Token for a named agent: "<expiry>.<nonce>.<agent>.<HMAC of expiry.nonce.agent.IP>". The signature
// covers the agent, so a token cannot be pointed at another agent's settings and budget. No agent: today's 3 parts.
func (s *Server) TokenFor(ip, agent string) string {
	exp := strconv.FormatInt(time.Now().Add(s.cfg.TokenTTL).Unix(), 10)
	n := make([]byte, 8)
	_, _ = rand.Read(n)
	head := exp + "." + hex.EncodeToString(n)
	if agent != "" {
		head += "." + agent
	}
	return head + "." + s.sign(head+"."+ip)
}

func (s *Server) sign(msg string) string {
	m := hmac.New(sha256.New, s.cfg.Secret)
	m.Write([]byte(msg))
	return hex.EncodeToString(m.Sum(nil))
}

// useToken checks a token for this client IP and spends its nonce: valid once, from the IP it was minted for.
// It returns the spent nonce, which the caller gives back with unspend when no session was started, and the token's
// agent ("" for the default). err: the store could not say whether the nonce is fresh, so the caller refuses (fail closed).
func (s *Server) useToken(tok, ip string) (nonce, agent string, ok bool, err error) {
	parts := strings.Split(tok, ".")
	if len(parts) != 3 && len(parts) != 4 {
		return "", "", false, nil
	}
	head, sig := strings.Join(parts[:len(parts)-1], "."), parts[len(parts)-1]
	if !hmac.Equal([]byte(sig), []byte(s.sign(head+"."+ip))) {
		return "", "", false, nil
	}
	if len(parts) == 4 {
		agent = parts[2]
	}
	exp, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil || time.Now().Unix() >= exp {
		return "", "", false, nil
	}
	fresh, err := s.cfg.Store.UseNonce(context.Background(), parts[1], time.Unix(exp, 0))
	return parts[1], agent, fresh && err == nil, err
}

func (s *Server) unspend(nonce string) {
	if err := s.cfg.Store.ReleaseNonce(context.Background(), nonce); err != nil {
		s.cfg.Log.Warn("could not give a token back", "err", err)
	}
}

func (s *Server) monoUS() int64 { return time.Since(s.start).Microseconds() }

type hello struct {
	Version   int    `json:"version"`
	Token     string `json:"token"`
	SessionID string `json:"session_id"`
	ResumeKey string `json:"resume_key"`
	Mic       struct {
		Rate    int `json:"rate"`
		FrameMS int `json:"frame_ms"`
	} `json:"mic"`
	Playout struct {
		Rate int `json:"rate"`
	} `json:"playout"`
}

const (
	statusBadToken     websocket.StatusCode = 4001
	statusBadFormat    websocket.StatusCode = 4002
	statusHeartbeat    websocket.StatusCode = 4003
	statusInvalidFrame                      = websocket.StatusInvalidFramePayloadData // 1007
	statusPolicy                            = websocket.StatusPolicyViolation         // 1008
)

func (s *Server) serveWS(w http.ResponseWriter, r *http.Request) {
	c, err := websocket.Accept(w, r, &websocket.AcceptOptions{OriginPatterns: s.origins()})
	if err != nil {
		s.c.RejectedUpgrade.Add(1) // mostly a disallowed origin
		return
	}
	c.SetReadLimit(64 << 10)
	ss, resumed, code, reason := s.hello(c, s.clientIP(r))
	if code != 0 {
		_ = c.Close(code, reason)
		return
	}
	ss.attach(c, resumed)
}

var (
	errBusy             = errors.New("session limit reached")
	errDraining         = errors.New("draining")
	errUpstreamNotReady = errors.New("orchestrator not ready")
	errUpstreamOpen     = errors.New("orchestrator circuit breaker open")
)

func (s *Server) hello(c *websocket.Conn, ip string) (ss *session, resumed bool, code websocket.StatusCode, reason string) {
	ctx, cancel := context.WithTimeout(context.Background(), s.cfg.HelloTimeout)
	defer cancel()
	typ, b, err := c.Read(ctx)
	if err != nil {
		return nil, false, statusPolicy, "no hello"
	}
	var h hello
	if e, err := protocol.DecodeEvent(b); typ != websocket.MessageText || err != nil || e.Type() != "hello" || json.Unmarshal(b, &h) != nil {
		return nil, false, statusPolicy, "first message must be hello"
	}
	if h.Version != 1 || h.Mic.Rate != 16000 || h.Mic.FrameMS != 20 || h.Playout.Rate != 24000 {
		return nil, false, statusBadFormat, "unsupported version or audio format"
	}
	if h.SessionID != "" && h.ResumeKey != "" { // the key proves ownership, so a spent token is fine on a reconnect
		s.mu.Lock()
		old := s.sessions[h.SessionID]
		s.mu.Unlock()
		if old != nil && hmac.Equal([]byte(h.ResumeKey), []byte(old.resumeKey)) && old.takeOver() {
			return old, true, 0, ""
		}
	}
	nonce, agent, ok, err := s.useToken(h.Token, ip)
	if err != nil {
		s.cfg.Log.Warn("token store unavailable", "err", err)
		return nil, false, websocket.StatusTryAgainLater, "unavailable"
	}
	if !ok {
		s.c.RejectedToken.Add(1)
		return nil, false, statusBadToken, "invalid, expired or already used token"
	}
	ss, err = s.newSession(ip, agent) // resumes above still work while draining; new sessions do not
	if err != nil {
		s.unspend(nonce) // no session started, so "try again later" can reuse the token
	}
	switch {
	case errors.Is(err, errDraining):
		s.c.RejectedDraining.Add(1)
		return nil, false, websocket.StatusTryAgainLater, "draining"
	case errors.Is(err, errUpstreamNotReady):
		s.c.RejectedUpstream.Add(1)
		return nil, false, websocket.StatusTryAgainLater, "orchestrator not ready"
	case errors.Is(err, errBusy):
		s.c.RejectedBusy.Add(1)
		return nil, false, websocket.StatusTryAgainLater, "too many sessions"
	case errors.Is(err, errUpstreamOpen):
		s.c.RejectedUpstream.Add(1)
		return nil, false, websocket.StatusInternalError, "orchestrator unavailable"
	}
	if err != nil {
		s.c.RejectedUpstream.Add(1)
		s.cfg.Log.Warn("upstream dial failed", "err", err)
		return nil, false, websocket.StatusInternalError, "orchestrator unavailable"
	}
	return ss, false, 0, ""
}

func (s *Server) newSession(ip, agent string) (*session, error) {
	s.mu.Lock()            // reserve a slot before dialling, so concurrent hellos cannot overshoot the caps
	if s.draining.Load() { // checked under the lock that Drain's count reads, so no session slips past a drain
		s.mu.Unlock()
		return nil, errDraining
	}
	if (s.cfg.MaxSessions > 0 && len(s.sessions)+s.pending >= s.cfg.MaxSessions) ||
		(s.cfg.MaxSessionsPerIP > 0 && s.perIP[ip] >= s.cfg.MaxSessionsPerIP) {
		s.mu.Unlock()
		return nil, errBusy
	}
	s.pending++
	s.perIP[ip]++
	s.mu.Unlock()
	registered := false
	defer func() {
		s.mu.Lock()
		s.pending--
		if !registered {
			s.releaseIP(ip)
		}
		s.mu.Unlock()
	}()
	id := make([]byte, 8)
	_, _ = rand.Read(id)
	sid := "s-" + s.cfg.CopyID + "-" + hex.EncodeToString(id)
	key := make([]byte, 32)
	_, _ = rand.Read(key)
	var up *websocket.Conn
	var chosen *upstream
	var err error = errUpstreamOpen // every breaker open: nothing was dialled
	notReady := false
	for _, u := range s.candidates() {
		if !u.br.allow() {
			continue
		}
		if up, err = s.dial(u, sid, agent); err == nil {
			chosen = u
			break
		}
		if errors.Is(err, errUpstreamNotReady) {
			notReady = true // draining or starting: try another, and tell the client to retry if none takes it
			continue
		}
		if timedOut(err) {
			break // the orchestrator may have taken the session (and reserved budget): never the same id on another
		}
		// anything else failed before an upgrade (refused, a name that no longer resolves, an error status):
		// no session started there, so the next orchestrator may have it
	}
	if chosen == nil {
		if notReady {
			return nil, errUpstreamNotReady
		}
		return nil, err
	}
	up.SetReadLimit(1 << 20)
	upCtx, cancelUp := context.WithCancel(context.Background())
	ss := &session{up0: chosen, id: sid, resumeKey: hex.EncodeToString(key), ip: ip, srv: s, up: up, upCtx: upCtx, cancelUp: cancelUp, claimed: true, started: time.Now(),
		upq: newQueue(s.cfg.QueueCap, &s.c.DropsOverload, s.cfg.MaxQueuedEvents), outq: newQueue(s.cfg.OutCap, &s.c.DropsOverloadOut, 0),
		lastSeq: map[uint32]uint32{}, revoked: map[uint32]bool{}}
	s.mu.Lock()
	s.sessions[sid] = ss
	chosen.sessions++
	registered = true
	s.mu.Unlock()
	s.cfg.Log.Info("session started", "session_id", sid, "agent", agent)
	if s.cfg.MaxSessionAge > 0 {
		ss.ageTimer = time.AfterFunc(s.cfg.MaxSessionAge, func() { ss.end("expired") })
	}
	s.trace(sid, "session_started", 0, nil)
	s.wg.Add(2)
	go func() { defer s.wg.Done(); ss.writeUpstream() }()
	go func() { defer s.wg.Done(); ss.readUpstream() }()
	return ss, nil
}

// releaseIP gives back one session slot of ip; the caller holds s.mu.
// candidates orders the upstreams for a new session: fewest of this gateway's sessions first, ties rotated.
func (s *Server) candidates() []*upstream {
	s.mu.Lock()
	defer s.mu.Unlock()
	n := len(s.ups)
	out := make([]*upstream, n)
	for i := range out {
		out[i] = s.ups[(s.rot+i)%n]
	}
	s.rot++
	sort.SliceStable(out, func(a, b int) bool { return out[a].sessions < out[b].sessions })
	return out
}

// dial opens a session on one upstream. A refused dial is retried once after 300 ms: nothing reached the
// orchestrator, so nothing was reserved. A timed-out dial is never retried (it may have reserved budget there).
func (s *Server) dial(u *upstream, sid, agent string) (*websocket.Conn, error) {
	opts := &websocket.DialOptions{HTTPClient: s.cfg.HTTPClient}
	if agent != "" { // a header, not a query string: the orchestrator reads the session id from the path
		opts.HTTPHeader = http.Header{AgentHeader: {agent}}
	}
	dial := func() (*websocket.Conn, *http.Response, error) {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second) // bounds the handshake only
		defer cancel()
		return websocket.Dial(ctx, u.url+"/v1/session/"+sid, opts)
	}
	up, resp, err := dial()
	if err != nil && errors.Is(err, syscall.ECONNREFUSED) {
		time.Sleep(300 * time.Millisecond)
		up, resp, err = dial()
	}
	if err != nil {
		if resp != nil && resp.StatusCode == http.StatusServiceUnavailable { // starting or draining: try another one
			u.br.release()
			return nil, errUpstreamNotReady
		}
		u.br.failure()
		return nil, fmt.Errorf("dial %s: %w", u.url, err)
	}
	u.br.success()
	return up, nil
}

func timedOut(err error) bool {
	var ne net.Error
	return errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &ne) && ne.Timeout())
}

func (s *Server) anyUpstreamReady() bool {
	for _, u := range s.ups {
		if u.br.ready() {
			return true
		}
	}
	return false
}

func (s *Server) releaseIP(ip string) {
	if s.perIP[ip]--; s.perIP[ip] <= 0 {
		delete(s.perIP, ip)
	}
}

// BeginDrain stops taking new sessions; open ones (and their resumes) continue.
func (s *Server) BeginDrain() { s.draining.Store(true) }

// Drain begins draining, waits up to timeout for open sessions to end, then ends the rest with reason "shutdown".
func (s *Server) Drain(timeout time.Duration) {
	s.BeginDrain()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		n := len(s.sessions) + s.pending
		s.mu.Unlock()
		if n == 0 {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	s.Close()
}

func writeJSON(w http.ResponseWriter, code int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(body)
}

// Probe GETs url with a 2 s timeout and returns a process exit code: 0 for HTTP 200, 1 otherwise. The gateway image
// is distroless (no curl), so `gateway -probe URL` is its container healthcheck.
func Probe(url string) int { return ProbeWith(&http.Client{Timeout: 2 * time.Second}, url) }

// ProbeWith is Probe with a given client (tests use the in-memory network).
func ProbeWith(c *http.Client, url string) int {
	resp, err := c.Get(url)
	if err != nil {
		return 1
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 1
	}
	return 0
}

// clientIP is the address limits and token binding use. X-Forwarded-For counts only when the peer is a trusted
// proxy; then the rightmost address that is not a trusted proxy is the client (the left part can be spoofed).
func (s *Server) clientIP(r *http.Request) string {
	peer := clientIP(r.RemoteAddr)
	if !s.trusted(peer) {
		return peer
	}
	hops := strings.Split(strings.Join(r.Header.Values("X-Forwarded-For"), ","), ",") // every header line, in order
	for i := len(hops) - 1; i >= 0; i-- {
		h := strings.TrimSpace(hops[i])
		if h == "" {
			continue
		}
		a, err := netip.ParseAddr(strings.Trim(h, "[]"))
		if err != nil { // some proxies write ip:port
			ap, err2 := netip.ParseAddrPort(h)
			if err2 != nil {
				return peer // garbage: key on the proxy rather than on a string the client may have chosen
			}
			a = ap.Addr()
		}
		if ip := a.Unmap().String(); !s.trusted(ip) {
			return ip
		}
	}
	return peer
}

func (s *Server) trusted(ip string) bool {
	a, err := netip.ParseAddr(ip)
	if err != nil {
		return false
	}
	for _, p := range s.cfg.TrustedProxies {
		if p.Contains(a.Unmap()) {
			return true
		}
	}
	return false
}
