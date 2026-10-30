package session

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"net/http"
	"testing"
	"testing/synctest"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/internal/fakeorch"
	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/internal/memnet"
	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
	"go.uber.org/goleak"
)

func TestMain(m *testing.M) { goleak.VerifyTestMain(m) }

// rig is a gateway plus fake orchestrator on an in-memory network, inside a synctest bubble.
type rig struct {
	t      *testing.T
	gw     *Server
	orch   *fakeorch.Orch
	http   *http.Client
	net    *memnet.Network
	orchLn *memnet.Listener
}

func run(t *testing.T, hold bool, f func(t *testing.T, r *rig)) { runCfg(t, hold, nil, f) }

// runCfg is run with a chance to change the gateway config before it starts.
func runCfg(t *testing.T, hold bool, mutate func(*Config), f func(t *testing.T, r *rig)) {
	synctest.Test(t, func(t *testing.T) {
		n := memnet.New()
		orch := fakeorch.New()
		if hold {
			orch.Hold = make(chan struct{})
		}
		orchSrv, orchLn := &http.Server{Handler: orch.Handler()}, n.Listen("orch:80")
		go func() { _ = orchSrv.Serve(orchLn) }()
		cfg := Defaults([]byte("test-secret"), "ws://orch:80")
		cfg.HTTPClient = n.HTTPClient()
		cfg.Log = slog.New(slog.DiscardHandler)
		if mutate != nil {
			mutate(&cfg)
		}
		gw := New(cfg)
		gwSrv, gwLn := &http.Server{Handler: gw.Handler()}, n.Listen("gw:80")
		go func() { _ = gwSrv.Serve(gwLn) }()
		adminSrv, adminLn := &http.Server{Handler: gw.AdminHandler()}, n.Listen("gwadmin:80")
		go func() { _ = adminSrv.Serve(adminLn) }()
		r := &rig{t: t, gw: gw, orch: orch, http: n.HTTPClient(), net: n, orchLn: orchLn}
		defer func() { // also runs after t.Fatal, so a failure does not turn into a bubble deadlock
			if hold {
				select {
				case <-orch.Hold:
				default:
					close(orch.Hold)
				}
			}
			gw.Close()
			_ = gwSrv.Close()
			_ = adminSrv.Close()
			_ = orchSrv.Close()
			r.http.CloseIdleConnections()
			cfg.HTTPClient.CloseIdleConnections()
			synctest.Wait()
		}()
		f(t, r)
	})
}

func (r *rig) token() string { return r.tokenVia(r.http) }

// tokenVia asks for a session token as the client behind hc (memnet.HTTPClientFrom picks its address).
func (r *rig) tokenVia(hc *http.Client) string {
	resp, err := hc.Post("http://gw:80/v1/session", "application/json", nil)
	if err != nil {
		r.t.Fatal(err)
	}
	defer resp.Body.Close()
	var body struct{ Token string }
	_ = json.NewDecoder(resp.Body).Decode(&body)
	return body.Token
}

func (r *rig) counters() map[string]int64 {
	resp, err := r.http.Get("http://gwadmin:80/debug/counters")
	if err != nil {
		r.t.Fatal(err)
	}
	defer resp.Body.Close()
	var m map[string]int64
	b, _ := io.ReadAll(resp.Body)
	if err := json.Unmarshal(b, &m); err != nil {
		r.t.Fatalf("%s: %v", b, err)
	}
	return m
}

type client struct {
	t      *testing.T
	ws     *websocket.Conn
	events chan protocol.Event
	frames chan protocol.Frame
	closed chan websocket.StatusCode
	gate   chan struct{} // reader waits on this before each read while non-nil
}

// connect dials the gateway and sends hello; extra fields override the defaults.
func (r *rig) connect(extra map[string]any, gate chan struct{}) *client {
	return r.connectVia(r.http, extra, gate)
}

