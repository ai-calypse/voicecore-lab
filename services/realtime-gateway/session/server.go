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
	"fmt"
	"log/slog"
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
}

func Defaults(secret []byte, upstream string) Config {
	return Config{Secret: secret, Upstream: upstream, TokenTTL: 60 * time.Second, HelloTimeout: 5 * time.Second,
		Heartbeat: 10 * time.Second, ResumeWindow: 10 * time.Second, QueueCap: 50, OutCap: 1500, Log: slog.Default()}
}

// Counters are totals across sessions, exposed at GET /debug/counters.
type Counters struct {
	DropsDuplicate, DropsStale, DropsOverload, DropsOverloadOut, DropsFenced, Gaps atomic.Int64
}

type Server struct {
	cfg      Config
	start    time.Time
	c        Counters
	wg       sync.WaitGroup
	mu       sync.Mutex
	sessions map[string]*session
}

func New(cfg Config) *Server {
	if cfg.HTTPClient == nil {
		cfg.HTTPClient = http.DefaultClient
	}
	return &Server{cfg: cfg, start: time.Now(), sessions: map[string]*session{}}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/session", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*") // development only: the token is not bound to a user
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"token": s.Token()})
	})
	mux.HandleFunc("GET /v1/ws", s.serveWS)
	mux.HandleFunc("GET /debug/counters", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(s.Snapshot())
	})
	return mux
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
		"drops_overload": s.c.DropsOverload.Load(), "drops_overload_out": s.c.DropsOverloadOut.Load(), "drops_fenced": s.c.DropsFenced.Load(), "gaps": s.c.Gaps.Load()}
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
	ss, resumed, code, reason := s.hello(c)
	if code != 0 {
		_ = c.Close(code, reason)
		return
	}
	ss.attach(c, resumed)
}

func (s *Server) hello(c *websocket.Conn) (ss *session, resumed bool, code websocket.StatusCode, reason string) {
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
	ss, err = s.newSession()
	if err != nil {
		s.cfg.Log.Warn("upstream dial failed", "err", err)
		return nil, false, websocket.StatusInternalError, "orchestrator unavailable"
	}
	return ss, false, 0, ""
}

func (s *Server) newSession() (*session, error) {
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
	ss := &session{id: sid, srv: s, up: up, upCtx: upCtx, cancelUp: cancelUp, claimed: true,
		upq: newQueue(s.cfg.QueueCap, &s.c.DropsOverload), outq: newQueue(s.cfg.OutCap, &s.c.DropsOverloadOut),
		lastSeq: map[uint32]uint32{}, revoked: map[uint32]bool{}}
	s.mu.Lock()
	s.sessions[sid] = ss
	s.mu.Unlock()
	s.wg.Add(2)
	go func() { defer s.wg.Done(); ss.writeUpstream() }()
	go func() { defer s.wg.Done(); ss.readUpstream() }()
	return ss, nil
}
