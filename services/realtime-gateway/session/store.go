package session

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

// Store holds what several gateway copies must share (Step 09 Phase 10): used token nonces and daily token counts.
// memStore is one process's memory (the default); redisStore is shared between copies.
type Store interface {
	UseNonce(ctx context.Context, nonce string, exp time.Time) (fresh bool, err error) // false: already used
	ReleaseNonce(ctx context.Context, nonce string) error                              // a refused hello gives it back
	TakeDaily(ctx context.Context, ip string, day int64, limit int) (ok bool, err error)
}

type memStore struct {
	mu     sync.Mutex
	nonces map[string]int64 // used nonce -> its token's expiry (unix s)
	swept  int64
	daily  map[string]int // tokens per client IP on day
	day    int64
}

func newMemStore() *memStore { return &memStore{nonces: map[string]int64{}, daily: map[string]int{}} }

func (m *memStore) UseNonce(_ context.Context, nonce string, exp time.Time) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if now := time.Now().Unix(); now != m.swept { // at most one linear sweep per second
		m.swept = now
		for n, e := range m.nonces {
			if e <= now {
				delete(m.nonces, n)
			}
		}
	}
	if _, used := m.nonces[nonce]; used {
		return false, nil
	}
	m.nonces[nonce] = exp.Unix()
	return true, nil
}

func (m *memStore) ReleaseNonce(_ context.Context, nonce string) error {
	m.mu.Lock()
	delete(m.nonces, nonce)
	m.mu.Unlock()
	return nil
}

func (m *memStore) TakeDaily(_ context.Context, ip string, day int64, limit int) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if day != m.day || len(m.daily) > 200_000 {
		m.day, m.daily = day, map[string]int{} // ponytail: crude memory bound, like the token buckets
	}
	if m.daily[ip] >= limit {
		return false, nil
	}
	m.daily[ip]++
	return true, nil
}

type redisStore struct{ r *redis.Client }

// NewRedisStore connects to the store copies share, e.g. redis://redis:6379/0.
func NewRedisStore(url string) (Store, error) {
	opts, err := redis.ParseURL(url)
	if err != nil {
		return nil, err
	}
	opts.DialTimeout, opts.ReadTimeout, opts.WriteTimeout = 2*time.Second, time.Second, time.Second
	return &redisStore{redis.NewClient(opts)}, nil
}

func (s *redisStore) UseNonce(ctx context.Context, nonce string, exp time.Time) (bool, error) {
	ttl := time.Until(exp)
	if ttl < time.Second {
		ttl = time.Second
	}
	return s.r.SetNX(ctx, "vc:nonce:"+nonce, 1, ttl).Result()
}

func (s *redisStore) ReleaseNonce(ctx context.Context, nonce string) error {
	return s.r.Del(ctx, "vc:nonce:"+nonce).Err()
}

func (s *redisStore) TakeDaily(ctx context.Context, ip string, day int64, limit int) (bool, error) {
	key := fmt.Sprintf("vc:quota:%s:%d", ip, day)
	var n *redis.IntCmd
	if _, err := s.r.TxPipelined(ctx, func(p redis.Pipeliner) error {
		n = p.Incr(ctx, key)
		p.Expire(ctx, key, 48*time.Hour)
		return nil
	}); err != nil {
		return false, err
	}
	return n.Val() <= int64(limit), nil
}
