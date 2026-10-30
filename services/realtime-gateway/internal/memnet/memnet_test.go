package memnet

import (
	"context"
	"errors"
	"io"
	"net/http"
	"syscall"
	"testing"
)

func serveRemoteAddr(t *testing.T, n *Network, addr string) {
	t.Helper()
	l := n.Listen(addr)
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, r.RemoteAddr) })}
	go func() { _ = srv.Serve(l) }()
	t.Cleanup(func() { _ = srv.Close() })
}

func TestMemnetRemoteAddrIsTheDialerAddress(t *testing.T) {
	n := New()
	serveRemoteAddr(t, n, "srv:1")
	resp, err := n.HTTPClientFrom("198.51.100.7:5000").Get("http://srv:1/")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if string(body) != "198.51.100.7:5000" {
		t.Fatalf("RemoteAddr = %q, want 198.51.100.7:5000", body)
	}
}

func TestMemnetRefusalIsConnRefused(t *testing.T) {
	n := New()
	_, err := n.DialContext(context.Background(), "tcp", "nobody:1")
	if !errors.Is(err, syscall.ECONNREFUSED) {
		t.Fatalf("err = %v, want ECONNREFUSED", err)
	}
}

func TestListenerRefusesTheNextNDials(t *testing.T) {
	n := New()
	l := n.Listen("srv:2")
	defer l.Close()
	l.RefuseNext(2)
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			c.Close()
		}
	}()
	for i, want := range []bool{true, true, false} {
		_, err := n.DialContext(context.Background(), "tcp", "srv:2")
		if got := errors.Is(err, syscall.ECONNREFUSED); got != want {
			t.Fatalf("dial %d refused = %v, want %v (err %v)", i+1, got, want, err)
		}
	}
}
