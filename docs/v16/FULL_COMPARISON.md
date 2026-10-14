# V16: bounded three-arm full-update comparison

2026-10-14. Prospective execution contract; not a result or promotion.
The [fixed plan](../../configs/v16/FULL_COMPARISON_PLAN.json) follows the completed
[state ownership qualification](SLOT_STATE_OWNER.md) and separately authorized
[V14 storage cleanup](../../provenance/inventory/v14_weight_prune_20261014/README.md).

## The one factor under test

All arms start from pinned original Mistral-7B-Instruct-v0.3 revision
`c170c708c41dac9275d15a8fff4eca08d52bab71`, not a deleted V14 checkpoint.
The common reader initialization and original base are identical. Raw and
centered interaction routes have identical initial tensors, parameter counts,
optimizer policy and norm budget; centering is not a FLOP-matching claim.

| Arm | Reader | State owner |
| --- | --- | --- |
| `common` | Existing query-modulated common reader | qualified adapter v2 |
| `raw_matched_control` | Common + uncentered interaction | qualified V16 slot owner |
| `slot_contrast` | Common + centered-slot interaction | qualified V16 slot owner |

The additional route has 2,359,808 parameters at H=4096, D=256. Its output
projection starts at zero. Initial upstream interaction-query gradients being
zero are expected; finite post-update gradients and their magnitude are observed,
not promoted into content-use evidence. The exact equal-slot null is an
architectural property, not a semantic success.

## Fixed work and unchanged arithmetic

- Seed 47; re-seed after reader construction so extra parameter initialization
  does not silently change the training RNG across arms.
- Identical 16 ordered pairs: exposed training worlds 0–1, queries 0–7.
- Two complete full-base update windows per arm. Same six-term objective,
  query mode `final`, context boundary 16 and EOS weight zero.
- Unchanged native BF16 base, FP32 bridge/addition, native head, CPU native-dtype
  gradient accumulation, FP32 base masters, Adafactor and bridge AdamW.
- Save steps 1 and 2; restore step 1 into fresh original targets and replay
  step 2 exactly, including each pair, accumulated gradients, update and RNG.
- Planned total: **6 unique windows + 3 replay windows = 144 backward pairs**.
  Replay pairs are not new training data or independent statistical samples.

No new preservation supervision, alternate precision, additional training data,
free generation, answer banks, paid judges, deletion, seed search or threshold
change belongs to this pilot. The old configurations provide immutable model,
data, objective and optimizer fields only; their historical generation schedules
and old frozen-base claim text do not define this new full-update selection.

## Evaluation without changing learner state

At steps 0, 1 and 2, the new evaluator uses the same owned native adapter with
`no_grad`, without `.eval()`/`.train()` changes, global RNG draws, alternate
selected-row logits or cached hidden features. Complete state fingerprints
before/after must match. Step-zero and zero-workspace full-vocabulary outputs
must equal the direct native base.

Per evaluation: **160 workspace rows + 16 direct-base rows + 80 factor rows**.
Ten conditions: intact/twin, fact-order-reversed intact/twin, zero, unrelated,
equal-mean-slot intact/twin, and norm-matched random intact/twin. The latter
controls have no assigned correctness targets. Five paired views are actual,
reversed, common slots, random pair and same memory. Same-memory reuses the
same captured output; it is an algebraic diagnostic null, not an independent
stochastic-repeat test. Random memories are not distribution-matched semantics.

The whole matrix plans **1,440 workspace rows, 144 direct-base rows and 720
factor rows**; these share two exposed worlds, not that many independent cases.
Record native no/yes scores and ties, donor-oriented changes on affected queries,
unaffected changes, donor-directed flips, intended versus applied residuals,
full-head transport diagnostics, and common/interaction norms. FP64 projections
are diagnostic only and never replace the native logits. Report regressions and
repairs against the recorded original-base step-zero choices separately.
All per-query outputs remain available for reciprocal-question analysis.

## Capacity and execution

Each arm runs in a **fresh OS process**, sequentially; never let a warmed prior
arm fail a cold-process admission screen. A failure stops later arms, retains
all partial evidence and has no automatic retry. Exclusive output/checkpoint
directories, STARTED/FINISHED receipts and pre-import source seals apply.

Unchanged admission: GPU free ≥31 GiB, allocator cap 30.5 GiB, sampled GPU free
floor 0.75 GiB; host available ≥100 GiB initially and ≥24 GiB ongoing; CPU threads
2; maximum 7,200 seconds per arm. Each independent snapshot requires another
32 GiB host capacity above the floor. CPU gradient observations are read-only.

Disk forecast: 64 GiB per arm + 50 GiB remaining, initially **242 GiB**.
At each arm admission, reserve 64 GiB for every remaining arm. The preceding
270.661-GiB observation passes this screen but live admission must still pass.
Two full checkpoints per condition remain. No new weight deletion is authorized
by this runner. The old 27.751-GiB common-reader CUDA peak is not a measurement
of the added interaction graph; current GPU/host peaks are recorded separately.

Before 7B dispatch, the new 12-case integration suite must pass on source-isolated
CPU and CUDA with a 4-GiB tiny CUDA ceiling and 900-second deadline. Six cells
(three arms × FP32/BF16) compare the observed update to the unchanged qualified
window and test evaluation nonmutation plus serialized next-update replay.
Other cases reject plan drift, verify matched initialization and retain negative
summary evidence. Separate offline tests reject damaged evaluation arithmetic.
Tiny success is not real-model resource or semantic qualification.

## Interpretation boundary

Use donor direction, reciprocal questions and controls to decide the next
mechanistic factor; do not choose a winner by a larger residual or a handful of
changed logits. Shared entities and training-exposed worlds preclude a held-out
quality claim. Original-base choice comparisons here are descriptive, not a
non-regression gate. Preserve **FAIL / winner:none / non_regression
NOT_ESTABLISHED** until separately scoped, adequate evidence justifies otherwise.
