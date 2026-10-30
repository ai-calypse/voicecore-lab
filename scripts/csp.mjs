// Writes the nginx security headers for a built site: node scripts/csp.mjs <build dir> <gateway URL> <out.conf>
// Inline scripts (Docusaurus writes a few: theme, announcement bar) are allowed by their sha256 hashes, so scripts
// never need 'unsafe-inline'. The gateway origin goes into connect-src, for the token request and the WebSocket.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [dir, gateway, out] = process.argv.slice(2);
const pages = (d) => readdirSync(d).flatMap((f) => {
  const p = join(d, f);
  return statSync(p).isDirectory() ? pages(p) : p.endsWith(".html") ? [p] : [];
});
const hashes = new Set();
for (const file of pages(dir)) {
  for (const [, attrs, code] of readFileSync(file, "utf8").matchAll(/<script(?![^>]*\ssrc=)([^>]*)>([\s\S]*?)<\/script>/g)) {
    if (!code.trim() || /type="application\/(ld\+)?json"/.test(attrs)) continue; // data, not code
    hashes.add(`'sha256-${createHash("sha256").update(code).digest("base64")}'`);
  }
}
const gw = new URL(gateway);
const ws = `${gw.protocol === "https:" ? "wss:" : "ws:"}//${gw.host}`;
const csp = [
  "default-src 'self'",
  `script-src 'self' blob: https://challenges.cloudflare.com ${[...hashes].sort().join(" ")}`.trim(), // blob: the audio worklet
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com", // the widget styles its own Shadow DOM
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data:",
  `connect-src 'self' ${gw.origin} ${ws}`,
  "frame-src https://challenges.cloudflare.com", // Turnstile
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");
writeFileSync(out, [
  `add_header Content-Security-Policy "${csp}" always;`,
  "add_header X-Content-Type-Options nosniff always;",
  "add_header Referrer-Policy strict-origin-when-cross-origin always;",
  "",
].join("\n"));
console.log(`csp: ${hashes.size} inline script hash(es), connect-src ${gw.origin}`);
