package rtp

import (
	"reflect"
	"testing"
	"time"
)

const ms = time.Millisecond

func seqs(ps []Packet) []uint16 {
	out := []uint16{}
	for _, p := range ps {
		out = append(out, p.Seq)
	}
	return out
}

func TestSequence65535Then0IsInOrder(t *testing.T) {
	b := NewBuffer(60*ms, 20*ms)
	t0 := time.Unix(0, 0)
	for i, s := range []uint16{65534, 0, 65535, 1} { // 0 arrives before 65535
		b.Push(Packet{Seq: s}, t0.Add(time.Duration(i)*ms))
	}
	if got := seqs(b.Pop(t0.Add(200 * ms))); !reflect.DeepEqual(got, []uint16{65534, 65535, 0, 1}) {
		t.Fatalf("got %v", got)
	}
	if b.Late != 0 || b.Lost != 0 {
		t.Fatalf("late %d lost %d", b.Late, b.Lost)
	}
}

func TestRFC3550JitterOnAHandWorkedFourPacketExample(t *testing.T) {
	// 20 ms of 8 kHz audio per packet: RTP timestamps 0, 160, 320, 480; arrivals in the same units 1000, 1170, 1310, 1500.
	// Transit 1000, 1010, 990, 1020 -> |D| 10, 20, 30 -> J = 0.625, 1.8359375, 3.59619140625 (J += (|D| - J) / 16).
	var j Jitter
	for i, arrival := range []uint32{1000, 1170, 1310, 1500} {
		j.Update(arrival, uint32(160*i))
	}
	if j.J != 3.59619140625 {
		t.Fatalf("jitter %v", j.J)
	}
}

func TestReorderedPacketsInsideTheWindowComeOutInOrderAndLateOnesAreDroppedAndCounted(t *testing.T) {
	b := NewBuffer(40*ms, 20*ms) // seq n plays at first arrival + 40 ms + 20 ms * n
	t0 := time.Unix(0, 0)
	b.Push(Packet{Seq: 10}, t0)
	b.Push(Packet{Seq: 12}, t0.Add(30*ms))
	b.Push(Packet{Seq: 11}, t0.Add(35*ms)) // reordered, still before its play time (60 ms)
	if got := seqs(b.Pop(t0.Add(80 * ms))); !reflect.DeepEqual(got, []uint16{10, 11, 12}) {
		t.Fatalf("got %v", got)
	}
	got := seqs(b.Pop(t0.Add(101 * ms)))    // seq 13 was due at 100 ms and has not arrived: concealed as lost
	b.Push(Packet{Seq: 13}, t0.Add(105*ms)) // arrives after its play time: late, dropped
	b.Push(Packet{Seq: 14}, t0.Add(110*ms))
	got = append(got, seqs(b.Pop(t0.Add(130*ms)))...)
	if !reflect.DeepEqual(got, []uint16{14}) || b.Late != 1 || b.Lost != 1 {
		t.Fatalf("got %v late %d lost %d", got, b.Late, b.Lost)
	}
}

func TestDuplicatesAreCountedOnce(t *testing.T) {
	b := NewBuffer(40*ms, 20*ms)
	t0 := time.Unix(0, 0)
	b.Push(Packet{Seq: 1}, t0)
	b.Push(Packet{Seq: 1}, t0.Add(ms))
	if got := seqs(b.Pop(t0.Add(100 * ms))); !reflect.DeepEqual(got, []uint16{1}) || b.Duplicate != 1 {
		t.Fatalf("got %v dup %d", got, b.Duplicate)
	}
}
