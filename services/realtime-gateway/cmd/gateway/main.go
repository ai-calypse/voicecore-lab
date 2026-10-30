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

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/session"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:8080", "listen address")
	upstream := flag.String("upstream", "ws://127.0.0.1:8765", "orchestrator base URL")
	origins := flag.String("origins", "localhost:*,127.0.0.1:*", "allowed browser origins, comma separated")
	tracePath := flag.String("trace", "", "append SPEC trace events (JSON lines) to this file")
	flag.Parse()

	secret := []byte(os.Getenv("GATEWAY_SECRET"))
	if len(secret) == 0 {
		secret = make([]byte, 32)
		_, _ = rand.Read(secret)
	}
	cfg := session.Defaults(secret, *upstream)
	cfg.Origins = strings.Split(*origins, ",")
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
	srv := &http.Server{Addr: *addr, Handler: gw.Handler()}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		gw.Close()
		_ = srv.Shutdown(context.Background())
	}()
	slog.Info("gateway listening", "addr", *addr, "upstream", *upstream)
	if err := srv.ListenAndServe(); err != http.ErrServerClosed {
		slog.Error("gateway stopped", "err", err)
		os.Exit(1)
	}
}
