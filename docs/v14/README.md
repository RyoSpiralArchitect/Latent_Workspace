# V14 review checkpoint and FT-beta direction

2026-10-09. English entry point for the completed three-judge comparison and the
next Mistral-7B-Instruct workspace design. This is a reporting/design checkpoint,
not a released or quality-qualified FT-beta model.

1. [Three-judge synthesis](FT_BETA_JUDGE_SYNTHESIS.md): shared observations,
   OpenAI/Gemini/Mistral-specific readings, failures, and exact evidence links.
2. [Preserve / strengthen / add plan](FT_BETA_IMPROVEMENT_PLAN.md): smallest next
   experiments and a zero-tolerance pinned-base correctness exit contract.
3. [Sealed final judge packet](../../provenance/pilots/v14_judge_capacity_20261009/README.md):
   raw responses, full Japanese judgments, executable reconstruction, and hashes.
4. [CPU learner audit, steps 1–2](../../provenance/pilots/ft_beta_learner_audit_20261009/README.md):
   new train-only native/zero checks, loss-specific reciprocal gradients, and a
   VRAM gate before any learner change. No optimizer updates or GPU execution.

The English synthesis is an analyst summary, not replacement translations or
new judge verdicts. Original Japanese reports and sealed proposals remain unchanged:
[first learner proposal](JUDGE_PANEL_LEARNER_PROPOSAL.md) and
[schema-relevance update](JUDGE_EXTENSION_LEARNER_UPDATE.md).
Their earlier Mistral availability/capacity statements describe their historical
stages; the new 16k packet is the current comparison receipt.

No new training, target-model generation, judge API calls, weight changes, or
historical label repair are part of this documentation update. PR review and
experimental qualification are different milestones.
