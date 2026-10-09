# Prospective cue-by-envelope confirmation before V15 learning

Client date: 2026-10-10. This protocol and its complete inputs must be committed
before model scoring. The primary method is **native chat without the internal
`Answer:` cue**. The other three methods are comparators, not fallback winners.
This is a new bounded base-only run. No historical generation score, failed
gate, source file, or exact replay policy is amended.

## Isolated question and fixed panel

Does the historical `Answer:` cue inside the user message interfere with the
native dialogue envelope? Cross raw/native-chat with present/absent cue. Keep
the identical symmetric instruction, facts, query wording, pinned model,
tokenizer, and generation/scoring policy across the two cue conditions. Remove
only the final eight characters ` Answer:` when absent. Do not rewrite the
instruction, introduce examples, or add a system message. The original query
with its cue remains metadata for symbolic parsing and exact question-span
binding; only the inference string changes.

Freeze seed 15002, 16 six-entity worlds, each with reciprocal atomic one-fact
and full-five-fact three-hop queries: 64 cases. Half the families use each of
the existing `ranked above` and `outrank` templates. Exclude all 640 historical
train/eval exact world orders and the 8 previously exposed elicitation orders.
Also exclude unordered atomic entity pairs seen in the exposed elicitation
panel, and do not reuse them among these 16 families. Reject families only on
these declared structural rules, never on model answers or margins. Labels
come from the text graph oracle. Reciprocal queries share byte-identical facts.

Names, relations, and wording templates are still from the historical task;
these are fresh instances, not unseen-task or independent lexical generalization.
Queries within a world are correlated. Atomic versus full-chain comparisons
also change hop count: they are not a causal distractor ablation.

Each case has four cue/envelope combinations and query-only/inline information:
**512 prefixes and 512 greedy generations**. Query-only lacks facts and measures
answer/format priors, not equal-information capability. No sampling selection
or additional development generation is part of this unit.

## Tokenization and native execution

Verify pinned metadata and active chat template. No double BOS, automatic
truncation, suffix fallback, or approximate question span is permitted. Present
cue rendering must reproduce the preceding renderer exactly on the new text.
Absent cue uses the same envelope with the one declared removal; independently
rebind offsets and entire prefix IDs. The canonical query metadata is not fed
to the model by the span binder. Verify text/tokenized chat-template agreement.

Check ordinary/base versus shared full-sequence, full-vocabulary native logits
on every initial prefix. All generation and forced-alias readouts also check
the historical native implementation. No workspace reader is loaded. A zero
residual is not a newly qualified zero-memory bridge.

Pinned Mistral-7B-Instruct-v0.3 revision and base hash remain unchanged. CPU
threads=2, nice=10, CUDA Torch cap=18 GiB, admission-free>=20 GiB, abort sampled
free<4 GiB. Poll every 16 forward groups and at loading/completion; peaks of
device/process allocations are sampled, while the cap covers Torch only.
Never interrupt another job to obtain these resources.

## Three distinct observations

1. Lowercase initial-choice logits, ties, and full-vocabulary probabilities.
2. Four symmetric fixed alias paths (` no`, ` No`, ` yes`, ` Yes`), both at
   initial token and followed immediately by EOS. Exact one-token extensions,
   within-class token deduplication, cross-class collision rejection, full-vocab
   FP64 log-softmax. Sum all unique paths per class; retain unnormalized masses.
   This finite set is not exhaustive valid-answer mass and is not a decoder.
3. Natural greedy generation, 64 new tokens, model EOS only. The whole stripped
   casefolded answer must equal no/yes and terminate at EOS. Extra text,
   truncation and invalid answers remain failures; no first-word repair.

The frozen generation gate—not forced-path ranking—decides qualification. No
constraint, EOS reward, candidate reranker, or selected best prefix is applied
to generation. Record every generated ID, full decoded answer, termination,
and native token trace. Preserve the complete 512-output answer bank.

## Primary gate, decision, and claim ceiling

On the 64-case inline/greedy primary cell require **64/64 valid whole answers
with EOS**, >=24/32 strict correct per view, >=12/16 per view-by-wording, and
>=12/16 per view-by-label. The label floor prevents a yes prior from qualifying
a balanced aggregate. Report every comparator and reciprocal both-correct
count, plus paired cue-removal corrections/regressions, without selecting a new
primary method after results. Missing or incomplete execution is not a pass.

A pass qualifies only this finite base-model instrument panel. It does not
prove causal use of facts, workspace semantic direction, general response
quality, correctness non-regression, or readiness for FT-beta. On failure, do
not start another learner or compensate with gain/token-budget increases.
On pass, decide the next separately frozen, matched learner experiment; no
optimizer run is automatically triggered by this script. Preserve the earlier
judge-derived quality objectives and aligned-serialization controls.

## Prospective numerical verification

The preceding completion summary has four one-ULP Linux/Mac differences and
retains its exact-replay failure. This new protocol fixes its own verification
policy before execution: raw bytes, source hashes, token/text identities,
categorical predictions and all accounting remain exact. Recomputed scalar
exp/log probability arithmetic uses relative 1e-12 / absolute 1e-15; log-gap
identity uses absolute 1e-12. The report summary contains only integer/categorical
accounting, not newly exponentiated aggregate probabilities. Raw probabilities
remain unchanged and indexed. This policy is not retroactive to the prior run.

Verify the complete corpus regeneration, rendering/grid identities, no-update
hashes, resources, native parity receipts, token-trace consistency and frozen
gate. Portable checks do not independently reload the model or reconstruct
unretained full logits. Publish planned/completed denominators and negative
outcomes alongside any positive slice.
