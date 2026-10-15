# Full adapter preparation repair, recovery 02

2026-10-14. Ryō approved the proposed repair → composed tiny tests → separate
missing-adapter/replay attempt. This is not a new semantic FT experiment.

## Failure retained, ownership repaired

Installed Transformers 5.15.0's `gradient_checkpointing_enable` already calls
`enable_input_require_grads` for text input. The historical engine helper calls
the second method again. This leaves two live embedding hooks but tracks only
one handle. The strict readout adapter correctly rejects the unowned first hook.
Direct-HF tests had not exercised this composed production path.

The additive [preparation boundary](../../src/latent_workspace_ft_v10/native_training_preparation.py)
owns exactly one native input-gradient hook and non-reentrant checkpoint policy.
Repeated identical preparation is a no-op. It checks the installed method
sources, native bound methods, handles/aliases and policy; it does not silently
remove old duplicates or admit arbitrary hooks. The historical engine and strict
readout guard remain byte-for-byte unchanged. This is a qualified HF setup
boundary, not a promise of compatibility with arbitrary runtimes/architectures.

The 22 composed tests cover four tiny model families (Mistral, GPT-2, OLMo2,
Gemma2), FP32/BF16, values/parameters/RNG, forward/all-gradient equality,
idempotence, negative hook/policy cases, two complete Mistral 16-pair updates and
serialized next-update replay against the historical preparation path. CUDA
qualification uses the same sealed tests, 4-GiB allocation cap and 300-second
limit, before any 7B dispatch. Tiny success is not a 7B memory/quality result.

## Exact selection and provenance

- Original frozen bundle: 26 immutable files, source `7c3af3c70df31a69bbe624532dbcd516dbb195a0`.
- Full continuation 01: 20 immutable files, source `6bf83985f02575a83aefe9817f1afcea7baa832e`.
  Manifest SHA256 `49c2b861805a1208e433011fa1dac9ed4c9e109161891bfb295a37acb1efbd2a`.
  Its legacy full 32 pairs are retained as the exact reference. Adapter work
  stopped before its first INITIAL/CONTEXT/pair receipt. Both historical terminal
  statuses remain INCOMPLETE_NO_RETRY, including their historical handoffs.
- Recovery 02 selects only full adapter-v2 steps 1/2 and step1→window2 replay:
  **2 unique + 1 replay windows = 48 pairs**. No frozen/legacy arm is redispatched.
  Combined maximum is still 8 unique + 2 replay windows = 160 pairs, not 192.

[The execution selection](../../configs/v16/ADAPTER_FULL_RECOVERY_02.json) and
[additive entry](../../scripts/run_v16_adapter_full_recovery_02.py) reuse the
unchanged complete-window, six-loss, CPU accumulation, FP32-master optimizer,
state fingerprint and v2 snapshot math. The fresh construction explicitly uses
owned preparation. It does not monkeypatch the old runner/helper at runtime.

The candidate contract may differ from the retained reference only in its
explicit source commit and added preparation receipt. All other contract keys,
initialization, feature receipts, losses, ordered per-pair accumulated gradient
hashes, native/bridge/master/optimizer/RNG states must match exactly. There is no
floating-point tolerance, skipped tensor or normalized state hash. The new
preparation/source/selection/reference provenance is owned by its checkpoints;
restore is within this new source, never across source contracts.

## Resource and stop boundaries

All original thresholds remain: 31-GiB cold-start admission, 30.5-GiB Torch cap,
0.75-GiB free-device stop, 100/24-GiB host admission/stop, 64-GiB durable-output
forecast with 50 GiB remaining, 32-GiB snapshot/write forecasts, two CPU threads
and 7200-second run budget. No competing compute client may be displaced.
The old legacy peak does not qualify the adapter's full backward/snapshot/restore.

A source-sealed fresh detached checkout and separate exclusive output/checkpoint
directories are required. A new error, mismatch, resource stop or missing terminal
receipt is not permission for another attempt. Preserve partial evidence and
ask Ryō for a new decision. No repeated recovery, generation, API judge, weight
deletion, semantic factor, merge or scheduled monitor is included.

The [offline verifier](../../scripts/verify_v16_adapter_full_recovery_02.py) checks
all three provenance sets, exact reference comparison, serialized replay receipts
and complete denominators without importing Torch or loading checkpoint binaries.
Only full update **and** replay equality can finish this engineering migration.
Even then old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains;
the new V16 slot-contrast reader is still a separate unintegrated prototype.

## Rethinking the boundary

Preparation is part of the native adapter's owned execution contract, not an
incidental helper call. Qualify the actual production composition (setup →
binding → complete-window update → snapshot → restore), not just its components.
Keep model-specific context extraction and native arithmetic in bindings; keep
losses, reader mechanism and optimizer policy separate. This repair removes a
setup failure, not the already-observed lack of reliable donor-directed use.

## Result

The [completed evidence](../../provenance/pilots/v16_adapter_full_recovery_02_20261014/README.md)
passes 295/295 ordinary CPU regressions and 22/22 source-isolated CUDA cases.
The source-sealed 7B attempt then completed all 48 selected pairs with exact
full updates and serialized replay, 1,164.569855 seconds total. Combined with
the untouched original/continuation evidence, the engineering migration now
has 160/160 pairs, 8/8 unique windows and 2/2 replays. Both historical terminal
failures remain unchanged. The next gate is new-reader state ownership, not a
claim of semantic improvement or a dispatch of V16 FT.
