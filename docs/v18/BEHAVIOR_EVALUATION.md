# V18 paired behavior evaluation: operator protocol draft

2026-10-15. **DRAFT / NOT_FROZEN / NO_NEW_ANSWERS / NO_NEW_JUDGMENTS**.
This is an operator document, not a blinded judge packet. Use the separate
[Claude sheet](CLAUDE_REVIEW_SHEET.md) for a manual reviewer. Do not send this
document, condition keys, historical results or the learner hypothesis to a
blinded judge. The [V18 preparation plan](PREPARATION.md) owns the launch gates.
The [blind transfer template](CLAUDE_BLIND_PACKET_TEMPLATE.md) strips the
operator-only sections; it is still empty, not a populated review request.

## Bank and comparisons

Freeze cases and task-family holdouts before generation. Proposed families:
free-form assistance, objectively checkable multi-step reasoning, and writing
with explicit audience/length/content constraints. Include a separate
memory-relevance lane with authoritative facts, unaffected questions, unrelated
memory and counterfactual twins. Old causal/clarification examples are exposed
sentinels, never fresh evidence. No case is selected because the answers differ.

Compare (a) pinned original base, (b) candidate's updated backbone without
workspace, and (c) the same updated backbone with workspace. This separates
backbone drift from workspace contribution. Add actual written-zero and
unrelated/twin controls on the memory lane. An original base given the same
facts inline is a separately labeled information-access reference, not an
equal-token-path control. General preservation comparisons receive identical
task information. No fictitious memory should be created just to activate a
workspace on an ordinary writing task.

Case count, training seeds, generation seeds, caps and statistical precision
remain **UNFROZEN**. Do not interpret this draft as an executable request budget.
Before launch, calculate unique prompts/families, generated answers, primary
pairs, AB/BA judgments, fixed repeats and calibration requests separately.

## Same-seed means matched token randomness, not shared model state

Reuse the counter-based `matched_uniform(case_id, seed, step)` convention and
token-ID-order inverse-CDF sampler in
[`answer_bank_generation.py`](../../src/latent_workspace_ft_v10/answer_bank_generation.py),
after fresh full-update qualification. Include greedy and prespecified sampled
regimes. Freeze tokenizer/template/prompt IDs, native dtype/head/backend,
temperature/sampling policy, EOS and symmetric task-class token caps. Record
rendered text, token IDs, token traces, first divergence and finish reason.

The V14 implementation assumes one frozen backbone and shares `encode(prefix)`
across conditions. **Do not reuse that sharing across distinct model weights.**
Any cache/share key must bind model/checkpoint identity and prefix, with native
state/execution policy. The zero-workspace check is against the candidate's
own direct backbone, not against the original base after full updating.
Test both same-prefix sharing and deliberately different-model same-prefix
non-sharing. Native zero-path logit parity must pass before collecting a bank.

Matched randomness makes comparisons paired; it does not force equal text.
After divergence, histories are different. Keep same-prefix transport probes
separate from natural multi-turn trajectories. A full-prefix recomputation
assay does not establish KV-cache-mediated amplification.

## Two ledgers, neither overriding the other

**Objective ledger:** oracle/reference identity, answer correctness, logical
contradictions, unsupported claims, exact task constraints, termination,
truncation/refusal and missingness. Use deterministic checks when possible.
Give judges symmetric mechanically measured word/character counts and
constraint results instead of asking them to count.

**Qualitative ledger:** usefulness, clarity, appropriate detail, calibration,
writing quality and pair preference, with literal evidence and uncertainty.
Wrong but fluent is not correct; preferred but incomplete remains incomplete.
Keep no-preference, cannot-assess, AB/BA disagreement, invalid response and
transport unknown as distinct categories. Judge output is untrusted evidence,
not authority to change a rubric, run code, or promote a model.

Publish all planned outcomes, including unchanged/failed/refused/truncated
answers. A changed-only gallery can help inspection but must retain its
selection rule and the full-bank denominator. Cluster analysis by independent
task/world/paraphrase family; sampling seeds, orders, repeats and judges do not
multiply the number of independent tasks.

## Blinding, calibration and replication

Use opaque pair/answer IDs and separate the operator's private identity key.
Prepare AB and BA presentations independently; do not reveal one judgment in
the other session. Freeze a stratified repeat panel before inspecting wins.
Record judge product/model/version if shown, date, settings, context/tool
availability and actual returned text; use UNKNOWN when unavailable. Repeated
Claude Code sessions are not independent model families.

Build untouched controls for identical answers, clear right/wrong reasoning,
unsupported claims, contradictions, abstention, unfinished predicates and
constraint violations. Specify admission fields and thresholds **before**
calibration; analyst fixtures are not independent human gold. Historical
calibration is not transferable to this broader rubric. The V15.5
[OpenAI repeatability failure](../../provenance/pilots/v15_5_diagnostic_judge_20261010/CALIBRATION_REVIEW.md)
and [partial Mistral continuation](../../provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010/README.md)
remain unchanged. Do not repeatedly sample calibration until a model passes.

For manually returned Claude reviews, retain the original response and session
metadata, then validate JSON/IDs/enums/quote substrings offline. A schema-valid
quote proves textual presence, not a correct inference. Human review remains
separate. No Claude API key is required for that transfer.

## Length and provider controls

Choose generation and judge-output caps with a separate interface preflight,
then freeze them symmetrically. Do not truncate/pad/regenerate one side after
seeing outcomes. Report length, finish reason and predeclared length-stratified
diagnostics next to raw preference; an equal cap does not remove length bias.
Any length-adjusted model is secondary and must be specified before analysis.

Position, verbosity and self-enhancement biases motivate these controls
([MT-Bench/Chatbot Arena judge study](https://arxiv.org/abs/2306.05685)).
Length-controlled evaluation provides a further motivation for separating
raw preference from length effects
([Length-Controlled AlpacaEval](https://arxiv.org/abs/2404.04475)). Neither
paper validates this proposed bank, its judges, or its learner.

Do not guess a provider API ID from `luna6` or reuse historical aliases as
current facts. Resolve the authorized execution surface and model availability,
then freeze request/model/settings/output bounds and run new-rubric calibration.
Use environment credentials without logging values. Never copy secrets into a
packet, artifact, command output, source repository or Claude handoff.

Reserve each request exclusively before dispatch; preserve source/body hashes,
response IDs, usage and exact outputs. On an ambiguous HTTP/transport timeout,
retain UNKNOWN remote execution/billing and stop new admission under the frozen
policy. Do not resend automatically. Any continuation needs a separate recovery
decision and may not relabel previous unknowns as never dispatched.

## Return artifacts

An eventual run should publish a manifest with planned/completed denominators;
literal answer bank and token/finish traces; mechanical ledger; blinded pair
packets; original judge/manual responses; validation and disagreement ledger;
source-backed readable panel; source/model/input seals; usage and missingness.
Keep model identity mappings separate from packets until judgments are frozen.
The current deliverable is the protocol and empty Claude sheet only.
