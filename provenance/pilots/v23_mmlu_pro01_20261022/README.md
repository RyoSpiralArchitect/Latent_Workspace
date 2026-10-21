# V23 MMLU-Pro 01 — inputs prepared; execution blocked

Frozen source `49b628db18cc284aedc26a3e57459eacce61d7a0`, 783 source files.
[Design](../../../docs/v23/MMLU_PRO_01.md),
[plan](../../../configs/v23/MMLU_PRO_01.json).
All 280 selected test rows and 70 five-shot examples were tokenized without
truncation. The nested generation panel has 28 rows. Max direct context:
1,306 tokens; max five-shot context: 2,713 tokens. Pinned tokenizer revision:
`c170c708c41dac9275d15a8fff4eca08d52bab71`. Original Parquet body SHA-256,
selected IDs, prompts, answers, tokens and file hashes are retained.

CPU qualification: **245/245 PASS**, zero skips/failures/errors,
57.023658 seconds. However, this process (PID `3785302`) initialized a CUDA
context while a different authorized evaluation was running. Its 522,190,848
GPU bytes were observed by that evaluation's exclusive-client guard, which
stopped P-on. **CPU test success is not GPU-isolation success.** The related
[failure record](../v23_comparison01_20261022/README.md) includes exact PID
attribution. The first CUDA-initializing call is not yet isolated.

**CUDA qualification: NOT_DISPATCHED. All 840 MMLU-Pro direct scores and all
84 reasoning sequences: NOT_DISPATCHED.** No weights were loaded for this
benchmark, no updates/saves/deletions occurred, and no retry was sent. The
predecessor gate remains closed because original comparison 01 is incomplete.
No benchmark score is available. Dataset preparation is not evaluation.

Remote source:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v23-mmlu-pro01-20261022`.
Remote output:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-mmlu-pro01-20261022`.
Both existing source and output stay immutable. A separate approved recovery
must add CPU GPU-invisibility before imports and explicit context checks,
preserve old receipts, and bind any separately recovered predecessor in a new
plan. Do not edit this plan/seal or reclassify the old failure as success.

No monitoring automation was created. Old **FAIL / winner:none /
non_regression NOT_ESTABLISHED** is unchanged.
