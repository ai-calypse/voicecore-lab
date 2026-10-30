package session

import (
	"context"
	"reflect"
	"testing"
	"testing/synctest"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
)

// S01-T02: transport.

func TestHelloWithValidTokenGetsWelcome(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		w := r.connect(nil, nil).next("welcome")
		var id string
		var window int
		var resumed bool
		_ = w.Get("session_id", &id)
		_ = w.Get("resume_window_ms", &window)
		_ = w.Get("resumed", &resumed)
		if id == "" || window != 10000 || resumed {
			t.Fatalf("welcome %v", w)
		}
		if oc := r.upstream(); oc.ID != id {
			t.Fatalf("upstream session %s, want %s", oc.ID, id)
		}
	})
}

func TestInvalidHeaderClosesWith1007(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		bad := (protocol.Frame{Kind: protocol.KindMic, Payload: []int16{1}}).Encode()
		bad[0] = 2
		_ = c.ws.Write(context.Background(), websocket.MessageBinary, bad)
		if s := c.closeStatus(); s != 1007 {
			t.Fatalf("close %d", s)
		}
	})
}

func TestTruncatedFrameClosesWith1007(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		_ = c.ws.Write(context.Background(), websocket.MessageBinary, (protocol.Frame{Kind: protocol.KindMic, Payload: []int16{1, 2}}).Encode()[:30])
		if s := c.closeStatus(); s != 1007 {
			t.Fatalf("close %d", s)
		}
	})
}

func TestMicFrameNot20msClosesWith1007(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		_ = c.ws.Write(context.Background(), websocket.MessageBinary, (protocol.Frame{Kind: protocol.KindMic, Payload: make([]int16, 16000)}).Encode())
		if s := c.closeStatus(); s != 1007 {
			t.Fatalf("close %d", s)
		}
	})
}

func TestFirstMessageNotHelloClosesWith1008(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		ws, _, _ := websocket.Dial(context.Background(), "ws://gw:80/v1/ws", &websocket.DialOptions{HTTPClient: r.http})
		_ = ws.Write(context.Background(), websocket.MessageText, protocol.NewEvent("ping", map[string]any{"t_client_us": 1}))
		_, _, err := ws.Read(context.Background())
		if s := websocket.CloseStatus(err); s != 1008 {
			t.Fatalf("close %d", s)
		}
	})
}

func TestDuplicateSequenceDroppedAndCounted(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		oc := r.upstream()
		for _, s := range []uint32{0, 1, 1, 2} {
			c.mic(1, s)
		}
		if got := seqs(oc); !reflect.DeepEqual(got, []uint32{0, 1, 2}) {
			t.Fatalf("upstream got %v", got)
		}
		if n := r.gw.c.DropsDuplicate.Load(); n != 1 {
			t.Fatalf("drops_duplicate %d", n)
		}
	})
}

func TestOlderSequenceDroppedAsStale(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		oc := r.upstream()
		for _, s := range []uint32{0, 1, 2, 1} {
			c.mic(1, s)
		}
		if got := seqs(oc); !reflect.DeepEqual(got, []uint32{0, 1, 2}) {
			t.Fatalf("upstream got %v", got)
		}
		if n := r.gw.c.DropsStale.Load(); n != 1 {
			t.Fatalf("drops_stale %d", n)
		}
	})
}

func TestForwardsMicFramesInOrderToUpstream(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		oc := r.upstream()
		for s := range uint32(10) {
			c.mic(1, s)
		}
		synctest.Wait()
		for want := range uint32(10) {
			f := <-oc.Frames
			if f.Sequence != want || f.Payload[0] != int16(want) || len(f.Payload) != 320 || f.CaptureUS != uint64(want)*20000 {
				t.Fatalf("frame %d: %+v", want, f.Sequence)
			}
		}
	})
}

func TestMissedHeartbeatClosesAfter10s(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		for range 10 { // pings every 2 s keep it open for 20 s
			time.Sleep(2 * time.Second)
			c.send("ping", map[string]any{"t_client_us": 1})
			c.next("pong")
		}
		last := time.Now()
		if s := c.closeStatus(); s != 4003 {
			t.Fatalf("close %d", s)
		}
		if d := time.Since(last); d != 10*time.Second {
			t.Fatalf("closed after %v", d)
		}
	})
}

func TestPongEchoesClientTime(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		time.Sleep(3 * time.Second)
		c.send("ping", map[string]any{"t_client_us": 1234})
		p := c.next("pong")
		var tc, ts int64
		_ = p.Get("t_client_us", &tc)
		_ = p.Get("t_server_us", &ts)
		if tc != 1234 || ts != 3_000_000 {
			t.Fatalf("pong %v", p)
		}
	})
}

func TestCleanCloseReleasesSession(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		oc := r.upstream()
		_ = c.ws.Close(websocket.StatusNormalClosure, "bye")
		<-oc.Closed
		synctest.Wait()
		if n := r.counters()["sessions"]; n != 0 {
			t.Fatalf("sessions %d", n)
		}
	})
}

// S01-T03: backpressure and counters.

func TestFullUpstreamQueueDropsOldestAndCounts(t *testing.T) {
	run(t, true, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		oc := r.upstream()
		c.mic(1, 0)
		synctest.Wait() // frame 0 is now stuck in the upstream write
		for s := uint32(1); s < 100; s++ {
			c.mic(1, s)
		}
		synctest.Wait()
		if m := r.counters(); m["drops_overload"] != 49 || m["depth"] != 50 {
			t.Fatalf("counters %v", m)
		}
		close(r.orch.Hold)
		want := []uint32{0}
		for s := uint32(50); s < 100; s++ {
			want = append(want, s)
		}
		if got := seqs(oc); !reflect.DeepEqual(got, want) {
			t.Fatalf("upstream got %v", got)
		}
	})
}

func TestQueueDepthAndCountersExposed(t *testing.T) {
	run(t, true, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		c.next("welcome")
		c.mic(1, 0)
		synctest.Wait()
		for _, s := range []uint32{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 13} {
			c.mic(1, s)
		}
		synctest.Wait()
		want := map[string]int64{"sessions": 1, "depth": 11, "depth_out": 0, "drops_duplicate": 1, "drops_stale": 0,
			"drops_overload": 0, "drops_overload_out": 0, "drops_ratelimit": 0, "drops_fenced": 0, "gaps": 2}
		if got := r.counters(); !reflect.DeepEqual(got, want) {
			t.Fatalf("counters %v", got)
		}
	})
}

func TestSequenceGapAfterResumeIsCounted(t *testing.T) {
	run(t, false, func(t *testing.T, r *rig) {
		c := r.connect(nil, nil)
		var id string
		_ = c.next("welcome").Get("session_id", &id)
		oc := r.upstream()
		for s := range uint32(5) {
			c.mic(1, s)
		}
		synctest.Wait()
		_ = c.ws.CloseNow() // network loss: no close frame
		time.Sleep(2 * time.Second)
		c2 := r.connect(map[string]any{"session_id": id}, nil)
		c2.next("welcome")
		c2.mic(1, 8)
		if got := seqs(oc); !reflect.DeepEqual(got, []uint32{0, 1, 2, 3, 4, 8}) {
			t.Fatalf("upstream got %v", got)
		}
		if n := r.counters()["gaps"]; n != 3 {
			t.Fatalf("gaps %d", n)
		}
	})
}
