# V23 recovered blind judge — existing process only

## Terminal handoff, 2026-10-22

**Complete; do not dispatch again.** Terminal at 02:41:47 UTC / 11:41 JST:
174 returned, 170 valid, four invalid exact-quote failures, zero undispatched
or unknown. Offline replay matches all response bytes and terminal analysis.
[Results](README.md) retain 13/72 main-pair order conflicts, two unjudged pairs,
four repeat disagreements out of 12, all six identical-control judgments,
usage and every final judgment. No extra API calls were made for publication.
Ryō's current request authorizes a PR for the accumulated branch; it supersedes
the launch-era no-PR restriction below, **not** the prohibitions on new runs,
training, deletion, merge or release. No heartbeat monitor is active.

## Historical launch and progress record

Launched once **2026-10-22T00:38:46.077221+00:00** (09:38 JST).
Local PID **40812**, executor session **92242**.
Source **`b2f569740636e2cffb80e4091323d551ea7de4c2`**.
Study seal SHA-256:
`2810f0fe338fc5518dfb3cd0879451c7a9db4ff9a8196838d466438ea17089a5`.
Calibration terminal SHA-256:
`70397d488d8bcb9852d0a5f22676b67d5d003ae834ae361eb603e444c70e7b81`.

Checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`,
branch `SpiralReality/latent-memory-full-ft`, remote
`https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
Output: this directory's `study/run`. All 174 requests verified undispatched
before this single launch; exact metadata model identity passed. Inspect
`STARTED.json`, existing PID, per-cell outcomes and `FINISHED.json` before action.
Never run/resume the command again. No heartbeat monitor was created.

While running, preserve the frozen study and every source in its seal and
adapter binding. Read-only progress inspections do not authorize new calls.
If the process stops without a terminal receipt, or dispatch halts on a
transport/HTTP error, retain missingness and seek a new decision. No retries,
extra calls, substitutions, threshold/rubric changes or repaired outcomes.

After terminal, run the offline `scripts/v23_recovered_judge.py verify` with:

- output: `provenance/pilots/v23_recovered_behavior_judge01_20261022/study`
- original: `provenance/pilots/v23_comparison01_20261022/furnace`
- recovered: `provenance/pilots/v23_comparison_recovery02_20261022/furnace`
- calibration: `provenance/pilots/v23_behavior_judge01_20261022/calibration`

Then publish exact denominators, completion/invalid/unknown status, usage,
order conflicts, repeated disagreements and all identical-control outcomes.
Only analyze paired valid/equivariant outcomes with visible exclusions; never
turn calibration PASS or different answer text into a preference result.
Save all raw response/receipt bytes and exact illustrative answer/judge text.
The complete 72-answer bank already exists; no new learner generation is needed.
No PR, merge, training, saved weights, deletion, export or release.

At the 00:44 UTC inspection, four returned outcomes replayed VALID, one
request was in flight (reserved with no outcome yet), and 169 were not
dispatched. The live replay labels that unresolved reservation
`UNKNOWN_REMOTE_EXECUTION`; it is not an observed timeout/error. PID 40812
remained alive. This snapshot is not a final denominator or preference result.
