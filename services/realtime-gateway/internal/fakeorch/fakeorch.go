// Package fakeorch is a scripted stand-in for the Python orchestrator, used by gateway tests
// and by cmd/fakeorch (echo mode) for the browser tracer bullet.
package fakeorch

import (
	"context"
	"net/http"
	"sync"
	"sync/atomic"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
)

// Conn is one upstream session as the orchestrator sees it.
type Conn struct {
	ID     string
	WS     *websocket.Conn
	Frames chan protocol.Frame
	Events chan protocol.Event
	Closed chan struct{}
}

type Orch struct {
	Echo  bool          // send every mic frame back as generation 1 audio, upsampled to 24 kHz
	Hold  chan struct{} // if set, wait for it to close before reading (simulates a stalled orchestrator)
	Conns chan *Conn    // each new session

	ready atomic.Int32 // GET /readyz status; 0 means 200
	mu    sync.Mutex
	live  map[*websocket.Conn]struct{}
}

func New() *Orch { return &Orch{Conns: make(chan *Conn, 16), live: map[*websocket.Conn]struct{}{}} }

func (o *Orch) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if code := int(o.ready.Load()); code != 0 {
			w.WriteHeader(code)
		}
	})
	mux.HandleFunc("GET /v1/session/{id}", func(w http.ResponseWriter, r *http.Request) {
		if code := int(o.ready.Load()); code >= 500 { // like the real orchestrator: no handshake while not ready
			w.WriteHeader(code)
			return
		}
		ws, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		ws.SetReadLimit(1 << 20)
		o.mu.Lock()
		o.live[ws] = struct{}{}
		o.mu.Unlock()
		defer func() {
			o.mu.Lock()
			delete(o.live, ws)
			o.mu.Unlock()
		}()
		c := &Conn{ID: r.PathValue("id"), WS: ws, Frames: make(chan protocol.Frame, 256), Events: make(chan protocol.Event, 64), Closed: make(chan struct{})}
		defer close(c.Closed)
		select {
		case o.Conns <- c:
		default:
		}
		if o.Hold != nil {
			<-o.Hold
		}
		ctx := context.Background()
		var seq uint32
		for {
			typ, b, err := ws.Read(ctx)
			if err != nil {
				return
			}
			if typ == websocket.MessageText {
				if e, err := protocol.DecodeEvent(b); err == nil {
					select {
					case c.Events <- e:
					default:
					}
				}
				continue
			}
			f, err := protocol.DecodeFrame(b)
			if err != nil {
				continue
			}
			select {
			case c.Frames <- f:
			default:
			}
			if o.Echo {
				if seq == 0 {
					_ = ws.Write(ctx, websocket.MessageText, protocol.NewEvent("agent.generation_started", map[string]any{"turn_id": "t1", "gen": 1}))
				}
				out := protocol.Frame{Kind: protocol.KindAgent, StreamID: 1, Sequence: seq, CaptureUS: f.CaptureUS, GenerationID: 1, Payload: Upsample(f.Payload)}
				seq++
				if ws.Write(ctx, websocket.MessageBinary, out.Encode()) != nil {
					return
				}
			}
		}
	})
	return mux
}

// Upsample converts 16 kHz to 24 kHz (3 outputs per 2 inputs) by linear interpolation.
func Upsample(in []int16) []int16 {
	out := make([]int16, 0, len(in)*3/2)
	for i := 0; i+1 < len(in); i += 2 {
		a, b := int32(in[i]), int32(in[i+1])
		var c int32
		if i+2 < len(in) {
			c = int32(in[i+2])
		} else {
			c = b
		}
		out = append(out, int16(a), int16((a+2*b)/3), int16((2*b+c)/3))
	}
	return out
}

// SetReady sets the status GET /readyz returns (default 200).
func (o *Orch) SetReady(code int) { o.ready.Store(int32(code)) }

// Kill closes every live session connection, as if the orchestrator process died.
func (o *Orch) Kill() {
	o.mu.Lock()
	defer o.mu.Unlock()
	for ws := range o.live {
		_ = ws.CloseNow()
	}
}
