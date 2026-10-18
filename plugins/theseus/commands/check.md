---
description: Check the working tree's infrastructure change against main, before a commit or PR
argument-hint: "[what the change is for]"
---

Call the `check_change` tool of the theseus MCP server, with `intent` set to: $ARGUMENTS

Leave `intent` empty if no text was given. Then report as the theseus skill says: the verdict and its reason,
each opened path with every hop's file and line, the impact line, and the fix tested on a graph copy. Offer
to make the fix as an edit. Do not commit.
