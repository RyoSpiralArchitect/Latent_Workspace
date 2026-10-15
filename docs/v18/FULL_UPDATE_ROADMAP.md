# V18: from controlled access to full updates and a conditional release

2026-10-15. Ryō requested further diagnosis, precise implementation, V18 full
updates, benchmarks and a conditional Hugging Face release. Routine engineering
within that request does not require repeated permission. Execution still needs
an explicit frozen source, inputs, budget and terminal receipts; a failed or
ambiguous dispatch is not silently retried.

## Ordered work, with parallel preparation

| Stage | Evidence required | What it does not establish |
| --- | --- | --- |
| Saved-state permutation diagnosis | Original controls reproduced; same-input repeats and instrumented/uninstrumented parity; raw logits and aligned intermediate tensors; original `1e-6` failures retained | Ordered-reader superiority or a repaired historical result |
| Actual writer, controlled facts | Query-independent writer inputs, explicit gradient partition, fresh identity frames, matched controls, archived raw controls and held-out donor/reciprocal/unaffected results | Natural-language extraction or native Mistral improvement |
| New selection owner and pipeline | Explicit query/binding policy and parameter/optimizer/RNG ownership; complete-window arithmetic; CPU/CUDA update and fresh-process resume qualification | Base preservation or semantic success |
| Bounded native integration and full-update pilot | Pinned Mistral revision/tokenizer; contextual backward; native full-vocabulary readout; live memory/storage admission; frozen comparison | A release winner, a large-data result or general non-regression |
| Benchmark and behavior | Original base, updated direct backbone and workspace as distinct conditions; fixed data/settings; all missingness, ties, regressions and repairs | Preference overriding incorrect answers |
| Export and conditional publication | Export-only fresh-load parity; supported inference route; resolved namespace, licenses and release candidate; human review | Untested generic-loader/backend support |

The [supplied-slot study](../../provenance/pilots/v18_operand_selection_continuation_01_20261015/README.md)
passes selected-factor learnability, not the selection-advantage gate. Its
three final-factor permutation failures per runtime remain. The next writer
design is [separate](ACTUAL_WRITER_TRANSITION.md). If a diagnosis requires an
arithmetic change, version and qualify that change across matched arms before
the next fit; never edit the original 572-file execution seal.

Do not turn engineering prerequisites into unnecessary semantic hurdles:
controlled-writer work informs the candidate, but a bounded research full-update
pilot need not already demonstrate the eventual release claim. A native
no-update/backward integration probe can jointly check contextual tensor routing,
bindings, physical gradients and the resource envelope. Larger exploratory
learning after a failed candidate requires an explicitly revised hypothesis,
not a hidden longer run or post-result tolerance change.

## Reuse existing contracts rather than bypass them

Use the qualified `WindowReductionSpec` / complete-window reduction and update
arithmetic. The current `V18WindowLearner` rejects `SelectionWorkspaceBridge`;
the new native selection owner now owns the split-query state, while its window
envelope remains pending. Add that explicit format/owner without widening old
whitelists or loading checkpoints by shape compatibility. A synthetic frozen-
common fit and a real full-update owner have different trainable partitions.
The [additive selection-owner plan](SELECTION_OWNER_PLAN.md) specifies the two
new owner boundaries, fresh-process qualification and static storage forecast;
the native owner passes 150 local tiny same-process cases and ten separate
CPU process-restart cases. The [window owner](SELECTION_WINDOW_QUALIFICATION.md)
then passed its sealed Furnace CPU and CUDA qualification (102 tests and ten
fresh-process restart pairs per device). Real 7B integration remains pending. The
[local engineering record](../../provenance/pilots/v18_selection_owner_local_20261015/README.md)
separates these tests from real-model and scientific qualification.

`run_v16_full_comparison.py` supplies resource, replay and artifact patterns,
not a V18 executable: it fixes old owners, three arms and two updates.
Likewise reuse native MMLU scoring and strict-tie handling from
`run_v16_population_eval.py`, not its old denominators or exposed 570 rows as a
fresh final gate. Source/model/data manifests must identify the new study.

Prepare correctness/behavior evaluation and inference export in parallel with
owner qualification. The original-base reference bank currently owns supplied
logits only; preservation supervision is a separate factor. Do not add a new
reader, writer loss, gain and preservation loss together and attribute the
result to just one mechanism.

## Contextual and free-generation scope

The current operand binder supports only two explicit relational question
grammars. It is not an arbitrary-writing prompt interpreter. Workspace-enabled
general prompts need a separately specified routing/binding policy; do not
guess operands or fabricate memory silently. Updated-direct-backbone writing
can be evaluated separately without making that workspace claim.

Existing generation helpers group by token prefix. When backbones differ, cache
ownership must also include model/checkpoint identity, or execute each backbone
separately. Matched seeds or common random numbers do not make distinct model
states interchangeable. Native zero-memory parity is with the candidate's own
direct backbone, not automatically the original base.

## Resources and unresolved publication choices

The historical V16 full update observed 29,835,256,320 bytes peak CUDA allocated,
30,454,841,344 reserved, and up to 95,808,610,304 host RSS. The unchanged-shape
[selection forecast](SELECTION_OWNER_PLAN.md) keeps **64 GiB retained outputs
plus 50 GiB free floor = 114 GiB for one arm**; three retained arms require
**192 + 50 = 242 GiB**. A third checkpoint written before oldest-checkpoint
rotation needs additional transient space (about 27.086 GiB; a conservative
32-GiB allowance makes the one-arm budget 146 GiB including the floor).
Reference-bank or export copies need their own allowance. These are
[prior results](../../provenance/pilots/v16_full_comparison_20261014/RESULTS.md)
and the [slot-arm resource receipt](../../provenance/pilots/v16_full_comparison_20261014/raw/slot_contrast/FINISHED.json),
not a V18 resource qualification. Re-measure with the actual sequence lengths, split queries,
retained graphs and chosen reference representation before a long run. Retain
the latest two checkpoints per condition; no deletion is authorized by this
document itself.

The historical correctness tolerance remains delta = 0. Freeze the new empirical
score floors, protected slices, uncertainty reporting and release decision rule
before candidate selection; do not conflate an observed score floor with formal
noninferiority. Any relaxation needs Ryō's explicit decision. The existing
MMLU570 and favorable V14 judge examples are exposed evidence, not training gold.

HF namespace/repository, redistribution/code license, final candidate and the
public visibility transition remain unresolved. They do not block the present
diagnostic or scoped FT engineering. Follow the [release contract](HF_RELEASE.md)
before any upload; ship the workspace and pinned loader as well as backbone
weights, excluding optimizer/RNG/private artifacts. No paid cloud training or
hosted endpoint is selected: the requested compute target remains Furnace.

Keep separate: engineering correctness; controlled learnability; native
semantic memory use; original-base non-regression; export/inference parity.
The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.
