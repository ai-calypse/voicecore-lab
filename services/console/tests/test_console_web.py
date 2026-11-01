"""Docs from a website address: the pages under it, read without running scripts, each kept at its real address."""
import pytest

from voicecore.answer.ingest import UnsafeURL, docusaurus, ingest
from voicecore_console import sources

PAGE = """<!doctype html><html><head><title>{title} | Acme Help</title><script>var x = "<h2>no</h2>";</script></head>
<body><nav><a href="/help/">Help</a> <a href="/help/billing">Billing</a> <a href="/blog/news">Blog</a>
<a href="https://other.example/x">Elsewhere</a> <a href="/help/logo.png">Logo</a> <a href="/help/refunds?ref=nav#top">Refunds</a></nav>
<header>Acme, the menu bar</header>
<main><article><header><h1>{title}</h1></header>{body}</article><div class="toc"><ul><li>On this page</li></ul></div></main>
<footer>© Acme</footer></body></html>"""

SITE = {
    "https://acme.example/help/": PAGE.format(title="Help", body="<p>Start here.</p>"),
    "https://acme.example/help/billing": PAGE.format(title="Billing", body="""
        <h2 id="refunds">Refunds <a class="hash-link" href="#refunds">​</a></h2><p>Refunds take   5 days.</p>
        <h3>Cards</h3><ul><li>Visa</li><li>Mastercard</li></ul><pre>pay --now
  --card</pre>"""),
    "https://acme.example/help/refunds": PAGE.format(title="Refunds", body="<p>See billing.</p>"),
    "https://acme.example/blog/news": PAGE.format(title="News", body="<p>Out of scope.</p>"),
}


def fake_get(site, redirects=None, log=None):
    def get(url):
        log is not None and log.append(url)
        if url in (redirects or {}):
            return 301, redirects[url], ""
        return (200, "", site[url]) if url in site else (404, "", "")
    return get


def fetch(dest, url="https://acme.example/help/", site=SITE, **kw):
    return sources.fetch_web(url, dest, get=kw.pop("get", None) or fake_get(site), check=lambda u: u, **kw)


def test_reads_the_pages_below_the_address(tmp_path):
    log = []
    r = fetch(tmp_path / "out", get=fake_get(SITE, log=log))
    assert (r["files"], r["skipped"], r["host"]) == (3, [], "acme.example")
    assert sorted(p.relative_to(tmp_path / "out").as_posix() for p in (tmp_path / "out").rglob("*.md")) == [
        "help/billing.md", "help/index.md", "help/refunds.md"]
    assert not any("blog" in u or "other.example" in u or "logo" in u for u in log)  # never fetched
    billing = (tmp_path / "out" / "help" / "billing.md").read_text()
    assert billing.startswith("---\nsource_url: https://acme.example/help/billing\n---\n\n# Billing\n")
    assert "## Refunds {#refunds}\n\nRefunds take 5 days." in billing
    assert "### Cards\n" in billing and "- Visa" in billing and "```\npay --now\n  --card\n```" in billing
    for left_out in ("menu bar", "© Acme", "On this page", "var x", "no</h2>"):
        assert left_out not in billing


def test_pages_keep_their_real_addresses_and_anchors(tmp_path):
    fetch(tmp_path / "out")
    site = docusaurus("https://unpublished.invalid/")
    passages = ingest(tmp_path / "out", site=site.__class__(site.base_url, site.style, frozenset({"acme.example"}), None))
    urls = {p.title: p.url for p in passages}
    assert urls["Billing > Refunds"] == "https://acme.example/help/billing#refunds"
    assert urls["Help"] == "https://acme.example/help/"


def test_a_redirect_to_www_moves_the_scope(tmp_path):
    site = {u.replace("acme.example", "www.acme.example"): h.replace("acme.example", "www.acme.example") for u, h in SITE.items()}
    r = fetch(tmp_path / "out", url="acme.example/help/", site=site,
              get=fake_get(site, {"https://acme.example/help/": "https://www.acme.example/help/"}))
    assert (r["files"], r["host"]) == (3, "www.acme.example")


def test_every_address_is_checked_redirects_included(tmp_path):
    def check(u):
        if "169.254" in u:
            raise UnsafeURL("host not allowed: 169.254.169.254")
        return u
    get = fake_get(SITE, {"https://acme.example/help/": "https://169.254.169.254/latest/"})
    with pytest.raises(sources.Rejected, match="^host not allowed: 169.254.169.254$"):
        sources.fetch_web("https://acme.example/help/", tmp_path / "out", get=get, check=check)


