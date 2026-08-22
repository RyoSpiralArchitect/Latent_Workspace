# Pre-prune generation behavior workflow

This workflow makes a bounded behavioral snapshot a required gate before a
trained base-model bundle may be pruned. Metric integrity remains necessary,
but is no longer the only retained view of a run.

## Required inputs

- a full, loadable final bundle with `manifest.json`, `experiment_config.json`,
  `workspace_state.pt`, and `base_model/`;
- the pinned original model ID and immutable revision;
- a versioned prompt suite and task-native JSONL dataset inside the repository;
- an offline local model cache; and
- any matched candidate/reference pair whose transport implementation is
  expected to be behaviorally exact.

The current prompt contract is
[`configs/v10/behavior_prompt_suite_v1.json`](../configs/v10/behavior_prompt_suite_v1.json).
Its task-native selection must have balanced expected choices and must include
both affected/unaffected and heldout/non-heldout cases. The capture fails closed
if any gate is absent.

## Two behavior surfaces

The capture deliberately keeps two surfaces separate.

1. Free-form generation uses deterministic greedy decoding through the pinned
   Mistral chat template. The original model and every saved trained
   `base_model/` receive the same prompts and token budget. For trained bundles,
   this surface exercises the saved base trunk only; it does not claim to use
   functional workspace tensors.
2. Task-native behavior evaluates one-token constrained choices on frozen
   functional world pairs. The original model is recorded as raw causal
   query-only and inline-context baselines. Each trained bundle is reconstructed
   as the complete `LatentWorkspaceCausalLM` and runs its configured functional
   route with intact memory.

The receipt retains prompt text, decoded completions, completion token IDs,
choice logits, predictions, exact hashes, model inventories, and source/config
bindings. A declared transport pair must match exactly in free-form completion
tokens, all task-native choice logits, and selected predictions.

## Capture command

Run from the repository root after assigning the offline cache to a
task-specific variable:

```bash
LW_HF_CACHE=/absolute/path/to/hf-cache

HF_HUB_CACHE="$LW_HF_CACHE" \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
TOKENIZERS_PARALLELISM=false \
PYTHONPATH=src \
python3 scripts/capture_v10_generation_behavior.py \
  --repo-root . \
  --prompt-suite configs/v10/behavior_prompt_suite_v1.json \
  --original-model mistralai/Mistral-7B-Instruct-v0.3 \
  --original-revision c170c708c41dac9275d15a8fff4eca08d52bab71 \
  --checkpoint F0=runs/v10/transport_v2/F0_cpu_accumulate_seed42_step1/final \
  --checkpoint B=runs/v10/transport_v2/B_cpu_accumulate_seed42_step1/final \
  --checkpoint F1=runs/v10/transport_v2/F1_cpu_accumulate_seed42_step1/final \
  --checkpoint O3=runs/v10/transport_v2/O3_cpu_accumulate_seed42_step1/final \
  --checkpoint B_reference=runs/v10/transport_v2/B_cuda_merge_reference_seed42_step1/final \
  --transport-pair B=B_reference \
  --device cuda \
  --max-new-tokens 96 \
  --seed 20260822 \
  --output provenance/pilots/transport_v2_cpu_accumulate/GENERATION_BEHAVIOR_V1.json
```

Existing output is never replaced unless `--overwrite` is explicit. An error
produces an `ERROR` receipt and no passing claim.

## Human observation record

A `PASS` receipt is not the end of the workflow. Before pruning, a reviewer must
read every completion and the selected task-native cases, then record:

- the frozen question and design;
- instruction-following, coherence, correctness, truncation, and qualitative
  changes, including regressions and non-changes;
- failed prompt or selection designs;
- the distinction between base-trunk free-form behavior and complete-wrapper
  task behavior;
- exact provenance hashes; and
- a claim boundary that rules out broad quality or scientific conclusions.

The first completed record is
[`BEHAVIOR_OBSERVATIONS.md`](../provenance/pilots/transport_v2_cpu_accumulate/BEHAVIOR_OBSERVATIONS.md).

## Pruning gate

A trained weight target may be placed in a prune intent only after all of the
following are durable and rehashed:

- the generation receipt has `status: PASS`;
- every declared transport sentinel passed;
- the human observation record exists and preserves negative results;
- the receipt's checkpoint inventory still matches the live bundle; and
- the prune receipt binds the generation receipt and observation record hashes.

Hashes and decoded outputs are evidence, not a trained-weight backup. Pruning
remains explicit, target-bounded, and non-recoverable unless a separate weight
archive is named.

The first transport-pilot cleanup uses
[`scripts/prune_transport_v2_weights.py`](../scripts/prune_transport_v2_weights.py).
It freezes an exact intent, requires that intent to be published before any
unlink, rehashes every target and bound behavior artifact, and uses the distinct
state `transport_pilot_weights_pruned`. It must not relabel one-step engineering
pilots as `verified_pruned`.

## Claim boundary

This workflow proves only a deterministic, artifact-bound capture on the named
prompts, task cases, model revisions, checkpoints, software, and device. It is
not a broad behavioral-equivalence test, a benchmark, a safety evaluation, a
model-quality result, or evidence that a latent workspace is causally useful.
