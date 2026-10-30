package protocol

import (
	"encoding/json"
	"errors"
	"fmt"
)

// Required lists each event type's required fields (SPEC.md section 2).
var Required = map[string][]string{
	"hello":                    {"version", "token", "mic", "playout"},
	"ping":                     {"t_client_us"},
	"text.input":               {"text"},
	"mic.revoked":              {},
	"client.paused":            {},
	"client.resumed_playout":   {},
	"playout.started":          {"gen", "t_us"},
	"playout.stopped":          {"gen", "reason", "t_us"},
	"cancel.ack":               {"gen", "played_until_seq"},
	"welcome":                  {"session_id", "resume_key", "resume_window_ms", "resumed"},
	"pong":                     {"t_client_us", "t_server_us"},
	"user.speech_started":      {"turn_id"},
	"transcript.partial":       {"turn_id", "text"},
	"transcript.final":         {"turn_id", "text"},
	"agent.generation_started": {"turn_id", "gen"},
	"agent.text":               {"gen", "text"},
	"agent.cancel":             {"gen"},
	"answer.sources":           {"gen", "sources"},
	"session.ended":            {"reason"},
	"client.resumed":           {},
}

// Event is a decoded control event; fields stay raw so unknown extras pass through unchanged.
type Event map[string]json.RawMessage

func (e Event) Type() string {
	var t string
	_ = json.Unmarshal(e["type"], &t)
	return t
}

// Get decodes one field into v.
func (e Event) Get(field string, v any) error { return json.Unmarshal(e[field], v) }

func DecodeEvent(b []byte) (Event, error) {
	var e Event
	if err := json.Unmarshal(b, &e); err != nil || e == nil {
		return nil, errors.New("event is not a JSON object")
	}
	req, ok := Required[e.Type()]
	if !ok {
		return nil, fmt.Errorf("unknown event type %q", e.Type())
	}
	for _, f := range req {
		if _, ok := e[f]; !ok {
			return nil, fmt.Errorf("%s: missing %s", e.Type(), f)
		}
	}
	return e, nil
}

// NewEvent builds an event from a type and fields.
func NewEvent(typ string, fields map[string]any) []byte {
	m := map[string]any{"type": typ}
	for k, v := range fields {
		m[k] = v
	}
	b, _ := json.Marshal(m)
	return b
}
