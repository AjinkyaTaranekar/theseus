"""Everything that knows a vendor or a format, one package per adapter (docs/spec/08-core-and-adapters.md).

Each package implements one protocol in `theseus/contracts/adapters.py` and imports only `theseus.contracts`,
`theseus.errors` and itself. Core code never imports from here; `cli.py` and `api/app.py` pick the adapters.
"""
