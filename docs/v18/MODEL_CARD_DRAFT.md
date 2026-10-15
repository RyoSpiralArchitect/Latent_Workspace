# mistral-7b-instruct-ver0.3-LTWspaced β

**UNRELEASED MODEL-CARD DRAFT — V18 IS NOT TRAINED OR EVALUATED.**
Do not upload this draft as if it described available model weights. Hub YAML
metadata and model-index are intentionally absent until their values are
verified. See [release preparation](HF_RELEASE.md) for all blocking decisions.

## Model identity and purpose

Planned upstream: `mistralai/Mistral-7B-Instruct-v0.3`, pinned revision
`c170c708c41dac9275d15a8fff4eca08d52bab71`.
Planned derivative: a full-updated backbone with a query-independent latent
workspace writer and an inference-question-conditioned reader, using the native
model readout. Actual V18 design, training recipe, source commit, checkpoint
hash and inference export revision: **NOT YET FIXED**.

Research objective: retain useful base behavior, improve selective use of
memory, and investigate differences in assistance, reasoning and writing
without unacceptable correctness regressions. These are objectives, not
demonstrated capabilities. This derivative is not an official Mistral release.

## Evidence status

| Required evidence | Current V18 status |
| --- | --- |
| Updated learner implementation and CPU/CUDA qualification | Not implemented/qualified |
| Full-update training and exact save/resume | Not run |
| Original/updated-base/workspace correctness comparison | Not run |
| Matched-seed free generation, reasoning and writing | Not generated |
| Blinded calibrated judges and independent human review | Not collected |
| Inference export and fresh-load parity | Not implemented/verified |
| Agreed beta acceptance and publication decision | Pending |

The predecessor [V16 diagnostic](../../provenance/pilots/v16_population_diagnostics_20261015/RESULTS.md)
showed no donor flips in 256 affected queries and retained
`FAIL / winner:none / non_regression NOT_ESTABLISHED`. It is not a V18 result
and must not be relabeled as the derivative's evaluation.

## Evaluation table to populate from frozen receipts

For each benchmark/task family record: version/split, information access,
prompt/template, scorer/tie policy, original and candidate counts, planned and
valid denominators, regressions/repairs, protected-slice results, paired
uncertainty, training-seed count, selection exposure and all missingness.
Keep backbone-only and workspace-on comparisons distinct. Do not present a
partial MMLU subset as the full MMLU score.

For behavior, link full literal answer banks and a readable paired panel;
include greedy/sampled regimes, sampling coupling, lengths/stops, mechanical
correctness, judge validity/order/repeat disagreement and independent human
comments. An illustrative win is not the bank's overall result.

## Intended use, limitations and risk

Proposed use is research and controlled evaluation, not a guaranteed upgrade
or validated high-stakes system. Record actual supported language/runtime
coverage and inherited/new failure modes after evaluation. The upstream card
notes missing moderation mechanisms; this derivative has not established new
safety or moderation capabilities. Check memory provenance and conflicting
facts. Do not claim greater intelligence or causal content use from style
changes or judge preference alone.

## Training and data disclosure

Pending: complete recipe, model seeds, full/frozen parameter scopes, data
provenance and rights, train/dev/final family splits, objective/reduction
contract, original-base preservation, sequence lengths, optimization schedule,
hardware/time/resource peaks, retention policy and contamination caveats.
Evaluation answers and judge-preferred examples are not silently training gold.

## Loading and reproducibility

Pending: tested inference-only package and exact commands from a clean
environment, model and workspace hashes, dependencies, minimal direct and
memory-enabled examples, export/native-zero parity and supported hardware.
Do not assume a standard backbone loader enables the custom workspace.
No executable loading snippet is supplied until it has been tested.

## License and provenance

The upstream pinned model declares Apache-2.0. Final derivative model/code/data
license inventory, required notices and redistribution clearance are pending.
Fill authorship, source repository/revision, candidate/evaluation manifests,
export hashes and public Hub revision only from verified records. No affiliation,
endorsement, license permission or benchmark qualification is inferred.
