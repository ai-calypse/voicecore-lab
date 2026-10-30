package session

import (
	"context"
	"sync"
	"sync/atomic"
	"time"
	"unicode/utf8"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
)

// Events a client may send after hello (SPEC.md section 2). Anything else closes the socket with 1008.
var clientEvents = map[string]bool{"ping": true, "text.input": true, "mic.revoked": true, "client.paused": true,
	"client.resumed_playout": true, "playout.started": true, "playout.stopped": true, "cancel.ack": true}

// session outlives client connections: the upstream (orchestrator) connection stays open
// for the resume window after the client drops.
type session struct {
	id        string
	resumeKey string // 32 random bytes, hex; given only to the client in welcome, required to resume
	ip        string
	ageTimer  *time.Timer
	srv       *Server
	up        *websocket.Conn
	upq, outq *queue
	upCtx     context.Context
	cancelUp  context.CancelFunc

	mu          sync.Mutex
	client      *websocket.Conn // nil while detached
	claimed     bool            // a connection owns or is attaching to this session
	ended       bool
	fence       uint32
	lastGen     uint32            // newest agent generation seen from upstream
	lastSeq     map[uint32]uint32 // per mic stream
	revoked     map[uint32]bool
	resumeTimer *time.Timer
}

// claim reserves a detached session for a resuming connection.
func (ss *session) claim() bool {
	ss.mu.Lock()
	defer ss.mu.Unlock()
	if ss.ended || ss.claimed {
		return false
	}
	ss.claimed = true
	if ss.resumeTimer != nil {
		ss.resumeTimer.Stop()
		ss.resumeTimer = nil
	}
	return true
}

// attach runs one client connection until it ends, then either ends the session or starts the resume window.
func (ss *session) attach(c *websocket.Conn, resumed bool) {
	ss.mu.Lock()
	if ss.ended {
		ss.mu.Unlock()
		_ = c.Close(websocket.StatusNormalClosure, "session ended")
		return
	}
	ss.client = c
	ss.mu.Unlock()
	ss.srv.trace(ss.id, "client_attached", 0, map[string]any{"resumed": resumed})

	if resumed {
		// The orchestrator will cancel the live generation; fence it here too so audio queued while the
		// client was away is not played. This happens before welcome: once the client has welcome, a new
		// generation may already be on its way and must not be caught by this fence (found as a test flake).
		ss.mu.Lock()
		ss.fence = max(ss.fence, ss.lastGen)
		fence := ss.fence
		ss.mu.Unlock()
		ss.srv.c.DropsFenced.Add(int64(ss.outq.purge(fence)))
		ss.upq.push(item{data: protocol.NewEvent("client.resumed", nil)})
	}
	welcome := protocol.NewEvent("welcome", map[string]any{"session_id": ss.id, "resume_key": ss.resumeKey,
		"resume_window_ms": ss.srv.cfg.ResumeWindow.Milliseconds(), "resumed": resumed})
	end := false
	if c.Write(context.Background(), websocket.MessageText, welcome) == nil {
		ctx, stop := context.WithCancel(context.Background())
		writerDone := make(chan struct{})
		go func() { defer close(writerDone); ss.writeClient(ctx, c) }()
		end = ss.readClient(c)
		stop()
		<-writerDone
	}

	ss.srv.trace(ss.id, "client_detached", 0, map[string]any{"ends_session": end})
	ss.mu.Lock()
	ss.client, ss.claimed = nil, false
	if !end && !ss.ended {
		ss.resumeTimer = time.AfterFunc(ss.srv.cfg.ResumeWindow, func() { ss.end("expired") })
	}
	ss.mu.Unlock()
	if end {
		ss.end("client")
	}
}

