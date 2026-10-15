# Pre-V15 learning: base-only answer-realization qualification

Client date: 2026-10-10. **PROSPECTIVE PROTOCOL / NOT EXECUTED**.

Here **V15 learning** means the next new training run; existing `v15` module
names label the completed engineering/readout work, not a trained V15 model.
This is the next bounded, no-training unit proposed in
[NEXT_STEPS.md](NEXT_STEPS.md). It follows the completed native-readout
transport assay, whose 64 functional generations all failed the whole-answer
contract. It does not alter those historical outcomes, train another bridge,
or qualify V15 learning or FT-beta release.

## Question and historical boundary

Can the pinned base model express the requested yes/no answer, terminate, and
answer a balanced fixed panel correctly when the **same complete task content**
is put inside its native chat envelope instead of the historical raw prefix?

This is not the first Mistral prompt-template test. The V14 prompt and
demonstration gates already tested plain/native instructions and capitalization
on the earlier seven-fact corpus. Those full-context gates were blocked. The
subsequent atomic-evidence gate qualified a native direct-capitalized renderer
and first-token scorer for one isolated edge; its report explicitly did not
qualify the full-context task or free generation. These earlier choice-readout
results are neither erased nor transferred to the present generation contract.

The present contrast changes only the model-owned dialogue envelope within
each case and information condition. It does not simultaneously add examples,
rewrite the instruction, capitalize the answer cue, or introduce a grammar.
The primary candidate is declared in advance: `native_chat`. Historical raw
rendering is a comparator, not a fallback selected after seeing results.

## Frozen panel and denominator

The complete corpus, source revision, model/tokenizer identities, and machine
plan must be frozen before model scoring. No cases are selected by their
generated answers, choice margins, or whether they differ between methods.

- **Exposed development:** four cases from the two previously exposed worlds,
  the reciprocal query pair used by the preceding generation assay. They stay
  development/continuity examples and cannot qualify the instrument.
- **Fresh confirmation:** eight deterministic families, seed `15001`, each
  supplying an atomic reciprocal pair and a five-fact, three-hop reciprocal
  pair: 32 cases. Four families use the `Is ... ranked above ...?` wording and
  four use `Does ... outrank ...?`. Reject overlap with historical exact world
  orders before freezing the corpus; record that audit.
- Both labels occur equally in every reciprocal pair. The historical name
  vocabulary and task templates are reused. These are fresh world instances,
  not unseen lexical or task-family generalization.

Each of the 36 cases has two renderers, two information conditions, and two
decoding regimes: **144 initial prefixes and 288 generated sequences**.
The confirmation denominator is 32 per renderer/information/regime cell.
All planned cases remain in the denominator, including invalid, truncated,
incorrect, tied-choice, or failed rows; missing execution cannot be a pass.

The atomic and full-context slices also differ in question/hop difficulty.
Their difference is descriptive and is **not** an isolated causal estimate of
distractor or context-length effects.

## Rendering, tokenization, and readout

1. Construct exactly one task-content string per case/information condition,
   using the historical symmetric lowercase yes/no instruction and answer cue.
   Inline receives the frozen facts; query-only receives none. The native
   renderer wraps the otherwise identical content as one user message, with
   `add_generation_prompt=True` and no system message.
2. Historical raw encoding retains `add_special_tokens=False`, with no newly
   added BOS or EOS. Native chat encoding uses the pinned tokenizer template
   once, followed by `add_special_tokens=False`; compare its IDs with the
   tokenizer's direct chat-template tokenization. Record template hash, exact
   rendered text/IDs, BOS/EOS IDs and counts. Never add a second BOS or infer
   the envelope from a generic `use_chat_template` switch.
3. Rebind the exact question span for every prefix. Require untruncated IDs
   and complete offset coverage. No label, answer, generated text, or outcome
   may determine the span.
4. Freeze lowercase choice suffixes separately from whole-output scoring.
   For each suffix, verify that concatenation preserves the **entire** prefix,
   appends exactly one token, and produces two distinct candidate IDs. Do not
   assume old token IDs apply after a changed boundary. Failure is a binding
   failure, not permission to silently choose another suffix.
5. Score the actual native full-vocabulary output. Record both choice logits,
   yes-minus-no margin, tie/unknown state, choice prediction and correctness,
   and full-vocabulary choice probabilities. These lowercase first-token
   diagnostics are not equivalent to casefolded whole-answer validity.
