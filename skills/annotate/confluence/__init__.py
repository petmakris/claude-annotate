"""Publishing an annotate document to Confluence.

Nothing in this package talks to Confluence. The Atlassian API is reachable
only through MCP tools, which the model calls and a subprocess cannot, so
these modules render a bundle on disk and `references/publishing.md` carries
the call sequence. That split is deliberate: it keeps every deterministic
part — anchor resolution, markdown conversion, image rendering — under test.
"""
