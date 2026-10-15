# V19 closeout: what the content lane taught us

2026-10-15. **CLOSED BY DECISION.** Ryō decided not to run an attempt 02, to
put the resources into V20, and to collect carefully what V19 has taught.
[Attempt 01](../../provenance/pilots/v19_frozen_dual_budget_20261015/README.md)
stays exactly as recorded: `final_cap025`'s endpoint stays missing and
`ordered_cap100` stays unrun, so the selection and budget-dose comparisons are
unanswered. Its checkpoints on Furnace (`ordered_cap025` steps 256 and 512,
`final_cap025` step 256) stay under the retention policy; nothing is deleted
without Ryō. The old **FAIL / winner:none / non_regression NOT_ESTABLISHED** is
unchanged.

Numbers below come from the verified receipts and from
[`posthoc_routes.py`](../../provenance/pilots/v19_frozen_dual_budget_20261015/posthoc_routes.py)
([V19 output](../../provenance/pilots/v19_frozen_dual_budget_20261015/POSTHOC.json),
[V18 reference](../../provenance/pilots/v19_frozen_dual_budget_20261015/POSTHOC_V18_REFERENCE.json)).
Everything past the pre-registered endpoints is post-hoc and descriptive.

## What is settled

1. **The budget coupling was real, and is gone.** In V18 the common route took
   0.998 of the shared cap and left the content route 0.0004. In V19 the
   workspace route carries its own 0.25 for every real memory.
2. **A freed route still learns a memory-independent shift.** Its norm is the
   same for intact, twin and reversed facts, and 0/256 held-out answers flip.
3. **The content signal is small and training does not grow it.** The median
   intact-minus-twin difference of the injected delta (L2) went from 0.032 to
   0.030 in V18 (update 128 → 512) and from **0.057 to 0.017** in V19. The
   separate budget at first carried almost twice V18's content difference;
   training then removed about two-thirds of it.
4. **It is far below what the native readout can show.** The resulting
   answer-gap change is 0.003–0.006 in FP64, 20–40 times smaller than the 0.125
   step of the published bf16 logits; published gaps changed on 14–40 of 256
   questions, in random direction. The bf16 input cast adds 5–7 times more
   intact-versus-twin difference to the delta than intended, but that noise
   mostly misses the answer direction (median gap residual 0.0005–0.0008). The
   binding limit is the size of the intended change, not the cast.
5. **The training signal for content never moved.** Answer CE is about 96% of
   the objective per window (1.77–1.83). The weighted donor hinge stays at
   0.062 of its 0.0625 maximum from the first epoch to the last, with 95–98%
   of active affected pairs at the maximum. Stability, unrelated and residual
   terms stay at or below 0.0034.
6. **The one memory-dependent behavior learned is coarse.** Memory from an
   unrelated world yields a smaller injected delta than the matching world's
   (1.12 versus 1.22 at update 512, 1.20 versus 1.23 at update 128), and the
   unrelated-memory term fell 2.3–2.7 times. Which of two twin worlds the
   memory holds stays invisible.
7. **The bridge never learned the relational task.** With memory, held-out
   accuracy stayed at the frozen base (V19 "ranked above" 272/512 versus 274/512
   without memory). In the frozen design the language model receives one
   bounded nudge at the answer position, so the bridge itself must retrieve two
   entities' ranks, compare them and encode the answer. The same model answers
   above chance when the facts are inline (V11 Gate-0: F1 above chance and above
   query-only).

## Engineering lessons

- Test a verifier against receipts the owner really writes: the V19 verifier
  inherited V18's checkpoint format string (fixed with
  [regression tests](../../tests/test_v19_frozen_verifier.py)).
- Furnace's GPU is shared. A multi-hour dispatch needs an agreed free window;
  the guard stops only our own job, as it should.
- Dev curves stay descriptive: `ordered_cap025` showed 5/0 dev worlds
  (p = 0.031) at update 512 and 2/6 on the held-out split.

## What V20 inherits from V16–V19

| Asset | Where | Use in V20 |
| --- | --- | --- |
| Sealed launcher, receipts, offline verifiers, no-retry dispatch | [`run_source_sealed.py`](../../scripts/run_source_sealed.py), per-run verifiers | every V20 run |
| Complete-window reduction; exact fresh-process resume for frozen/full, FP32/BF16 | [V18 window owner](../v18/WINDOW_REFERENCE.md), [V19 owners](DUAL_BUDGET.md) | any training lane |
| Operand-span selection reader and dual-budget reader | [`v18_selection_reader.py`](../../src/latent_workspace_ft_v10/v18_selection_reader.py), [`v19_dual_budget_reader.py`](../../src/latent_workspace_ft_v10/v19_dual_budget_reader.py) | content-lane components; the budget fix stays |
| Transport decomposition (intended FP64 gap, after cast, published) | [`v18_native_eval.py`](../../src/latent_workspace_ft_v10/v18_native_eval.py) | the lower rungs of any content measurement |
| Behavior protocol, blind review sheet, release checklist | [behavior](../v18/BEHAVIOR_EVALUATION.md), [sheet](../v18/CLAUDE_REVIEW_SHEET.md), [release](../v18/HF_RELEASE.md) | lanes B and C, the β |
| V16–V19 negative results | per-version provenance | the content lane's baseline |

## Open questions carried into V20

- Where is content lost? V16–V19 measured only the last two steps: the
  injected delta and the native answer. Whether the written slots or the read
  output separate intact from twin facts has not been measured directly.
- Should the workspace act as a steering nudge, as now, or as latent context
  that the model's own reasoning can attend to, as it does with inline facts?
  Earlier injection-site studies (v9 localization conditions, V14 routes)
  must be reviewed before treating this as new.
- How the three [V20 lanes](../v20/SCOPE.md) are weighted for the β is open.
