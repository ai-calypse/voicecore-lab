// Command wsload paces N mic streams at 20 ms through the gateway (or straight to an echoing
// fakeorch with -direct) and reports echo round-trip time and receive inter-arrival percentiles.
// -delay/-jitter insert a userspace TCP proxy (simulated network, no packet loss).
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"math/rand/v2"
	"net"
	"net/http"
	"os"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/protocol"
	"github.com/coder/websocket"
)

var start = time.Now()

func mono() uint64 { return uint64(time.Since(start).Microseconds()) }

type result struct {
	Label        string             `json:"label"`
	Streams      int                `json:"streams"`
	Seconds      float64            `json:"seconds"`
	Sent         int                `json:"sent"`
	Received     int                `json:"received"`
	RTTms        map[string]float64 `json:"rtt_ms"`
	InterArrival map[string]float64 `json:"inter_arrival_ms"`
	Counters     map[string]int64   `json:"gateway_counters,omitempty"`
}

func main() {
	gw := flag.String("gateway", "127.0.0.1:8080", "gateway host:port")
	admin := flag.String("admin", "", "gateway admin host:port (its -admin-addr), to record /debug/counters")
	orch := flag.String("orch", "127.0.0.1:8765", "fakeorch host:port (used with -direct)")
	direct := flag.Bool("direct", false, "bypass the gateway: talk to fakeorch directly")
	n := flag.Int("n", 1, "parallel streams (sessions)")
	secs := flag.Duration("duration", 10*time.Second, "how long each stream sends")
	delay := flag.Duration("delay", 0, "proxy one-way delay")
	jitter := flag.Duration("jitter", 0, "proxy one-way jitter (uniform +-)")
	label := flag.String("label", "local", "result label")
	flag.Parse()

	target := *gw
	if *direct {
		target = *orch
	}
	if *delay > 0 || *jitter > 0 {
		target = proxy(target, *delay, *jitter)
	}
	var mu sync.Mutex
	var rtt, gaps []float64
	sent, recv := 0, 0
	var wg sync.WaitGroup
	for i := range *n {
		wg.Add(1)
		go func() {
			defer wg.Done()
			s, r, rt, ia, err := stream(target, *direct, i, *secs)
			if err != nil {
				log.Printf("stream %d: %v", i, err)
			}
			mu.Lock()
			sent, recv, rtt, gaps = sent+s, recv+r, append(rtt, rt...), append(gaps, ia...)
			mu.Unlock()
		}()
	}
	wg.Wait()
	res := result{Label: *label, Streams: *n, Seconds: secs.Seconds(), Sent: sent, Received: recv, RTTms: pct(rtt), InterArrival: pct(gaps)}
	if !*direct && *admin != "" {
		if resp, err := http.Get("http://" + *admin + "/debug/counters"); err == nil {
			_ = json.NewDecoder(resp.Body).Decode(&res.Counters)
			resp.Body.Close()
		}
	}
	_ = json.NewEncoder(os.Stdout).Encode(res)
}

func stream(addr string, direct bool, i int, d time.Duration) (sent, recv int, rtt, gaps []float64, err error) {
	ctx := context.Background()
	url := fmt.Sprintf("ws://%s/v1/session/load-%d", addr, i)
	if !direct {
		url = "ws://" + addr + "/v1/ws"
	}
	c, _, err := websocket.Dial(ctx, url, nil)
	if err != nil {
		return 0, 0, nil, nil, err
	}
	defer c.CloseNow()
	if !direct {
		resp, err := http.Post("http://"+addr+"/v1/session", "application/json", nil)
		if err != nil {
			return 0, 0, nil, nil, err
		}
		var tok struct{ Token string }
		_ = json.NewDecoder(resp.Body).Decode(&tok)
		resp.Body.Close()
		_ = c.Write(ctx, websocket.MessageText, protocol.NewEvent("hello", map[string]any{"version": 1, "token": tok.Token,
			"mic": map[string]any{"rate": 16000, "frame_ms": 20}, "playout": map[string]any{"rate": 24000}}))
		if _, _, err := c.Read(ctx); err != nil { // welcome
			return 0, 0, nil, nil, err
		}
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		var last uint64
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
			now := mono()
			recv++
			rtt = append(rtt, float64(now-f.CaptureUS)/1000)
			if last != 0 {
				gaps = append(gaps, float64(now-last)/1000)
			}
			last = now
		}
	}()
	tick := time.NewTicker(20 * time.Millisecond)
	end := time.After(d)
	payload := make([]int16, 320)
loop:
	for seq := uint32(0); ; seq++ {
		select {
		case <-tick.C:
			f := protocol.Frame{Kind: protocol.KindMic, StreamID: 1, Sequence: seq, CaptureUS: mono(), Payload: payload}
			if err := c.Write(ctx, websocket.MessageBinary, f.Encode()); err != nil {
				break loop
			}
			sent++
		case <-end:
			break loop
		}
	}
	time.Sleep(time.Second) // let the last echoes arrive
	if !direct {
		_ = c.Write(ctx, websocket.MessageText, protocol.NewEvent("mic.revoked", nil))
	}
	c.CloseNow()
	<-done
	return sent, recv, rtt, gaps, nil
}

func pct(x []float64) map[string]float64 {
	if len(x) == 0 {
		return nil
	}
	slices.Sort(x)
	at := func(p float64) float64 { return x[int(p*float64(len(x)-1))] }
	r := func(v float64) float64 { return float64(int(v*100+0.5)) / 100 }
	return map[string]float64{"n": float64(len(x)), "p50": r(at(0.5)), "p95": r(at(0.95)), "p99": r(at(0.99)), "max": r(x[len(x)-1])}
}

// proxy listens on a free local port and forwards to target, delaying every chunk in each direction
// by delay +- jitter while keeping byte order (TCP cannot reorder).
func proxy(target string, delay, jitter time.Duration) string {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		log.Fatal(err)
	}
	go func() {
		for {
			in, err := ln.Accept()
			if err != nil {
				return
			}
			out, err := net.Dial("tcp", target)
			if err != nil {
				in.Close()
				continue
			}
			go pipe(in, out, delay, jitter)
			go pipe(out, in, delay, jitter)
		}
	}()
	return ln.Addr().String()
}

func pipe(src, dst net.Conn, delay, jitter time.Duration) {
	type chunk struct {
		b  []byte
		at time.Time
	}
	q := make(chan chunk, 4096)
	go func() {
		defer dst.Close()
		for c := range q {
			time.Sleep(time.Until(c.at))
			if _, err := dst.Write(c.b); err != nil {
				return
			}
		}
	}()
	var last time.Time
	buf := make([]byte, 32<<10)
	for {
		n, err := src.Read(buf)
		if n > 0 {
			j := time.Duration(0)
			if jitter > 0 {
				j = time.Duration(rand.Int64N(int64(2*jitter))) - jitter
			}
			at := time.Now().Add(delay + j)
			if at.Before(last) {
				at = last
			}
			last = at
			q <- chunk{append([]byte(nil), buf[:n]...), at}
		}
		if err != nil {
			if err != io.EOF && !strings.Contains(err.Error(), "closed") {
				log.Print(err)
			}
			close(q)
			return
		}
	}
}
