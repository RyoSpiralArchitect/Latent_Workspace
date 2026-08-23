# LatentWorkspace FT V11.0: instrument gate and objective repair

## Question

V10 integrity and transport checks passed, but the bounded full-update routes
collapsed to a constant choice. V11.0 tests one narrower explanation: the
full-vocabulary answer-token cross-entropy may first increase generic answer
token mass instead of learning the balanced `no`/`yes` comparison.

This is an objective-mismatch hypothesis, not an established cause.

## Step 0: qualify the instrument

`configs/v11/GATE0_CONTRACT.json` froze the first gate before execution. The
gate loads the pinned Mistral-7B revision and the complete 64-record eval
corpus, then evaluates the current grouped-world wrapper in two paired modes:

- `F0_query_only`: query plus answer continuation, without context;
- `F1_inline`: exact `context + "\n\n" + query` continuation.

For every valid world side and query, the script also calls the wrapped base
model directly on the same flattened tensor. Training is blocked unless
direct/wrapper logits and predictions are exact, the labels are balanced, F1
overall and one-hop Wilson lower bounds exceed chance, both labels are
predicted, both label recalls remain usable, and F1 improves over F0.

The legacy raw continuation did show a non-chance F1 signal, but failed the
frozen per-label recall gate. It was not qualified. Four prompt styles were
then compared only on a frozen subset of the training corpus. The selected
`symmetric_instruction` style was bound in
`configs/v11/CONTINUATION_AFTER_GATE0_BLOCK.json`, and
`configs/v11/GATE0_SYMMETRIC_CONTRACT.json` authorized one untouched-eval
qualification run. That second gate passed all nine checks. No threshold was
relaxed and no prompt was selected on eval.

## Single changed mechanism

V10 used the target token's cross-entropy over the complete vocabulary. V11.0
adds three explicit modes:

- `full_vocab`: the backward-compatible V10 objective;
- `choice_normalized`: cross-entropy over only the declared candidate logits;
- `hybrid`: choice-normalized CE plus a configured amount of full-vocabulary
  CE.

The V11.0 pilots select `choice_normalized` with full-vocabulary weight `0.0`.
The old full-vocabulary NLL remains a reported diagnostic. Optimizer, learning
rates, clipping, data bytes, model revision, accumulation, and CPU transport
stay fixed. Relative to the original V10 run, the qualified continuation also
changes elicitation from legacy to the train-selected symmetric instruction;
therefore the continuation is not a one-factor causal comparison against V10.

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

## Frozen result

Gate-0 qualified the instrument at optimizer step zero:

- F0 accuracy: 0.4980
- F1 accuracy: 0.7793
- F1 one-hop accuracy: 0.6816
- F1 no/yes recall: 0.6758 / 0.8828
- F1 minus F0 accuracy: +0.2812
- direct-base versus wrapper logits: bitwise exact

The 16-step F1 pilot then completed with integrity `PASS` but scientific status
`BLOCKED`. At step 4 it had already become constant `yes`; at step 16 its
choice loss was 0.6934, accuracy 0.5000, no/yes recall 0.0 / 1.0, and
full-vocabulary NLL 14.9688. All five frozen positive-control gates failed, so
O0 was not launched.

The pre-pruning behavior workflow also completed. The original model scored
0.875 and emitted both labels on the selected 32-case inline subset. The
trained final emitted `yes` for all 32 and its six free-form completions
degenerated into repetitions dominated by `#`, `no`, and `Question`. The 28
GiB run root and final weights remain on Furnace; no pruning was performed.

The compact evidence is under
`provenance/pilots/v11_f1_symmetric_choice_repair_seed42_step16/`.

## Next handoff

Choice normalization is not a sufficient repair under the frozen full-update
schedule. The next experiment should be a pre-registered F1 update-response
surface that saves or evaluates after one update and varies only update
dynamics (for example base learning rate, optimizer family, or update
precision) with a no-update control. It must pass the F1 positive control
before any O0 workspace branch, matrix expansion, or 14B scaling.

## Claim boundary

A Gate-0 PASS validates only this pinned model, data, raw prompt, constrained
choices, and wrapper implementation. A pilot integrity PASS means the run is
complete and auditable; it is not a positive scientific result. One seed and
two bounded routes cannot establish a general objective-repair claim.