// connectVia is connect as the client behind hc; a token in extra is used as is, otherwise one is minted through hc.
func (r *rig) connectVia(hc *http.Client, extra map[string]any, gate chan struct{}) *client {
	ws, _, err := websocket.Dial(context.Background(), "ws://gw:80/v1/ws", &websocket.DialOptions{HTTPClient: hc})
	if err != nil {
		r.t.Fatal(err)
	}
	c := &client{t: r.t, ws: ws, events: make(chan protocol.Event, 64), frames: make(chan protocol.Frame, 256),
		closed: make(chan websocket.StatusCode, 1), gate: gate}
	go func() {
		for {
			if c.gate != nil {
				<-c.gate
			}
			typ, b, err := ws.Read(context.Background())
			if err != nil {
				c.closed <- websocket.CloseStatus(err)
				return
			}
			if typ == websocket.MessageBinary {
				f, _ := protocol.DecodeFrame(b)
				c.frames <- f
			} else {
				e, _ := protocol.DecodeEvent(b)
				c.events <- e
			}
		}
	}()
	h := map[string]any{"version": 1, "mic": map[string]any{"rate": 16000, "frame_ms": 20}, "playout": map[string]any{"rate": 24000}}
	if _, ok := extra["token"]; !ok {
		h["token"] = r.tokenVia(hc)
	}
	for k, v := range extra {
		h[k] = v
	}
	c.send("hello", h)
	return c
}

func (c *client) send(typ string, fields map[string]any) {
	if err := c.ws.Write(context.Background(), websocket.MessageText, protocol.NewEvent(typ, fields)); err != nil {
		c.t.Fatal(err)
	}
}

func (c *client) mic(stream, seq uint32) {
	f := protocol.Frame{Kind: protocol.KindMic, StreamID: stream, Sequence: seq, CaptureUS: uint64(seq) * 20000, Payload: make([]int16, 320)}
	f.Payload[0] = int16(seq)
	if err := c.ws.Write(context.Background(), websocket.MessageBinary, f.Encode()); err != nil {
		c.t.Fatal(err)
	}
}

func (c *client) next(typ string) protocol.Event {
	c.t.Helper()
	timeout := time.After(time.Minute)
	for {
		select {
		case e := <-c.events:
			if e.Type() == typ {
				return e
			}
		case <-timeout:
			c.t.Fatalf("no %s event", typ)
		}
	}
}

func (c *client) closeStatus() websocket.StatusCode {
	c.t.Helper()
	select {
	case s := <-c.closed:
		return s
	case <-time.After(time.Minute):
		c.t.Fatal("connection not closed")
		return 0
	}
}

func (r *rig) upstream() *fakeorch.Conn {
	r.t.Helper()
	select {
	case oc := <-r.orch.Conns:
		return oc
	case <-time.After(time.Minute):
		r.t.Fatal("no upstream connection")
		return nil
	}
}

// seqs drains the upstream mic frames received so far.
func seqs(oc *fakeorch.Conn) []uint32 {
	synctest.Wait()
	var s []uint32
	for {
		select {
		case f := <-oc.Frames:
			s = append(s, f.Sequence)
		default:
			return s
		}
	}
}

func upEvents(oc *fakeorch.Conn) []string {
	synctest.Wait()
	var s []string
	for {
		select {
		case e := <-oc.Events:
			s = append(s, e.Type())
		default:
			return s
		}
	}
}

// unresolvable wraps a client so dials to host fail like a name that no longer resolves (not refused, not a timeout).
func unresolvable(c *http.Client, host string) *http.Client {
	base := c.Transport.(*http.Transport)
	t := base.Clone()
	t.DialContext = func(ctx context.Context, network, addr string) (net.Conn, error) {
		if addr == host {
			return nil, &net.DNSError{Err: "no such host", Name: host, IsNotFound: true}
		}
		return base.DialContext(ctx, network, addr)
	}
	return &http.Client{Transport: t}
}
