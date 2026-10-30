// Package memnet is an in-memory network of net.Pipe connections, so HTTP and WebSocket
// tests can run inside a testing/synctest bubble (real sockets would block fake time).
package memnet

import (
	"context"
	"net"
	"net/http"
	"sync"
	"syscall"
)

type Network struct {
	mu        sync.Mutex
	listeners map[string]*Listener
}

func New() *Network { return &Network{listeners: map[string]*Listener{}} }

// Listen registers addr ("host:port"); dials to it are handed to Accept.
func (n *Network) Listen(addr string) *Listener {
	l := &Listener{addr: addr, conns: make(chan net.Conn), done: make(chan struct{}), net: n}
	n.mu.Lock()
	n.listeners[addr] = l
	n.mu.Unlock()
	return l
}

func (n *Network) DialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	return n.dial(ctx, addr, "")
}

// refused is what a real TCP dial to a closed port returns, so errors.Is(err, syscall.ECONNREFUSED) holds.
func refused(addr string) error {
	return &net.OpError{Op: "dial", Net: "memnet", Addr: memAddr(addr), Err: syscall.ECONNREFUSED}
}

func (n *Network) dial(ctx context.Context, addr, from string) (net.Conn, error) {
	n.mu.Lock()
	l := n.listeners[addr]
	n.mu.Unlock()
	if l == nil || l.refuse() {
		return nil, refused(addr)
	}
	client, server := net.Pipe()
	var conn net.Conn = server
	if from != "" {
		conn = fromConn{server, memAddr(from)}
	}
	select {
	case l.conns <- conn:
		return client, nil
	case <-l.done:
		return nil, refused(addr)
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// fromConn is the server end of a pipe that reports the dialer's chosen address.
type fromConn struct {
	net.Conn
	remote net.Addr
}

func (c fromConn) RemoteAddr() net.Addr { return c.remote }

// HTTPClient dials through this network.
func (n *Network) HTTPClient() *http.Client {
	return &http.Client{Transport: &http.Transport{DialContext: n.DialContext}}
}

type Listener struct {
	addr    string
	conns   chan net.Conn
	done    chan struct{}
	once    sync.Once
	net     *Network
	mu      sync.Mutex
	refuseN int
}

func (l *Listener) refuse() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.refuseN > 0 {
		l.refuseN--
		return true
	}
	return false
}

func (l *Listener) Accept() (net.Conn, error) {
	select {
	case c := <-l.conns:
		return c, nil
	case <-l.done:
		return nil, net.ErrClosed
	}
}

func (l *Listener) Close() error {
	l.once.Do(func() {
		close(l.done)
		l.net.mu.Lock()
		delete(l.net.listeners, l.addr)
		l.net.mu.Unlock()
	})
	return nil
}

func (l *Listener) Addr() net.Addr { return memAddr(l.addr) }

type memAddr string

func (a memAddr) Network() string { return "memnet" }
func (a memAddr) String() string  { return string(a) }

// HTTPClientFrom dials through this network as a client at from ("ip:port"); the server sees it as r.RemoteAddr.
func (n *Network) HTTPClientFrom(from string) *http.Client {
	return &http.Client{Transport: &http.Transport{DialContext: func(ctx context.Context, _, addr string) (net.Conn, error) {
		return n.dial(ctx, addr, from)
	}}}
}

// DialContextFrom is DialContext for a client at from (for WebSocket dial options).
func (n *Network) DialContextFrom(from string) func(context.Context, string, string) (net.Conn, error) {
	return func(ctx context.Context, _, addr string) (net.Conn, error) { return n.dial(ctx, addr, from) }
}

// RefuseNext makes the next k dials to this listener fail with connection refused.
func (l *Listener) RefuseNext(k int) {
	l.mu.Lock()
	l.refuseN = k
	l.mu.Unlock()
}
