# V23 state factorial 01: upper-reader gain, two different transport failures

**Completed frozen-V22 diagnosis, not V23 training or a release.** The upper
reader carries most of the measured improvement; increasing question-encoder
adaptation is not justified by this panel. Later symbol copying exposes a
writer–upper-reader interaction, while one early identity error and two
unsupported answers are sensitive to the query encoding. Neither a lower-only
nor an upper-only weight hybrid preserves the original MMLU floor.

Source: `6064c69ab722330f3d51574768a1c52e887d6866` (744 sealed files).
The pinned V22 step-32 checkpoint remains byte-identical:
`cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68`.
Keep **FAIL / winner:none / non_regression NOT_ESTABLISHED**.

## Evidence and denominators

- [Frozen design](../../../docs/v23/STATE_FACTORIAL_01.md),
  [plan](../../../configs/v23/STATE_FACTORIAL_01.json),
  [execution handoff](EXECUTION_HANDOFF.md).
- [SUMMARY.json](SUMMARY.json): every cell, loss/repair contrast, interactions,
  natural-twin margins and resource counts.
- [INTERPRETATION.json](INTERPRETATION.json): token-type repairs, exact copy
  margins, all changed-query endpoints and the two original MMLU losses.
- [Full fixed-prefix panel](FACTORIAL_PANEL.md): all 96 world rows, exact
  historical generations, and all ten MMLU questions whose prediction changes
  under any Q/R combination. These are not newly generated hybrid answers.
- [Raw records and source seal](furnace/SOURCE_SEAL.json),
  [terminal receipt](furnace/raw/FINISHED.json),
  [post-terminal witness](furnace/REMOTE_TERMINAL_CHECK.json).

All inputs were already exposed: 96 world rows in 16 groups, 623 gold-prefix
positions, and 570 reused MMLU questions. Nonempty memory contributes 559
positions × eight W/Q/R cells = 4,472; 64 absent positions × four Q/R cells =
256. MMLU contributes 570 × four = 2,280. Total: **7,008 unique cells**.
Another 1,193 base self-cells are repeated controls, not independent samples:
**8,201 journal entries** (5,351 world + 2,850 MMLU).

CPU and CUDA each pass **216/216 selected tests**, no failures/errors/skips.
Full native/split logits are bitwise equal at **2,386 self prefixes**; all
**1,193 repeated base endpoints** agree. Original cropped world vocabulary
hashes and original MMLU scores replay exactly. No invalid/missing cells, no
retries, no new generations, updates, checkpoints, judges or deletions.
The [local preflight](LOCAL_PREFLIGHT.md) retains its separate 214/216 result:
two existing macOS isolated-Python dependency failures were not hidden.

## 1. Separate W, Q and R

- **W:** memory written by base or V22 below cut 4.
- **Q:** question **and identical fixed answer-prefix** encoded below cut 4.
- **R:** layers 4 onward, final normalization and the full native head.

The table uses the same cropped prefix in every cell. All token scores include
the normal full vocabulary; no candidate-only output head, padding trick or
precision change is used. Q is not purely a natural-language question effect.

| W | Q | R | Gold top-1 / 559 positions | First two / 160 | Later symbol tokens / 231 | All gold-prefix positions agree / 80 rows |
| --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 442 | 132 | 231 | 7 |
| base | V22 | base | 454 | 137 | 231 | 10 |
| V22 | base | base | 446 | 135 | 231 | 7 |
| V22 | V22 | base | 456 | 139 | 231 | 10 |
| base | base | V22 | 550 | 151 | 231 | 71 |
| base | V22 | V22 | 549 | 150 | 231 | 70 |
| V22 | base | V22 | 549 | 151 | 230 | 70 |
| V22 | V22 | V22 | 548 | 150 | 230 | 69 |

Later symbol tokens are explicitly the positions `j >= 2`, before the separate
period/EOS, in single `N[a-z]+.` targets. They are a bounded copy diagnostic,
not proof that all preceding answer identity has already been correctly chosen.
The last column requires the exact oracle tokens including punctuation/EOS.
It is **not** the prior normalized generation accuracy: base's historical
36/80 nonempty answers often omit the final period or add other text, while
this exact-token path criterion accepts only 7/80. No historical score changes.

At base W/Q, changing R repairs 108 positions with zero losses, but **71 repairs
are periods, 16 are EOS and 21 are other tokens**. This is largely useful
format/stopping alignment, not 108 independent reasoning improvements. First
two-token agreement also improves 132→151/160; that alone does not establish
general reasoning quality. Keep the prior content-sensitive generation evidence
separate from this prefix diagnostic.

Q adaptation helps the base R (12 or ten token repairs, no losses, depending on
W), but with V22 R it contributes one loss and no repairs for either W. Thus
Q is not globally useless: its value depends on the reader. Mean token-weighted
gold-log-probability effects at the all-base corner are W +0.027827, Q +0.127636,
R +1.193604, with WQ −0.005346, WR −0.027584, QR −0.128326 and WQR +0.002817.
These are descriptive inclusion–exclusion contrasts, not additive causal
percentages or independent-sample significance tests.

Absent-memory results also depend on Q: with base R, base/V22 Q gives 4/16 and
3/16 exact oracle paths; with V22 R it gives **16/16 and 14/16**. This is a
no-memory Q/R intervention, not a memory-content effect.

## 2. Later copying: a writer–reader compatibility failure

For `wb01-linked_location-ood-0058/s1/affected`, the oracle is `Nymszrcrff.`.
The historical V22 generation is exactly `Nymszrcrk.`. At the identical oracle
prefix before token index 5, the target is token 1264 (`ff`), rival 29497 (`k`).
Gold-versus-best-other margins are:

