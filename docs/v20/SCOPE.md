# V20 scope: what the Latent Workspace is for

2026-10-15. **PLANNING NOTE / NOT FROZEN / NO NEW RUNS, GENERATIONS OR JUDGE
CALLS.** The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is
unchanged.

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

## Three lanes, each with its own endpoint

**A. Content use** — the V15–V19 endpoint as frozen: held-out donor-directed
flips against a norm-matched random-pair control, world-level sign test.
Reported as its own claim.

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

## Path to the β

The [release checklist](../v18/HF_RELEASE.md) already asks for no marked
degradation plus interesting, reproducible behavioral differences, and keeps
content use as a separate claim. Lanes B and C are those behavioral
differences; lane A is the separate claim. One sentence there still expects the
candidate "after memory use is established". Whether
**mistral-7b-instruct-v0.3-LTWS β** may ship with lane A reported as
`NOT_ESTABLISHED` is Ryō's decision; this note does not change the checklist.

## Not authorized here

No generation, judge request (API or manual), training run, upload or
checklist change. For scale: the V14 answer bank's 28 calls had a usage-based
estimate of $0.55 (actual bill unknown), and the three-judge bank was 420
calls. A V20 bank needs frozen counts, judges, caps and an explicit budget
before any request.
