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
	"net/netip"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
)

type Config struct {
	Secret       []byte
	Upstream     string       // orchestrator base URL, e.g. ws://127.0.0.1:8765
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

	// Abuse limits (security review 2026-10-30). Zero means no limit.
	Hosts            []string      // allowed Host header names (DNS rebinding); empty = any
	MaxSessions      int           // live sessions in total
	MaxSessionsPerIP int           // live sessions per client IP
	MaxSessionAge    time.Duration // a session ends after this long
	TextMaxChars     int           // text.input must be a string of at most this many characters
	MaxQueuedEvents  int           // client events waiting for the orchestrator; more closes with 1008
	TokensPerMinute  float64       // POST /v1/session per client IP (burst of the same size)
}

func Defaults(secret []byte, upstream string) Config {
	return Config{Secret: secret, Upstream: upstream, TokenTTL: 60 * time.Second, HelloTimeout: 5 * time.Second,
		Heartbeat: 10 * time.Second, ResumeWindow: 10 * time.Second, QueueCap: 50, OutCap: 1500, Log: slog.Default(), Version: "dev", CopyID: "gw",
		MaxSessions: 50, MaxSessionsPerIP: 4, MaxSessionAge: 15 * time.Minute, TextMaxChars: 500, MaxQueuedEvents: 256,
		TokensPerMinute: 10}
}

// Counters are totals across sessions, exposed at GET /debug/counters.
type Counters struct {
	DropsDuplicate, DropsStale, DropsOverload, DropsOverloadOut, DropsFenced, DropsRateLimit, Gaps atomic.Int64
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
	nonces   map[string]int64   // used token nonces until their expiry (unix s): a token starts one session
	swept    int64              // unix s of the last nonce sweep
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

func New(cfg Config) *Server {
	if cfg.HTTPClient == nil {
		cfg.HTTPClient = http.DefaultClient
	}
	if cfg.CopyID == "" {
		cfg.CopyID = "gw"
	}
	return &Server{cfg: cfg, start: time.Now(), sessions: map[string]*session{}, perIP: map[string]int{}, tokens: map[string]*bucket{},
		nonces: map[string]int64{}}
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
		writeJSON(w, http.StatusOK, map[string]any{"ready": true, "draining": false})
	})
	mux.HandleFunc("POST /v1/session", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*") // development only: the token is not bound to a user
		if s.draining.Load() {
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
			http.Error(w, "too many session requests", http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"token": s.Token(ip)})
	})
	mux.HandleFunc("GET /v1/ws", s.serveWS)
	mux.HandleFunc("GET /debug/counters", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(s.Snapshot())
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !s.hostAllowed(r.Host) { // a DNS-rebinding page arrives with its own host name
			http.Error(w, "unknown host", http.StatusMisdirectedRequest)
			return
		}
		mux.ServeHTTP(w, r)
	})
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
		"drops_overload": s.c.DropsOverload.Load(), "drops_overload_out": s.c.DropsOverloadOut.Load(), "drops_ratelimit": s.c.DropsRateLimit.Load(), "drops_fenced": s.c.DropsFenced.Load(), "gaps": s.c.Gaps.Load()}
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
func (s *Server) Token(ip string) string {
	exp := strconv.FormatInt(time.Now().Add(s.cfg.TokenTTL).Unix(), 10)
	n := make([]byte, 8)
	_, _ = rand.Read(n)
	nonce := hex.EncodeToString(n)
	return exp + "." + nonce + "." + s.sign(exp+"."+nonce+"."+ip)
}

func (s *Server) sign(msg string) string {
	m := hmac.New(sha256.New, s.cfg.Secret)
	m.Write([]byte(msg))
	return hex.EncodeToString(m.Sum(nil))
}

// useToken checks a token for this client IP and spends its nonce: valid once, from the IP it was minted for.
// It returns the spent nonce, which the caller gives back with unspend when no session was started.
func (s *Server) useToken(tok, ip string) (string, bool) {
	parts := strings.Split(tok, ".")
	if len(parts) != 3 || !hmac.Equal([]byte(parts[2]), []byte(s.sign(parts[0]+"."+parts[1]+"."+ip))) {
		return "", false
	}
	exp, err := strconv.ParseInt(parts[0], 10, 64)
	now := time.Now().Unix()
	if err != nil || now >= exp {
		return "", false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if now != s.swept { // at most one linear sweep per second, so a burst of hellos does not rescan the map each time
		s.swept = now
		for n, e := range s.nonces {
			if e <= now {
				delete(s.nonces, n)
			}
		}
	}
	if _, used := s.nonces[parts[1]]; used {
		return "", false
	}
	s.nonces[parts[1]] = exp
	return parts[1], true
}

func (s *Server) unspend(nonce string) {
	s.mu.Lock()
	delete(s.nonces, nonce)
	s.mu.Unlock()
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
	c, err := websocket.Accept(w, r, &websocket.AcceptOptions{OriginPatterns: s.cfg.Origins})
	if err != nil {
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
		if old != nil && hmac.Equal([]byte(h.ResumeKey), []byte(old.resumeKey)) && old.claim() {
			return old, true, 0, ""
		}
	}
	nonce, ok := s.useToken(h.Token, ip)
	if !ok {
		return nil, false, statusBadToken, "invalid, expired or already used token"
	}
	ss, err = s.newSession(ip) // resumes above still work while draining; new sessions do not
	if err != nil {
		s.unspend(nonce) // no session started, so "try again later" can reuse the token
	}
	switch {
	case errors.Is(err, errDraining):
		return nil, false, websocket.StatusTryAgainLater, "draining"
	case errors.Is(err, errUpstreamNotReady):
		return nil, false, websocket.StatusTryAgainLater, "orchestrator not ready"
	case errors.Is(err, errBusy):
		return nil, false, websocket.StatusTryAgainLater, "too many sessions"
	}
	if err != nil {
		s.cfg.Log.Warn("upstream dial failed", "err", err)
		return nil, false, websocket.StatusInternalError, "orchestrator unavailable"
	}
	return ss, false, 0, ""
}

func (s *Server) newSession(ip string) (*session, error) {
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
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	up, resp, err := websocket.Dial(ctx, s.cfg.Upstream+"/v1/session/"+sid, &websocket.DialOptions{HTTPClient: s.cfg.HTTPClient})
	if err != nil {
		if resp != nil && resp.StatusCode == http.StatusServiceUnavailable { // starting or draining: retry shortly
			return nil, errUpstreamNotReady
		}
		return nil, fmt.Errorf("dial %s: %w", s.cfg.Upstream, err)
	}
	up.SetReadLimit(1 << 20)
	upCtx, cancelUp := context.WithCancel(context.Background())
	ss := &session{id: sid, resumeKey: hex.EncodeToString(key), ip: ip, srv: s, up: up, upCtx: upCtx, cancelUp: cancelUp, claimed: true,
		upq: newQueue(s.cfg.QueueCap, &s.c.DropsOverload, s.cfg.MaxQueuedEvents), outq: newQueue(s.cfg.OutCap, &s.c.DropsOverloadOut, 0),
		lastSeq: map[uint32]uint32{}, revoked: map[uint32]bool{}}
	s.mu.Lock()
	s.sessions[sid] = ss
	registered = true
	s.mu.Unlock()
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