// readClient returns true when the session should end (normal close or protocol violation)
// and false when the client just disappeared (resumable).
func (ss *session) readClient(c *websocket.Conn) bool {
	hb := ss.srv.cfg.Heartbeat
	watchdog := time.AfterFunc(hb, func() { _ = c.Close(statusHeartbeat, "heartbeat missed") })
	defer watchdog.Stop()
	var micRate, textRate bucket // per connection: audio at real-time pace (2 s burst), typed questions 1/s (burst 5)
	for {
		typ, b, err := c.Read(context.Background())
		if err != nil {
			st := websocket.CloseStatus(err)
			return st == websocket.StatusNormalClosure || st == websocket.StatusGoingAway
		}
		watchdog.Reset(hb)
		if typ == websocket.MessageBinary {
			f, err := protocol.DecodeFrame(b)
			if err != nil || f.Kind != protocol.KindMic || len(f.Payload) != 320 || f.GenerationID != 0 {
				_ = c.Close(statusInvalidFrame, "invalid frame")
				return true
			}
			if !micRate.take(time.Now(), 50, 100) { // faster than real time: the VAD and STT behind us pay for it
				ss.srv.c.DropsRateLimit.Add(1)
				continue
			}
			if ss.acceptMic(f) {
				ss.upq.push(item{data: b, binary: true, audio: true})
			}
			continue
		}
		e, err := protocol.DecodeEvent(b)
		if err != nil || !clientEvents[e.Type()] {
			_ = c.Close(statusPolicy, "invalid event")
			return true
		}
		switch e.Type() {
		case "ping":
			var t int64
			_ = e.Get("t_client_us", &t)
			ss.outq.pushFront(item{data: protocol.NewEvent("pong", map[string]any{"t_client_us": t, "t_server_us": ss.srv.monoUS()})})
			continue
		case "mic.revoked":
			ss.mu.Lock()
			for id := range ss.lastSeq {
				ss.revoked[id] = true
			}
			ss.mu.Unlock()
		case "text.input":
			// The text goes into an LLM prompt and its history: a string of bounded length, nothing else
			// (security review: a list of content parts could make provider calls cost far more than the guard counts).
			var text string
			if e.Get("text", &text) != nil || (ss.srv.cfg.TextMaxChars > 0 && utf8.RuneCountInString(text) > ss.srv.cfg.TextMaxChars) {
				_ = c.Close(statusPolicy, "text.input text must be a short string")
				return true
			}
			if !textRate.take(time.Now(), 1, 5) {
				ss.srv.c.DropsRateLimit.Add(1)
				continue
			}
		}
		if !ss.upq.push(item{data: b}) {
			_ = c.Close(statusPolicy, "too many queued events")
			return true
		}
	}
}

// acceptMic applies the per-stream sequence rules: duplicate and older frames are dropped, gaps are counted.
func (ss *session) acceptMic(f protocol.Frame) bool {
	ss.mu.Lock()
	defer ss.mu.Unlock()
	c := &ss.srv.c
	if ss.revoked[f.StreamID] {
		c.DropsStale.Add(1)
		return false
	}
	last, seen := ss.lastSeq[f.StreamID]
	switch {
	case seen && f.Sequence == last:
		c.DropsDuplicate.Add(1)
		return false
	case seen && f.Sequence < last: // ponytail: no u32 wrap handling; wraps after 2.7 years of 20 ms frames
		c.DropsStale.Add(1)
		return false
	case seen && f.Sequence > last+1:
		c.Gaps.Add(int64(f.Sequence - last - 1))
	case !seen && f.Sequence > 0:
		c.Gaps.Add(int64(f.Sequence))
	}
	ss.lastSeq[f.StreamID] = f.Sequence
	return true
}

func (ss *session) writeClient(ctx context.Context, c *websocket.Conn) {
	for {
		it, ok := ss.outq.pop(ctx)
		if !ok {
			return
		}
		if it.close {
			_ = c.Close(websocket.StatusNormalClosure, "session ended")
			return
		}
		wctx, cancel := context.WithTimeout(ctx, 10*time.Second)
		err := c.Write(wctx, it.typ(), it.data)
		cancel()
		if err != nil {
			ss.outq.pushFront(it) // keep it for a resumed connection
			return
		}
	}
}

func (ss *session) writeUpstream() {
	for {
		it, ok := ss.upq.pop(ss.upCtx)
		if !ok {
			return
		}
		if ss.up.Write(ss.upCtx, it.typ(), it.data) != nil {
			ss.end("error")
			return
		}
	}
}

// readUpstream forwards orchestrator output to the client and applies the generation fence.
func (ss *session) readUpstream() {
	for {
		typ, b, err := ss.up.Read(context.Background())
		if err != nil {
			ss.end("error")
			return
		}
		if typ == websocket.MessageBinary {
			f, err := protocol.DecodeFrame(b)
			if err != nil || f.Kind != protocol.KindAgent {
				continue
			}
			ss.mu.Lock()
			fenced := f.GenerationID <= ss.fence
			first := f.GenerationID > ss.lastGen
			ss.lastGen = max(ss.lastGen, f.GenerationID)
			ss.mu.Unlock()
			if first && !fenced {
				ss.srv.trace(ss.id, "agent_first_frame", f.GenerationID, nil)
			}
			if fenced {
				ss.srv.c.DropsFenced.Add(1)
				continue
			}
			ss.outq.push(item{data: b, binary: true, audio: true, gen: f.GenerationID})
			continue
		}
		e, err := protocol.DecodeEvent(b)
		if err != nil {
			continue
		}
		if e.Type() == "agent.cancel" {
			var g uint32
			_ = e.Get("gen", &g)
			ss.mu.Lock()
			ss.fence = max(ss.fence, g)
			ss.mu.Unlock()
			n := ss.outq.purge(g)
			ss.srv.c.DropsFenced.Add(int64(n))
			ss.srv.trace(ss.id, "fence", g, map[string]any{"dropped_queued": n})
		}
		ss.outq.push(item{data: b})
		if e.Type() == "session.ended" { // the orchestrator ended it (e.g. budget): that is the reason, said once
			var reason string
			_ = e.Get("reason", &reason)
			if reason == "" {
				reason = "ended"
			}
			if len(reason) > 100 { // a WebSocket close reason must fit 123 bytes
				reason = reason[:100]
			}
			ss.finish(reason, false)
			return
		}
	}
}

