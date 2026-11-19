"""Org-aware MCP tools for claude-files (extension API v1)."""

__version__ = "0.1.0"
REQUIRES_API = 1

from .tools import INSTRUCTIONS, register  # noqa: E402,F401
