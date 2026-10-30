// Package memnet is an in-memory network of net.Pipe connections, so HTTP and WebSocket
// tests can run inside a testing/synctest bubble (real sockets would block fake time).
package memnet

import (
	"context"
	"errors"
	"net"
	"net/http"
	"sync"
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

func (n *Network) DialContext(ctx context.Context, _, addr string) (net.Conn, error) {
	n.mu.Lock()
	l := n.listeners[addr]
	n.mu.Unlock()
	if l == nil {
		return nil, errors.New("memnet: connection refused: " + addr)
	}
	client, server := net.Pipe()
	select {
	case l.conns <- server:
		return client, nil
	case <-l.done:
		return nil, errors.New("memnet: listener closed: " + addr)
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// HTTPClient dials through this network.
func (n *Network) HTTPClient() *http.Client {
	return &http.Client{Transport: &http.Transport{DialContext: n.DialContext}}
}

type Listener struct {
	addr  string
	conns chan net.Conn
	done  chan struct{}
	once  sync.Once
	net   *Network
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

func (l *Listener) Addr() net.Addr { return addr(l.addr) }

type addr string

func (a addr) Network() string { return "memnet" }
func (a addr) String() string  { return string(a) }