// end is idempotent: it tells an attached client why, closes the upstream and stops the session goroutines.
func (ss *session) end(reason string) { ss.finish(reason, true) }

// finish ends the session; tell is false when the client already got session.ended from the orchestrator.
func (ss *session) finish(reason string, tell bool) {
	ss.mu.Lock()
	if ss.ended {
		ss.mu.Unlock()
		return
	}
	ss.ended = true
	c := ss.client
	if ss.resumeTimer != nil {
		ss.resumeTimer.Stop()
	}
	ss.mu.Unlock()
	if ss.ageTimer != nil {
		ss.ageTimer.Stop()
	}
	ss.srv.mu.Lock()
	ss.srv.releaseIP(ss.ip)
	delete(ss.srv.sessions, ss.id)
	ss.srv.mu.Unlock()
	ss.srv.trace(ss.id, "session_ended", 0, map[string]any{"reason": reason})
	if c != nil {
		if tell {
			ss.outq.push(item{data: protocol.NewEvent("session.ended", map[string]any{"reason": reason})})
		}
		ss.outq.push(item{close: true})
	}
	_ = ss.up.Close(websocket.StatusNormalClosure, reason)
	ss.cancelUp()
}

type item struct {
	data   []byte
	binary bool
	audio  bool   // droppable when the queue is full; fenced by generation
	gen    uint32 // agent audio only
	close  bool   // writer closes the connection
}

func (it item) typ() websocket.MessageType {
	if it.binary {
		return websocket.MessageBinary
	}
	return websocket.MessageText
}

// queue holds events (never dropped; at most maxEvents) and audio (at most cap; the oldest is dropped beyond it).
type queue struct {
	mu        sync.Mutex
	items     []item
	audio     int
	cap       int
	maxEvents int // 0 = unlimited
	drops     *atomic.Int64
	ready     chan struct{}
}

func newQueue(cap int, drops *atomic.Int64, maxEvents int) *queue {
	return &queue{cap: cap, drops: drops, maxEvents: maxEvents, ready: make(chan struct{}, 1)}
}

// push returns false (and queues nothing) when an event would exceed maxEvents.
func (q *queue) push(it item) bool {
	q.mu.Lock()
	if !it.audio && q.maxEvents > 0 && len(q.items)-q.audio >= q.maxEvents {
		q.mu.Unlock()
		return false
	}
	if it.audio && q.audio >= q.cap {
		for i := range q.items {
			if q.items[i].audio {
				q.items = append(q.items[:i], q.items[i+1:]...)
				q.audio--
				q.drops.Add(1)
				break
			}
		}
	}
	q.items = append(q.items, it)
	if it.audio {
		q.audio++
	}
	q.mu.Unlock()
	q.signal()
	return true
}

func (q *queue) pushFront(it item) {
	q.mu.Lock()
	q.items = append([]item{it}, q.items...)
	q.mu.Unlock()
	q.signal()
}

func (q *queue) signal() {
	select {
	case q.ready <- struct{}{}:
	default:
	}
}

func (q *queue) pop(ctx context.Context) (item, bool) {
	for {
		q.mu.Lock()
		if len(q.items) > 0 {
			it := q.items[0]
			q.items = q.items[1:]
			if it.audio {
				q.audio--
			}
			q.mu.Unlock()
			return it, true
		}
		q.mu.Unlock()
		select {
		case <-q.ready:
		case <-ctx.Done():
			return item{}, false
		}
	}
}

// purge drops queued agent audio of generation <= fence and returns how many.
func (q *queue) purge(fence uint32) int {
	q.mu.Lock()
	defer q.mu.Unlock()
	kept := q.items[:0]
	n := 0
	for _, it := range q.items {
		if it.audio && it.gen <= fence {
			n++
			continue
		}
		kept = append(kept, it)
	}
	q.items, q.audio = kept, q.audio-n
	return n
}

func (q *queue) depth() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	return q.audio
}