def test_stops_at_the_page_limit(tmp_path):
    r = fetch(tmp_path / "out", max_pages=2)
    assert (r["files"], r["skipped"]) == (2, ["the pages after the first 2 (the limit)"])


def test_a_page_with_no_text_is_refused(tmp_path):
    spa = {"https://acme.example/": '<html><head><title>App</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'}
    with pytest.raises(sources.Rejected, match="no readable text at https://acme.example/. If the site needs JavaScript"):
        fetch(tmp_path / "out", url="https://acme.example/", site=spa)
    assert not (tmp_path / "out").exists()


def test_left_out_parts_end_where_they_end():
    """Menus and forms often leave out optional end tags (</li>, </option>); what follows them is still read."""
    page = sources._Html("https://acme.example/")
    page.feed("""<html><head><title>Acme</title></head><body><nav><ul><li>Home<li>Docs</ul></nav>
        <form><select><option>EN<option>FR</select></form><svg><title>Close menu</title></svg>
        <h2 id="setup">Setup</h2><p>Plug it in.</body></html>""")
    assert page.markdown() == "# Acme\n\n## Setup {#setup}\n\nPlug it in."


class Peer:
    def __init__(self, ip):
        self.ip = ip

    def get_extra_info(self, name):
        return (self.ip, 443) if name == "server_addr" else None


def client(ip, body=b"<p>Hi</p>", ctype="text/html"):
    import httpx

    respond = lambda req: httpx.Response(200, headers={"content-type": ctype}, content=body, extensions={"network_stream": Peer(ip)})  # noqa: E731
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_the_address_actually_connected_to_must_be_public():
    """DNS can answer one way for the check and another for the request: the connection's own address decides."""
    assert sources._http_get(client("93.184.216.34"), "https://acme.example/") == (200, "", "<p>Hi</p>")
    with pytest.raises(sources.Rejected, match="^acme.example connected to a non-public address$"):
        sources._http_get(client("169.254.169.254"), "https://acme.example/")


def test_an_unknown_charset_is_read_as_utf8():
    assert sources._http_get(client("93.184.216.34", ctype="text/html; charset=x-unknown"), "https://acme.example/")[2] == "<p>Hi</p>"


def test_not_a_page(tmp_path):
    with pytest.raises(sources.Rejected, match="^no web page at https://acme.example/nothing$"):
        fetch(tmp_path / "out", url="https://acme.example/nothing")


def test_api_website_source_to_cited_answer(tmp_path):
    """Add a website, publish, and the live version cites the site's own pages; its site may now embed the button."""
    import json
    import time

    from fastapi.testclient import TestClient

    from voicecore import agents
    from voicecore_console.app import create_app

    read = lambda url, dest: sources.fetch_web(url, dest, get=fake_get(SITE), check=lambda u: u)  # noqa: E731
    app = create_app(tmp_path / "console", tmp_path / "agents", setup_token="s", read_site=read)
    with TestClient(app, base_url="http://localhost:8000") as c:
        c.post("/api/setup", json={"token": "s", "password": "correct horse battery"})
        c.post("/api/agents", json={"name": "Acme Docs"})
        r = c.post("/api/agents/acme-docs/sources/web", json={"url": "https://acme.example/help/"})
        assert (r.status_code, r.json()["files"], r.json()["allowed"]) == (201, 3, ["acme.example", "www.acme.example"])
        source = c.get("/api/agents/acme-docs").json()["sources"][0]
        assert (source["kind"], source["label"]) == ("web", "https://acme.example/help/")
        assert c.post(f"/api/agents/acme-docs/sources/{source['id']}/sync").json() == {"files": 3, "skipped": [], "allowed": []}
        assert c.post("/api/agents/acme-docs/publish").status_code == 202
        deadline = time.monotonic() + 60
        while (b := c.get("/api/agents/acme-docs/builds/latest").json())["status"] not in ("done", "failed"):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        assert b["status"] == "done", b["log"]
    bundle = agents.read(tmp_path / "agents", "acme-docs", agents.current(tmp_path / "agents", "acme-docs"))
    assert "https://acme.example/help/billing#refunds" in {p.url for p in bundle.passages}
    assert json.loads((tmp_path / "agents" / "_site" / "origins.json").read_text())["origins"] == ["acme.example", "www.acme.example"]
