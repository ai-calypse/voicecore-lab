package protocol

import (
	"encoding/hex"
	"encoding/json"
	"reflect"
	"testing"
)

func TestGoldenEvents(t *testing.T) {
	var vs struct {
		Required map[string][]string
		Valid    []json.RawMessage
		Invalid  []struct{ Name, Text string }
	}
	loadVectors(t, "events.json", &vs)
	if !reflect.DeepEqual(Required, vs.Required) {
		t.Fatalf("Required table differs from vectors")
	}
	for _, raw := range vs.Valid {
		e, err := DecodeEvent(raw)
		if err != nil {
			t.Fatalf("%s: %v", raw, err)
		}
		out, _ := json.Marshal(e)
		var got, want any
		_ = json.Unmarshal(out, &got)
		_ = json.Unmarshal(raw, &want)
		if !reflect.DeepEqual(got, want) {
			t.Errorf("round trip: got %s want %s", out, raw)
		}
	}
	for _, v := range vs.Invalid {
		if _, err := DecodeEvent([]byte(v.Text)); err == nil {
			t.Errorf("%s: accepted", v.Name)
		}
	}
}

func FuzzDecodeFrame(f *testing.F) {
	var vs frameVectors
	loadVectors(f, "frames.json", &vs)
	for _, v := range vs.Valid {
		raw, _ := hex.DecodeString(v.Hex)
		f.Add(raw)
	}
	f.Fuzz(func(t *testing.T, b []byte) {
		fr, err := DecodeFrame(b)
		if err == nil && string(fr.Encode()[:HeaderBytes-2]) != string(b[:HeaderBytes-2]) {
			t.Fatalf("decoded header does not re-encode")
		}
	})
}