| W | R | Q=base | Q=V22 |
| --- | --- | --- | --- |
| base | base | +3.1875 (`ff`) | +2.625 (`ff`) |
| V22 | base | +1.0 (`ff`) | +1.0 (`ff`) |
| base | V22 | +1.125 (`ff`) | +1.125 (`ff`) |
| V22 | V22 | −1.0 (`k`) | −1.625 (`k`) |

Both updated W and updated R are required for this observed failure; Q alters
its margin but reverting Q alone does not repair it. This locates a *state-path
interaction*, not a specific neuron, attention head or weight tensor. It does
not justify freezing all writer parameters or promoting a post-hoc hybrid.
W and Q share lower-layer parameters in the actual learner.

## 3. Early binding and abstention: a different failure mode

Hold W/R at V22 and change only the query/continuation states. The only changed
nonempty endpoint is `linked_location-ood-0023/s1/unaffected`, index 1:
target `er`, base Q predicts `er` (margin +1.25), V22 Q predicts `k` (−0.25).
The full target is `Neruhfebov.`; the historical V22 output is `Nkxfboiobj.`.

Two absent-memory rows change at index 0 from correct `Not` under base Q to
`N` under V22 Q: `event_order-test-0006/s0/absent` (+0.5→0 margin) and
`event_order-test-0015/s0/absent` (+0.75→−0.25). Their historical V22 answers
are `Nbwxsmihfd.` and `Nfzyxfrnok.` rather than `Not specified.`. The first
case is a tie under the unchanged native argmax rule; no tie rule is revised.

These are fixed-prefix effects, not newly sampled hybrid continuations. Other
unaffected-query misbindings remain: the query encoder is not the only place
question-to-fact selection can fail. Increasing its gradients alone is not a
supported remedy.

Natural-twin donor margin shifts remain positive in **32/32 directions in all
eight cells**, including **20/20 matched-length directions** (ten groups) per
cell. Base already has this sign, and mean amplitude is not larger for full
V22. Directional logits are therefore not the missing milestone by themselves.

## 4. Protect both lower and upper ordinary-host computation

| Q | R | MMLU correct / 570 | Unique-top correct | Tied items |
| --- | --- | --- | --- | --- |
| base | base | 356 | 351 | 15 |
| V22 | base | 354 | 352 | 14 |
| base | V22 | 355 | 351 | 15 |
| V22 | V22 | 354 | 349 | 18 |

Relative to all-base, Q-only loses two and repairs zero; R-only loses three
and repairs two. Full V22 loses two and repairs zero. The original losses,
nutrition `9596` and world-religions `13900`, remain wrong in **all three
non-base cells**. An apparently better aggregate hybrid does not recover them.
All ten prediction-changing questions are retained, including wrong→wrong
changes and compensating effects. Native BF16 ties remain visible; the earlier
FP32-head assay is not substituted here.

This supports protecting ordinary-host computation across the body, not only
the head or only the query encoder. It does not prove a particular anchoring
loss will work, and these exposed questions must not become training targets.

## 5. What to take into V23

See [evidence-updated next factors](../../../docs/v23/NEXT_FACTORS.md) and
[workspace revival](../../../docs/v23/WORKSPACE_REVIVAL.md). Preserve native
full-vocabulary computation and the useful upper-reader improvement. Next
separate (a) train-only fact recruitment from formatting, (b) joint writer/
reader symbol transport, and (c) ordinary-host preservation. First measure the
gradient paths/conflicts before selecting independent learner factors. Do not
add several losses, new data, new precision and a larger LR together.

The original workspace intent also needs occupancy/persistence, useful latent
computation and behavioral consequence. This assay tests transport and readout;
it **does not demonstrate recurrent deliberation or multi-turn memory quality**.
No V23 training, beta replacement, PR/merge or Hub upload has occurred.

## Resources, retained bodies and reproducibility

| Role | Seconds | Peak CUDA allocated GiB | Peak CUDA reserved GiB | Peak host RSS GiB |
| --- | --- | --- | --- | --- |
| base | 244.166 | 17.181 | 25.926 | 7.793 |
| V22 | 511.173 | 17.207 | 25.928 | 55.761 |
| base-cross | 301.140 | 16.980 | 25.881 | 7.883 |

Qualification took 44.294 s CPU and 49.505 s CUDA. Full-owner restoration,
byte hashing and provenance work are included in role times; this is not a
throughput benchmark. All worker PIDs ended; the terminal witness found no GPU
clients and five source worktrees clean. The learner graph was not modified.
The Furnace skill's isolated-worktree and resource checks governed execution;
managed serving was not used because it cannot implement this exact cut graph.

Two activation bodies remain **on Furnace only**, 3,380,089,608 bytes each,
1,008 tensors each, **6.295908 GiB combined**. They are not checkpoints and
were not deleted or committed to Git:

`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-state-factorial01-20261021/raw/{base,v22}/cut_states.safetensors`

Their hashes are in [PUBLICATION_MANIFEST.json](furnace/PUBLICATION_MANIFEST.json),
per-tensor manifests and the remote byte/tensor witness. The published bundle
contains 55 smaller files (16,227,993 bytes). Local replay checks their bytes,
all 744 committed source hashes, receipts, all cells, original endpoints and
the literal panel. It relies explicitly on the remote witness for the two
omitted activation bodies; it does not pretend to rehash absent local files.

```sh
python3 provenance/pilots/v23_state_factorial01_20261021/test_publication.py
python3 provenance/pilots/v23_state_factorial01_20261021/summarize.py --verify
python3 provenance/pilots/v23_state_factorial01_20261021/interpret.py --verify
```

The original V22 comparison, weight diagnosis and causality replay were also
verified unchanged. Historical literal trailing spaces are preserved. No new
results are used to reclassify their original gates.
