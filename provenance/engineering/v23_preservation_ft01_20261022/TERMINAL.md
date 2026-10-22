# V23 P-off/on native full FT — completed, not a quality pass

The once-launched trial completed all five roles at frozen source
`b46f04caefcfd596ccde3b0af8fd886d859f11b7`.
[Terminal receipt](furnace/raw/FINISHED.json):
`V23_MATCHED_P_OFF_ON_32_STEPS_COMPLETE_NOT_QUALITY`.
Dispatcher wall time was **10,970.213 seconds (3 h 02 m 50 s)**, excluding
the preceding tiny qualifications. No retry, new sequence, judge call, weight
deletion, best-checkpoint selection or release occurred.

## What completed

- CPU and CUDA: **472/472 tests each**, zero errors, failures or skips.
- Original-host teacher: **89 rows / 18,727 positions**, all 89 same-weight
  eval/train forwards bitwise equal; no weight updates.
- Positive-P engineering canary: **2 updates** and one step-1 save.
- Fresh-process replay: **1 update**, exact row/gradient/state receipts and
  entire v2 payload, including KL history/cursors.
- P-off and P-on: **32/32 updates each**, **723 unique rows / 20,860 targets
  each**; P-on additionally accounted for **16,763 preservation targets**.
  Thus 64 comparative + 3 engineering/replay = **67 native updates**, not
  67 independent training examples or replicates. One seed, one run per arm.
- Exactly three checkpoint bodies remain on Furnace. [Read-only byte checks](BODY_VERIFICATION.json)
  matched all three save receipts and the private teacher body. The 769-file
  frozen source seal also passed on the clean remote checkout.

The [offline replay](verify_terminal.py) verifies **3,049 public raw files**,
all parent/role manifests with one explicit private-body omission, matched
exposure, dev denominators, replay, and previous V22 evidence. The
[structured analysis](ANALYSIS.json) is derived exclusively from those records.
The 2.286-GiB private teacher body and checkpoint bodies are not published.
Metadata verification locally is not a second local body verification.

## Fixed development readout

Same exposed **40 rows / 4,694 causal targets**, no generated answers. NLL is
the sum of target losses divided by the sum of target counts, not an unweighted
average of bucket means. Lower is better for this endpoint only.

| Dev bucket | Rows / targets | Base | P-off | P-on |
| --- | ---: | ---: | ---: | ---: |
| All | 40 / 4,694 | 1.267038 | 1.058723 | 1.069616 |
| Instruction | 8 / 1,957 | 1.273324 | 1.117111 | 1.130524 |
| Prose | 4 / 508 | 3.031372 | 3.004748 | 3.008279 |
| Code | 4 / 2,088 | 0.698288 | 0.596449 | 0.607452 |
| World affected | 6 / 47 | 3.310362 | 0.200979 | 0.201872 |
| World unaffected | 6 / 46 | 3.566308 | 0.035684 | 0.037887 |
| World absent | 6 / 24 | 2.894054 | 0.001289 | 0.001024 |
| World unrelated | 6 / 24 | 2.855213 | 0.022620 | 0.021715 |

Both arms lower NLL on **40/40** rows versus base. Overall reductions are
**16.4411% off** and **15.5814% on**. P-on is **1.0289% higher NLL** than
P-off; it is lower on 17/40 rows and higher on 23/40, with no ties. These are
descriptive paired counts, not independent trials or statistical superiority.
Do not call this accuracy, factual identity, causal memory use or reasoning.

The defensible observation is that coefficient-one KL modestly reduces the
dev CE gain under this short schedule. It does **not** establish that the
trade-off bought retention. Nor does higher CE establish worse generations.
P-on's online training KL averages **0.00511459 nats/eligible target**, but this
is sampled along a changing model/row trajectory. Its last window is
0.01994745 on 417 targets, not final-model KL over the full bank. Off has no
measured KL: `null` must not be rendered as zero. Matched post-training
distribution drift needs a separate read-only measurement.

A numerical caveat is retained: first-window CE rows are identical and
reported KL is exactly zero, yet preclip gradient norms differ slightly
(183.044113 off / 183.051315 on), and the first native state hashes differ.
Equal scalar KL at initialization is not bitwise derivative/update parity
for an enabled FP32 KL computation plus BF16 gradient accumulation. The
precise derivative-level cause has not been isolated. This is not a failed
disabled-path test (off exactly reproduces V22), but it limits attribution
of every later on/off difference to semantic regularization alone. Keep a
same-weight KL-gradient null audit as a separate diagnostic; do not silently
change the frozen implementation or erase these observations.

## Reproduction anchor and claim boundary

P-off reproduces prior V22's complete final **fingerprint** (native weights,
FP32 masters, optimizer, RNG, buffers, execution, history and token cursor)
and all 40 dev outputs exactly. It ran 32 updates continuously, whereas V22
used a 16+16 fresh-process resume. The checkpoint **file and whole payload
hashes differ** because source contracts differ; no whole-file equality is
claimed. Native SHA256 is
`d2a6e4f2a9861a211289f3300b98fa9e2877b23a79f254661dd2305912bf2f70`.
P-on's different native SHA256 is
`0909d80e636b732f700f243cd3831cae94adbc4971627cde880dc9ac4b31460c`.

No fresh benchmark, free generation, reader/W/Q intervention, new confirmation
or OOD panel was opened by this FT run. The 512-group expansion stays unused.
Historical FAIL and retention concerns are not erased by improved dev NLL.
**FAIL / winner:none / non_regression NOT_ESTABLISHED** remains unchanged.

## Resources and the next comparison

| Role | Minutes | Peak CUDA allocated GiB | Peak host RSS GiB |
| --- | ---: | ---: | ---: |
| Teacher | 0.96 | 13.898 | 5.571 |
| Canary | 8.72 | 27.751 | 86.868 |
| Replay | 6.04 | 27.750 | 87.071 |
| Off | 83.76 | 27.746 | 86.906 |
| On | 82.94 | 27.761 | 86.910 |

Peak reserved CUDA reached 30.225 GiB in replay. Minimum observed disk free
was 60.830 GiB, above the unchanged 50-GiB floor. These are observed resource
figures, not evidence that KL speeds training or a larger run will fit.

The [next frozen comparison](../../../docs/v23/COMPARISON_01.md) compares
**base/off/on**, with fresh processes and the existing frozen
V22 570-item exposed MMLU panel, 96 world rows on latent/inline routes, and
12 free prompts x two identical seeds. Keep the existing caps and preserve
truncations; inspect exact copying, identity versus punctuation, reasoning,
writing and code separately. Strictly restore v1/v2 ownership before an
explicit inference transition; do not strip a v2 objective to force a v1 load.
No paid judge, new training, deletion or release is implied. This is a new
post-training diagnostic, not untouched confirmatory evidence.
