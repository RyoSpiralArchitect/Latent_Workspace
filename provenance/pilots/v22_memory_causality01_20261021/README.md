# V22 memory causality 01 — terminal results

**V22 answers depend on memory content, not merely a nonzero carrier, on this
exposed world panel. Most of the measured improvement travels with the reader
side, not with the memory writer alone.** A particular copy regression is also
removed by supplying base-written memory to the otherwise unchanged V22 reader.
These are bounded causal diagnostics, not a fresh benchmark or a 1.0 pass.

[Summary](SUMMARY.json) · [all 80 nonempty-row answer panels](ANSWER_BANK.md) ·
[additive case audit](INTERPRETATION.json) ·
[frozen design](../../../docs/v22/MEMORY_CAUSALITY_01.md) ·
[execution handoff](EXECUTION_HANDOFF.md) ·
[V23 proposal](../../../docs/v23/ROADMAP_TO_1_0.md).

## Scope, identity and completion

- Same original Mistral-7B-Instruct-v0.3 revision
  `c170c708c41dac9275d15a8fff4eca08d52bab71` and V22 step 32 as comparison 01.
  The checkpoint is 29,004,418,636 bytes; SHA256
  `cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68`.
  Full owner state, not just native weights, was restored exactly before inference.
- Execution source `fd77ee4c84a99a99c22b28aa85d321e95caa843f`, **739 sealed files**.
  BF16/eager, cut 4, native full vocabulary, no KV cache or candidate-restricted
  generation. The trained learner is unchanged; intervention helpers are additive.
- Same **96 unique rows / 16 groups** as the exposed comparison. Prefix checks
  include all 96; intervention generation uses the **80 nonempty-memory rows**:
  32 affected, 32 unaffected, 16 unrelated. The original 16 empty-memory controls
  are not counted as newly generated examples. Original V22 accuracy remains
  **83/96**, not retrospectively replaced by a hybrid score.
- **187/187 selected tests on CPU and CUDA**, no failures/errors/skips. The
  29 new tests include four tiny architectures in BF16/FP32, exact no-op and
  replacement checks, a deliberately leaky negative control, and the actual
  three-role runner. Legacy tests mix CPU and device-aware fixtures; 187 is not
  a count of GPU-kernel tests. See the separate [Mac preflight](LOCAL_PREFLIGHT.md).
- **2,492/2,492 prefix positions**, **928/928 sequences**, **7,653 generated
  tokens**. All are greedy, cap 24, EOS 2, seed 20261021. There are **876 EOS /
  52 capped** replies and zero empty-text replies. Caps remain scored and visible;
  they are not silently excluded. Base contributes 47 caps, base-cross five,
  and V22 zero. No execution-invalid rows, missing roles or retries.
- **288/288 identity/twin historical generation replays** agree exactly.
  All 928 token sequences independently decode to the saved literal text.
  Native weight identities match before/after; the checkpoint body was rehashed
  after completion. No run worker remains on the GPU.
- **Zero training updates, checkpoint saves, weight deletions or judge calls.**
  The three small safetensor files contain observation-only BF16 activations,
  not model weights or restorable checkpoints. They retain 48 unique memories
  per bank with byte/tensor hashes; base's repeated bank is exactly identical.

## 1. The prefix discrepancy follows extent, not future token content

At each gold next-token position, preceding tokens and memory are identical.
Two equal-extent controls are **bitwise equal over the entire vocabulary**:
replace future tokens with different valid tokens while retaining the mask,
or replace them with masked padding. Both controls pass all **1,246 positions
per arm**, including latent and inline routes. Observed future-content effect:
**0/2,492**. This qualifies the stated control; it is not an exhaustive proof
about every possible sequence or backend.

Cropping to the current prefix changes the sequence extent:

| Arm | Exact full-vocabulary equality /1,246 | Argmax changes | Gold-correctness changes | Maximum vocabulary-logit difference |
|---|---:|---:|---:|---:|
| Base | 2 | 12 | 8 | 1.25 |
| V22 | 1 | 2 | 2 | 0.75 |

