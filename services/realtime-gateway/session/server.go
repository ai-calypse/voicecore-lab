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
		Heartbeat: 10 * time.Second, ResumeWindow: 10 * time.Second, QueueCap: 50, OutCap: 1500, Log: slog.Default(),
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
	return &Server{cfg: cfg, start: time.Now(), sessions: map[string]*session{}, perIP: map[string]int{}, tokens: map[string]*bucket{}}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/session", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*") // development only: the token is not bound to a user
		ip := clientIP(r.RemoteAddr)
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
		_ = json.NewEncoder(w).Encode(map[string]string{"token": s.Token()})
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

// Token is "<expiry unix seconds>.<hex HMAC-SHA256 of the expiry>".
func (s *Server) Token() string {
	exp := strconv.FormatInt(time.Now().Add(s.cfg.TokenTTL).Unix(), 10)
	return exp + "." + s.sign(exp)
}

func (s *Server) sign(msg string) string {
	m := hmac.New(sha256.New, s.cfg.Secret)
	m.Write([]byte(msg))
	return hex.EncodeToString(m.Sum(nil))
}

func (s *Server) validToken(tok string) bool {
	exp, mac, ok := strings.Cut(tok, ".")
	if !ok || !hmac.Equal([]byte(mac), []byte(s.sign(exp))) {
		return false
	}
	t, err := strconv.ParseInt(exp, 10, 64)
	return err == nil && time.Now().Unix() < t
}

func (s *Server) monoUS() int64 { return time.Since(s.start).Microseconds() }

type hello struct {
	Version   int    `json:"version"`
	Token     string `json:"token"`
	SessionID string `json:"session_id"`
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
	ss, resumed, code, reason := s.hello(c, clientIP(r.RemoteAddr))
	if code != 0 {
		_ = c.Close(code, reason)
		return
	}
	ss.attach(c, resumed)
}

var errBusy = errors.New("session limit reached")

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
	if !s.validToken(h.Token) {
		return nil, false, statusBadToken, "invalid or expired token"
	}
	if h.Version != 1 || h.Mic.Rate != 16000 || h.Mic.FrameMS != 20 || h.Playout.Rate != 24000 {
		return nil, false, statusBadFormat, "unsupported version or audio format"
	}
	if h.SessionID != "" {
		s.mu.Lock()
		old := s.sessions[h.SessionID]
		s.mu.Unlock()
		if old != nil && old.claim() {
			return old, true, 0, ""
		}
	}
	ss, err = s.newSession(ip)
	if errors.Is(err, errBusy) {
		return nil, false, websocket.StatusTryAgainLater, "too many sessions"
	}
	if err != nil {
		s.cfg.Log.Warn("upstream dial failed", "err", err)
		return nil, false, websocket.StatusInternalError, "orchestrator unavailable"
	}
	return ss, false, 0, ""
}

func (s *Server) newSession(ip string) (*session, error) {
	s.mu.Lock() // reserve a slot before dialling, so concurrent hellos cannot overshoot the caps
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
	sid := "s-" + hex.EncodeToString(id)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	up, _, err := websocket.Dial(ctx, s.cfg.Upstream+"/v1/session/"+sid, &websocket.DialOptions{HTTPClient: s.cfg.HTTPClient})
	if err != nil {
		return nil, fmt.Errorf("dial %s: %w", s.cfg.Upstream, err)
	}
	up.SetReadLimit(1 << 20)
	upCtx, cancelUp := context.WithCancel(context.Background())
	ss := &session{id: sid, ip: ip, srv: s, up: up, upCtx: upCtx, cancelUp: cancelUp, claimed: true,
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
