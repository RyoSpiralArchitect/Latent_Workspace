# Native full-FT branch: review map and terminal evidence

This PR targets **main** from **SpiralReality/latent-memory-full-ft**. It covers
the accumulated native full-FT implementation, V22 training/diagnosis, V23
matched P-only training and completed evaluation. It is not just an MMLU-Pro
score change. Most changed files are immutable source/data/run evidence; review
the implementation and the evidence indexes separately. No weight body or
provider credential belongs in Git. Do not squash away source commits used by
the sealed `git archive <commit>` replay without retaining their reachability.

## Suggested review order

1. **Question and current conclusion:** [evaluation synthesis](EVALUATION_SYNTHESIS.md),
   [full-FT architecture](../v1_0/FULL_FT.md), [workspace revival](WORKSPACE_REVIVAL.md).
   The native path trains writer, question-side computation, reader and native
   vocabulary head; it does not replace the frozen-host beta's public claim.
2. **Graph and state authority:**
   [native_memory.py](../../src/latent_workspace/native_memory.py),
   [native_owner.py](../../src/latent_workspace/native_owner.py),
   [optimizer_state.py](../../src/latent_workspace/optimizer_state.py),
   [offload.py](../../src/latent_workspace/offload.py),
   [native owner contract](../v1_0/NATIVE_OWNER.md).
   Check empty-memory native parity, shared-parameter gradient ownership,
   CPU FP32 masters/BF16 projection, accumulation denominators, poisoned-state
   behavior, v1/v2 objective ownership and exact fresh-process restore.
3. **Preservation and data boundary:**
   [preservation_objective.py](../../src/latent_workspace/preservation_objective.py),
   [preservation_binding.py](../../src/latent_workspace/preservation_binding.py),
   [objective contract](OBJECTIVE_OWNER_CONTRACT.md), [P-only plan](PRESERVATION_FT_01.md),
   [data provenance](../v1_0/DATA_PREPARATION.md).
   Check full-vocabulary targets, whole-context/causal-position binding,
   denominator/no-op behavior, objective identity in checkpoints and exclusion
   of exposed diagnostics from training. Teacher text quarantine is not training.
4. **Diagnostics are not causal overclaims:**
   [native_causality.py](../../src/latent_workspace/native_causality.py),
   [state_factorial.py](../../src/latent_workspace/state_factorial.py),
   [objective_audit.py](../../src/latent_workspace/objective_audit.py),
   [gradient_spill.py](../../src/latent_workspace/gradient_spill.py),
   [W/Q/R results](../../provenance/pilots/v23_state_factorial01_20261021/README.md),
   [gradient audit](../../provenance/engineering/v23_gradient_audit01_20261022/TERMINAL.md).
   State interventions do not create disjoint trainable parameter groups.
5. **Evaluation validity:**
   [native_evaluation.py](../../src/latent_workspace/native_evaluation.py),
   [v23_mmlu_pro.py](../../scripts/v23_mmlu_pro.py),
   [v23_behavior_judge.py](../../scripts/v23_behavior_judge.py),
   [v23_recovered_bank.py](../../scripts/v23_recovered_bank.py),
   [qualification_isolation.py](../../scripts/qualification_isolation.py),
   [v23_generation_cache.py](../../scripts/v23_generation_cache.py).
   Check selected IDs, ties, strict parses, unchanged caps, normalized AB/BA,
   repeats, invalid literal quotes, CPU isolation and no retry/resume semantics.
6. **This publication layer:**
   [MMLU-Pro offline replay](../../provenance/pilots/v23_recovered_mmlu_pro02_20261022/analyze.py),
   [judge offline replay](../../provenance/pilots/v23_recovered_behavior_judge01_20261022/analyze.py),
   [publication regressions](../../tests/test_v23_evaluation_publication.py).
   These read retained outputs; they cannot launch the original study or a model.

## Evidence index

| Milestone | Primary record | What it does not establish |
| --- | --- | --- |
| Native 7B two-update/restart | [identity recovery](../../provenance/engineering/native_7b_identity_recovery01_20261020/README.md) | Quality or long-run retention |
| V22 32-update full FT | [training recovery](../../provenance/pilots/v22_full_ft_recovery01_20261021/README.md) | General benchmark/generation gains |
| V22 observed regressions and memory causality | [comparison](../../provenance/pilots/v22_base_comparison01_20261021/README.md), [next steps](../v22/POST_DIAGNOSTIC_NEXT_STEPS.md) | Arbitrary new latent reasoning |
| V23 32+32 matched P-only FT | [terminal](../../provenance/engineering/v23_preservation_ft01_20261022/TERMINAL.md) | A retention winner from CE/KL loss alone |
| Complete base/off/on readout | [comparison](../../provenance/pilots/v23_comparison_recovery02_20261022/README.md) | Original incomplete dispatcher becoming complete |
| 840-score/84-sequence MMLU-Pro | [terminal results](../../provenance/pilots/v23_recovered_mmlu_pro02_20261022/README.md) | Leaderboard equivalence or causal workspace use |
| 174-request blind judge | [terminal results](../../provenance/pilots/v23_recovered_behavior_judge01_20261022/README.md) | Human gold or universal evaluator reliability |

Keep the failed evidence: [original comparison isolation stop](../../provenance/pilots/v23_comparison01_20261022/README.md),
[CPU collection recovery stop](../../provenance/pilots/v23_comparison_recovery01_20261022/README.md),
[MMLU-Pro inactive-reservation stop](../../provenance/pilots/v23_recovered_mmlu_pro01_20261022/README.md),
and earlier native-owner/identity/length/restart failures linked by the root
README. Subsequent attempts have separate sources and explicit authority;
partial original P-on rows and interrupted reasoning are never silently filled.
Historical approved retirement ledgers are evidence, not permission for new deletion.

## Validation and review scope

The original matched FT source `b46f04caefcfd596ccde3b0af8fd886d859f11b7`
has historical 472/472 CPU and CUDA qualification and exact real-model v2
restart. Whole recovered P-on uses `af9cd1a727d98d942df1845c35a14628f8f7481b`
with 248/248 on each device. MMLU-Pro and the paid judge bind
`b2f569740636e2cffb80e4091323d551ea7de4c2`; MMLU-Pro has historical
315/315 CPU and CUDA plus isolation. These are different sealed gates,
**not** fresh qualification of the eventual PR head.

This publication was checked on local CPU only, without model/provider calls.
The local Python/Torch/Transformers environment differs from the historical
Furnace runtime; do not equate publication checks with a new full-engine suite.
The exact local test command/result and artifact checks are in
[LOCAL_VALIDATION.md](LOCAL_VALIDATION.md). Replay instructions are in each
result README. Native model weight bodies are not needed to replay these records;
the MMLU-Pro literal/prompt replay additionally needs the pinned local tokenizer.

Review is requested for correctness and reproducibility, **not merge/release
authorization**. No GPU work was started while Aether occupied Furnace. There
is no new training, generation, API judging, deletion, merge or HF publication
in this publication turn. Unchanged gate: **FAIL / winner:none /
non_regression NOT_ESTABLISHED**.
