package session

import (
	"net/http"
	"testing"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/internal/fakeorch"
)

// second starts another fake orchestrator at orch2:80 on the rig's network; stop() closes it like a dead process.
func second(r *rig) (o *fakeorch.Orch, stop func()) {
	o = fakeorch.New()
	srv, ln := &http.Server{Handler: o.Handler()}, r.net.Listen("orch2:80")
	go func() { _ = srv.Serve(ln) }()
	return o, func() { o.Kill(); _ = srv.Close() }
}

func twoUpstreams(c *Config) { c.Upstream = "ws://orch:80,ws://orch2:80" }

func TestPicksLeastLoadedReadyUpstream(t *testing.T) {
	runCfg(t, false, twoUpstreams, func(t *testing.T, r *rig) {
		b, stop := second(r)
		defer stop()
		welcomeOf(r.connect(nil, nil))
		r.upstream() // the first session: a tie, so the first upstream
		welcomeOf(r.connect(nil, nil))
		<-b.Conns // the second: the upstream with none of our sessions
		welcomeOf(r.connect(nil, nil))
		r.upstream() // the third: a tie, the rotation is back at orch
		b.SetReady(503)
		welcomeOf(r.connect(nil, nil))
		r.upstream() // the fourth: orch2 has fewer of our sessions but is not ready, so orch
	})
}

func TestOrchestratorDeathOnlyEndsItsSessions(t *testing.T) {
	runCfg(t, false, twoUpstreams, func(t *testing.T, r *rig) {
		_, stop := second(r)
		onA := r.connect(nil, nil)
		welcomeOf(onA)
		r.upstream()
		onB := r.connect(nil, nil)
		welcomeOf(onB)
		stop() // orch2 dies
		var reason string
		_ = onB.next("session.ended").Get("reason", &reason)
		if reason != "error" {
			t.Fatalf("its session ended with %q, want error", reason)
		}
		onA.send("ping", map[string]any{"t_client_us": 1})
		onA.next("pong") // the other orchestrator's session carries on
		welcomeOf(r.connect(nil, nil))
		r.upstream() // a new session: orch2 refuses, so it goes to orch
		time.Sleep(time.Second)
	})
}
