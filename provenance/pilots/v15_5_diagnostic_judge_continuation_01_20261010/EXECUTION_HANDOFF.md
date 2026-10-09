# V15.5 continuation 01 execution handoff

Client date: 2026-10-10 (Asia/Tokyo). **FROZEN_NOT_DISPATCHED** at this prelaunch
checkpoint. The following authorized scope must not expand automatically.

## Exact scope and lineage

- Checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-ft-v14-semantic-chat`.
- Branch: `SpiralReality/v15-5-judge-diagnostics`.
- Remote: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Parent partial-result commit: `5a27d0d663dfd3e3a6f607256fe0201439929386`.
- Original paid source: `59ac10623c0f088d61481e1cfbb9898c206002b5`.
- New bundle: `provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010`.
- Protocol: [continuation 01](../../../docs/v15_5/DIAGNOSTIC_CONTINUATION_01.md).
- Target: exactly 320 Mistral study r0 requests that had never been dispatched.
  Manifest hash: `5259a36f5afa912191af349503925aaa3e351a05e1e5fd8138f3e4c072bdb766`.
- New source and request selection: [CONTINUATION_SEAL.json](CONTINUATION_SEAL.json).
  All 1,042 files in the original bundle and the original 79-file source seal
  remain unchanged. Never edit the original bundle, even its historical README.
- Mistral calibration PASS is reused. The same model ID, body, seed, temperature,
  caps, timeout, concurrency and dispatch spacing are used. No provider or rubric
  substitutions. No new calibration calls or learner generations.
- The four ambiguous original requests and one invalid repeat are **excluded**,
  not retried. OpenAI's calibration FAIL and all 544 undispatched study requests
  remain excluded. Overall status stays `INCOMPLETE_OR_CALIBRATION_BLOCKED`.
- All 274 selected local tests passed (33 new continuation checks); Ruff passed;
  original cue receipts verified with expression gate **FAIL**. This is not CI
  or scientific qualification. [Prelaunch receipt](PRELAUNCH_VALIDATION.json).

## Launch and monitoring

The source must be committed before the one authorized launch. `STARTED.json`
records its exact commit, PID and start time. The process is local CPU plus the
official Mistral API, not Furnace. `caffeinate` may prevent idle sleep only while
the owned process runs; it is not a job restart mechanism.

After launch, inspect `mistral/study/calls/*/OUTCOME.json` and the exact process.
Do not re-run `run --execute`, even if only a STARTED or RESERVATION exists.
No automatic retries. A new HTTP/transport failure stops dispatch and drains
in-flight requests. Process loss without FINISHED requires a recovery decision.
Unknown remote execution/billing must remain unknown.

## Terminal publication, offline only

Once `mistral/study/FINISHED.json` exists, replay the original and continuation
before interpreting results. These commands make no API calls:

```sh
PYTHONPATH=src:scripts .venv/bin/python scripts/continue_v15_5_diagnostic_judge.py verify
PYTHONPATH=src:scripts .venv/bin/python scripts/continue_v15_5_diagnostic_judge.py write-analysis
PYTHONPATH=src:scripts .venv/bin/python scripts/continue_v15_5_diagnostic_judge.py verify-analysis
```

Use `write-analysis` only if this bundle's `analysis/` is absent. If present,
verify without rewriting. The original analysis is never changed. The combined
view preserves every original reservation, all 512 main records, 32 fixed repeat
coordinates, both calibrations, and the 1,120-request original plan denominator.
It counts calibration usage once and links each main Mistral row to its raw
source bundle. At best, 508/512 main diagnoses will be valid; four remain unknown.

Prepare an English results README here with all completed/invalid/unknown/
undispatched denominators, repeat disagreements, usage, exact original-output
illustrations, missingness limits and the unchanged old FAIL. Update root README
and `docs/v15/NEXT_STEPS.md` with bounded interpretation and proposed learner
factors only. No training or new learner generations, new judge requests,
threshold/rubric changes, provider substitutions, source-seal edits or weight
deletion. Any additional completion effort needs a separate human decision.

Verify both seals, the original cue bundle, the selected 274 tests, Ruff, literal
panel replay, report numbers/links and staged publication. Preserve trailing
spaces inside original-output fences. Scan for credentials/unrelated content.
Check branch/remote/staged diff, then commit and push **only this branch**. Do not
create or merge a PR. Record local checks separately from CI (no workflow here).

Update the existing heartbeat `v15-5-judge-run-completion` to monitor only this
new continuation while running. Keep routine progress quiet; report completion,
failure or a required decision in Japanese. Pause it after recording the terminal
handoff, including a partial terminal result if another failure occurs.