The two V22 correctness changes reproduce the previous entity decision
(`linked_location-ood-0023/s1/unaffected`, latent, index 1) and punctuation/EOS
boundary (`linked_location-ood-0058/s1/affected`, inline, index 6). Base has
eight here versus two in the earlier diagnostic because this assay covers
**all gold prefixes**, including ones already diverged from the recorded free
path; the earlier comparison used only common recorded/gold prefixes. The
maximum above is over the full vocabulary, not just the gold logit.

This supports **sequence-extent-sensitive numerical computation** as the
explanation in this assay, not answer-content leakage. It does not identify a
particular kernel or make teacher-forced scores interchangeable with generation.
Keep native prefix-realistic decisions as an endpoint. No padding, tie-break,
score or historical answer was retroactively changed.

## 2. Natural memory content changes the answer in the intended direction

The question and its tokenized common answer prefix are fixed. Only the cut-4
memory is exchanged with its natural counterfactual twin. At the first differing
oracle-answer token, measure the donor-minus-original logit margin change.
Reciprocal directions are **not independent observations**.

| Endpoint | Base | V22 |
|---|---:|---:|
| Donor-directed margin increases | 32/32 directions | 32/32 directions |
| Output equals donor answer after swap | 15/32 | 28/32 |
| Correct original → correct donor answer | 8/32 directions (4/16 groups) | 24/32 (12/16 groups) |
| Changed token sequence, irrespective of correctness | 30/32 | 28/32 |
| Unaffected-query exact token preservation | 24/32 | 28/32 |
| Unaffected-query both sides correct | 12/32 | 24/32 |

The key length control is **10 groups / 20 reciprocal directions with exactly
equal memory-token length**. Here V22 has donor-directed margin increases in
**20/20**, donor answers in **17/20**, and correct-to-correct donor switches in
**14/20 directions = 7/10 groups** (base: 20/20, 9/20, 4/20 = 2/10 groups).
The nonzero carrier and its length remain present in both conditions, so the
effect cannot be explained solely by carrier existence/length. Unequal-length
results are separately retained in SUMMARY.json, not pooled as length controls.

Do not claim V22 invented memory sensitivity: base already has positive margin
movement in all 32 directions. Nor is the mean margin displacement larger in
V22 (18.9789 versus 19.5068). The improvement is in **realizing the appropriate
answer**, including formatting, while preserving more unaffected outputs.
Two V22 swapped outputs still equal the original answer; four swapped answers
miss their donor target. Directional score movement is not sufficient by itself.

### Presence/order stress controls, with their limits

On the 64 answer-bearing affected/unaffected rows, original-answer retention is:

| Memory condition | Base | V22 |
|---|---:|---:|
| Intact | 29/64 | 53/64 |
| Empty bypass | 0/64 | 4/64 |
| Same-length zero cut states | 0/64 | 5/64 |
| Reversed cut-state order | 0/64 | 6/64 |

These are **retention of the original answer**, not accuracy against valid
alternate semantic labels. Empty also changes positions/path; zero/reverse are
off-manifold. Reversal rearranges already-contextualized states, not raw facts.
These controls support dependence on the supplied representation but cannot
alone demonstrate semantic use. Natural, length-matched twins supply that test.

For the original unrelated-memory controls, V22 abstains correctly in **16/16**
(base 7/16). With memory removed from all 80 intervention rows, V22 abstains in
**72/80** versus base 51/80; these collapse to **29/32 versus 20/32 unique query
prefixes**, so the duplicate condition rows must not inflate the denominator.
The earlier V22 **14/16** original empty-control result remains unchanged.

## 3. Writer × reader: the large gain travels with the reader

The writer is only the memory encoding through cut 4. The reader side includes
the **query encoder, remaining decoder layers and native head**. Identical BF16
memory-state tensors are transported without conversion; query/continuation
states are re-encoded each step by the reader. This is an inference intervention,
not detached-memory training or a new production model.

