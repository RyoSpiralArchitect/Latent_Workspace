# V15.5 execution handoff

Client date: 2026-10-10. This file records the launch, not a completed study.

- Repository: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-ft-v14-semantic-chat`.
- Branch: `SpiralReality/v15-5-judge-diagnostics`.
- Remote: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Paid source: `59ac10623c0f088d61481e1cfbb9898c206002b5` (pushed).
- Bundle: `provenance/pilots/v15_5_diagnostic_judge_20261010`.
- OpenAI calibration finished: 16 valid, 15 expected-field matches, 6/8 equal
  repeat signatures, **FAIL**. Its study must remain undispatched.
- Mistral calibration finished: 16 valid, 16 expected-field matches, 8/8 equal
  repeat signatures, **PASS**.
- Mistral study launched at `2026-10-09T20:19:01.884412+00:00`, 544 planned
  requests (512 r0 plus 32 fixed r1 repeats). Local exec session: `4213`.
  Progress is retained in `mistral/study/calls/*/OUTCOME.json`; terminal status
  is `mistral/study/FINISHED.json`.
- This uses local CPU and the official Mistral API, not Furnace/GPU. No weights,
  learner updates, or new learner generations are involved.
- Completion follow-up: thread heartbeat `v15-5-judge-run-completion`, every
  ten minutes while active; no routine progress notifications.
- Post-calibration local checks: 241 selected tests passed; Ruff passed; all
  79 sealed source/input files revalidated; the original cue verifier returned
  `VERIFIED_RECEIPTS` with its expression gate still `FAIL`. These are local
  checks, not CI or a substantive model qualification.

## Immutable boundaries

Do not change any file in the source seal, prompt, schema, data, request
manifest, calibration threshold, or provider setting. Do not relaunch an
already-started cell or retry a failed request. A terminal API/transport failure
halts new dispatch and requires a separate recovery decision; preserve all
missing rows. Do not run the OpenAI study, substitute a provider, or start new
training. Existing secrets must never be printed or copied into artifacts.

## Once the admitted study terminates

1. Read `FINISHED.json` and replay both providers from stored outcomes. Report
   failure, invalidity, truncation, and missingness explicitly. A partial run is
   not a completed 512-response study.
2. Run the frozen summarizer with `--write` **only if `analysis/` does not yet
   exist**, then `--verify`. If it already exists, verify rather than overwrite.

   ```sh
   PYTHONPATH=src:scripts .venv/bin/python scripts/summarize_v15_5_diagnostic_judge.py --bundle provenance/pilots/v15_5_diagnostic_judge_20261010 --write
   PYTHONPATH=src:scripts .venv/bin/python scripts/summarize_v15_5_diagnostic_judge.py --bundle provenance/pilots/v15_5_diagnostic_judge_20261010 --verify
   ```

3. Write an additive English results README, preserving the old gate and the
   blocked OpenAI denominator. Interpret Mistral diagnoses alongside the machine
   axes, 32 fixed repeats, all strata, and verbatim human panel. Use identified
   examples only as illustrations, not representative independent evidence.
   Distinguish calibration pass, complete collection, and substantive claims.
4. Update the root README and `docs/v15/NEXT_STEPS.md` without touching frozen
   evidence. Propose, but do not execute, any learner change. Keep the base
   correctness floor, semantic direction, and qualitative response qualities as
   separate requirements; this base-only diagnostic tests none of their learned
   improvement claims.
5. Verify the original cue bundle and new source seal, run the relevant tests
   and Ruff, scan publishable artifacts for credentials/unrelated content, and
   check the staged diff. Commit and push only this branch after verification.
   Do not create or merge a PR without further user direction. Report local
   checks and push separately from CI (no workflow exists here).

The final cross-provider summary is expected to retain
`INCOMPLETE_OR_CALIBRATION_BLOCKED` even if all 544 admitted Mistral requests
finish: OpenAI was correctly blocked. Do not “repair” that status into success.
