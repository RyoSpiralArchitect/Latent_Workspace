# V23 base / P-off / P-on readout comparison 01

Frozen **after** reading the completed FT development losses, **before** any
new evaluation forward or generated sequence. This is descriptive follow-up,
not a pre-training preregistration or a new acceptance panel.
The [training result](../../provenance/engineering/v23_preservation_ft01_20261022/TERMINAL.md)
shows a modest CE trade-off, not demonstrated retention. Preserve both arms.

## Unchanged panels, three fresh processes

The [plan](../../configs/v23/COMPARISON_01.json) pins the two step-32 checkpoint
bytes and the [old evaluation plan](../../configs/v22/BASE_COMPARISON_01.json)
by canonical hash. Reuse its already-tokenized, sealed input bundle, without
relabeling its original plan hash or editing its contents. All original
exposure disclosures remain: MMLU and the 16 world groups are now exposed,
and old linked-location OOD is not a new V23 confirmation claim.

| Per-arm endpoint | Per arm | Three-arm total |
| --- | ---: | ---: |
| MMLU scores | 570 | 1,710 |
| World teacher-forced rows | 96 x 2 routes | 576 |
| World greedy sequences | 96 x 2 routes | 576 |
| Free prompt / seed sequences | 12 x 2 seeds | 72 |
| All new sequences | 216 | 648 |

Order: original base, P-off, P-on. No earlier output is silently substituted
for a fresh arm, even though P-off's final fingerprint matches V22. Per-answer
RNG is reset to the old identical seeds. World cap 24, free cap 256, free
temperature 0.7 / top-p 0.9 stay unchanged. Cap stops remain truncations, not
completed answers. No retry or post-result cap/prompt adjustment.

The same native evaluator serves all three arms. Preserve constrained-choice
and strict vocabulary accuracy, world target NLL and normalized exact match,
counterfactual affected/unaffected/absent/unrelated rows, route, family and
group identities. Free reasoning/writing/code remains **UNJUDGED** until a
separate review; token differences are not quality wins. Sampling seeds pair
randomness, not output trajectories. No provider calls are part of this run.

The latent/inline comparison is not layer-level causal attribution. No new
W/Q/R intervention, copying repair, final-model full-bank KL, new world bank
or untouched confirmation/OOD is included. Those remain distinct next axes.

## Strict state loading, then explicit inference

The shared native owner must validate exact checkpoint bytes, whole payload,
original run contract, native/master/moment/RNG fingerprint, and (on) the
engine-owned full-vocabulary teacher body and KL history. V2 is **not**
converted to v1 and updated weights are **not** loaded by dropping the objective.
Only after strict restore are gradient checkpointing and gradients disabled
and the graph put in eval mode. Each arm checks bitwise empty-memory bypass
parity and unchanged native state hashes around inference.

The new runner only supplies v1/v2 restore and fixed three-arm orchestration;
it reuses V22's evaluator, token handling and generation function. The old
runner's default paths remain unchanged. Before any 7B call, qualify **223
tests on CPU and CUDA**, with zero skips, <=4 GiB and <=900 seconds each.
This includes four host families, FP32/BF16, v1/v2 save/restore-to-inference
parity, corrupt receipt/objective/bank rejection, and the existing sampler,
normalization and fresh-process owner tests.

Use the existing native PyTorch lane: generic serving does not implement the
cut-4 memory composition and full owner checkpoint. Managed runtime remains
unchanged. Same 31-GiB GPU admission / 30.5-GiB allocator cap, 100-GiB host
admission, 50-GiB disk floor and four-hour limit per role. No checkpoint saves
or deletions; refresh disk availability before creating the isolated source.
Failure ends dispatch with missingness; never patch a running sealed source
or restart under its identity.

**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains. Report all
three arms and all denominators; no quality threshold or release rule is
introduced from the observed development results.