| Memory writer | Base reader: exact /80 | V22 reader: exact /80 |
|---|---:|---:|
| Base | **36** | **70** |
| V22 | **39** | **69** |

At the fixed base writer, changing the reader yields **34 repairs, zero losses**.
At the fixed V22 writer, it yields **31 repairs, one loss**. Changing only the
writer at the base reader yields **three repairs, zero losses**; at the V22
reader it yields **one loss, zero repairs**. Formatting affects exact match;
these are not all newly acquired reasoning skills. All literal changes are in
INTERPRETATION.json, including the writer-only formatting repair.

The prefix-decision gold log-probability decomposition across 80 rows has mean
writer effect **+0.0756343**, reader effect **+0.7805262**, interaction
**−0.0753126** (base/base reference). This is a conditional nonlinear factorial,
not a universal percentage attribution. The memory encodings are not identical:
all **48/48** unique tensors and **7,565,897/8,560,640 (88.3800%)** native state
elements change. Bit changes alone were not a measure of useful writing.

**Bounded inference:** much of what V22 now uses can already be written by the
original host. Reader-side adaptation is the larger operational change on this
panel. This does not isolate query encoding from upper-layer reading, identify
a particular layer/loss, or justify replacing V22 with a selected hybrid.

## 4. Concrete remaining mechanisms

**Writer-induced copy error.** For
`wb01-linked_location-ood-0058/s1/affected`, the target is `Nymszrcrff.`:

| Same V22 reader | Exact output |
|---|---|
| Base-written memory | `Nymszrcrff.` |
| V22-written memory | `Nymszrcrk.` |

All other V22-reader outputs are token-identical across writers (**79/80**).
Earlier FP32-head projection did not rescue this first fork. Here changing the
memory state alone repairs it with native arithmetic and the same reader.
This localizes a causal contribution, not the responsible coordinate/layer.

**Question-conditioned fact selection still fails.** The four changed
unaffected directions are all in two linked-location groups. For 0058, the
unaffected question targets `Njkkqvkind.`, yet its outputs follow the changed
*other object's* location: `Ndojyaptgn.` ↔ `Nymszrcrff.`. Both are wrong.
For 0023, the unaffected target `Neruhfebov.` changes to `Nkxfboiobj.` on one
side; reversing the swap restores it. These are preserved negative controls,
not counted as successful semantic redirection. The complete questions,
memories and outputs are in ANSWER_BANK.md.

## Resources, replay and claim ceiling

| Role | Seconds | Peak allocated / reserved GiB | Peak host RSS GiB |
|---|---:|---:|---:|
| Base | 530.47 | 13.560 / 13.689 | 5.542 |
| V22 | 600.27 | 13.560 / 13.689 | 55.759 |
| Base reader, V22 writer | 101.35 | 13.551 / 13.689 | 5.541 |

CPU/CUDA qualifications took 44.06/48.80 s including harness overhead. The
Furnace skill's separate checkout/resource checks and native-backend exception
kept the existing managed runtimes and other jobs untouched. The copied
Furnace bundle has **58 files / 68,929,103 bytes**. Reproduction:

```sh
python3 provenance/pilots/v22_memory_causality01_20261021/summarize.py --verify
python3 provenance/pilots/v22_memory_causality01_20261021/interpret.py --verify
python3 provenance/pilots/v22_memory_causality01_20261021/test_publication.py
```

These replay old bundles, source seals, qualification XML, terminal manifests,
full-owner restoration, activation bytes, all denominators and the literal
panel without a model call. [Post-terminal witness](furnace/REMOTE_TERMINAL_CHECK.json)
also verifies the unchanged 29-GB checkpoint, four clean source checkouts,
literal decoding and exited workers. No old evidence was edited.

Still **FAIL / winner:none / non_regression NOT_ESTABLISHED**. The reused native
MMLU result remains **356→354/570**; its two losses and the unjudged/capped free
generation bank do not disappear. This panel contains one checkpoint, seven
synthetic families and 16 exposed groups. It does not establish general latent
intelligence, multi-turn utility, other-model gains or readiness for 1.0.
