package session

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// checkTurnstile verifies the widget token sent as the form field cf-turnstile-response (a form keeps the request a
// CORS "simple request": no preflight). It returns 0 when the visitor passed, else the HTTP status to answer.
func (s *Server) checkTurnstile(w http.ResponseWriter, r *http.Request, ip string) (int, string) {
	r.Body = http.MaxBytesReader(w, r.Body, 4<<10) // a widget token is at most 2,048 characters
	// A plain form first (its size error would hide behind ErrNotMultipart), then FormData.
	parse := func() error {
		if err := r.ParseForm(); err != nil {
			return err
		}
		if err := r.ParseMultipartForm(4 << 10); err != nil && !errors.Is(err, http.ErrNotMultipart) {
			return err
		}
		return nil
	}
	if err := parse(); err != nil {
		if errors.As(err, new(*http.MaxBytesError)) {
			return http.StatusRequestEntityTooLarge, "request too large"
		}
		return http.StatusBadRequest, "bad form"
	}
	tok := r.PostForm.Get("cf-turnstile-response")
	if tok == "" {
		s.c.RejectedTurnstile.Add(1)
		return http.StatusForbidden, "human check missing"
	}
	ok, err := s.siteverify(r.Context(), tok, ip)
	if err != nil {
		s.cfg.Log.Warn("turnstile siteverify failed", "err", err)
		return http.StatusServiceUnavailable, "human check unavailable, try again"
	}
	if !ok {
		s.c.RejectedTurnstile.Add(1)
		return http.StatusForbidden, "human check failed"
	}
	return 0, ""
}

func (s *Server) siteverify(ctx context.Context, tok, ip string) (bool, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	form := url.Values{"secret": {s.cfg.TurnstileSecret}, "response": {tok}, "remoteip": {ip}}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.cfg.TurnstileURL, strings.NewReader(form.Encode()))
	if err != nil {
		return false, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := s.cfg.HTTPClient.Do(req)
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	var out struct {
		Success bool `json:"success"`
	}
	if resp.StatusCode != http.StatusOK {
		return false, errors.New("siteverify status " + resp.Status)
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return false, err
	}
	return out.Success, nil
}
