package fakeorch

import (
	"context"
	"net/http"
	"testing"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/internal/memnet"
	"github.com/coder/websocket"
)

func TestFakeorchReadyzAndKill(t *testing.T) {
	n := memnet.New()
	o := New()
	srv := &http.Server{Handler: o.Handler()}
	go func() { _ = srv.Serve(n.Listen("orch:1")) }()
	defer srv.Close()
	hc := n.HTTPClient()

	status := func() int {
		resp, err := hc.Get("http://orch:1/readyz")
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		return resp.StatusCode
	}
	if got := status(); got != 200 {
		t.Fatalf("readyz = %d, want 200", got)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	ws, _, err := websocket.Dial(ctx, "ws://orch:1/v1/session/s1", &websocket.DialOptions{HTTPClient: hc})
	if err != nil {
		t.Fatal(err)
	}
	c := <-o.Conns
	o.SetReady(503)
	if got := status(); got != 503 {
		t.Fatalf("readyz after SetReady(503) = %d, want 503", got)
	}
	if _, resp, err := websocket.Dial(ctx, "ws://orch:1/v1/session/s2", &websocket.DialOptions{HTTPClient: hc}); err == nil || resp == nil || resp.StatusCode != 503 {
		t.Fatalf("new session while not ready: want an HTTP 503 handshake refusal, got err=%v", err)
	}
	o.Kill()
	if _, _, err := ws.Read(ctx); err == nil {
		t.Fatal("client read after Kill: want an error")
	}
	select {
	case <-c.Closed:
	case <-ctx.Done():
		t.Fatal("conn not closed after Kill")
	}
}
