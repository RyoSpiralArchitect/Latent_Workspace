# FT-beta learner step 3: matched question-pooling micro-fit

Client date: 2026-10-10. **Execution completed; neither cell passed the frozen
tiny-feasibility gate. No winner, semantic promotion, or FT-beta qualification.**
The important new finding is a readout-budget ceiling, alongside a serious
fact-serialization failure. Neither is solved by question pooling alone.

## Fixed experiment

Source commit: `02dd87872f7e3c5ab9c9fcf9c7335145e03656ff`.
[Frozen plan](../../../configs/v14/FT_BETA_QUERY_POOL_PLAN.json).
[Prior CPU audit](../ft_beta_learner_audit_20261009/README.md).

- Independently loaded, frozen `mistralai/Mistral-7B-Instruct-v0.3`, revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71`; native BF16 CUDA, SDPA.
- Only 4,200,192 FP32 workspace/bridge parameters trained. No backbone update,
  quantization, CPU offload, model copy, API judge, or generation run.
- First two **already exposed training worlds**, eight questions each. All 16
  world/query pairs in every batch, world-major order, 256 AdamW updates per cell,
  seed 47. Same initial parameters, frozen features, labels, objective, LR and
  smooth residual-norm cap 1.0. This is not a replay of the historical 256-world
  shuffled schedule.
- `final`: original final normalized answer-prefix state queries the workspace.
  `mean_span`: FP32 average of the normalized **question-token** states queries
  the same workspace. Both add their residual to the **original final state**.
  No added parameters. The prediction-state anchor never becomes the mean.
- Strict token-offset binding excludes the instruction and `Answer:`. All 16
  prefixes passed answer/side/query-order/metadata permutation checks. Historical
  symmetric-instruction rendering remains unchanged, with `use_chat_template:
  false`; prompt changes are not part of this intervention.
- Primary checkpoint fixed at step 256; step 128 is diagnostic, not selection.
  Gradient/reader/eight-control panels collected at steps 0, 1, 128 and 256.

## Outcomes at the fixed primary checkpoint

Ties are never counted as correct. The native base has four tied scored rows;
the FP32 base has none. Query-only base lacks the world facts and is therefore
an **unequal-information reference**, not a general non-regression benchmark.

| Condition | Native intact correct | FP32 intact correct | Correct affected flips, native / FP32 |
|---|---:|---:|---:|
| Query-only base / written zero | 15/32 | 18/32 | 0/4 / 0/4 |
| Final-position reader | 24/32 | 25/32 | 2/4 / 3/4 |
| Question-mean reader | 24/32 | 25/32 | 2/4 / 3/4 |

There are only **four unique affected world/query pairs** (two reciprocal pairs),
and twelve unique unaffected queries. The 32 accuracy rows include both sides;
they are not 32 independent worlds.

Both cells have all four FP32 donor-signed changes above the frozen 0.25 target:
approximately 0.6453–0.6456 (`final`) and 0.6460–0.6464 (`mean_span`). Both have
zero unaffected prediction flips and pass the preregistered margin-separation
screen. Neither reaches 32/32 intact plus 4/4 affected correct flips, so both
original feasibility gates remain **false**.

Within these exposed rows, intact predictions introduce zero new base-correct
errors: native improves nine rows and FP32 improves seven. This does **not**
establish the requested pinned-base correctness floor on an independent battery.
Native versus FP32 changes postnorm composition and head arithmetic together;
it is not a whole-model precision comparison.

### A previously unmeasured geometric ceiling

The post-hoc, CPU-only [readout-cap audit](READOUT_CAP_AUDIT.json) reads the two
pinned head rows directly from the cached safetensors. It does not train,
change the cap, use CUDA, or rewrite the original gates.

Let `a = w_yes - w_no`. The selected FP32 readout obeys the real-arithmetic bound

`|change in yes-minus-no gap| = |a · delta| <= ||a||₂ × ||delta||₂`.

Here `||a||₂ ≈ 0.32372028157905`, while `||delta||₂ < 1.0`. Seven intact rows
start with wrong signed base margins between approximately -0.4874 and -0.4960.
Even optimally directed correction leaves them wrong by at least 0.1637. The
conditional FP32 upper bound is therefore **25/32**. Both learners attain all
25 reachable rows; all seven remaining FP32 errors are in the unreachable set.
The next native-only failure is a score tie, not an additional FP32 error.

This exposes a **protocol-design limitation**: our frozen 32/32 requirement was
structurally unattainable with this readout cap. We retain its FAIL result and
disclose that limitation instead of changing the threshold after the run.
The bound concerns the selected FP32 path; it is not a BF16-native bound, and
the diagnostic arithmetic guard is not a formal floating-point error proof.
A necessary cap greater than about 1.5323 for these seven rows is only a lower
bound, **not** a recommended production gain or a reason to tune on these rows.

### Reader discrimination opens, but fact-order robustness fails

The mean reader starts with greater reverse-query separation: mean relative L2
0.436 versus 0.114. At step 1, reciprocal donor writer gradients remain almost
opposed (cosines -0.999994 and -0.99999975). By steps 128/256 the donor hinge is
satisfied; its zero gradient is expected, not an autograd failure. Both cells
learn strongly differentiated reverse-query residuals (relative L2 near 2).
Step-32 training loss is 0.58584 for pooling versus 0.74525 for final-position,
but the final outcomes coincide. One trajectory cannot establish a speed or
generalization advantage. The readout ceiling can mask differences between
reader representations: equal endpoints do not establish that pooling is
ineffective outside this bounded interface.

The control that prevents a semantic-success claim is **same-world fact-sentence
reversal**. Facts and labels are unchanged, but FP32 accuracy drops from 25/32
to 20/32 (`final`) or 19/32 (`mean_span`), introducing five or six errors relative
to intact. All four donor-signed changes become **negative** when both sides
are reserialized. Slot-permutation invariance is not fact-sentence-order
invariance: causal backbone encodings themselves change with serialization.

Fixed-carrier/random/different-schema controls also do not define a clean
generalizable content-use result. Random memory matches global raw-memory L2
only, and different-schema memory is not amplitude matched. These results are
consistent with a serialization-sensitive tiny-fit solution, not robust access
to the underlying ranking relation.

## Execution, resources and retention

- Runtime: Python 3.14.4, Torch 2.13.0+cu132, Transformers 5.15.0, CUDA 13.2,
  RTX 5090. Two CPU threads; process nice level 10.
- Completed both cells and all diagnostics in **53.56 seconds**.
- Peak Torch allocated **13.736 GiB**, reserved **13.871 GiB**; sampled own-process
  GPU high **14.596 GiB**. Lowest sampled device free memory **14.174 GiB**.
- Admission required at least 20 GiB free; allocator cap 18 GiB; abort below
  4 GiB free. The cap excludes CUDA context/non-Torch allocations. Process
  observations are sampled, not a continuous process high-water mark.
- The pre-existing other GPU client was left untouched and disappeared from
  later snapshots. No intervention in any other job was made.
- Ordinary-versus-split full-vocabulary native equality: **16/16 prefixes**.
  Written-zero full-logit equality: **128/128 diagnostic checks**. Initial
  all-control equality: **320/320 unique memory/prefix checks**. All eight
  loss-gradient reconstructions passed without tolerance relaxation.
- Original base state hash before/after is identical:
  `54d161755862ebf00d8acbca083d5f290a5de44d33af82ca885f3bd8f9c94312`.
- Four small bridge checkpoints retained on Furnace, **128 and 256 per condition**,
  about 64.1 MiB total. No old weights deleted and no base copied locally.

Remote checkout:
`/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-workspace-ft-beta-query-pool-20261010`

Checkpoint directory within it: `runs/ft_beta_query_pool_20261010/`.
Exact file hashes and byte sizes are in the two raw mode reports and summary.

## Verification and next design boundary

[Index](ARTIFACT_INDEX.json) seals 32 raw JSON/JSONL receipts;
[summary](SUMMARY.json) reconstructs eight evaluations / 2,048 control rows and
512 training rows. [Validation receipt](VALIDATION.json).

```sh
PYTHONPATH=src:scripts python3 scripts/verify_ft_beta_query_pool.py \
  --bundle provenance/pilots/ft_beta_query_pool_20261010
