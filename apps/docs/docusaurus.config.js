// VoiceCore docs: a docs-only Docusaurus site. The voice assistant indexes docs/ (voicecore/answer/ingest.py)
// and opens the page and section it cites (src/theme/Root.jsx).
const { themes } = require("prism-react-renderer");

// The gateway the embedded widget talks to. The browser only ever gets a short-lived session token from it.
const GATEWAY = process.env.VOICECORE_GATEWAY ?? "http://localhost:8080";
// The Cloudflare Turnstile sitekey (public). Unset locally: the widget then skips the human check.
const TURNSTILE_SITEKEY = process.env.TURNSTILE_SITEKEY ?? "";

module.exports = {
  title: "VoiceCore Docs",
  tagline: "Build, measure and tune a real-time voice agent",
  favicon: "img/favicon.svg",
  url: process.env.DOCS_URL ?? "http://localhost:3000",
  baseUrl: "/",
  onBrokenLinks: "throw",
  // .md is CommonMark (no JSX, so "<" and "{" are plain text); .mdx would be MDX
  markdown: { format: "detect", hooks: { onBrokenMarkdownLinks: "throw" } },
  i18n: { defaultLocale: "en", locales: ["en"] },
  customFields: { gateway: GATEWAY, turnstileSitekey: TURNSTILE_SITEKEY },
  stylesheets: [
    { href: "https://fonts.googleapis.com/css2?family=Inter:wght@400..700&family=JetBrains+Mono:wght@400..600&display=swap", rel: "stylesheet" },
  ],
  headTags: [
    { tagName: "link", attributes: { rel: "preconnect", href: "https://fonts.googleapis.com" } },
    { tagName: "link", attributes: { rel: "preconnect", href: "https://fonts.gstatic.com", crossorigin: "anonymous" } },
  ],
  themes: [
    [
      "@easyops-cn/docusaurus-search-local",
      { hashed: true, indexDocs: true, indexBlog: false, indexPages: false, docsRouteBasePath: "/", highlightSearchTermsOnTargetPage: true },
    ],
  ],
  presets: [
    [
      "classic",
      {
        docs: { routeBasePath: "/", sidebarPath: require.resolve("./sidebars.js") },
        blog: false,
        theme: { customCss: require.resolve("./src/css/custom.css") },
      },
    ],
  ],
  themeConfig: {
    navbar: {
      title: "VoiceCore",
      logo: { alt: "", src: "img/favicon.svg" },
      items: [
        { to: "/", label: "Docs", position: "left", activeBaseRegex: "^/(?!reference|results)" },
        { to: "/results", label: "Results", position: "left" },
        { href: "pathname:///console/", label: "Console demo", position: "left", target: "_self" },
        { to: "/reference/wire-protocol", label: "Reference", position: "left", activeBaseRegex: "^/reference" },
      ],
    },
    footer: { style: "dark", copyright: "VoiceCore Lab: a voice AI systems portfolio. Every number on these pages is labelled with how it was measured." },
    colorMode: { defaultMode: "light", respectPrefersColorScheme: true },
    prism: { theme: themes.oneLight, darkTheme: themes.oneDark, additionalLanguages: ["bash", "json", "go", "python"] },
    tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 3 },
  },
};
