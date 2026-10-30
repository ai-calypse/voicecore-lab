// Package protocol is the Go codec for the VoiceCore wire protocol (packages/protocol/SPEC.md).
package protocol

import "encoding/binary"

const (
	HeaderBytes     = 28
	KindMic         = 1
	KindAgent       = 2
	FlagEndOfStream = 1
)

// Frame is one audio frame. Version is always 1 and Samples is len(Payload), so neither is stored.
type Frame struct {
	Kind         uint8
	Flags        uint16
	StreamID     uint32
	Sequence     uint32
	CaptureUS    uint64
	GenerationID uint32
	Payload      []int16
}

type FrameError struct{ Reason string } // short | version | kind | length

func (e *FrameError) Error() string { return "invalid frame: " + e.Reason }

func DecodeFrame(b []byte) (Frame, error) {
	be := binary.BigEndian
	switch {
	case len(b) < HeaderBytes:
		return Frame{}, &FrameError{"short"}
	case b[0] != 1:
		return Frame{}, &FrameError{"version"}
	case b[1] != KindMic && b[1] != KindAgent:
		return Frame{}, &FrameError{"kind"}
	}
	n := int(be.Uint16(b[24:]))
	if len(b)-HeaderBytes != 2*n {
		return Frame{}, &FrameError{"length"}
	}
	p := make([]int16, n)
	for i := range p {
		p[i] = int16(binary.LittleEndian.Uint16(b[HeaderBytes+2*i:]))
	}
	return Frame{Kind: b[1], Flags: be.Uint16(b[2:]), StreamID: be.Uint32(b[4:]), Sequence: be.Uint32(b[8:]),
		CaptureUS: be.Uint64(b[12:]), GenerationID: be.Uint32(b[20:]), Payload: p}, nil
}

func (f Frame) Encode() []byte {
	be := binary.BigEndian
	b := make([]byte, HeaderBytes+2*len(f.Payload))
	b[0], b[1] = 1, f.Kind
	be.PutUint16(b[2:], f.Flags)
	be.PutUint32(b[4:], f.StreamID)
	be.PutUint32(b[8:], f.Sequence)
	be.PutUint64(b[12:], f.CaptureUS)
	be.PutUint32(b[20:], f.GenerationID)
	be.PutUint16(b[24:], uint16(len(f.Payload)))
	for i, s := range f.Payload {
		binary.LittleEndian.PutUint16(b[HeaderBytes+2*i:], uint16(s))
	}
	return b
}
