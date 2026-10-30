// Command gateway runs the real-time gateway: browser WebSocket in, one orchestrator WebSocket per session out.
package main

import (
	"context"
	"crypto/rand"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/session"
)

// version is set at build time: go build -ldflags "-X main.version=$(git rev-parse --short HEAD)".
var version = "dev"

func main() {
	addr := flag.String("addr", "127.0.0.1:8080", "listen address")
	upstream := flag.String("upstream", "ws://127.0.0.1:8765", "orchestrator base URL")
	origins := flag.String("origins", "localhost:*,127.0.0.1:*", "allowed browser origins, comma separated")
	tracePath := flag.String("trace", "", "append SPEC trace events (JSON lines) to this file")
	perIP := flag.Int("max-sessions-per-ip", 4, "live sessions per client IP (0 = no limit)")
	maxSessions := flag.Int("max-sessions", 50, "live sessions in total (0 = no limit)")
	tokensPerMin := flag.Float64("tokens-per-minute", 10, "session tokens per client IP per minute (0 = no limit)")
	hosts := flag.String("hosts", "localhost,127.0.0.1,::1", "allowed Host header names, comma separated; empty allows any (blocks DNS rebinding)")
	probe := flag.String("probe", "", "GET this URL and exit 0 on HTTP 200, else 1 (container healthcheck; the image has no curl)")
	drain := flag.Duration("drain", 25*time.Second, "on SIGTERM, how long open sessions may finish before they are ended")
	flag.Parse()
	if *probe != "" {
		os.Exit(session.Probe(*probe))
	}

	secret := []byte(os.Getenv("GATEWAY_SECRET"))
	if len(secret) == 0 {
		secret = make([]byte, 32)
		_, _ = rand.Read(secret)
	}
	cfg := session.Defaults(secret, *upstream)
	cfg.Version = version
	cfg.Origins = strings.Split(*origins, ",")
	cfg.MaxSessionsPerIP, cfg.MaxSessions, cfg.TokensPerMinute = *perIP, *maxSessions, *tokensPerMin
	if *hosts != "" {
		cfg.Hosts = strings.Split(*hosts, ",")
	}
	if *tracePath != "" {
		f, err := os.OpenFile(*tracePath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			slog.Error("trace file", "err", err)
			os.Exit(1)
		}
		defer f.Close()
		cfg.Trace = f
	}
	gw := session.New(cfg)
	srv := &http.Server{Addr: *addr, Handler: gw.Handler(), ReadHeaderTimeout: 10 * time.Second}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	done := make(chan struct{})
	go func() {
		defer close(done)
		<-ctx.Done()
		stop() // a second Ctrl-C now kills the process instead of waiting out the drain
		slog.Info("draining", "for", drain.String())
		gw.Drain(*drain) // new sessions get 503/1013; open ones finish or end with reason "shutdown"
		sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(sctx)
	}()
	slog.Info("gateway listening", "addr", *addr, "upstream", *upstream, "version", version)
	if err := srv.ListenAndServe(); err != http.ErrServerClosed {
		slog.Error("gateway stopped", "err", err)
		os.Exit(1)
	}
	<-done // ListenAndServe returns as soon as Shutdown starts; wait for the drain and shutdown to finish
}
