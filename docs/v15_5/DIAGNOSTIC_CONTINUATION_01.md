# V15.5 diagnostic continuation 01: only never-dispatched requests

Client date: 2026-10-10. This is a separately authorized execution continuation,
not a revised experiment or permission to retry failed calls.

Following the terminal partial report, Ryō approved completion of the proposed
320 **never-dispatched** Mistral requests. The parent record is commit
`5a27d0d663dfd3e3a6f607256fe0201439929386`. The original paid source remains
`59ac10623c0f088d61481e1cfbb9898c206002b5`.

## Fixed boundary

- Original bundle: `provenance/pilots/v15_5_diagnostic_judge_20261010`.
- New, exclusive bundle:
  `provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010`.
- Select exactly the 320 `not_dispatched` rows from replay of the original
  terminal cell; every selected row is Mistral study replicate 0. Selection
  preserves the original opaque-ID order and exact request bodies. It is not
  selected by new outcomes, scores, or model opinion.
- Exclude every original reservation: 219 valid diagnoses, one invalid repeat,
  and four ambiguous timeout outcomes. Do not resubmit, repair, or overwrite any.
- Preserve the original bundle byte-for-byte, including its partial analysis,
  historical README and handoff. Seal its entire file inventory separately.
- Reuse the frozen Mistral calibration PASS and metadata identity receipt;
  no new calibration or model-discovery request is needed. The remote weight
  revision remains UNKNOWN, and a temporal continuation is not proven to use
  immutable remote weights.
- Keep `mistral-large-4`, temperature 0.2, original random seed 15501, output cap
  16,384, original HTTP body/schema, official endpoint, 1,200-second timeout,
  at most four concurrent calls and at least two seconds between starts.
- Reuse the previously authorized Mistral environment key without printing or
  copying it. No new credential or OpenAI access is involved.
- Preserve the four timeout outcomes with unknown remote execution/billing,
  the invalid repeat, and OpenAI's calibration FAIL and 544 undispatched study
  calls. Never interpret absent usage as zero cost.

## Execution and replay

The additive runner is `scripts/continue_v15_5_diagnostic_judge.py`. It imports
the unchanged original request builder, validators, HTTP transport, reservation
writer and raw replay. `freeze` writes an exclusive selected manifest and seal.
Source and seal must be committed before `run --execute`; the runner checks the
branch, remote, lineage, source hashes and original bundle before dispatch.

`STARTED.json` is exclusive and prevents relaunch, even when no response was
recorded. Each HTTP dispatch gets an exclusive request directory and reservation.
There is no retry loop. A terminal HTTP/transport/recording failure stops new
admission and drains already in-flight calls. Process loss or an incomplete
reservation requires another explicit decision, not an automatic resume.

Offline `verify` performs no network request. After `FINISHED.json`,
`write-analysis` creates a new combined snapshot once; `verify-analysis` checks
it without overwriting. The combined view overlays only formerly undispatched
coordinates, preserving the 512 main / 32 repeat denominators, unchanged repeats,
original machine truth, exact output text, and separate raw provenance.
Original calibration usage is counted once, not once per bundle.

The maximum improvement in coverage is 508/512 valid main diagnoses, assuming
all 320 selected calls yield valid results. Four original main calls remain
unknown; the repeat panel remains 31 valid pairs and one invalid pair.
Cross-provider status must remain `INCOMPLETE_OR_CALIBRATION_BLOCKED`, and the
old expression gate remains **FAIL**. A completed dispatch grid is not complete
validity, independent human gold, a learner result, or a non-regression claim.

## Completion handoff

Follow only this bounded process. While it runs, do not launch, resume, or edit
any call or source. At termination, replay both bundles, publish a source-backed
English report with all denominators, usage, invalidities, repeat disagreements
and literal examples, and update the root README and `docs/v15/NEXT_STEPS.md`
with bounded conclusions and proposed factors only. Preserve the prior report.
Verify the cue bundle, both seals, tests and publication artifacts before a
branch-only commit/push. No PR, merge, training, learner generations, provider
substitution, rubric/threshold changes, or weight deletion is authorized.
Pause the existing completion heartbeat after recording the terminal handoff.
