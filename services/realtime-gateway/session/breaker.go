package session

import (
	"sync"
	"time"
)

// breaker guards the upstream dial with the orchestrator's rules (voicecore/resilience.py): five failed session
// dials within 60 s open it, whatever succeeded in between; for 30 s new sessions fail fast without dialling; then one dial goes out as
// a probe, and its success closes the breaker while its failure opens it again.
type breaker struct {
	mu       sync.Mutex
	state    string // closed, half_open or open
	failures []time.Time
	openedAt time.Time
	opens    int64
}

const (
	breakerFailMax = 5
	breakerWindow  = 60 * time.Second
	breakerOpenFor = 30 * time.Second
)

func newBreaker() *breaker { return &breaker{state: "closed"} }

// allow says whether a dial may go out; moving from open to half-open hands out the single probe.
func (b *breaker) allow() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	switch {
	case b.state == "closed":
		return true
	case b.state == "open" && time.Since(b.openedAt) >= breakerOpenFor:
		b.state = "half_open"
		return true
	}
	return false
}

// ready is false only while open with no probe due yet (readyz: send new users elsewhere).
func (b *breaker) ready() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.state != "open" || time.Since(b.openedAt) >= breakerOpenFor
}

// success closes the breaker only from the probe; in the closed state it does not reset the count.
func (b *breaker) success() {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.state == "half_open" {
		b.failures, b.state = nil, "closed"
	}
}

func (b *breaker) failure() {
	b.mu.Lock()
	defer b.mu.Unlock()
	now := time.Now()
	if b.state == "half_open" {
		b.open(now)
		return
	}
	b.failures = append(b.failures, now)
	for len(b.failures) > 0 && now.Sub(b.failures[0]) > breakerWindow {
		b.failures = b.failures[1:]
	}
	if len(b.failures) >= breakerFailMax {
		b.open(now)
	}
}

// release ends a probe that got no verdict (the orchestrator answered 503): back to open, never stuck half-open.
func (b *breaker) release() {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.state == "half_open" {
		b.open(time.Now())
	}
}

func (b *breaker) open(now time.Time) {
	b.failures, b.state, b.openedAt = nil, "open", now
	b.opens++
}

// gauge is the state as the metric reports it, the same scale as voicecore_breaker_state.
func (b *breaker) gauge() float64 {
	b.mu.Lock()
	defer b.mu.Unlock()
	return map[string]float64{"closed": 0, "half_open": 1, "open": 2}[b.state]
}
