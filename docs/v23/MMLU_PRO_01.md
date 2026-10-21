# MMLU-Pro diagnostic 01 — fixed before any scoring

This implements the [additional evaluation](ADDITIONAL_EVALUATION_01.md).
The source dataset is pinned to `b189ec765aa7ed75c8acfea42df31fdae71f97be`.
Both original Parquet bodies were downloaded once and matched the Hugging Face
LFS SHA-256 and byte lengths; 12,032 test / 70 validation rows were read.
Selected rows and all validation examples are in the compressed
[panel](../../configs/v23/mmlu_pro01_20261022/PANEL.json.gz), with
[source/selection receipt](../../configs/v23/mmlu_pro01_20261022/MANIFEST.json).

Selection is SHA-256 order of `v23-mmlu-pro01-20261022:category:question_id`,
20 test rows per category, 14 categories, **280 rows**. Within each stratum,
the first two selected rows form a nested **28-row reasoning panel**. No model
answer, logit, gold label or rationale affects selection. Five original
validation examples of the same category are shown in their original order.
Test rationales/gold answers never enter the model prompt. N/A options are
removed with explicit answer remapping; validation rationale letters cannot
silently change. Selected exact test/example overlaps are rejected.

## Two endpoints, no pooled or leaderboard score

1. **Zero-shot chat direct choice:** 280 per arm, 840 total. Score the stable
   one-token letter continuations A through the actual option count (4–10 in
   this panel). Keep all option logits, target log probability, gold-vs-best-
   other margin, first-maximum prediction, ties and tie-free correctness.
   Full-vocabulary argmax is recorded, not restricted during any generation.
2. **Five-shot chat reasoning generation:** 28 per arm, 84 new sequences total.
   Greedy, seed 20261022, 1,024-token symmetric cap, EOS=2, full vocabulary.
   The prompt requests a brief explanation and an explicit final option marker.
   Same 4,096-token prompt ceiling, **no prompt truncation or shot reduction**;
   a preparation failure blocks execution. Use no KV cache, the already
   qualified native full-prefix evaluator, with no workspace facts injected.

These are custom, bounded, native diagnostics, **not** the official full
MMLU-Pro score. Chat elicitation, caps, strict parser, fixed shots and backend
differ from the upstream evaluation. The upstream dataset motivates keeping
reasoning separate from direct probability scoring. Benchmark test data is
never admitted to training, preservation targets or checkpoint selection.

An explicit `answer is (X)` or `Answer: X` marker must be in range; conflicting
markers remain unparsed. Bare-letter guesses/random fallback are disallowed.
Report (a) literal parsed answer correctness including cap stops and (b)
EOS-complete correctness separately. An unparsed/capped row stays in the full
denominator, with its status alongside it. Correct final letters do not prove
correct reasoning; preserve the literal explanations for later reading.

Against each FT arm, publish both-correct / base-only / candidate-only /
both-wrong counts and IDs, plus all subject denominators. Candidate-only means
the base was wrong **under this exact protocol**, not intrinsically incapable.
The balanced aggregate is a macro-style diagnostic, not a population-micro
estimate. Twenty items/subject and two reasoning items/subject are small.
Pretraining contamination and overlap with historically exposed MMLU are not
excluded. No generalization, non-inferiority or release claim follows alone.

## Execution gate

Wait for comparison 01 to complete successfully and replay its entire manifest.
Recheck Furnace contention and the unchanged 31-GiB GPU / 100-GiB host /
50-GiB disk admission floors. Create a separate clean source worktree; never
modify either completed FT or running comparison source. Qualify all **245
tests on CPU and CUDA**, zero skips/failures/errors, <=4 GiB and <=900 seconds
per device. This reuses 223 native/owner/restore tests plus 22 new dataset,
parsing, denominator and entire mock-runner tests.

Run base, P-off, P-on in separate processes, <=4 hours each. The original
checkpoint bytes, all owner state, v2 teacher bank and original run contract
are verified before the common inference transition. Check native hashes
before/after and empty-memory bypass parity. No optimizer update or saved
weight is created. A failed role stops subsequent roles; no automatic retry,
extension, prompt adjustment or provider substitution.

Local development: 22/22 new tests pass. The first parser test caught whitespace
required before `Answer:`; this was fixed before input freeze/model execution.
Combined local checks: 241 passed, four fresh isolated-process cases could not
import the macOS environment's `typing_extensions`. This is not a qualification
pass or a reason to omit them: all 245 must run on Furnace. No environment was
changed. Old **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.
