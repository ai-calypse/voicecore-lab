package session

import (
	"net/http"
	"sync/atomic"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// AdminHandler serves /metrics (Prometheus) and /debug/counters (JSON) for an operator-only listener.
// The metrics read the same atomic counters as Snapshot, from a registry of this Server's own.
func (s *Server) AdminHandler() http.Handler {
	reg := prometheus.NewRegistry()
	counter := func(name, help, reason string, v func() int64) {
		labels := prometheus.Labels{}
		if reason != "" {
			labels["reason"] = reason
		}
		reg.MustRegister(prometheus.NewCounterFunc(prometheus.CounterOpts{Name: name, Help: help, ConstLabels: labels},
			func() float64 { return float64(v()) }))
	}
	for reason, c := range map[string]*atomic.Int64{"duplicate": &s.c.DropsDuplicate, "stale": &s.c.DropsStale,
		"overload": &s.c.DropsOverload, "overload_out": &s.c.DropsOverloadOut, "ratelimit": &s.c.DropsRateLimit, "fenced": &s.c.DropsFenced} {
		counter("gateway_drops_total", "mic and agent frames dropped, by reason", reason, c.Load)
	}
	for reason, c := range map[string]*atomic.Int64{"ratelimit": &s.c.RejectedRateLimit, "host": &s.c.RejectedHost,
		"upgrade": &s.c.RejectedUpgrade, "draining": &s.c.RejectedDraining, "token": &s.c.RejectedToken,
		"busy": &s.c.RejectedBusy, "upstream": &s.c.RejectedUpstream, "turnstile": &s.c.RejectedTurnstile,
		"origin": &s.c.RejectedOrigin} {
		counter("gateway_rejected_total", "requests refused before a session started, by reason", reason, c.Load)
	}
	counter("gateway_gaps_total", "mic frames missing between received sequence numbers", "", s.c.Gaps.Load)
	counter("gateway_tokens_issued_total", "session tokens issued", "", s.c.TokensIssued.Load)
	reg.MustRegister(prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "gateway_sessions", Help: "live sessions"},
		func() float64 { return float64(s.Snapshot()["sessions"]) }))
	reg.MustRegister(prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "gateway_breaker_state", Help: "upstream dial breaker: 0 closed, 1 half-open, 2 open",
		ConstLabels: prometheus.Labels{"provider": "upstream"}}, func() float64 { return s.upstream.gauge() }))

	mux := http.NewServeMux()
	mux.Handle("GET /metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{}))
	mux.HandleFunc("GET /debug/counters", s.serveCounters)
	return mux
}
