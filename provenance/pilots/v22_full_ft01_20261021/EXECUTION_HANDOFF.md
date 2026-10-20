# V22 full-FT 01 — execution handoff

**Terminal failure recorded:** `raw/FINISHED.json` is `INCOMPLETE_NO_RETRY`.
The canary completed two updates and its save. Replay restored step 1 exactly
and matched its first backward row, then stopped when device free memory was
440 MiB, below the unchanged 768-MiB minimum. Training A/B were undispatched.
The worker has exited; do not restart it. See [results](README.md).

This is one already-started bounded run, not permission to create another run.
No heartbeat/recurring monitor was created. The finite dispatcher owns the
four authorized roles and stops at the first unsuccessful role.

## Exact locations

- Local repository: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`
- Local branch: `SpiralReality/latent-memory-full-ft`
- Origin: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`
- **Execution source:** `3c6da4218526cbaaf4690efe6910a2dc493d004b`, pushed to that branch.
- Furnace execution worktree:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v22-full-ft01-20261021`
- Furnace run bundle:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-full-ft01-20261021`
- Furnace data bundle:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-data01-20261021/bank`
- Runtime Python:
  `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python`
- Historical tmux session: `ltws-v22-full-ft01-20261021`; its worker has exited.

Use `spiral`, not reconstructed SSH. Do not pull/checkout/edit the execution
worktree while the run exists. Later local documentation/verifier commits are
not a replacement for its 717-file source seal.

## Established at dispatch

CPU and CUDA qualification each passed **290/290**, without failures, skips
or exclusions. Their terminal files and XML are under `furnace/qualification`.
The two local macOS isolated-child dependency failures remain recorded in the
data validation note; they were not silently deleted from the suite.
The offline verifier replayed the complete source seal and both qualifications.

The English-only bank and every training/dev/canary key are frozen. Planned
training exposure is **32 updates / 723 unique rows / 20,860 supervised tokens**;
none of these training updates was dispatched in this trial.
No Japanese rows, quarantined teacher prose, test/OOD rows or benchmark labels
are training inputs. The parent banks are untouched. See
[the plan](../../../docs/v22/FULL_FT_01.md) and
[data record](../../data/v22_english_mixture01_20261021/README.md).

## Existing worker and terminal conditions

The dispatch was started once in the named tmux session. Its PID/command are
recorded in `raw/STARTED.json` and `raw/DISPATCH_<role>.json`. The first observed
canary child PID was **3173956**; use receipts and process identity, not that
number alone, for future checks.

The fixed role order is `canary → replay → train_a → train_b`:

- Canary: two long mixed updates, save `canary_step1.pt`, hash step-2 payload.
- Replay: fresh process restore and bit-exact step-2 replay. No weight save.
- Train A: fresh original model (not canary weights), frozen dev baseline,
  training updates 1–16, save `training_step16.pt`.
- Train B: fresh process restore 16, exact state/history/cursor check,
  training updates 17–32, save `training_step32.pt`, same dev NLL panel.

The top-level `raw/FINISHED.json` is the terminal authority. The success status
is `V22_NATIVE_TRAINING_32_STEPS_COMPLETE_NOT_QUALITY`. Successful physical
updates total 35, of which only 32 are training; total backward row occurrences
are 737. A missing terminal is not success, and a completed partial role is
not complete training.

The complete terminal raw tree is now copied here and verified offline.
The old source, all terminal files and the sole canary checkpoint remain.
A cache-boundary repair/new trial and conditional single-checkpoint retirement
were presented to Ryō as separate recovery decisions; this handoff does not
grant them. No weight has been deleted or fresh trial launched.

On an error or process death: preserve all partial outputs, missingness and
checkpoint bodies. No retry, changed seed/length/LR/threshold, provider call,
new generation, weight deletion, beta replacement, HF upload or PR merge is
authorized by this handoff. Request a recovery decision if needed. Do not
restart a stopped dispatcher or rerun any completed role.

## Offline follow-through

Pull only finished role artifacts while another role is running; do not
publish a torn snapshot as a terminal manifest. After top-level termination,
pull the complete `raw` tree and replay:

```bash
python3 scripts/verify_v22_full_ft.py \
  --bundle provenance/pilots/v22_full_ft01_20261021/furnace \
  --repo . \
  --data provenance/data/v22_english_mixture01_20261021/furnace
```

This verifier is offline, post-dispatch tooling. It reads the **execution
commit's** blobs, not the current HEAD as a substitute. `NO_TERMINAL` is an
explicit partial state, not zero activity. Optional `--checkpoints` can verify
actual weight bodies where they reside; without it, file receipts do not claim
independent weight-file hashing. Keep the raw data tokens/weights on Furnace.

Record planned versus completed denominators, actual peaks, checkpoint sizes,
exact replay, fresh train resume, and before/after fixed-dev NLL. Report loss
changes as development diagnostics, not broad benchmark non-regression.
The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** stays unchanged.
No final quality or release decision follows from training completion alone.
