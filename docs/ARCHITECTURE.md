# Latent Workspace architecture: one stack, portable hosts

2026-10-16. **PROPOSAL; no behavior change.** Ryō asked to organize the
versions so that they stop being islands, keeping the repository's goal in
view: portability to the fine-tuning of other models, and to training from
scratch. Historical modules, runners and seals stay untouched; every past run
stays verifiable from its execution commit.

## What the stack is for

The [V20 square](v20/SCOPE.md) names four things a latent workspace can do.
Every component below serves at least one of them.

| Corner | Question | Lane |
| --- | --- | --- |
| Deliberation (潜在熟考) | Does the model think through a latent lattice formed from its own states? | D |
| Occupancy | Is a workspace state active, and does it persist across turns? | B |
| Availability | Can the state be recruited when needed; does a local memory edit flip only affected answers? | A |
| Consequence | What does forming the workspace leave in the base model and its outputs? | C |

## Six layers, and where today's modules sit

| Layer | Owns | Today |
| --- | --- | --- |
| **1. Host binding** | Decoder cuts (run to cut N, continue from cut N), the native head, prompt rendering | `model_binding.FunctionalBoundaryAdapter` (GPT-2, Mistral, OLMo2, and a custom interface), `v15_readout.NativeWorkspaceReadout` (any linear head), `readout_transport` (`ReadoutAdapter` protocol, `inject_last`), `hf_readout_adapter`, `hf_training_readout`; Mistral-only: `training_binding`, `cache_binding`, `MistralPrecisionBridgeAdapter` |
| **2. Workspace algorithms** | Writers, lattices, readers, budgets, losses, operators; no host layout | `workspace_core` (v9 writer and reader, v4 logit adapter), `engine` (v4.1 and v5 lattices, `LatentWorkspaceLoss`), readers in `precision_bridge`, `query_modulated_bridge`, `v16_slot_contrast`, `v18_selection_reader`, `v19_dual_budget_reader`; `normalization`, `numerics`, `observability` |
| **3. Routes** | Where the workspace speaks to the host | logit residual (v4 adapter, used by V20 D1); answer-position residual through the native head (`inject_last`, V15–V19); residual at a cut with the rest of the decoder run (v9 reader, `engine`'s functional route) |
| **4. Composition** | Writer + lattice + reader + route over a host, text-bound queries | `v15_pipeline`, `adapted_workspace`, `v18_selection_pipeline`, `v19_dual_budget_pipeline`, `engine`'s functional forward, `v20_deliberation.DeliberationRoute`; `reader_query`, `v18_operand_query` |
| **5. Ownership and training** | State guards, exact resume, complete windows, objectives | `v15_native_learner` (used by 16 modules), `adapter_native_learner(_v2)`, per-reader state guards, learners and window learners (V16, V18, V19), `v15_5_learner`, `adapted_pair_objective`, `v18_window_objective`, `v18_reference_bank`; V20 D1's frozen-feature trainer |
| **6. Instruments and execution** | Measurement by corner; sealed runs | `v16_comparison_eval`, `v18_native_eval` (transport decomposition), `v16_population_probe`, `reader_factor_audit`, `bridge_mechanistic`, `learner_gradient_audit`, `answer_bank_generation`, `v15_generation`; `scripts/run_source_sealed.py`, one runner and verifier per run (178 scripts, 178 test files) |

## Where the islands are

1. **v4/v5/v9 algorithms live in a 17,612-line monolith.** V14 moved the v9
   writer, reader and v4 adapter into `workspace_core`, but the lattices and
   `LatentWorkspaceLoss` are still reached only through `engine.py`. V20 D1
   imports them from there.
2. **Each V16–V19 reader carries a full private stack**: pipeline, state guard,
   learner and window learner. V19's owners were derived from V18's by text
   replacement. The ownership logic (exact resume, complete windows, parameter
   partitions) is generic in substance but copied per reader, with partition
   counts such as 20/6/6 hard-coded.
3. **Routes are implicit.** The logit residual (v4, D1), the answer-position
   residual (V15–V19) and the residual at a cut (v9, V10–V14) live in three
   code paths with three evaluators, so results do not compare across routes.
   D1 showed why this matters: the native head reads its own final state
   poorly on this task (0.68 against 0.81–0.89 for a trained readout), which
   bounds every route that must go through it.
4. **Training graphs are Mistral-specific** (`MistralTrainingBinding`,
   `MistralPrecisionBridgeAdapter`, `cache_binding`), while the inference cut
   protocol already covers GPT-2, Mistral and OLMo2, with bitwise native/split
   parity on real OLMo2-1B at cuts 0, 8 and 16
   ([V14 portability](../provenance/pilots/v14_portability_20260904/OBSERVATIONS.md)).
5. **Instruments are per version** (`v16_comparison_eval` → `v18_native_eval`,
   D1's own evaluator), so the same quantity is measured slightly differently
   in each.

## Target: one stack, versions as configurations

- A version-free package, `latent_workspace` (`src/latent_workspace/`), is the
  public API. It wraps and re-exports; the historical package stays as it is.
- **Host** = cut protocol + native head + renderer. Implementations: HF
  decoders through `FunctionalBoundaryAdapter` (GPT-2, Mistral, OLMo2; Llama
  and Qwen layouts to add behind the same fail-closed checks), and a
  **ScratchHost**, a small decoder that implements the custom split interface
  and trains with the workspace from step 0.
- **Workspace** = writer + optional lattice + reader + budget + **route**,
  built from a descriptor. Every historical version becomes a descriptor:
  v4 = lattice + logit route; v9 = writer + reader + cut route; V14–V19 =
  bridge + answer route; V20 D1 = lattice + logit route over final states.
- **One owner** (state guard, exact resume, complete windows), with parameter
  partitions read from the descriptor instead of copied per reader.
- **Instruments by corner, not by version**, and route-agnostic. Availability
  ladder: written memory → read output → route output → native gap → answer.
  Deliberation: step dependence and truncation. Occupancy: branching against
  random perturbations. Consequence: the paired behavior protocol.
- Execution is unchanged (sealed launcher, receipts, offline verifiers), with a
  shared runner skeleton in place of per-run copies.

## Portability targets

- **Other models.** Add decoder layouts to the cut protocol with the same
  fail-closed version checks; generalize the training graph from
  `MistralTrainingBinding` to a decoder-generic binding; qualify each family
  with the V14 native/split parity canary before any experiment.
- **From scratch.** A ScratchHost trains jointly with the workspace from the
  first step: v4's "workspace-forming training" in its plainest form. The same
  descriptors and instruments apply, so scratch and fine-tuning results are
  comparable.

## Migration rules (seal-safe)

1. Historical modules and sealed runners stay byte-identical, so every past
   run remains verifiable from its execution commit and runnable from `main`.
2. The new package wraps. Parity tests, in the style of V14's legacy parity
   tests, show on fixed tiny cases that each wrapper reproduces the historical
   module exactly (outputs, gradients, state).
3. New experiments import only `latent_workspace`.
4. Order: (a) host, routes, descriptors, and the lattice and loss behind the
   new package; (b) the Availability ladder; (c) the generic owner; (d) the
   ScratchHost and a second HF family.

## The three agreed experiments on this stack

- **A1, Availability ladder** on the V19 checkpoints: the V19 descriptor plus
  the ladder instrument; no training. Where is memory content lost?
- **A2, the flip through v4's route**: deferred memory → lattice → logit
  residual, frozen backbone, with the ladder and the unchanged flip endpoints.
  Its claim is that the system (host plus workspace) answers from memory, not
  that memory moves the native head.
- **D2, Deliberation with feedback**: the lattice writes back at a cut and the
  model's own remaining layers continue, so latent steps can change the
  model's computation rather than only its readout.
