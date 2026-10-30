package session

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/coder/websocket"
)

// Seam 18: the shared-state contract, for memStore and redisStore (VOICECORE_TEST_REDIS, e.g. redis://127.0.0.1:16379/14).
func stores(t *testing.T) map[string]Store {
	out := map[string]Store{"mem": newMemStore()}
	if url := os.Getenv("VOICECORE_TEST_REDIS"); url != "" {
		s, err := NewRedisStore(url)
		if err != nil {
			t.Fatal(err)
		}
		s.(*redisStore).r.FlushDB(context.Background())
		out["redis"] = s
	}
	return out
}

func TestNonceSingleUse(t *testing.T) {
	for name, s := range stores(t) {
		ctx, exp := context.Background(), time.Now().Add(time.Minute)
		first, err1 := s.UseNonce(ctx, "n1", exp)
		second, err2 := s.UseNonce(ctx, "n1", exp)
		_ = s.ReleaseNonce(ctx, "n1")
		third, _ := s.UseNonce(ctx, "n1", exp)
		if err1 != nil || err2 != nil || !first || second || !third {
			t.Errorf("%s: first %v second %v after release %v (%v %v)", name, first, second, third, err1, err2)
		}
	}
}

func TestDailyQuota(t *testing.T) {
	for name, s := range stores(t) {
		ctx := context.Background()
		var got []bool
		for i := 0; i < 3; i++ {
			ok, _ := s.TakeDaily(ctx, "198.51.100.7", 20000, 2)
			got = append(got, ok)
		}
		nextDay, _ := s.TakeDaily(ctx, "198.51.100.7", 20001, 2)
		other, _ := s.TakeDaily(ctx, "203.0.113.5", 20000, 2)
		if !got[0] || !got[1] || got[2] || !nextDay || !other {
			t.Errorf("%s: %v next day %v other address %v", name, got, nextDay, other)
		}
	}
}

type downStore struct{}

func (downStore) UseNonce(context.Context, string, time.Time) (bool, error) {
	return false, errors.New("store down")
}
func (downStore) ReleaseNonce(context.Context, string) error { return errors.New("store down") }
func (downStore) TakeDaily(context.Context, string, int64, int) (bool, error) {
	return false, errors.New("store down")
}

func TestStoreDownFailsClosedForSessionsAndOpenForQuotas(t *testing.T) {
	runCfg(t, false, func(c *Config) { c.Store, c.SessionsPerIPPerDay = downStore{}, 1 }, func(t *testing.T, r *rig) {
		tok, again := r.token(), r.token() // the quota cannot be counted: tokens are still issued (Turnstile, the bucket and the caps bound spend)
		if tok == "" || again == "" {
			t.Fatal("no token while the quota store is down")
		}
		if s := r.connect(map[string]any{"token": tok}, nil).closeStatus(); s != websocket.StatusTryAgainLater {
			t.Fatalf("hello while the nonce store is down: close %d, want 1013 (a reused token must never get through)", s)
		}
	})
}
