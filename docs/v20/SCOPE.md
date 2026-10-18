# V20 scope: what the Latent Workspace is for

2026-10-15, square added 2026-10-16. **PLANNING NOTE / NOT FROZEN / NO NEW
RUNS, GENERATIONS OR JUDGE CALLS.** The old **FAIL / winner:none /
non_regression NOT_ESTABLISHED** is unchanged.

**Naming (Ryō, 2026-10-16).** The work this note scoped first (the square,
D1, A1 and the engine) is V19.5. V20 is A2, the flip through v4's logit route.
Files, status strings and receipts keep the `v20` names under which they were
frozen and sealed; see [docs/v20](README.md).

## Ryō's point

> そもそもworkspaceに入れた情報によって回答を変えれることだけ、がLatent
> Workspaceの設計思想や意義ではなかった、という点にもv20ではちゃんと注視したい
> よね! 複数ターン会話では回答が分岐することや、baseとの生成差分ですでに
> llm-as-a-judgeの判定では優位な差が見れた、この辺りも忘れずにいたいポイントだ!

Changing answers according to what is written into the workspace was never the
whole design intent or the whole value of the Latent Workspace. V20 keeps two
further properties in view: answers branch across multi-turn conversations, and
generations already differed from base in ways LLM judges preferred.

V15 through V19 measured one property only: whether intact versus twin memory
flips held-out answers in the donor's direction. Every arm so far is
`NOT_ESTABLISHED`, including [V19 attempt 01](../../provenance/pilots/v19_frozen_dual_budget_20261015/README.md).
That lane stays, with its endpoint unchanged, but its negatives do not refute
the other two properties, and the other two cannot relabel it.

## Where the flip test came from

From Ryō's pre-repository packages (v4–v8, local archives, not in this
repository) and the [v9 matrix](../../configs/v9_reference/MATRIX.json):

- **v4:** a K-step latent workspace computed from the base model's own causal
  hidden states adds a low-rank vocabulary residual, trained with task CE plus
  `LatentWorkspaceLoss`, which keeps the latent trajectory's information
  recoverable without letting its geometry collapse (variance, covariance,
  retention, identity, relational, temporal and rank terms).
- **v5** asked whether the workspace state moves, is retained and contributes
  directly to the task. On GPT-2 Small the direct contribution was small, but
  workspace-forming training changed the base model's learning trajectory.
- **v6.5** therefore split the question in three: *Occupancy* (is a
  workspace-like state active), *Availability* (can it be recruited when
  needed) and *Consequence* (what forming it leaves in later learning and
  outputs), and measured mainly the last two.
- **v7** kept the triad and added one goal among several: is a deferred
  workspace memory causally and content-specifically necessary?
- **v8** targeted semantic load-bearing memory and identifiability, and the
  **v9** matrix made the flip its primary claim: "whether one query-independent
  memory can implement a reusable relation function across multiple future
  queries and whether a local counterfactual memory edit flips only affected
  answers."
- From **V15** on, the flip also became the training objective (the donor
  hinge) and the reader's design target, not only the test.

So the flip is not a drift from the design: it is the sharpest test of one
corner of it, content-specific Availability through a deferred memory.
Consequence and Occupancy kept turning up without a lane of their own:
v6.5's changed learning trajectory, V14's judge-preferred differences and
branching, and V18's step-2 divergence "through the backbone, not through
memory".

The v4 idea itself left the line quietly. v5 had turned the token-local K-step
update into a causal-broadcast lattice (positions × latent steps). The v9
objective matrix was a 2×2 of `LatentWorkspaceLoss` (`lw`, weight 0.02) against
the flip objective (`cf`) on that lattice, but v9 stopped at 28 of 190 runs. On
Mistral-7B the loss was on only in V10's short smokes (one to eight optimizer
steps; the planned 512-step matrix stayed blocked). V11 to V14 kept the lattice
with the loss weight at 0, for at most 16 steps, and the bridges introduced in
V14 carried V15 onward. The code is still in
[`engine.py`](../../src/latent_workspace_ft_v10/engine.py).

## Ryō's square (2026-10-16)

> v4の時点が一番素直な発想ではあったんだよな。でも一方で君のいう通りflip
> testが出てきたのはある種必然でもあったと思う、なのでその△案に加えて、v4の
> 時点の思想を担保する角を入れて四角としてみるのはどうかな

v4 was the most direct form of the idea; the flip test was also, in a sense,
inevitable: v5 and v6.5 showed signs of an effect that was hard to attribute,
and the flip gives a causal, content-specific handle. So the triad gains a
fourth corner that secures v4's idea. v6.5 had set it aside on purpose ("not
only the workspace as an always-active organ"); the square brings it back as a
goal of its own.

