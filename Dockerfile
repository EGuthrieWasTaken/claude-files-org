# Org-aware tools for claude-files, as a drop-in replacement for the Emacs Files container.
# Same env vars, port, tokens, /mcp path and volumes as the base image; adds the org_* tools.
FROM ghcr.io/eguthriewastaken/claude-files:1.4.0

USER root
# uvicorn runs from /srv, so a package placed here is importable as `claude_files_org`.
COPY claude_files_org /srv/claude_files_org
RUN python -m compileall -q /srv/claude_files_org
USER 1000:1000

ENV EXTRA_TOOL_MODULES=claude_files_org
