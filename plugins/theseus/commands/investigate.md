---
description: Ask the access graph a question - who reaches what, how, and what if something is compromised
argument-hint: "<question, e.g. what if casey-contractor is compromised?>"
---

Answer this with the theseus MCP server's graph tools: $ARGUMENTS

Choose the tools the question needs (the theseus skill's table says which), call them, and answer from their
output only. Name each path hop by hop with its file and line, and say which targets hold sensitive data. When
the answer shows a risk, end with the smallest fix: `min_cut`, then `simulate_fix` to test it on a graph copy.
Say UNKNOWN wherever a tool did.
