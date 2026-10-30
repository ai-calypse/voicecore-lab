// Package rtp is the Step 07 media lab: a fixed-delay jitter buffer and RFC 3550 interarrival jitter.
// Unlike the WebSocket path (TCP, in order), RTP over UDP can reorder, duplicate and lose packets.
package rtp

import "time"

type Packet struct {
	Seq       uint16
	Timestamp uint32
	Payload   []byte
}

// Buffer plays packet n (extended sequence) at firstArrival + delay + (n - first) * frame.
// A packet that arrives after its play time is late and dropped; a play time with no packet is lost.
type Buffer struct {
	delay, frame                  time.Duration
	started                       bool
	base                          time.Time
	first, next, last             int64 // extended sequence numbers (16-bit wrap removed)
	pending                       map[int64]Packet
	Played, Late, Lost, Duplicate int
}

func NewBuffer(delay, frame time.Duration) *Buffer {
	return &Buffer{delay: delay, frame: frame, pending: map[int64]Packet{}}
}

// extend picks the 64-bit sequence closest to the highest one seen (RFC 3550 A.1 style unwrapping).
func (b *Buffer) extend(s uint16) int64 {
	if !b.started {
		return int64(s)
	}
	n := b.last&^0xffff | int64(s)
	switch d := n - b.last; {
	case d > 0x8000:
		n -= 0x10000
	case d < -0x8000:
		n += 0x10000
	}
	return n
}

func (b *Buffer) playAt(n int64) time.Time {
	return b.base.Add(b.delay + time.Duration(n-b.first)*b.frame)
}

func (b *Buffer) Push(p Packet, arrival time.Time) {
	n := b.extend(p.Seq)
	if !b.started {
		b.started, b.base, b.first, b.next, b.last = true, arrival, n, n, n
	}
	b.last = max(b.last, n)
	if n < b.next || arrival.After(b.playAt(n)) {
		b.Late++
		return
	}
	if _, dup := b.pending[n]; dup {
		b.Duplicate++
		return
	}
	b.pending[n] = p
}

// Pop returns, in sequence order, every packet whose play time has come. Missing ones are counted lost,
// but only up to the highest sequence seen, so the end of a stream is not mistaken for loss.
func (b *Buffer) Pop(now time.Time) []Packet {
	var out []Packet
	for b.started && b.next <= b.last && !b.playAt(b.next).After(now) {
		if p, ok := b.pending[b.next]; ok {
			out = append(out, p)
			delete(b.pending, b.next)
			b.Played++
		} else {
			b.Lost++
		}
		b.next++
	}
	return out
}

// Jitter is the RFC 3550 section 6.4.1 interarrival jitter estimate, in RTP timestamp units.
type Jitter struct {
	J           float64
	prevTransit uint32
	have        bool
}

// Update takes a packet's arrival time and RTP timestamp, both in the stream's clock-rate units.
// Differences are taken modulo 2^32, so a timestamp wrapping past 0xFFFFFFFF is not a 4e9 jump.
func (j *Jitter) Update(arrival, rtpTimestamp uint32) {
	transit := arrival - rtpTimestamp
	if j.have {
		d := int64(int32(transit - j.prevTransit))
		if d < 0 {
			d = -d
		}
		j.J += (float64(d) - j.J) / 16
	}
	j.prevTransit, j.have = transit, true
}
