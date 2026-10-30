package session

import (
	"bytes"
	"context"
	"encoding/json"
	"reflect"
	"testing"
	"testing/synctest"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
)

// S01-T04: reconnect and lifecycle.

func TestExpiredTokenClosesWith4001(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		tok := r.token()
		time.Sleep(61 * time.Second)
		for name, token := range map[string]string{"expired": tok, "forged": "9999999999.00ff"} {
			c := r.connect(map[string]any{"token": token}, nil)
			if s := c.closeStatus(); s != 4001 {
				t.Fatalf("%s token: close %d", name, s)
			}
		}
	})
}

func TestUnsupportedFormatClosesWith4002(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(map[string]any{"mic": map[string]any{"rate": 48000, "frame_ms": 20}}, nil)
		if s := c.closeStatus(); s != 4002 {
			t.Fatalf("close %d", s)
		}
	})
}

func TestResumeWithin10sKeepsSessionAndTellsUpstreamClientResumed(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		var id, id2 string
		_ = c.next("welcome").Get("session_id", &id)
		oc := r.upstream()
		_ = c.ws.CloseNow()
		time.Sleep(9 * time.Second)
		w := r.connect(map[string]any{"session_id": id}, nil).next("welcome")
		var resumed bool
		_ = w.Get("session_id", &id2)
		_ = w.Get("resumed", &resumed)
		if id2 != id || !resumed {
			t.Fatalf("welcome %v", w)
		}
		if got := upEvents(oc); !reflect.DeepEqual(got, []string{"client.resumed"}) {
			t.Fatalf("upstream events %v", got)
		}
		select {
		case <-r.orch.Conns:
			t.Fatal("resume opened a second upstream connection")
		default:
		}
	})
}

func TestResumeDropsAudioQueuedWhileAway(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		var id string
		_ = c.next("welcome").Get("session_id", &id)
		oc := r.upstream()
		_ = c.ws.CloseNow()
		synctest.Wait()
		for s := range uint32(3) { // gen 3 keeps streaming while the client is away
			_ = oc.WS.Write(context.Background(), websocket.MessageBinary,
				(protocol.Frame{Kind: protocol.KindAgent, StreamID: 3, Sequence: s, GenerationID: 3, Payload: make([]int16, 480)}).Encode())
		}
		synctest.Wait()
		c2 := r.connect(map[string]any{"session_id": id}, nil)
		c2.next("welcome")
		_ = oc.WS.Write(context.Background(), websocket.MessageBinary,
			(protocol.Frame{Kind: protocol.KindAgent, StreamID: 4, GenerationID: 4, Payload: make([]int16, 480)}).Encode())
		synctest.Wait()
		if len(c2.frames) != 1 || (<-c2.frames).GenerationID != 4 {
			t.Fatal("resumed client got audio queued for the old generation")
		}
		if n := r.counters()["drops_fenced"]; n != 3 {
			t.Fatalf("drops_fenced %d", n)
		}
	})
}

func TestResumeAfter10sStartsNewSession(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		var id, id2 string
		_ = c.next("welcome").Get("session_id", &id)
		oc := r.upstream()
		_ = c.ws.CloseNow()
		time.Sleep(11 * time.Second)
		<-oc.Closed
		w := r.connect(map[string]any{"session_id": id}, nil).next("welcome")
		var resumed bool
		_ = w.Get("session_id", &id2)
		_ = w.Get("resumed", &resumed)
		if id2 == id || resumed {
			t.Fatalf("welcome %v", w)
		}
		if r.upstream().ID != id2 {
			t.Fatal("new session has no upstream")
		}
	})
}

func TestMicRevokedEndsMicStreamButKeepsSession(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		oc := r.upstream()
		c.mic(1, 0)
		c.mic(1, 1)
		c.send("mic.revoked", nil)
		c.mic(1, 2) // late frame of the revoked stream
		c.send("text.input", map[string]any{"text": "how do I install uv"})
		c.mic(2, 0) // a new mic stream after consent again
		if got := seqs(oc); !reflect.DeepEqual(got, []uint32{0, 1, 0}) {
			t.Fatalf("upstream frames %v", got)
		}
		if got := upEvents(oc); !reflect.DeepEqual(got, []string{"mic.revoked", "text.input"}) {
			t.Fatalf("upstream events %v", got)
		}
		c.send("ping", map[string]any{"t_client_us": 1})
		c.next("pong")
	})
}

