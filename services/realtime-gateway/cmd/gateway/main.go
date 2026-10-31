// Command gateway runs the real-time gateway: browser WebSocket in, one orchestrator WebSocket per session out.
package main

import (
	"context"
	"crypto/rand"
	"flag"
	"log/slog"
	"net"
	"net/http"
	"net/netip"
	"os"
	"os/signal"
	"regexp"
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
	redisURL := flag.String("redis-url", "", "shared store for token nonces and daily quotas, e.g. redis://redis:6379/0 (several copies need it)")
	perDay := flag.Int("sessions-per-ip-per-day", 0, "session tokens per client IP per UTC day (0 = no limit; in memory until Redis)")
	tokensPerMin := flag.Float64("tokens-per-minute", 10, "session tokens per client IP per minute (0 = no limit)")
	hosts := flag.String("hosts", "localhost,127.0.0.1,::1", "allowed Host header names, comma separated; empty allows any (blocks DNS rebinding)")
	copyID := flag.String("copy-id", "gw", "this gateway copy's id, inside every session id (routes resumes to the owner)")
	trusted := flag.String("trusted-proxies", "", "comma-separated CIDRs whose X-Forwarded-For is believed (e.g. the load balancer)")
	probe := flag.String("probe", "", "GET this URL and exit 0 on HTTP 200, else 1 (container healthcheck; the image has no curl)")
	drain := flag.Duration("drain", 25*time.Second, "on SIGTERM, how long open sessions may finish before they are ended")
	env := flag.String("env", "dev", "dev, or prod: refuse to start unless every public-deployment setting is present")
	turnstileURL := flag.String("turnstile-url", "", "Turnstile siteverify URL (default Cloudflare's); the secret comes from TURNSTILE_SECRET")
	adminAddr := flag.String("admin-addr", "", "operator listener for /metrics and /debug/counters, e.g. :9091 (empty = off); keep it off the public internet")
	agentsDir := flag.String("agents-dir", "", "the console's published agent bundles (read-only); token requests may name an agent there")
	widget := flag.String("widget", "", "the built voicecore.js, served at /widget.js (empty = not served)")
	humanCheck := flag.String("human-check", "on", "off: allow a prod install without TURNSTILE_SECRET (any visitor can start a session; the spend caps still apply)")
	flag.Parse()
	if *env != "dev" && *env != "prod" { // a typo must not silently mean dev
		slog.Error("-env must be dev or prod", "env", *env)
		os.Exit(2)
	}
	if *probe != "" {
		os.Exit(session.Probe(*probe))
	}
	if os.Getenv("LOG_FORMAT") == "json" { // one JSON object per line, for Loki; text otherwise
		slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stderr, nil)))
	}

	secret := []byte(os.Getenv("GATEWAY_SECRET"))
	if len(secret) == 0 && *env != "prod" { // prod must set it: a random secret dies with the process
		secret = make([]byte, 32)
		_, _ = rand.Read(secret)
	}
	cfg := session.Defaults(secret, *upstream)
	cfg.Version = version
	cfg.TurnstileSecret = os.Getenv("TURNSTILE_SECRET") // env, not a flag: flags show up in ps
	if *turnstileURL != "" {
		cfg.TurnstileURL = *turnstileURL
	}
	if !regexp.MustCompile(`^[a-z0-9]{1,32}$`).MatchString(*copyID) { // it goes into URL paths and the LB's "s-<id>-" prefix match
		slog.Error("-copy-id must be 1-32 lowercase letters or digits", "copy_id", *copyID)
		os.Exit(2)
	}
	cfg.CopyID = *copyID
	for _, c := range strings.Split(*trusted, ",") {
		if c = strings.TrimSpace(c); c != "" {
			p, err := netip.ParsePrefix(c)
			if err != nil {
				slog.Error("bad -trusted-proxies entry", "cidr", c, "err", err)
				os.Exit(2)
			}
			cfg.TrustedProxies = append(cfg.TrustedProxies, p)
		}
	}
	cfg.Origins = splitList(*origins)
	cfg.AgentsDir, cfg.Widget = *agentsDir, *widget
	if *humanCheck != "on" && *humanCheck != "off" {
		slog.Error("-human-check must be on or off", "human_check", *humanCheck)
		os.Exit(2)
	}
	cfg.HumanCheckOff = *humanCheck == "off" && cfg.TurnstileSecret == ""
	if cfg.HumanCheckOff && *env == "prod" {
		slog.Warn("human check off: any visitor can start a session; only the rate limits and spend caps bound it")
	}
	cfg.MaxSessionsPerIP, cfg.MaxSessions, cfg.TokensPerMinute, cfg.SessionsPerIPPerDay = *perIP, *maxSessions, *tokensPerMin, *perDay
	if *hosts != "" {
		cfg.Hosts = splitList(*hosts)
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
	if *redisURL != "" {
		store, err := session.NewRedisStore(*redisURL)
		if err != nil {
			slog.Error("bad -redis-url", "err", err)
			os.Exit(2)
		}
		cfg.Store = store
	}
	if *env == "prod" {
		if err := cfg.ValidateProd(); err != nil {
			slog.Error("refusing to start with -env prod", "missing", err.Error())
			os.Exit(1)
		}
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
	if *adminAddr != "" {
		ln, err := net.Listen("tcp", *adminAddr) // bind now: a gateway nobody can scrape would page as GatewayDown
		if err != nil {
			slog.Error("admin listener", "addr", *adminAddr, "err", err)
			os.Exit(2)
		}
		admin := &http.Server{Handler: gw.AdminHandler(), ReadHeaderTimeout: 10 * time.Second}
		go func() { _ = admin.Serve(ln) }() // ponytail: not drained; a scrape cut off at exit is harmless
	}
	slog.Info("gateway listening", "addr", *addr, "upstream", *upstream, "version", version)
	if err := srv.ListenAndServe(); err != http.ErrServerClosed {
		slog.Error("gateway stopped", "err", err)
		os.Exit(1)
	}
	<-done // ListenAndServe returns as soon as Shutdown starts; wait for the drain and shutdown to finish
}

// splitList splits a comma-separated flag, trimming spaces: "a.example, b.example" is two entries.
func splitList(v string) []string {
	var out []string
	for _, x := range strings.Split(v, ",") {
		if x = strings.TrimSpace(x); x != "" {
			out = append(out, x)
		}
	}
	return out
}
