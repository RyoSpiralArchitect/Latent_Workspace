# Native-memory 7B canary — execution handoff

Authorized scope: two unique native full-parameter updates, save steps 1/2,
then one exact step-2 replay from step 1 in a fresh process. This is not a
full training population, quality evaluation or release. No retries, generation,
paid judge, further deletion, PR merge or Hub upload.

- Execution source: `59188535516eb32d57a42fb23fa4a7cc91585511`.
- Plan: `configs/v1_0/NATIVE_7B_CANARY.json`, canonical SHA-256
  `ecb1058c32a4647cf4486710e4eec0fb0670a59139e34be63a7f4c8a9f206a71`.
- Local branch: `SpiralReality/latent-memory-full-ft`, worktree
  `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
- Origin: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Furnace source:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-native-7b-canary-attempt02-20261020`.
- Furnace output:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-native-7b-canary-attempt02-20261020`.
- Interpreter:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.

The output root holds `SOURCE_SEAL.json`, `qualification/{cpu,cuda}`, `raw/`
and `checkpoints/` if those stages have started. Before a 7B dispatch, both
qualification devices must finish **229/229**, no skipped/failed/error cases.
The 20 additional verifier tests are local; 249 local tests pass.
The [prelaunch-01 record](../native_7b_canary_prelaunch01_20261020/README.md)
retains the prior source's CPU-only qualification, superseded before CUDA/7B
dispatch because the tokenizer API default was not represented by the stub.

Inspect `STARTED.json` and `DISPATCH_<role>.json` for actual process identities;
never trust a PID without matching its command. While an existing process runs,
preserve its files and do not dispatch another. After terminal completion, pull
only `SOURCE_SEAL.json`, `qualification/` and `raw/`, **not checkpoint bodies**.
Run the offline `scripts/verify_native_7b_canary.py --bundle <copied root> --repo .`.
An incomplete terminal receipt or absent terminal after process exit requires
recording the partial denominators and deciding recovery, not an automatic retry.

Record exact token counts, updates, per-role resource peaks, checkpoint bytes,
native BF16 changes, replay status and source hashes in the results README.
Keep old **FAIL / winner:none / non_regression NOT_ESTABLISHED** unchanged.
No heartbeat or recurring monitor is created.

## Terminal handoff — 2026-10-20

**INCOMPLETE_NO_RETRY**, dispatcher 24.740 s, primary 22.614 s. CPU and CUDA
both passed 229/229. The original-model load completed, then the legacy
identity assertion failed before owner construction or any training forward.
The plan accidentally binds the historical tree-hash digest to the legacy
hash function. See [the diagnosis and exact source-backed values](README.md).
The actual hash was not persisted; present-cache identity remains unverified.

Replay was never dispatched. Both terminal receipts keep native activity
`null`; no update or checkpoint was reached on the identified source path.
The checkpoint directory is empty and the recorded processes have exited.
The [16 copied execution files](furnace/) retain the original bytes; offline
source/qualification/terminal verification returns
`VERIFIED_INCOMPLETE_NO_RETRY`.

Do not dispatch, resume or edit this source or its raw outputs. A separately
authorized repair must use a new source and new paths, qualify CPU and CUDA
again, preserve both hash schemes explicitly and persist actual identity
measurements before comparison. The same bounded update/replay scope and
resource limits apply; full training and quality evaluation are still gated.
