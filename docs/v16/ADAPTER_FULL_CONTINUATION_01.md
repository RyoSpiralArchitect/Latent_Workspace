# Full-only adapter migration, continuation 01

2026-10-14. Ryō explicitly approved **only the never-dispatched full mode in a
separate process**. This is an additive engineering continuation, not a retry
of frozen work, a new reader factor or authorization for repeated recovery.

## Immutable parent and exact selected work

The [original terminal bundle](../../provenance/pilots/v16_adapter_migration_20261014/README.md)
is pinned in full: 26 files including raw receipts, source seal, prelaunch tests,
offline verification and historical README. Canonical manifest SHA256:
`643300b3ec9468933d7ab68e9d03aedf3d3a9450fe6077bc0ff3c6540b5f034c`.
Its source is `7c3af3c70df31a69bbe624532dbcd516dbb195a0`; its terminal status
stays **INCOMPLETE_NO_RETRY**, with frozen exactness/replay and 80/160 pairs.
There are no original full-mode model, update, pair-journal or checkpoint files.

The [continuation selection](../../configs/v16/ADAPTER_FULL_CONTINUATION_01.json)
admits only full: old-reference and adapter-v2, two complete 16-pair windows
each, then adapter step1→window2 serialized replay. **4 unique + 1 replay
windows = 80 backward pairs**. The original frozen 80 pairs are reused only
as evidence. Total combined intended budget remains 160, not 240.

## What changes, and what does not

[The additive entry](../../scripts/continue_v16_adapter_full.py) calls the
original sealed `arm`, `replay`, checkpoint, paired-loss and CPU-accumulation
functions unchanged. It never edits their plan's two-mode list or patches a
runtime method. The sole execution-layout change is a new process containing
only full mode. A new committed checkout/source seal owns that selection and
its checkpoint metadata; both full arms share the new identity. No cross-source
checkpoint restore is attempted.

Model/revision, seed47, data/order, initial bridge, native BF16/SDPA, six losses,
Adafactor/AdamW, two updates, live features, snapshot ownership and exact
comparisons are unchanged. All [original resource gates](ADAPTER_MIGRATION.md)
remain: 31-GiB device-free admission, 30.5-GiB Torch cap, 0.75-GiB device-free
stop, 100/24-GiB host admission/stop, 64-GiB retained-output forecast plus
50-GiB remaining disk, 32-GiB full snapshot/write forecasts, 7200-second budget.
New admission is checked before work and again at `full:admission`, just as in
the original. No competing GPU process is allowed; none may be stopped.

A clean isolated pre-import launcher checks the new source before project
imports. The complete original bundle and original source hashes are checked
before dispatch and after a successful run. Output and checkpoint directories
must be new, outside source and on one persistent filesystem. Every exception
is terminal **INCOMPLETE_NO_RETRY** with partial journals retained. Do not resume
or retry without another human decision.

## Offline and scientific interpretation

`verify-original` and `verify --bundle .../raw` are strictly offline: no Torch,
model load or API call. They check source hashes, the literal file set, complete
ordered pair journals, old/new initial/update states, contexts, saved replay
state, and denominators. Checkpoint binary reload remains the live run's duty.

Only if full matches and replays may the combined engineering view be
`EXACT_7B_MIGRATION_PASS_ACROSS_TWO_PROCESSES`; the original terminal receipt
must remain incomplete. This qualifies the unchanged common reader's migration,
not the as-yet-unintegrated V16 slot-contrast reader or cross-runtime equality.
Old **FAIL / winner:none / non-regression NOT_ESTABLISHED** remains. No new
generation, judge, checkpoint deletion, semantic long run or merge is included.

[Continuation evidence](../../provenance/pilots/v16_adapter_full_continuation_01_20261014/README.md)
now records terminal **INCOMPLETE_NO_RETRY**: legacy full 32/32 pairs completed,
but adapter construction rejected an unowned duplicate HF input-gradient hook
before its first pair. CPU construction-only diagnosis reproduced the same
production-helper failure; no repair/retry occurred. Combined evidence is
112/160 pairs, with frozen only qualified. All initial criteria above remain
unchanged rather than being retrospectively relaxed.
