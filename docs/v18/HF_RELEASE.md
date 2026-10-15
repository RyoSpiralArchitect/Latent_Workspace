# Conditional Hugging Face beta release preparation

2026-10-15. **PREPARATION ONLY / NO V18 WEIGHTS / NO HUB REPOSITORY CREATED**.

Requested display name: **mistral-7b-instruct-ver0.3-LTWspaced β**.
Provisional ASCII repository slug: `mistral-7b-instruct-v0.3-LTWspaced-beta`.
The owner/organization and final repository ID are **UNRESOLVED**; availability
and write authority have not been checked. Do not publish to an inferred
namespace. The [model-card draft](MODEL_CARD_DRAFT.md) is not release evidence.

Ryō's condition is no marked V18 degradation plus interesting, reproducible
behavioral differences. This establishes a release-preparation target, not
permission to skip missing gates or to upload the current V16 weights as V18.

## Decide the release contract before observing V18 results

1. Freeze what "no marked degradation" means for each primary benchmark and
   protected slice: allowed loss, uncertainty, missingness and multiplicity.
   The previous proposed FT-beta floor is delta = 0; it is not silently relaxed
   by this document. A separately agreed beta risk allowance would be an
   explicit prospective policy, not a changed historical PASS or a claim of
   strict noninferiority. Current MMLU570 is exposed descriptive evidence.
2. Freeze an equal-information correctness battery and a fresh paired behavior
   bank covering assistance, checkable reasoning and constrained writing.
   Compare original base, updated direct backbone and workspace-enabled model.
   Preserve all answers, failures and unchanged cases, not only a win gallery.
3. Require repeatable useful differences, grounded/constraint-aware judgments,
   and Ryō's independent review. Preference cannot compensate for incorrect
   reasoning or unacceptable protected-slice regression. Neither a model judge
   nor this document alone selects a release candidate.
4. Preserve a separate content-use claim: if donor-selective memory use is
   unproven, say so. Do not market changed phrasing as demonstrated new reasoning,
   intelligence, or causal workspace functionality.

The [V16 terminal result](../../provenance/pilots/v16_population_diagnostics_20261015/RESULTS.md)
is a diagnostic predecessor, not a V18 score. V18 training, generation and
judgment remain unexecuted. The [learner preparation](PREPARATION.md) and
[behavior protocol](BEHAVIOR_EVALUATION.md) must become qualified, frozen
execution contracts before collecting those outcomes.

## An inference release, not a raw optimizer checkpoint

The public artifact must contain the updated backbone **and** the trained
writer/reader/selection state needed for the advertised behavior, plus a pinned
loader. Exporting only backbone weights loses the workspace; shipping the full
research checkpoint unnecessarily includes optimizer/master/RNG state.

Proposed package, to be implemented and verified:

- Native backbone safetensor shards/config and exact tokenizer/chat template.
- Separate safetensor workspace tensors, an explicit architecture/state
  descriptor, masks/normalization/readout policy and a versioned inference API.
- Manifest of source commit, model/checkpoint/input hashes, tensor schemas,
  dependencies, runtime/dtype/backend and all inference artifact hashes.
- Executable minimal examples for ordinary direct generation and workspace
  generation, with authoritative-memory handling and no label leakage.
- Model card, license/attribution/notice files, limitations, exact evaluation
  artifacts, and a reproducible smaller smoke fixture that does not contain
  private prompts, credentials or provider secrets.

Choose a qualified packaging route: a pinned explicit Python package/loader or
a separately audited Transformers custom-model wrapper. Do not claim generic
`AutoModelForCausalLM`, vLLM, quantized, CPU, MPS or hosted-inference support
unless that route is actually tested. A standard backbone loader alone does not
activate the custom workspace. Do not require arbitrary remote-code execution
without explaining and reviewing the exact code being loaded.

In a fresh process/environment, reconstruct from **only the export**, verify
tensor and native zero-path identity, compare fixed same-prefix logits and
matched-seed generation with the original candidate, and record unsupported
runtime paths. Export/parity failure blocks upload; do not convert weights or
relax tolerances silently. Keep research resume checkpoints separate and retain
the latest two checkpoints per condition under the existing policy.

## Rights, card and publication checks

The pinned upstream
[Mistral-7B-Instruct-v0.3 card](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3/blob/c170c708c41dac9275d15a8fff4eca08d52bab71/README.md)
declares Apache-2.0. Before publishing, inventory the actual bundled license
and notice obligations for model, tokenizer, new code, data and examples;
preserve required attribution and document modifications. The derivative code
license and redistribution clearance remain **UNRESOLVED** here. The upstream
label alone is not clearance for every added artifact or data source.

Follow the official [Hub model-card format](https://huggingface.co/docs/hub/model-cards)
and [license metadata guidance](https://huggingface.co/docs/hub/repositories-licenses).
Fill only verified metadata: upstream model/revision, actual full-fine-tuning
method and workspace, supported languages/runtimes, license, task and measured
evaluation results. Do not copy upstream leaderboard values or V16 diagnostics
into a V18 model-index. Keep the beta/research-use status, inherited limitations,
regressions, judge disagreement and missingness prominent.

Use the supported `hf` CLI for eventual transfer; verify installed help/version
and the exact account/repository before any write. Credentials stay in the
authorized environment, not command arguments, exported files or logs. Create
no repository, upload, visibility change, tag, hosted endpoint or paid service
from this plan. An eventual staged/private validation and public transition
must target the explicitly resolved repository and the agreed release candidate.

Before publication, review the complete file allowlist and size budget; exclude
optimizer states, raw private logs, tokens, caches, unrelated research and
unlicensed artifacts. Verify the downloaded revision's hashes and a fresh-load
smoke, retain immutable candidate/evaluation identities, and only then record
the public revision and URL. A successful upload is separate from valid
inference, a reproduced evaluation, and release qualification.

## Open decisions (not silently filled)

- Beta risk tolerance/protected slices and statistical acceptance contract.
- One V18 reader factor, general-window implementation and preservation axis.
- Final train/dev/holdout families, model seeds and resource/storage budgets.
- Generation-cap and same-seed bank manifest; judge IDs/settings/calibration.
- HF namespace, final slug, code/data licensing, loader/export route.
- Exact release candidate, complete evaluation and explicit publication decision.

No key was read for this release plan. No HF write or model API call occurred.
