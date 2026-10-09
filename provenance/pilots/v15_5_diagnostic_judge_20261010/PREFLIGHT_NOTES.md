# V15.5 preflight history

Client date: 2026-10-10. No learner generation or training.

## JSON round-trip failure before any API request

The initial candidate passed **240 selected tests in 20.52 seconds** and Ruff.
It prepared all 1,120 request bodies with an undiscounted conservative bound
of USD 118.173444 (not an invoice). The first metadata command then failed
inside `load_frozen()` before output-directory creation, credential access, or
HTTP dispatch:

```text
ValueError: Dataset no longer matches the frozen bank
```

The independent fact oracle returned its edges as Python tuples, while JSON
persisted them as lists. The serialized dataset was correct, but the in-memory
regeneration comparison was not round-trip stable. This is a harness defect,
not a judge result or a changed semantic gate. The failed source/seal is retained
in the initial protocol commit. The correction makes oracle edges JSON-native
and adds a dataset serialization round-trip test before any paid call.

All 512 original responses, machine labels, calibration expectations, requested
judge settings, request bodies, and acceptance thresholds remain unchanged.
