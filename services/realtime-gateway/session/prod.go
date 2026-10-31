package session

import (
	"errors"
	"path"
	"strings"
)

// ValidateProd lists every setting a public deployment needs, so a misconfigured gateway refuses to start
// instead of serving with development defaults. It returns nil when all are set.
func (c Config) ValidateProd() error {
	var errs []error
	if len(c.Secret) < 32 {
		errs = append(errs, errors.New("GATEWAY_SECRET must be set, at least 32 bytes (a random one would not survive a restart)"))
	}
	if c.TurnstileSecret == "" && !c.HumanCheckOff {
		errs = append(errs, errors.New("TURNSTILE_SECRET must be set (the human check on new sessions), or -human-check off on purpose"))
	}
	if len(c.Origins) == 0 || anyOf(c.Origins, local) || anyOf(c.Origins, broad) {
		errs = append(errs, errors.New("-origins must list the public site, nothing local, and no pattern that matches any site"))
	}
	if len(c.Hosts) == 0 || anyOf(c.Hosts, local) || anyOf(c.Hosts, broad) {
		errs = append(errs, errors.New("-hosts must list the public host name and nothing local"))
	}
	if len(c.TrustedProxies) == 0 {
		errs = append(errs, errors.New("-trusted-proxies must name the load balancer, or every client shares its IP"))
	}
	return errors.Join(errs...)
}

func anyOf(names []string, pred func(string) bool) bool {
	for _, n := range names {
		if pred(strings.ToLower(strings.TrimSpace(n))) {
			return true
		}
	}
	return false
}

// local: a loopback or any-address name, with or without a scheme.
func local(n string) bool {
	if i := strings.Index(n, "://"); i >= 0 {
		n = n[i+3:]
	}
	for _, p := range []string{"localhost", "127.", "::1", "[::1]", "0.0.0.0"} {
		if strings.HasPrefix(n, p) {
			return true
		}
	}
	return false
}

// broad: a pattern that also matches an arbitrary site, such as *, *.* or ?*.
func broad(pattern string) bool {
	for _, probe := range []string{"attacker.invalid", "attacker.invalid:443", "https://attacker.invalid"} {
		if ok, _ := path.Match(pattern, probe); ok {
			return true
		}
	}
	return false
}
