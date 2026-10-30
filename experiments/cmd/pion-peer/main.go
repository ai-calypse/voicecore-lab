// Command pion-peer is the Step 07 WebRTC spike: a Go peer that receives the browser microphone as Opus RTP,
// logs the ICE/DTLS/connection steps, runs every packet through the rtp jitter buffer, and (for the WS vs
// WebRTC comparison) also accepts the SDK's WebSocket mic stream on /ws, timing both on one clock.
package main

import (
	"context"
	_ "embed"
	"encoding/json"
	"flag"
	"log/slog"
	"net/http"
	"sort"
	"sync"
	"time"

	"github.com/ai-calypse/voicecore-lab/experiments/rtp"
	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
	"github.com/pion/webrtc/v4"
)

//go:embed index.html
var page []byte

var start = time.Now()

type stream struct {
	Packets   int     `json:"packets"`
	Codec     string  `json:"codec,omitempty"`
	JitterMS  float64 `json:"jitter_ms"` // RFC 3550 estimate, converted from clock units
	clockRate float64
	jitter    rtp.Jitter
	arrivals  []time.Duration
	buffer    *rtp.Buffer
	Played    int `json:"played"`
	Late      int `json:"late"`
	Lost      int `json:"lost"`
	Duplicate int `json:"duplicate"`
}

type peer struct {
	mu    sync.Mutex
	steps []map[string]any
	rtp   *stream
	ws    *stream
	pc    *webrtc.PeerConnection // the current call; a new offer replaces and closes it
}

func (p *peer) step(s string, kv ...any) {
	p.mu.Lock()
	defer p.mu.Unlock()
	e := map[string]any{"t_ms": float64(time.Since(start).Microseconds()) / 1000, "step": s}
	for i := 0; i+1 < len(kv); i += 2 {
		e[kv[i].(string)] = kv[i+1]
	}
	p.steps = append(p.steps, e)
	slog.Info(s, kv...)
}

// receive records one packet: interarrival, RFC 3550 jitter (timestamp in clock units) and the jitter buffer.
func (p *peer) receive(s *stream, seq uint16, ts uint32) {
	p.mu.Lock()
	defer p.mu.Unlock()
	now := time.Since(start)
	s.Packets++
	s.arrivals = append(s.arrivals, now)
	s.jitter.Update(uint32(now.Seconds()*s.clockRate), ts)
	s.JitterMS = s.jitter.J / s.clockRate * 1000
	s.buffer.Push(rtp.Packet{Seq: seq, Timestamp: ts}, start.Add(now))
	s.buffer.Pop(start.Add(now))
	s.Played, s.Late, s.Lost, s.Duplicate = s.buffer.Played, s.buffer.Late, s.buffer.Lost, s.buffer.Duplicate
}

func (p *peer) offer(w http.ResponseWriter, r *http.Request) {
	var offer webrtc.SessionDescription
	if err := json.NewDecoder(r.Body).Decode(&offer); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	pc, err := webrtc.NewPeerConnection(webrtc.Configuration{}) // loopback only: no STUN/TURN
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	ok := false
	defer func() {
		if !ok {
			_ = pc.Close()
		}
	}()
	pc.OnICEConnectionStateChange(func(s webrtc.ICEConnectionState) { p.step("ice " + s.String()) })
	pc.OnConnectionStateChange(func(s webrtc.PeerConnectionState) { p.step("connection " + s.String()) })
	pc.OnTrack(func(tr *webrtc.TrackRemote, rec *webrtc.RTPReceiver) {
		p.step("track", "codec", tr.Codec().MimeType, "clock_rate", tr.Codec().ClockRate, "ssrc", uint32(tr.SSRC()))
		p.mu.Lock()
		p.rtp = &stream{Codec: tr.Codec().MimeType, clockRate: float64(tr.Codec().ClockRate), buffer: rtp.NewBuffer(60*time.Millisecond, 20*time.Millisecond)}
		s := p.rtp
		p.mu.Unlock()
		for {
			pkt, _, err := tr.ReadRTP()
			if err != nil {
				return
			}
			p.receive(s, pkt.SequenceNumber, pkt.Timestamp)
		}
	})
	if err := pc.SetRemoteDescription(offer); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	p.step("offer applied")
	for _, t := range pc.GetTransceivers() { // the receiver's DTLS transport exists now; the handshake comes later
		if r := t.Receiver(); r != nil {
			r.Transport().OnStateChange(func(s webrtc.DTLSTransportState) { p.step("dtls " + s.String()) })
			break
		}
	}
	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	gathered := webrtc.GatheringCompletePromise(pc)
	if err := pc.SetLocalDescription(answer); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	<-gathered // one signalling round trip: no trickle ICE
	ok = true
	p.mu.Lock()
	old := p.pc
	p.pc = pc
	p.mu.Unlock()
	if old != nil {
		_ = old.Close() // its track reader ends with it
	}
	p.step("answer sent")
	_ = json.NewEncoder(w).Encode(pc.LocalDescription())
}

