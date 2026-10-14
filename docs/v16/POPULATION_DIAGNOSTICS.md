# V16 population diagnostics and public-benchmark preservation screen

2026-10-15. Authorized expansion of evaluation, **not additional training**.
The [fixed plan](../../configs/v16/POPULATION_EVAL_PLAN.json) evaluates pinned
original Mistral-7B-Instruct-v0.3 and the three existing step-2 full-update
checkpoints. Do not change any source, weights, thresholds or loss during a run.

## Questions and denominators

1. Is useful slot variation present after normalization and centering?
2. Does query-conditioned attention select that variation rather than cancel it?
3. Does the resulting residual reach native answer direction, not just other logits?
4. Does the full-updated base retain correctness on a fixed public test subset?

The original pilot covered two exposed worlds. This diagnostic freezes **128
new world pairs, 1,024 reciprocal queries, 256 affected and 768 unaffected**.
Four fresh data seeds contribute 32 world pairs each. Text-only graph traversal
checks every target. Neither side's ranking order may overlap any of the 320
historical training/evaluation world pairs or another selected world. Entity
names and query templates are shared: this is not entity/template holdout.
There is still only **one model-training seed (47), two training worlds, and two
updates per trained arm**. More evaluations do not create training replications.

Each trained arm retains all ten historical memory controls and five paired
transport factors. Per arm: 10,240 workspace rows, 1,024 direct-base rows,
5,120 factor rows, and 2,048 additional read-only slot traces. The original model
provides 1,024 direct-base rows. Reciprocal queries are correlated; confidence
intervals resample whole worlds within the four data-seed strata.

The additive observer measures normalized and centered slot norms, attention
distance from uniform, read versus uniform-query read, pre-cap output, remaining
norm budget, and production interaction output. Its reconstructed interaction
must exactly match production. Attention weights use a separate observer
recomputation; its difference from the production SDPA read is retained, and
those shadow weights never replace production activations. FP64 transport
projections remain diagnostic-only. No gain sweep or precision change is made.

## MMLU: paired, descriptive, not a leaderboard or workspace claim

The source is [cais/mmlu](https://huggingface.co/datasets/cais/mmlu), revision
`c30699e8356da336a370243923dbaf21066bb9fe` (MIT). Dataset Viewer split metadata
was checked; `all/test` and `all/dev` parquet bytes are hashed in the
[input manifest](../../configs/v16/population_20261015/INPUTS.json).
The [upstream evaluator](https://github.com/hendrycks/test/blob/master/evaluate.py)
provides the five-shot plain-text prompt layout. No upstream API calls or retry
loop are used. The test selection is fixed without consulting test answers or
model scores: **10 questions per subject × 57 subjects = 570**. Each subject's
five dev examples are the only answered demonstrations. Test answers are used
for offline correctness only, never inference inputs or gradient updates.

All four models receive identical five-shot plain-text prefixes, without a chat
template, truncation, sampling, workspace, quantization, or alternate head math.
Native full-vocabulary next-token A/B/C/D scores are used; prefix compatibility
and single-token candidates must pass for every row. Report standard first-index
argmax and a separate strict-tie count/accuracy. Ties are never hidden. The first
ten rows form a finite-score/tokenization smoke, not a post-hoc accuracy gate.

Report correct/planned, subject denominators, original-correct regressions,
repairs, and paired percentile intervals resampling questions within subject.
This **subject-balanced 570-question subset is not the full MMLU headline
score**, not free-generation quality, not a formal non-inferiority test, and not
proof of no pretraining contamination. Most importantly, no workspace is active:
this checks the updated base, not retrieval or workspace-assisted MMLU ability.

## State, provenance and resource safeguards

- Use fresh sequential processes. Verify source before project imports.
- Before broader evaluation, restore each checkpoint through its qualified owner
  and exactly replay the original 160-row evaluation at its recorded step.
- Compare whole learner/optimizer/RNG fingerprints before and after evaluation;
  check parameter versions and RNG around each added world observer.
- Retain the original 535-file source seal; no old implementation is edited.
- No new training, generation, paid judge, checkpoint, weight deletion or automatic
  retry. A failure records partial counts and stops subsequent arms.
- GPU admission 31 GiB, allocator ceiling 30.5 GiB, free floor 0.75 GiB;
  host admission 100 GiB/free floor 24 GiB; disk floor 50 GiB; two CPU threads.
  Each arm is bounded to four hours. This is a ceiling, not an ETA.
- Tiny observer/data qualification runs first on source-isolated CPU and CUDA.
  It is not 7B semantic evidence.

The offline verifier replays manifests, selected inputs, score arithmetic,
controls, paired transitions and summaries without loading model weights.
Keep **FAIL / winner:none / non_regression NOT_ESTABLISHED**. Inspect the expanded
diagnostic before selecting the next learner factor; do not tune on MMLU labels.
