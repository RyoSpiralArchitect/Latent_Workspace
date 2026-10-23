# R1: native input-route learning, not another format loss

The first V24 probe found conditional option binding already present, weaker
content selectivity in three of four exposed world groups after FT, and much
larger likelihood improvements on format than content. This motivates a
**matched route-learning experiment**, not a claim that an adapter, new loss
or recurrence has solved intelligence.

## Predeclared contrast

Start both arms from the pinned original Mistral-7B-Instruct-v0.3. Give them the
same examples, reference answers, ordered update windows, supervised token
counts and seed. Only the information route changes: supplied record inline
in the user message, versus the same record at the native memory M interface.
Both use the existing query-only full-vocabulary CE, all native parameters,
FP32 CPU masters, BF16 model and the historical optimizer/LR/clip policy. Keep
P=0 in **both** arms as an explicit control, not a claim that P-off won V23.
No new adapter or numerical engine policy is introduced in this data factor.

Inline and workspace do not have identical token positions, arithmetic or
compute. This contrast measures the joint route/training interaction, **not**
matched-FLOP superiority, newly computed S, recurrent reasoning or KV memory.
The larger supplied record is not latent thought. We do not compare either
new arm to V23 and attribute all differences to one causal factor: the new
curriculum differs from that historical study.

## Sources and leakage boundary

- Existing V23 additive world bank: independent/shared-prefix identifiers,
  multiple questions, twins, missing/unrelated controls. It has not been trained
  before. Former two-hop family is explicitly trainable; three-hop stays OOD.
- New executable arithmetic, register-trace and stable-filter tasks: **264
  groups / 2,112 raw rows**, including 192 train, 24 development and 48 untouched
  confirmation groups. Each has two records and affected/unaffected/absent/
  unrelated questions. The non-missing references are checked by two code paths.
- Unchanged English instruction/prose/code preservation rows from the V22
  sealed bank. Keep these source-owned token arrays private on Furnace; the
  existing research-use permission does not imply redistribution/HF clearance.

No exposed MMLU(-Pro) problem, V24 diagnostic answer, judge output, benchmark
gold, or model-produced selection enters these generators. All variants of a
source group stay together. Confirmation and three-hop OOD are never projected
into the training registry. Repeated unknown controls are deduplicated within
each source group, with identical aliases in both routes.

The [recipe](../../configs/v24/RECRUITMENT_BANK_01.json) fixes 32 complete
token-weighted windows per arm, at least 512 target tokens per window. Requested
token shares are world 10%, new reasoning/transform 10%, instruction 40%, prose
25%, code 15%. Whole-row overshoot is reported, not hidden. The old preservation
mixture remains 80% by requested target share; JSON format receives no new
auxiliary loss or intrinsic reward. It may still learn formatting: content,
intermediate steps, exact copying and complete output must be scored separately.

The frozen schedule actually selects 538 distinct rows from 403 source groups.
Of these, 457 synthetic rows come from 324 world/reasoning groups. Only **9 of
324** selected synthetic groups include both affected twin sides; **zero** have
all six distinct cells selected. These counts follow directly from the public
synthetic rows and fixed schedule in the [prepared bank](../../provenance/engineering/v24_recruitment_preparation01_20261023/furnace/raw/data/bank/MANIFEST.json).
The generator's full control structure is not equivalent to balanced exposure
to every control in 32 updates. R1 tests matched input-route learning with a
sparse row-level curriculum, not a complete pairwise contrastive-training
experiment. This post-freeze audit does not resample or change the schedule.

## Qualification and storage lifecycle

First run the [data-only preparation](../../scripts/prepare_v24_recruitment.py)
with the pinned offline tokenizer and isolated CPU tests. Its measured token
counts, route hashes and exact schedule become a frozen input to a separate
FT source seal. No 7B call or training is authorized by a successful data receipt
alone. Next qualify the unchanged owner plus the new routing/schedule harness
on tiny CPU/CUDA; run a two-update mixed-route canary and exact fresh-process
replay. Canary updates are never inherited by a scientific arm.

Disk floor stays 50 GiB. After the V15 engineering retirement, approximately
120 GiB was free. One 28-GiB canary plus two 28-GiB finals would require 134 GiB,
so the planned lifecycle is: canary -> verified replay -> published exact
retirement ledger -> retire only that spent canary -> two 28-GiB final saves.
Peak new retained weight bodies are then 56 GiB, requiring **106 GiB** plus
small artifacts. A runner cannot delete bodies automatically. Every phase
rechecks live shared-disk, host-memory and GPU availability; no floor is lowered.

## Evaluation boundary before any quality claim

Each candidate needs original/candidate × absent/inline/workspace development
cells (nine unique cells for original plus two candidate models), relevant/twin/
unrelated/absent controls, and a fully specified ordinary no-memory capability
panel. An absent-record question has an unknown-answer oracle: it is a boundary
control, **not** a test of ordinary reasoning ability. Fully specified ordinary
questions are a distinct endpoint. Equal generation budgets and source-group
denominators are required; parse errors/wrong answers stay wrong, not excluded.

Report content accuracy, reference-step correctness, copy fidelity, output
completeness, paired repairs/losses and native readout stages separately. Correct
JSON alone is not capability. The supplied information contrast alone is not
workspace-mediated intelligence. No choice among the new arms, held-out
confirmation claim, broad non-regression or release follows from training loss.
Writing/judge qualification and public-benchmark comparison remain separate
protocols. Old gate `FAIL`, winner `none`, non-regression `NOT_ESTABLISHED` remain.

**Current status (2026-10-23):** data frozen; 570/570 CPU and 570/570 CUDA
qualification PASS. The [first 7B canary attempt](../../provenance/engineering/v24_recruitment_ft01_20261023/README.md)
completed one update and saved before detecting a separate GPU client. It is
sealed as `INCOMPLETE_NO_RETRY`; exact replay and both scientific arms are
unrun. No new scientific checkpoint or quality result is claimed here. The
canary body is retained, and the successful-replay retirement gate is not met.