6. Verify ordinary base forward versus the shared native readout, and exact
   zero-residual equality on the new initial-prefix geometry. A zero residual
   in this **base-only** assay is not a freshly verified zero-memory bridge.

Model revision remains the pinned Mistral-7B-Instruct-v0.3 snapshot. The base
is frozen and unchanged. No retained reader checkpoint is loaded, no optimizer
step occurs, and no new model weights are written.

## Generation and scoring

- Greedy: temperature 0, seed 0. Sampled: temperature 0.7, seed 211, using
  the existing full-vocabulary decoder and common-uniform implementation.
- A matched case/seed/token-index uniform is shared across both renderers and
  both information conditions. Renderer and information names must not enter
  that uniform's key. Matched uniforms reduce one source of variation; they
  do not make different prompts equivalent interventions.
- Recompute complete prefixes with `use_cache=False`. This unit does not
  test KV persistence, hidden-state recurrence, or trajectory amplification.
- Stop only on the pinned generation-config EOS token IDs, or after 64 newly
  generated tokens. The budget includes a generated EOS. There is no newline,
  first-word, answer-grammar, or inferred-delimiter stop and no longer retry.
- Preserve all token IDs, full decoded answer, termination reason, length,
  and matched-uniform/selection traces. Use the existing whole-answer parser:
  strip surrounding whitespace, casefold, and require the entire remaining
  text to be exactly `yes` or `no`. Record lowercase compliance separately.
- A **strict correct** result requires both the matching whole answer and
  EOS termination. A correct-looking prefix, extra explanation, or a `yes` at
  the budget boundary without EOS does not count. Parsed validity and EOS
  termination are also reported separately so neither hides the other.

Query-only is an answer-prior/formatting reference. It is not an
equal-information capability baseline or the user's requested non-regression
battery. The inline-versus-query difference combines access to facts and any
consequent formatting change; do not call it isolated semantic transport.

## Prespecified finite-panel gate

The primary gate applies only to **native-chat, inline, greedy confirmation**:

1. All 32/32 cases have a valid whole yes/no answer and EOS termination.
2. Strict correctness is at least 12/16 on the atomic slice and 12/16 on the
   full five-fact, three-hop slice.
3. Strict correctness is at least 6/8 in each view-by-wording slice (atomic
   or full, crossed with ranked-above or outrank).
4. Complete execution, finite outputs, exact declared binding/parity checks,
   unchanged base/source identity, and resource guards pass.

These are finite-panel acceptance counts, not a statistical population claim.
Report both label recalls, reciprocal-pair both-correct counts, query-only
comparisons, native-choice metrics, and all invalid/termination counts beside
the gate. In each view, record paired inline-minus-query strict-correct and
native-choice accuracy differences separately; neither is an added acceptance
gate. An overall mean must not conceal the prespecified slices.

Raw rendering, sampled generation, and exposed development are descriptive
comparisons. They do not substitute for a failed primary cell, select a
different method, or get pooled with greedy confirmation to pass its gate.
The gate qualifies only bounded **answer expression on this fixed panel**;
it does not by itself prove fact use beyond answer priors, robust reasoning,
workspace benefit, or preservation of judge-preferred free-chat behavior.

On failure, preserve the complete negative record and stop this unit. Do not
rewrite instructions, raise the token cap, constrain the decoder, change the
parser, or inspect additional examples until a separately frozen follow-up.
If the method passes, a retained-workspace comparison still needs its own
locked protocol and is not silently included in this base-only run.

## Resource and evidence contract

Use a clean isolated Furnace worktree, the offline pinned cache, CPU thread
limit 2, and the existing admission/abort guards: at least 20 GiB free at
admission, an 18 GiB Torch allocator cap, and stop this run if sampled device
free memory falls below 4 GiB. A currently idle GPU does not enlarge the
scientific comparison or authorize changes to other jobs. Report allocated,
reserved, and sampled process peaks separately.

Publish the frozen plan/corpus/source hashes, tokenization and parity receipts,
initial choice rows, all 288 generation rows, recomputable summaries and gate,
resource log, and human-readable answer bank. Portable verification can check
the recorded identities, complete grid, scorer, traces and scalar arithmetic;
it does not independently reproduce GPU full logits or reload model weights.

No training, cap change, new loss, quantization/offload experiment, paid judge,
checkpoint deletion, or release decision is included. The historical
judge-derived keep/strengthen/add goals, the independent equal-information
base-floor battery, and human review remain pending.
