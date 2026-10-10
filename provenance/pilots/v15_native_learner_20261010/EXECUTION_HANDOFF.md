# V15 native learner execution handoff

2026-10-10. Source commit `3ee78fbd157174059cc3bbd52f05ea02938ec754`.
Local branch `SpiralReality/v15-native-learner`; remote
`https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
Prior diagnostics are separated in PR #9, based on
`SpiralReality/v15-5-native-answer`. No merge is authorized for the new work.

The user authorized implementing and validating the end-to-end full-update
learner. The prospective contract is [NATIVE_LEARNER.md](../../../docs/v15/NATIVE_LEARNER.md)
and [NATIVE_LEARNER_PLAN.json](../../../configs/v15/NATIVE_LEARNER_PLAN.json).
The historical frozen-native route is conceptually V14.5; do not rename or
overwrite its files. All old FAIL / winner:none / non-regression unestablished
and closed judge missingness remain.

Furnace isolated checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-v15-native-learner-20261010`.
The source seal is `runs/input/SOURCE_SEAL.json`. Local prepared copy:
`/tmp/latent-v15-build.iBVCF3/SOURCE_SEAL.json`.
280 selected tests passed locally and on Furnace before dispatch. No competing
GPU processes were present at admission. No external APIs or model downloads.

Raw output directories (relative to the Furnace checkout):

- Reader comparison: `runs/v15_native_reader_20261010`.
- Full engineering pair: `runs/v15_native_full_20261010`.

Reader phase completed with its terminal receipt: 16 distinct complete updates,
576 evaluation rows, 80 generated sequences, 140.84586159419268 seconds. The
offline phase verifier passed. Both readers still have 0/4 native donor flips
and workspace strict generation 0/4 at step 8. This is not semantic promotion.
The full engineering phase was then dispatched once on the same sealed source,
after confirming the reader process exited and Furnace GPU was idle again.

## Terminal outcome

Both phases now have `FINISHED.json`, with no FAILED receipt. Full phase:
815.7911780606955 seconds, 576 evaluation rows and 80 generations. Both frozen
and full next-update resumes are exact. Across the phases: 20 distinct updates,
22 executed windows, 1,152 evaluation rows and 160 sequences. Source and raw
receipts verify offline. Full-update native accuracy is 18/32 but donor flips
and strict workspace generation remain 0/4; the updated base alone is 15/32.
The original-base floor and usable semantic binding are not qualified.

A separate read-only file audit rehashed all eight retained checkpoint files
(58,412,456,846 bytes), reconstructed the full step-2 native model from saved
masters exactly, and verified the first bridge/AdamW update matches the frozen
control. It performed zero model forwards/updates. All weights stay on Furnace.
The GPU was idle after the two jobs. No further run, retry or monitor is pending.

Checkpoint directories are separate from publication outputs:

- `runs/checkpoints_v15_native_reader_20261010/{legacy,query_modulated}`.
- `runs/checkpoints_v15_native_full_20261010/{frozen,full}`.

Do not retry, replace or overwrite any started output. Read STARTED/FINISHED/
FAILED receipts and preserve all incomplete outcomes. Reader study budget is
eight complete 16-pair updates per arm. Full pair budget is two updates per arm,
plus one replay of the second update from the first checkpoint in each arm;
the replay does not produce additional generations or saved checkpoints.
The full pair is an independently authorized engineering qualification even if
semantic criteria remain unmet; it is not a declaration of a winning reader.

Use only `spiral` transport and recheck resources before dispatch. Do not delete
old weights, resume judge collection, restart monitoring, change thresholds,
substitute providers or broaden the training budget. Pull JSON receipts only,
not the approximately 54 GiB of full checkpoints. Verify source hashes, raw
index, scalar replay, exact literals, old seals, tests and staged diff before
publication. Update this handoff with terminal outcomes; never claim that
engineering completion qualifies the held-out original-base floor.
