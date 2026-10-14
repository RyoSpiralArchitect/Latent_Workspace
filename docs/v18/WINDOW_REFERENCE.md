# V18 complete-window and original-reference ownership

2026-10-15. **IMPLEMENTED; final source-isolated qualification pending.**
This is an engineering prerequisite to the [V18 design](PREPARATION.md), not a
new 7B learner result, preservation loss, or reader-selection mechanism.
The original **FAIL / winner:none / non_regression NOT_ESTABLISHED** is unchanged.

## What changes, and what does not

Three additive modules leave the sealed V15/V16 algorithms and evidence intact:

- [WindowReductionSpec](../../src/latent_workspace_ft_v10/v18_window_objective.py)
  derives denominators from the complete ordered window, before backward.
  For n pairs, a affected and u unaffected, counts are 2n answer terms, a donor
  hinges, u unaffected gaps, n unrelated gaps and 3n residual terms. Both a and u
  must be positive in this initial contract; empty strata are rejected, not
  divided by a clamp. Duplicate occurrences and window identifiers are rejected.
- [ReferenceBank](../../src/latent_workspace_ft_v10/v18_reference_bank.py)
  owns supplied full-vocabulary final-prefix logits as immutable primitive
  tuples. Tensor exports are fresh detached CPU copies. Rows bind prompt tokens,
  train-family declarations, source hashes, native dtype and content hashes.
  No capture, disk-backed streaming, preservation loss or semantic family audit
  is implemented. Synthetic qualification rows are labelled as synthetic.
- [V18WindowLearner](../../src/latent_workspace_ft_v10/v18_window_learner.py)
  composes the qualified common or slot/raw owner. It binds schedule, reductions,
  optional bank identity, EOS policy and canonical reader structure before the
  first update. It computes the owned objective itself instead of accepting an
  arbitrary scalar as evidence of the declared reduction.

The old 16-pair, 4-affected window still uses exactly 32/4/12/16/48. Forward graph,
pair order, native-dtype CPU gradient addition, family clipping, FP32 masters,
Adafactor, bridge AdamW and native cast/copy are unchanged. Labels select loss
terms and teacher-forced completion only; no label/donor argument is added to
writer or answer reader. Zero-memory identity is not semantic selectivity.

The objective accepts the old tiny flat term mapping or the explicit 7B mapping
`{terms, eos_weight, query_mode: final}`; mismatched EOS/query policy and missing
or nonfinite weights fail before construction. This is not implicit adoption
of an old trained checkpoint: construction starts from the pinned original.

## Reference provenance and scope

When a bank is supplied, the run must separately declare `reference_source`
(model repository, immutable revision, model-content SHA256, tokenizer SHA256
and execution-policy SHA256). All fields must match the bank. Model content,
execution, vocabulary and native dtype also match the learner's original/native
binding. The caller still owns verifying the actual tokenizer files, capture
origin, prompt/family content and split disjointness: matching declarations do
not establish these facts. The bank's role is `reference_only_no_preservation_loss`.

Full-vocabulary values currently use Python tuples and repeated content checks.
These deliberately conservative mechanics are not a large-bank RAM/throughput
qualification. A future bounded store and capture path need separate estimates
and tests. Preservation must not silently leave reader gradients absent: every
owned parameter still needs a physical finite gradient in every backward slot.

## Save/resume and mutation boundary

The new envelope is `v18-window-reference-resume-v1`. Complete-window cursor,
ordered schedule, optional immutable bank and policy wrap the unchanged inner
state. Snapshots do not alias live tensors or caller metadata. Save is exclusive;
partial windows cannot save or update. Restoration requires externally supplied
metadata, original run contract, schedule, bank and checkpoint content receipt.

Exact outer and nested schemas, typed policy identities, canonical reader graph,
native/master state, optimizer moments and RNG are checked before any target
tensor or global RNG publication. The common arm now also guards normalization
epsilon, dropout, training flags, hooks, module/parameter replacement and storage
aliasing. Publication assumes exclusive ownership and a functioning device;
process death and concurrent out-of-band mutation are not rollback transactions.

## Qualification and next boundary

The [fixed plan](../../configs/v18/WINDOW_REFERENCE_QUALIFICATION_PLAN.json)
selects only tiny synthetic tests, in fresh CPU/CUDA processes from the same
sealed source. CUDA has a 4-GiB allocator ceiling; each suite has a 900-second
deadline. Historical source is not changed to make new tests pass. Comparisons
are within each runtime, not bitwise equality between CPU and CUDA.

After terminal replay, the next factor remains the inference-text-conditioned
selection of differentiated memory, with reciprocal-query controls. This
engineering contract does not establish that factor, a language-quality gain,
Mistral-7B capacity, non-regression or HF beta readiness. No 7B training, new
learner generation, judge request, weight deletion or HF upload is part of it.