| Corner | Question | Identifiable test | Record so far | Lane |
| --- | --- | --- | --- | --- |
| **Deliberation** (潜在熟考; v4) | Does the model think through a latent lattice formed from its own hidden states, and does that computation reach its outputs at inference? | Step dependence at matched capacity (K latent steps against one) and loss of the gain when the lattice is bypassed at inference; `LatentWorkspaceLoss` geometry as health diagnostics, not claims | GPT-2 (v4–v5): direct contribution small. Mistral-7B: loss on only in V10's 1–8-step smokes; lattice without it for at most 16 steps (V11–V14). V19.5 D1: +20–23 points on held-out worlds with the facts inline, but no step dependence: a readout gap, not deliberation | D |
| **Occupancy** | Is a workspace state active and holding information, and does it persist across turns? | State metrics; persistence and branching across turns against random-perturbation controls | V19 route active at its cap; V14 branching, not donor-directed | B |
| **Availability** | Can the state be recruited when needed? Content-specifically: does a local memory edit flip only affected answers? | Donor-directed flips (endpoint unchanged), read through a ladder: slots → read output → FP64 gap → published answer | V16–V19: 0 flips, FP64 direction at chance. V19.5 A1: the memory probe was underpowered; at V19's update 256 the workspace read output carried the content (161/256 held out), weaker by 512: lost in transport, descriptively. V20 A2 depth ladder: the frozen host reads a separately encoded memory at cut 0 (`CONTENT_REACHES_ANSWERS`, 55 flips of 256); with v4's route at cut 4 (`DIRECTIONAL_ONLY`, 0.79–0.83 against 0.50); not from cut 8 on, where V16–V19 wrote theirs | A |
| **Consequence** | What does forming it leave in the base model and its outputs? | Paired generation versus base; backbone drift versus workspace contribution | v6.5's changed learning; V14 judge-preferred differences; V18 backbone divergence | C |

Ryō confirmed the name on 2026-10-16: **Deliberation (潜在熟考)**. It differs
from Occupancy as computing differs from holding: a state can be active and
retained without the model doing work through it.

**How the corners meet the world-pair data.** Every affected question is hop 1:
the edited fact is stated in the context (train 512/512, eval 128/128).
The flip therefore tests retrieval, Availability, not composition. Unaffected
questions span hops 1–5. With the facts inline the base answers hops 2–5
better than hop 1 (V11 Gate-0: 449/512 = 0.88 against 349/512 = 0.68), so hop
depth alone is not a clean difficulty axis for Deliberation. Its test should
rest on step dependence and bypass at matched capacity, on cases the base gets
wrong with the facts inline, or on a task family built so that composition is
required.

## What the record already shows

**Generation differences judged against base** (V14,
[answer bank](../../provenance/pilots/v14_answer_bank_20261009/README.md) and
[three-judge synthesis](../v14/FT_BETA_JUDGE_SYNTHESIS.md)). Of 96 primary
pairs, the legacy-semantic V14 changed the text of 10; the centered V14 changed
none. Each of three judge settings (OpenAI, Gemini, Mistral Large 4 at 16k)
judged the 10 changed pairs plus 4 identical controls in both orders, five
times. Stable workspace preferences were **2 / 1 / 1**, stable base
preferences **0 / 0 / 0**, and the identical controls were stable ties in all
three. One pair, the causal-design prompt under sample211, was stably
preferred by all three: 80 → 54 words inside a 60-word limit, proposing a
separate-team test. The direction is favorable and consistent across judges.
It is not yet a population-level significant difference: the bank was
selected for changed text (10 pairs, 7 prompts, 6 clusters), repeats are not
independent tasks, no stable base win is not non-regression, and memory
content was not identified as the cause.

**Branching across turns** (V14,
[boundary chat](../../provenance/pilots/v14_boundary_chat_20260907/README.md)
and [4-turn choice assay](../../provenance/pilots/v14_multiturn_choice_20260913/README.md)).
In free-text continuations, first answers never changed (0/32), yet semantic
intact versus twin memory sent 12/32 continuations down different paths
(8/16 affected, 4/16 unaffected), earliest at token four; one kept the same
"no" and then wrote about Eris's moons or the planets' order depending on which
twin memory was read. In the constrained four-turn assay, a small same-prefix
difference crossed a matched-sampling threshold at an unaffected turn, entered
the history, and later turns diverged (intact `no, no, no, no` versus twin
`no, yes, no, yes`). Limits: full-prefix recomputation, so no KV-cache claim;
free history also branches without any workspace (12–13/16 base query-only
trajectories differ between fixed and free history); the branches were not
donor-directed. Branching is real and reproducible: the workspace reaches
generation and changes where a conversation goes. Whether those branches are
better than base, or than any perturbation of the same size, is untested.

## Four lanes, each with its own endpoint

