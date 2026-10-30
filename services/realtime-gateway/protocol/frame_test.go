package protocol

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"strconv"
	"testing"
)

type frameVectors struct {
	Valid []struct {
		Name   string
		Hex    string
		Fields struct {
			Version      uint8   `json:"version"`
			Kind         uint8   `json:"kind"`
			Flags        uint16  `json:"flags"`
			StreamID     uint32  `json:"stream_id"`
			Sequence     uint32  `json:"sequence"`
			CaptureUS    string  `json:"capture_us"`
			GenerationID uint32  `json:"generation_id"`
			Samples      uint16  `json:"samples"`
			Payload      []int16 `json:"payload"`
		}
	}
	Invalid []struct{ Name, Hex, Error string }
}

func loadVectors(t testing.TB, name string, v any) {
	t.Helper()
	b, err := os.ReadFile("../../../packages/protocol/vectors/" + name)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(b, v); err != nil {
		t.Fatal(err)
	}
}

func TestGoldenFrames(t *testing.T) {
	var vs frameVectors
	loadVectors(t, "frames.json", &vs)
	for _, v := range vs.Valid {
		raw, _ := hex.DecodeString(v.Hex)
		f, err := DecodeFrame(raw)
		if err != nil {
			t.Fatalf("%s: %v", v.Name, err)
		}
		capture, _ := strconv.ParseUint(v.Fields.CaptureUS, 10, 64)
		want := Frame{Kind: v.Fields.Kind, Flags: v.Fields.Flags, StreamID: v.Fields.StreamID, Sequence: v.Fields.Sequence,
			CaptureUS: capture, GenerationID: v.Fields.GenerationID, Payload: v.Fields.Payload}
		if want.Payload == nil {
			want.Payload = []int16{}
		}
		if !reflect.DeepEqual(f, want) {
			t.Errorf("%s: got %+v want %+v", v.Name, f, want)
		}
		if got := hex.EncodeToString(f.Encode()); got != v.Hex {
			t.Errorf("%s: encode got %s want %s", v.Name, got, v.Hex)
		}
	}
	for _, v := range vs.Invalid {
		raw, _ := hex.DecodeString(v.Hex)
		var fe *FrameError
		if _, err := DecodeFrame(raw); !errors.As(err, &fe) || fe.Reason != v.Error {
			t.Errorf("%s: got %v want reason %s", v.Name, err, v.Error)
		}
	}
}
