// Wraps the whole site and never unmounts (Docusaurus "Root"), so the voice widget and its session survive
// page changes. When an answer cites a section, the widget dispatches "voicecore:navigate"; we change the
// route without a reload, scroll to the cited heading and highlight that section.
import React, { useEffect } from "react";
import { useHistory } from "@docusaurus/router";
import useDocusaurusContext from "@docusaurus/useDocusaurusContext";

const HEADINGS = ["H1", "H2", "H3", "H4"];

// The elements of one section: the heading and its siblings up to the next heading of the same or higher
// level. Without an anchor, the page's opening text (before the first ## heading).
function sectionOf(id) {
  const root = document.querySelector(".theme-doc-markdown");
  if (!root) return null;
  if (!id) {
    const intro = [];
    for (const el of root.children) {
      if (el.tagName === "HEADER") continue;
      if (HEADINGS.includes(el.tagName)) break;
      intro.push(el);
    }
    return intro;
  }
  const heading = document.getElementById(id);
  if (!heading || !root.contains(heading)) return null;
  const level = HEADINGS.indexOf(heading.tagName);
  const out = [heading];
  for (let el = heading.nextElementSibling; el; el = el.nextElementSibling) {
    const l = HEADINGS.indexOf(el.tagName);
    if (l !== -1 && l <= level) break;
    out.push(el);
  }
  return out;
}

// The new page renders after the route change: wait until the old page's content is gone and the section
// exists (up to about 3 s), then reveal it.
function reveal(id, old = null, tries = 180) {
  const fresh = document.querySelector(".theme-doc-markdown") !== old;
  const section = fresh && sectionOf(id);
  if (!section?.length) {
    if (tries > 0) requestAnimationFrame(() => reveal(id, old, tries - 1));
    return;
  }
  document.querySelectorAll(".vc-cited").forEach((el) => el.classList.remove("vc-cited"));
  section.forEach((el) => el.classList.add("vc-cited"));
  const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  (id ? section[0] : document.documentElement).scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
}

export default function Root({ children }) {
  const history = useHistory();
  const { siteConfig } = useDocusaurusContext();

  useEffect(() => {
    if (!document.querySelector("script[data-voicecore]")) {
      const s = document.createElement("script");
      s.src = "/embed/voicecore.js";
      s.dataset.voicecore = "";
      s.dataset.endpoint = siteConfig.customFields.gateway;
      s.dataset.title = "Ask the docs";
      s.dataset.name = "VoiceCore docs assistant";
      document.body.append(s);
    }
    const onNavigate = (e) => {
      const url = new URL(e.detail.url, location.href);
      if (url.origin !== location.origin) return; // another site: the widget opens it in a new tab
      e.preventDefault();
      const id = decodeURIComponent(url.hash.slice(1));
      const page = url.pathname !== location.pathname;
      const old = page ? document.querySelector(".theme-doc-markdown") : null;
      if (page || url.hash !== location.hash) history.push(url.pathname + url.hash);
      reveal(id, old);
    };
    addEventListener("voicecore:navigate", onNavigate);
    return () => removeEventListener("voicecore:navigate", onNavigate);
  }, [history, siteConfig]);

  return <>{children}</>;
}
