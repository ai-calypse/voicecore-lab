// Command fakeorch is a scripted orchestrator: it echoes mic audio back as generation 1 (24 kHz).
package main

import (
	"flag"
	"log/slog"
	"net/http"

	"github.com/ai-calypse/voicecore-lab/services/realtime-gateway/internal/fakeorch"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:8765", "listen address")
	flag.Parse()
	o := fakeorch.New()
	o.Echo = true
	slog.Info("fakeorch listening", "addr", *addr)
	slog.Error("fakeorch stopped", "err", http.ListenAndServe(*addr, o.Handler()))
}
