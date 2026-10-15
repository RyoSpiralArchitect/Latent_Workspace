# Full-only real-Mistral migration: legacy completed, adapter admission blocked

2026-10-14. Terminal **INCOMPLETE_NO_RETRY**. The fresh process passed the
unchanged 31-GiB start gate and completed both full legacy updates. Adapter
construction then rejected an unowned input-gradient hook, **before its first
training pair**. This is not OOM, numerical divergence, full equivalence or a
semantic win. No automatic retry or repair was applied.

Executed source: `6bf83985f02575a83aefe9817f1afcea7baa832e`,
[513 sealed source files](SOURCE_SEAL.json), Python3.12.14, Torch2.13.0+cu132,
Transformers5.15.0, CUDA13.2. The [fixed selection](../../../configs/v16/ADAPTER_FULL_CONTINUATION_01.json)
and [execution contract](../../../docs/v16/ADAPTER_FULL_CONTINUATION_01.md)
admitted only full mode, with all old math and thresholds unchanged.

## Denominators and retained evidence

| Evidence | Unique update windows | Replay windows | Backward pairs | Exact mode qualification |
|---|---:|---:|---:|---|
| Original run | 4/8 | 1/2 | 80/160 | Frozen only |
| Full-only continuation | 2/4 | 0/1 | 32/80 | None; adapter not dispatched |
| Combined, no duplicate work | 6/8 | 1/2 | 112/160 | Frozen only; full incomplete |

Here, a completed unique window is **not** an old/new equivalence pass. The
two new windows both belong to the legacy reference. Adapter: 0/2 updates,
0/1 replay and 0/2 checkpoints. Its original base was loaded and hash-checked,
but construction failed before a context, initial-state or pair receipt.
The reference retains complete hashes/receipts, not restorable weight binaries,
as planned. The new checkpoint directory is empty; no files were deleted.

[FINISHED.json](raw/FINISHED.json) seals nine raw companions (10 raw files
including FINISHED). [SUMMARY.json](SUMMARY.json) records the derived counts
and resources. [Offline verification](OFFLINE_VERIFY.json) passes literal
integrity/denominators, **not** the blocked engineering experiment. The
combined status remains **INCOMPLETE**. No large checkpoint was reloaded offline.

The [original 26-file bundle](../v16_adapter_migration_20261014/README.md), its
510 source hashes and incomplete terminal receipt remain unchanged. Its SHA256
is `643300b3ec9468933d7ab68e9d03aedf3d3a9450fe6077bc0ff3c6540b5f034c`.
The completed frozen comparison/replay is preserved and was not rerun.

## Failure localization: duplicate HF input-gradient registration

Exact exception: `ValueError: Training adapter rejects unqualified native hooks`.
The traceback in FINISHED leads through `MistralTrainingBinding` into
`HFTrainingReadoutAdapter._validate`, before adapter learner construction.

The installed Transformers5.15.0 `gradient_checkpointing_enable` already calls
`enable_input_require_grads` for this text model. The sealed
[engine helper](../../../src/latent_workspace_ft_v10/engine.py) calls it again.
The second call replaces `_require_grads_hooks` while the first registered
embedding hook remains active. The strict
[training adapter](../../../src/latent_workspace_ft_v10/hf_training_readout.py)
requires both the exact installed hook code and tracked-handle ownership;
therefore it correctly refuses the leftover registration.

The post-terminal [CPU construction-only diagnosis](HOOK_DIAGNOSTIC.json)
reproduces this using the same installed runtime and sealed helper:

- Direct HF checkpointing: one hook, one tracked handle, adapter accepted.
- Historical helper: two hooks, only the later handle tracked; the earlier hook
  is rejected and the exact production exception recurs.
- Two tiny random model constructions; **zero forward/backward/update calls,
  checkpoint writes, downloads, generation or judge calls; CUDA uninitialized**.

The [diagnostic script](HOOK_DIAGNOSTIC.py) is separately hash-receipted and runs
only after checking the existing sealed checkout. It is additive post-failure
diagnosis, not part of the real-run source seal or a new 7B attempt.

The existing [tiny adapter-owner tests](../../../tests/test_adapter_native_learner.py)
call HF checkpointing directly, so they do not exercise the production helper's
second registration. Their prior passes remain true within that narrower scope;
they did not qualify this composition. Do not solve this by admitting arbitrary
hooks or weakening the source/ownership gate.

## Resource observations, limited to executed work

Elapsed: **679.930067 seconds** (11.33 minutes). Peak Torch allocated/reserved:
**27.751084 / 28.353516 GiB**. Minimum sampled device free: **2.203125 GiB**;
minimum sampled host available: **57.878460 GiB**. Process peak RSS:
**88.163403 GiB**. Sampling does not bound unsampled host peaks.

These cover legacy full training and adapter construction, **not** adapter full
backward, independent checkpoint snapshot or restore. No memory limit was
loosened. After exit, Furnace returned to 10 MiB used, no compute clients and
119 GiB host available; persistent free space was 267,192,778,752 bytes.

Each legacy update changed all **291/291 FP32 base masters**, including all
**65/65 RMSNorm masters**. Native BF16 changes occurred in 237/291 base tensors
per step (123,205,237 and 174,891,214 elements respectively). Bridge changes
were 18/26 then 26/26 tensors. These are update instrumentation, not accuracy,
base-preservation or content-binding evidence.

## Tests, next decision and claim ceiling

[Prelaunch tests](PRELAUNCH_TESTS.xml): **186/186 passed in 23.87 seconds**,
comprising 29 new continuation checks plus the preceding 157 cases. These are
ordinary local CPU tests, including
full-only routing/no-retry stubs, immutable-parent and scope guards, synthetic
publication mutations, and the existing tiny update/resume checks. Stub/synthetic
cases are not real-7B results. The runtime launch and source seal are separate.
[50 additional source-launcher/runner/adapter tests](ADDITIONAL_REGRESSION_TESTS.xml)
passed in 8.66 seconds. Those tests also do not repair the production-helper gap.
[The final combined local rerun](FINAL_TESTS.xml) passed **236/236** selected
cases in 32.24 seconds; Ruff and 157 publication-link checks passed. This reruns
the same 186+50 cases, not 236 additional independent observations. No CI result
is inferred from local tests.

Next proposal, **not executed**: qualify one owned, idempotent input-gradient
setup in an additive adapter path; test the exact production preparation entry
before any optimizer work, keep arbitrary/untracked hook rejection, and renew
complete-window/replay checks. Freeze a new source/selection before considering
the still-unexecuted adapter and replay work. Reuse the retained legacy reference
only under an explicit cross-source compatibility/comparison contract; do not
silently rerun either completed reference or frozen mode.

[The terminal handoff](EXECUTION_HANDOFF.md) records the stopped process and
pending recovery decision. No V16 slot-contrast training, learner generation,
paid judge, new weight deletion, heartbeat or merge occurred.

Old **FAIL / winner:none / non-regression NOT_ESTABLISHED** stays unchanged.
