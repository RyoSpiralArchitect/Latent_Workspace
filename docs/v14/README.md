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
5. [Matched reader-query micro-fit, step 3](../../provenance/pilots/ft_beta_query_pool_20261010/README.md):
   two frozen-backbone CUDA cells completed on 2026-10-10; identical endpoint
   accuracy, a readout-cap ceiling, and failed fact-order robustness. No promotion.
6. [V15 native transport continuation](../../provenance/pilots/v15_readout_transport_20261010/README.md):
   shared readout, aligned-order controls, and all 64 generated answers; no new
   training, with serialization and output-format failures kept explicit.

The English synthesis is an analyst summary, not replacement translations or
new judge verdicts. Original Japanese reports and sealed proposals remain unchanged:
[first learner proposal](JUDGE_PANEL_LEARNER_PROPOSAL.md) and
[schema-relevance update](JUDGE_EXTENSION_LEARNER_UPDATE.md).
Their earlier Mistral availability/capacity statements describe their historical
stages; the new 16k packet is the current comparison receipt.

The original 2026-10-09 synthesis did not run new training, generation, judge
calls, or historical label repair. The separately sealed 2026-10-10 micro-fit
does update only compact bridge weights; it is not a quality qualification.
PR review and experimental qualification remain different milestones.
