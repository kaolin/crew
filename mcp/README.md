# spacetag-mcp (parked spike)

A ~40-line MCP server that wraps the `spacetag` CLI so **MCP clients that can't run a
shell** — Claude Desktop, claude.ai, phone — can drive your macOS Spaces by *talking*
to Claude: *"what am I working on?"*, *"take me to izzit."*

**Status: not built / not wired up.** crew and terminal sessions already shell the
`spacetag` CLI directly, so this adds a process + a dependency for zero gain *there*.
It only earns its keep when the consumer has **no terminal** (a chat client), or wants
structured, autonomous tool-use mid-task.

## If/when you want it

```
pip install mcp
claude mcp add spacetag -- python3 "$(pwd)/spacetag_mcp.py"
```

Then any Claude client can call `list_spaces`, `list_windows`, `goto_space`.

## Notes

- **stdio transport:** the client spawns it as a child process (~10–30 MB idle, ~0%
  CPU) — not a daemon you babysit; it dies with the session.
- `goto_space` visibly switches Spaces — keep it user-initiated, not autonomous.
- Needs **spacetags ≥ 0.1.1** (the `dump` / `goto` / `windows` CLI).
