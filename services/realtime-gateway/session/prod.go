package session

import (
	"errors"
	"strings"
)

// ValidateProd lists every setting a public deployment needs, so a misconfigured gateway refuses to start
// instead of serving with development defaults. It returns nil when all are set.
func (c Config) ValidateProd() error {
	var errs []error
	if len(c.Secret) < 32 {
		errs = append(errs, errors.New("GATEWAY_SECRET must be set, at least 32 bytes (a random one would not survive a restart)"))
	}
	if c.TurnstileSecret == "" {
		errs = append(errs, errors.New("TURNSTILE_SECRET must be set (the human check on new sessions)"))
	}
	if len(c.Origins) == 0 || anyLocal(c.Origins) {
		errs = append(errs, errors.New("-origins must list the public site and nothing local"))
	}
	if len(c.Hosts) == 0 || anyLocal(c.Hosts) {
		errs = append(errs, errors.New("-hosts must list the public host name and nothing local"))
	}
	if len(c.TrustedProxies) == 0 {
		errs = append(errs, errors.New("-trusted-proxies must name the load balancer, or every client shares its IP"))
	}
	return errors.Join(errs...)
}

func anyLocal(names []string) bool {
	for _, n := range names {
		h := strings.ToLower(n)
		if strings.HasPrefix(h, "localhost") || strings.HasPrefix(h, "127.") || strings.HasPrefix(h, "::1") || strings.HasPrefix(h, "[::1]") {
			return true
		}
	}
	return false
}
