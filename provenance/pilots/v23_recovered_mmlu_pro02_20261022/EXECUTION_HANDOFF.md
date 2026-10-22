# V23 recovered MMLU-Pro 02 — authorized separate launch

## Terminal handoff, 2026-10-22

**Complete; do not relaunch.** The dispatcher and all three arms terminated
successfully: 840 direct rows, 84 reasoning sequences, 17,005 generated tokens.
The full bundle was pulled and replayed locally; [results](README.md) and
[all literal reasoning outputs](analysis/REASONING_BANK.md) are published.
Base/off/on direct correctness is 92/101/100 of 280; strict parsed reasoning
correctness is 11/9/8 of 28. Missingness, ties and format failures remain visible.
The current human request authorizes a PR for this accumulated branch, not a
merge, release, fresh run, training or deletion. Aether was not disturbed.
No monitor is active. The launch/progress observations below are historical.

## Original launch record

Launched once **2026-10-22T00:39:17Z** (09:39 JST).
Committed source: **`b2f569740636e2cffb80e4091323d551ea7de4c2`**.
Furnace source:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v23-recovered-mmlu-pro02-20261022`.
Output:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-recovered-mmlu-pro02-20261022`.
tmux: `ltws-v23-recovered-mmlu-pro02-20261022`, initial pane PID **3829068**.

The worktree was clean at the exact commit. Complete recovered-bank verification
passed with original base/off plus whole recovered on (79 original partial
scores excluded). Prelaunch disk free was 57,045,671,936 bytes, GPU usage 10 MiB,
no compute clients. Managed runtime doctor returned `ok:true`, retaining its
existing ModelOpt/transformers-version warning. No environment was modified.
The explicit native-graph/strict-restore PyTorch exception remains documented.

CPU→CUDA qualification passed **315/315 each**, zero skips/errors/failures,
within **4 GiB / 900 seconds**. CPU visibility audit passed (153 samples, no
own GPU clients); CPU 81.156651 seconds, CUDA 85.653395 seconds, CUDA peak
67,325,952 bytes. Their immutable files are copied here and replayed by
`verify_qualification.py`. Base subsequently started. This is not terminal
model success. Do not rerun or resume. On any new failure preserve all files
and seek a new decision; do not weaken resource floors or change inputs,
shots, decoding, checkpoint selection or scoring. All original attempts remain.

After terminal completion pull the whole bundle, replay source/manifest/XML/
isolation, original inputs and every score/parse, cache audit, unchanged native
weights and paired IDs. Report all base-wrong/FT-correct and reverse transitions,
ties, unparsed/capped answers and complete/planned denominators. Do not splice
the 280 retained base rows from attempt 01. Planned scope: 840 direct scores
and 84 reasoning sequences. No training, model weight save/deletion, judge
calls from this job, export or release. No heartbeat monitor was created.

## Nonterminal observation, 2026-10-22T00:44:29Z

Base has 280 direct rows and one complete reasoning sequence (119 tokens, EOS).
Its direct journal SHA-256 is
`c629c3563a105b22ebd56fbc8e73d94a8f3b97af21f1d3225512eae8ff7d580e`,
byte-identical to all 280 direct rows retained in stopped attempt 01. The
previous generation:107 stopping point was passed, and a later sequence
reached generation:168. Across 288 cache-audit rows every live before/after
allocation was equal. The last observed reservation was 14,665,383,936 bytes,
with 18,308,136,960 free GPU bytes. These are a progress snapshot, not peak
resource guarantees or proof that all 84 sequences will finish. No terminal
dispatcher receipt existed; continue the existing process only.
