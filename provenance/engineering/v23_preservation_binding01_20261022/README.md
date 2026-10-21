# V23 preservation-target binding — offline preparation

This is additive preparation while the separately frozen
[gradient audit](../v23_gradient_audit01_20261022/README.md) continues, not its
terminal analysis, a new teacher run, or objective integration. Its remote
source remains `66467502064b08b1ea8e246edc6696bd9d35a60e`. No additional 7B
forwards, optimizer updates, checkpoint saves, private data transfers or
deletions are performed by this preparation. The local regression suite does
exercise synthetic tiny-model forward/backward instruments on CPU.

The new engine-owned
[`preservation_binding`](../../../src/latent_workspace/preservation_binding.py)
validates a caller-pinned teacher receipt and all complete ordered train rows,
records the causal logit positions, and rejects metadata/row mismatches. The
binding is immutable and its exported descriptor omits the input tokens.
It is model-layout independent; synthetic vocabulary tests include 17, 32,768
and 64,000 entries. The English-only data policy is explicit, not a claimed
architectural limitation.

**Metadata only:** real tensor bodies are not opened or admitted. File integrity,
normalization, teacher execution, optimizer integration and a new-objective
restart remain separate requirements. The current owner still rejects CE+KL;
its source, arithmetic and v1 checkpoint contract are unchanged. This does not
turn the 12-row audit reference into a full-FT preservation bank.

The [implementation contract](../../../docs/v23/OBJECTIVE_OWNER_CONTRACT.md)
specifies the proposed CE/KL denominators, strict P-off parity, target-binding
boundary, new state/restart fields and the distinction between V22 warm-start
and exact resume. It selects no 7B coefficient, starting checkpoint or P/B/I
winner, and dispatches no trial.

Local checks pass **142/142, no failures/errors/skips**, recorded in
[LOCAL_TESTS.xml](LOCAL_TESTS.xml) and [LOCAL_VALIDATION.json](LOCAL_VALIDATION.json):
50 new binding/old-owner-rejection cases, 39 objective-instrument cases,
28 gradient-spill cases, 13 source-launcher cases, six architecture checks and
six actual-audit-runner cases. Ruff passes. The local runtime is Python 3.13.13,
PyTorch 2.11.0 and Transformers 4.57.6; this is not a pinned Furnace qualification.
All 761 files in the existing audit's source seal remain byte-identical.
The pinned remote audit and its
338/338 CPU/CUDA qualification are a separate evidence source, not validation
of this new module. No new GPU job or recurring monitor is started.

## Live audit observation, not a terminal receipt

At **2026-10-22 02:23:48 JST**, the [read-only observation](AUDIT_PROGRESS_OBSERVATION.json)
found the same V22 worker still present and the remote source worktree clean.
Both preservation terms had finished their 12 rows / 932 targets, and world
total had finished 84 rows / 532 targets. The identity log contained 33 complete
row records out of 84; identity/copy/format/mixed summaries and the parent/V22
terminal receipts were absent. This is a sequential live read, not an atomic
snapshot, completed analysis, or prediction of its eventual outcome.

The next terminal publication must still use the original
[handoff](../v23_gradient_audit01_20261022/EXECUTION_HANDOFF.md) and offline verifier,
into a new `furnace/` sibling. Do not relaunch the job or overwrite its immutable
`interim_furnace/` record. Metadata preparation is not a reason to change the
ongoing audit or act on partial conflict signs.

Unchanged ceiling: **FAIL / winner:none / non_regression NOT_ESTABLISHED**.
