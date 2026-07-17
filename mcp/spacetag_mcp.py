#!/usr/bin/env python3
"""spacetag-mcp — an MCP server exposing the `spacetag` CLI to any MCP client.

PARKED SPIKE — not wired up. See mcp/README.md for the "when is this worth it"
rationale (short version: only when a client that CAN'T run a shell — Claude
Desktop / claude.ai / phone — needs to drive your Spaces by talking to Claude).

Enable:  pip install mcp
         claude mcp add spacetag -- python3 "$(pwd)/spacetag_mcp.py"
"""
import json
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

SPACETAG = shutil.which("spacetag") or "/opt/homebrew/bin/spacetag"
mcp = FastMCP("spacetag")


def _json(*args):
    out = subprocess.run([SPACETAG, *args], capture_output=True, text=True)
    return json.loads(out.stdout or "[]")


@mcp.tool()
def list_spaces() -> list:
    """List macOS Spaces: 1-based index, uuid, whether it's current, and project tag."""
    return _json("dump")


@mcp.tool()
def list_windows() -> list:
    """List every window with the Space it's on (geometry only; no window titles)."""
    return _json("windows")


@mcp.tool()
def goto_space(target: str) -> str:
    """Switch to a Space by tag label, 1-based index, or uuid (e.g. 'izzit', '4')."""
    r = subprocess.run([SPACETAG, "goto", target], capture_output=True, text=True)
    return "ok" if r.returncode == 0 else (r.stderr.strip() or "failed")


if __name__ == "__main__":
    mcp.run()  # stdio transport; the client spawns this as a child process
