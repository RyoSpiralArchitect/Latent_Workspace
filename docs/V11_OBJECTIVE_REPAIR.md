# LatentWorkspace FT V11.0: instrument gate and objective repair

## Question

V10 integrity and transport checks passed, but the bounded full-update routes
collapsed to a constant choice. V11.0 tests one narrower explanation: the
full-vocabulary answer-token cross-entropy may first increase generic answer
token mass instead of learning the balanced `no`/`yes` comparison.

This is an objective-mismatch hypothesis, not an established cause.

## Step 0: qualify the instrument

`configs/v11/GATE0_CONTRACT.json` freezes the gate before execution. The gate
loads the pinned Mistral-7B revision and the complete 64-record eval corpus,
then evaluates the current grouped-world wrapper in two paired modes:

- `F0_query_only`: query plus answer continuation, without context;
- `F1_inline`: exact `context + "\n\n" + query` continuation.

For every valid world side and query, the script also calls the wrapped base
model directly on the same flattened tensor. Training is blocked unless
direct/wrapper logits and predictions are exact, the labels are balanced, F1
overall and one-hop Wilson lower bounds exceed chance, both labels are
predicted, both label recalls remain usable, and F1 improves over F0.

This deliberately qualifies the legacy `use_chat_template: false` instrument.
Changing the elicitation after looking at these results would require a new
frozen contract and a fresh calibration surface.

## Single changed mechanism

V10 used the target token's cross-entropy over the complete vocabulary. V11.0
adds three explicit modes:

- `full_vocab`: the backward-compatible V10 objective;
- `choice_normalized`: cross-entropy over only the declared candidate logits;
- `hybrid`: choice-normalized CE plus a configured amount of full-vocabulary
  CE.

The V11.0 pilots select `choice_normalized` with full-vocabulary weight `0.0`.
The old full-vocabulary NLL remains a reported diagnostic. Optimizer, learning
rates, clipping, data bytes, prompt format, model revision, accumulation, and
CPU transport stay fixed.

The evaluator additionally records per-label recall and prediction counts,
prediction entropy, mean signed `yes - no` gap, constrained-choice loss, and
full-vocabulary loss. A fresh training run writes `eval-step0` before the first
optimizer update.

## Bounded sequence

1. Run exact Gate-0. Stop on any failed check.
2. Run the 16-step F1 inline positive control.
3. Run the 16-step O0 active workspace route only if the F1 control passes its
   frozen gates.
4. Capture task-native and free-form generation behavior before considering
   weight pruning.

The frozen thresholds and config hashes are in
`configs/v11/CONTRACT.json`. Pure-native B/F1/O3 equivalence, the 57-run
matrix, 14B scaling, and optimizer redesign remain out of scope.

## Claim boundary

A Gate-0 PASS validates only this pinned model, data, raw prompt, constrained
choices, and wrapper implementation. A pilot integrity PASS means the run is
complete and auditable; it is not a positive scientific result. One seed and
two bounded routes cannot establish a general objective-repair claim.