func TestAgentFramesAtOrBelowFenceAreNotSent(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		gate := make(chan struct{})
		c := r.connect(nil, gate)
		oc := r.upstream()
		agent := func(gen, seq uint32) {
			f := protocol.Frame{Kind: protocol.KindAgent, StreamID: gen, Sequence: seq, GenerationID: gen, Payload: make([]int16, 480)}
			_ = oc.WS.Write(context.Background(), websocket.MessageBinary, f.Encode())
		}
		synctest.Wait() // welcome is stuck in the write to the paused client
		for s := range uint32(4) {
			agent(1, s)
		}
		_ = oc.WS.Write(context.Background(), websocket.MessageText, protocol.NewEvent("agent.cancel", map[string]any{"gen": 1}))
		agent(2, 0)
		agent(1, 4) // late frame of the cancelled generation
		synctest.Wait()
		close(gate)
		c.next("agent.cancel")
		synctest.Wait()
		var got [][2]uint32
		for len(c.frames) > 0 {
			f := <-c.frames
			got = append(got, [2]uint32{f.GenerationID, f.Sequence})
		}
		if !reflect.DeepEqual(got, [][2]uint32{{2, 0}}) {
			t.Fatalf("client got frames %v", got)
		}
		if n := r.counters()["drops_fenced"]; n != 5 {
			t.Fatalf("drops_fenced %d", n)
		}
	})
}

// Leaks are caught twice: synctest panics if any bubble goroutine is still blocked at the end,
// and goleak (TestMain) checks the whole process.
func TestNoGoroutinesLeftAfterStopExpireOrResume(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		stop := r.connect(nil, nil)
		stop.next("welcome")
		_ = stop.ws.Close(websocket.StatusNormalClosure, "")

		expire := r.connect(nil, nil)
		expire.next("welcome")
		_ = expire.ws.CloseNow()
		time.Sleep(11 * time.Second)

		resume := r.connect(nil, nil)
		var id string
		_ = resume.next("welcome").Get("session_id", &id)
		_ = resume.ws.CloseNow()
		again := r.connect(map[string]any{"session_id": id}, nil)
		again.next("welcome")
		_ = again.ws.Close(websocket.StatusNormalClosure, "")
		synctest.Wait()
		if n := r.counters()["sessions"]; n != 0 {
			t.Fatalf("sessions %d", n)
		}
	})
}

func TestTraceEventsFollowTheSpecSchema(t *testing.T) {
	var buf bytes.Buffer
	run(t, false, func(t *testing.T, r *rig) {
		r.gw.cfg.Trace = &buf
		c := r.connect(nil, nil)
		c.next("welcome")
		oc := r.upstream()
		f := protocol.Frame{Kind: protocol.KindAgent, StreamID: 1, GenerationID: 1, Payload: make([]int16, 480)}
		_ = oc.WS.Write(context.Background(), websocket.MessageBinary, f.Encode())
		_ = oc.WS.Write(context.Background(), websocket.MessageText, protocol.NewEvent("agent.cancel", map[string]any{"gen": 1}))
		c.next("agent.cancel")
		_ = c.ws.Close(websocket.StatusNormalClosure, "")
		<-oc.Closed
		synctest.Wait()
	})
	var events []string
	for _, line := range bytes.Split(bytes.TrimSpace(buf.Bytes()), []byte("\n")) {
		var e map[string]any
		if err := json.Unmarshal(line, &e); err != nil {
			t.Fatal(err)
		}
		for _, k := range []string{"trace_id", "span", "event", "t_mono_us", "process", "attrs"} {
			if _, ok := e[k]; !ok {
				t.Fatalf("event %s has no %s", line, k)
			}
		}
		events = append(events, e["event"].(string))
	}
	want := []string{"session_started", "client_attached", "agent_first_frame", "fence", "client_detached", "session_ended"}
	if !reflect.DeepEqual(events, want) {
		t.Fatalf("events %v", events)
	}
}