**A. Content use** — the V15–V19 endpoint as frozen: held-out donor-directed
flips against a norm-matched random-pair control, world-level sign test.
Reported as its own claim. First: [A1](A1_LADDER.md), the Availability ladder
on the V19 checkpoints (where is the content lost?):
[`CONTENT_ABSENT_IN_MEMORY` by rule, not readable literally](../../provenance/pilots/v20_a1_ladder_20261016/README.md).
The read output carried the content at update 256, so the descriptive reading
is transport. Next, and V20 itself: A2, the flip through v4's logit route. Its
[power checks](../../provenance/pilots/v20_a2_flip_20261016/DEV_POWER_CHECKS.md)
found the wall is depth. The frozen host reads a separately encoded memory at
cut 0–4 and not from cut 8 on, while V16–V19 wrote memory at cut 16. A2
becomes a sealed [depth ladder](A2_DEPTH_LADDER.md):
[read depth host 0, route 4](../../provenance/pilots/v20_a2_depth_ladder_20261016/README.md).
A workspace that writes a compact memory into the lower layers comes next.

**B. Conversation branching.** Natural multi-turn dialogues, with the
constrained harness kept as a mechanical probe. Conditions: original base;
updated backbone without workspace; with workspace and its real memory;
written-zero; norm-matched random memory; twin and unrelated memory where a
memory lane exists. Matched counter-based randomness, so base against base
never branches. Record branch rate per turn, first divergent turn and token,
and persistence. Because a random perturbation of the same norm also branches
trajectories, branching alone shows reach, not value; the endpoint must
compare the branches themselves: judged quality and consistency with the
memory, against random-perturbation branches and base, with history
amplification measured on base alone.

**C. Paired generation quality versus base**, under the
[V18 behavior protocol](../v18/BEHAVIOR_EVALUATION.md): a fresh bank frozen
before generation and not selected for changed text; every pair kept,
unchanged ones included; both orders, fixed repeats, calibration controls and
symmetric length caps; an objective ledger next to judge preference. Split the
comparison into backbone drift (base versus the updated backbone without
workspace) and workspace contribution (with versus without workspace on the
same updated backbone). The primary endpoint should count stable preferences
per independent task family with a sign test across families, plus objective
no-regression floors. V14's causal pair is an exposed sentinel, not fresh
evidence.

V19 makes lane C more pressing: its reader learned a large memory-independent
shift (workspace norm 0.25 for any real memory). Such a shift may change
generations for better or worse; lane C measures that, and only lane A or the
random and zero-memory controls can attribute a gain to memory.

**D. Latent deliberation** (v4's corner). Bring back a latent lattice formed
from the model's own hidden states under the V16+ owners and sealed execution.
Endpoint: a gain from K latent steps over a matched-capacity single-step
control on pre-registered cases, which disappears when the lattice is bypassed
at inference, with geometry health reported alongside. It can share the
world-pair data with lane A, so one run can read both corners. First
experiment: [D1](DELIBERATION_PILOT.md), frozen backbone with the facts inline:
[`LATTICE_GAIN_WITHOUT_STEP_DEPENDENCE`](../../provenance/pilots/v20_deliberation_pilot_20261016/README.md).
A Deliberation test needs a setting where one forward pass does not already
contain the answer, such as a lattice that feeds back into the model's own
processing.

## Path to the β

The [release checklist](../v18/HF_RELEASE.md) already asks for no marked
degradation plus interesting, reproducible behavioral differences, and keeps
content use as a separate claim. Lanes B, C and D are behavioral claims;
lane A stays the separate content claim. One sentence there still expects the
candidate "after memory use is established". Whether
**mistral-7b-instruct-v0.3-LTWS β** may ship with lane A reported as
`NOT_ESTABLISHED` is Ryō's decision; this note does not change the checklist.

**Evaluating the next full-update weights (Ryō, 2026-10-16).** Base Mistral
already does reasonably on MMLU, so a gain there would be small. Read the
full-update weights on harder benchmarks, where base Mistral struggles and an
improvement or accuracy gain would be visible, and on multi-step reasoning
inside the workspace (for example accuracy by hop depth). Either could show
what the record has not yet seen. This is a planning note: no generation or
benchmark run is authorized by it.

## After the β: toward a full fine-tune (Ryō, 2026-10-18)

"このままadapterとして最適化させるのではなくadapterであるのはfull FTを成功させて通す=βがなくなるver1.0までの学びを得るための過渡期として考えて、その前提でadapterとしての性能を上げることにoverfitはしない進め方でゆこう … hf repoのβの記述にも次はadapterではないことも明記しておこう"

- **v1.0 is a full fine-tune, not an adapter.** The β's route is a
  transitional instrument. It is not tuned further, and adapter scores are
  not targets.
- **What the β taught, for the full fine-tune:** separately written memory can
  enter frozen Mistral at layer 4 and still be read; content gating keeps
  memory from moving answers it is not about; a learning rate that decays late
  keeps seeds consistent; natural text held at layer 4 keeps its gist but
  loses details.
- **Next experiments** ask what the full fine-tune needs, and build the checks
  it must pass. They are not adapter optimizations.

## Not authorized here

No generation, judge request (API or manual), training run, upload or
checklist change. For scale: the V14 answer bank's 28 calls had a usage-based
estimate of $0.55 (actual bill unknown), and the three-judge bank was 420
calls. A V20 bank needs frozen counts, judges, caps and an explicit budget
before any request.