// ws accepts the SDK client's hello and mic frames (same wire protocol as the gateway) and times them.
func (p *peer) wsHandler(w http.ResponseWriter, r *http.Request) {
	c, err := websocket.Accept(w, r, &websocket.AcceptOptions{OriginPatterns: []string{"127.0.0.1:*", "localhost:*"}})
	if err != nil {
		return
	}
	defer c.CloseNow()
	ctx := context.Background()
	if _, _, err := c.Read(ctx); err != nil { // hello
		return
	}
	_ = c.Write(ctx, websocket.MessageText, protocol.NewEvent("welcome", map[string]any{"session_id": "s-compare", "resume_window_ms": 0, "resumed": false}))
	p.mu.Lock()
	p.ws = &stream{Codec: "pcm16/16000 over WebSocket", clockRate: 16000, buffer: rtp.NewBuffer(60*time.Millisecond, 20*time.Millisecond)}
	s := p.ws
	p.mu.Unlock()
	p.step("ws mic stream open")
	for {
		typ, b, err := c.Read(ctx)
		if err != nil {
			return
		}
		if typ != websocket.MessageBinary {
			continue
		}
		f, err := protocol.DecodeFrame(b)
		if err != nil {
			continue
		}
		p.receive(s, uint16(f.Sequence), uint32(f.CaptureUS*16/1000)) // capture time in 16 kHz units, like an RTP timestamp
	}
}

func interarrival(a []time.Duration) map[string]float64 {
	if len(a) < 2 {
		return nil
	}
	d := make([]float64, 0, len(a)-1)
	for i := 1; i < len(a); i++ {
		d = append(d, float64((a[i]-a[i-1]).Microseconds())/1000)
	}
	sort.Float64s(d)
	at := func(q float64) float64 { return d[int(q*float64(len(d)-1))] }
	return map[string]float64{"n": float64(len(d)), "p50": at(0.5), "p95": at(0.95), "p99": at(0.99), "max": d[len(d)-1]}
}

func (p *peer) stats(w http.ResponseWriter, _ *http.Request) {
	p.mu.Lock()
	defer p.mu.Unlock()
	out := map[string]any{"steps": p.steps}
	for name, s := range map[string]*stream{"webrtc": p.rtp, "websocket": p.ws} {
		if s != nil {
			out[name] = map[string]any{"stream": s, "interarrival_ms": interarrival(s.arrivals)}
		}
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(out)
}

func main() {
	addr := flag.String("addr", "127.0.0.1:8090", "listen address")
	flag.Parse()
	p := &peer{}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write(page)
	})
	mux.HandleFunc("POST /offer", p.offer)
	mux.HandleFunc("GET /stats", p.stats)
	mux.HandleFunc("GET /ws", p.wsHandler)
	slog.Info("pion-peer listening", "addr", *addr)
	slog.Error("stopped", "err", http.ListenAndServe(*addr, mux))
}