```

The portable verifier rechecks hashes, scalar arithmetic, gates and source
identities. It does **not** reload checkpoint bodies, rerun full logits, recover
hidden tensors, or redifferentiate gradients. Those are explicitly execution
receipts, not an independent tensor replay.

Next bounded work should separate three concerns:

1. Add a **readout reachability preflight** before setting a perfect-fit gate.
   Keep model/head/numerical geometry in the architecture adapter; do not put
   a Mistral-specific gain or yes/no oracle into the model-neutral workspace.
2. First freeze a **no-training content × serialization crossover** on these
   retained checkpoints, using a label-independent canonical fact order and its
   reversal for both twin worlds. Keep the cap unchanged and measure donor
   direction, native ties and full-vocabulary disturbance. Then isolate a
   serialization-robust learner change: multiple fact orders with equivalent-world
   consistency, reserving unseen orders for evaluation. Do not collapse intact
   and twin into one representation through an incorrectly specified consistency
   loss. Two-choice gap preservation alone is not full-vocabulary preservation.
3. Only then isolate a capacity/readout-budget change with a predeclared safety
   budget and independent base-correctness gate. Wider correction without
   order robustness would amplify the current shortcut. Free generation and
   judge comparisons follow that gate, not this train-only result.

These are proposed next experiments, **not executed changes**. The current raw
results, cap, objective and checkpoints remain frozen.
