# V23 state factorial 01 — execution handoff

## Authorized scope

Ryō requested finer separation of question encoding and the later reader,
exact copy and base preservation, with the original workspace intent restored
to V23 planning. This is **frozen V22 analysis only**, zero new training,
generated sequences, paid judges, checkpoint saves/deletion or releases.

Checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
Branch: `SpiralReality/latent-memory-full-ft`.
Remote: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
Starting head: `07922f832905227260985f51856aba3b6cc53af9`.

The exact execution source will be the commit containing the initial frozen
[plan](../../../../configs/v23/STATE_FACTORIAL_01.json), runner and tests;
the remote `SOURCE_SEAL.json` is authoritative. No source patch in place after
launch. Outputs are exclusive and all old bundles/checkpoints stay unchanged.

## Furnace execution

- Worktree: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v23-state-factorial01-20261021`.
- Output: `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-state-factorial01-20261021`.
- Runtime: existing `worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`.
- Launcher: `scripts/launch_v23_state_factorial.sh EXACT_SOURCE_COMMIT`.
- Selected qualification: 216 tests each CPU and CUDA, 4 GiB / 900 s per device.
- Roles: base, V22, base-cross, each a fresh process; no retries.
- Planned unique cells: 4,728 world + 2,280 MMLU; journal entries include
  623 world / 570 MMLU repeated base references, totaling 8,201 entries.
- Full self parity: 2,386 prefixes; repeated base endpoint parity: 1,193.
- Two cut-state banks under 7 GiB combined are activation artifacts, not weights.
  Keep remotely with hashes; publish small records, explicitly mark omissions.

Runtime doctor passed, with its existing modelopt/transformers warning retained.
Native PyTorch is required for intermediate-state exchange and exact complete-
owner restoration; managed serving cannot implement this graph. No environment
changes. Admission observation: idle GPU, 119 GiB host available, ~75 GB disk.

## Completion / stop policy

Inspect existing receipts and process only while running. On terminal success,
verify source seals, complete bank bytes/tensors, all self/repeated/historical
parity, exact denominators and unchanged checkpoint identity. Publish the full
factorial, paired loss/repair and interaction analysis plus the original claim
ceiling. No post-result hybrid promotion or training on these exposed examples.
On failure keep all artifacts, missingness and the terminal error; do not
retry or change a gate without a separate recovery decision.

No recurring automation is created. **FAIL / winner:none / non_regression
NOT_ESTABLISHED** remain unchanged.
