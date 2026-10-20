# From the latent-memory beta to native full fine-tuning

2026-10-20. **Engineering foundation, not a full-FT run or a release.**
Ryō asked to inspect Claude's subsequent work and proceed toward full FT.
This starts from `origin/main` at `d085344cd448ec9ee27daffa1c1c301b6f4c6bd2`,
not from the earlier unfinished V18 plan. The beta, historical sources, sealed
results and their claim ceilings remain unchanged.

## What the handoff actually establishes

- [V18's real-model pilot](../../provenance/pilots/v18_native_pilot_20261015/README.md)
  already completed full-parameter updates and exact fresh-process replay.
  Its answer-position mechanism did not establish memory-dependent answers.
- [A5](../v20/A5_STABLE_ROUTE.md) stabilized the frozen-host, content-gated
  cut-4 route. Two of three seeds passed its content endpoint, but the primary
  all-seeds verdict is still `NOT_ESTABLISHED`. The released three-route mean
  was a subsequent release choice, not a retroactive primary success.
- The [beta package](../v20/BETA_PACKAGE.md) has two separate parts: memory
  written/read through Mistral, and an added two-candidate residual route.
  `package.LatentMemory.write/read` use `no_grad`; its route reads detached
  final states. `training.FeatureBank` likewise trains on frozen features.
  Those are appropriate for the beta, not for updating its host.
- The [free-generation record](../../provenance/beta/ltws_beta_generation_20261018/README.md)
  used **Mistral alone with latent memory**, without the two-candidate route.
  Its 168/200 correct verdicts versus 165/200 with the passage in the prompt
  are descriptive, not a demonstrated advantage over the prompt. All three
  judges generally preferred prompt-conditioned answers for detail. This
  motivates answer-token learning and detail/faithfulness checks; it is not
  a new training target made from judge outputs.
- Ryō's [post-beta direction](../v20/SCOPE.md#after-the-β-toward-a-full-fine-tune-ryō-2026-10-18)
  is full fine-tuning, not further optimization of the adapter.

Checkout audit: the existing local `main` was `70bdbb5`, with no tracked
changes and an untracked `provenance/research/` directory, left untouched.
The only newer upstream commit changed the README. The old semantic-chat and
the two A5 development/execution checkouts inspected on Furnace were clean,
detached snapshots. Work here is isolated on
`SpiralReality/latent-memory-full-ft`.

## First mechanism: learn the native latent-memory path

[`NativeMemoryCausalLM`](../../src/latent_workspace/native_memory.py) is a new
composition in the living engine, not a modification of the inference package.

1. Encode memory tokens alone through the lower host layers.
2. Encode the question and teacher-forced answer separately through the same
   layers. The answer never enters the memory writer.
3. Pack memory before query at the cut and run the remaining native layers.
4. Apply the **entire native vocabulary head** at query positions. Train
   answer tokens with shifted causal cross-entropy, not a two-choice head.

All native parameters remain available to the optimizer, including embeddings,
lower writer layers, upper reader layers, native norms and head. The component
does not silently unfreeze them; `require_full_update()` checks the policy.
No new adapter parameters are added. The host binding still owns architecture-
specific norms, positions and layer calls. No Mistral internals enter the new
composition.

**Cut 4 is the first proposed 7B condition**, carried from the readable beta
path, not a declaration that it is universally optimal. Other families require
their own real-model parity and resource checks. GPT-2 and the scratch host
retain the separate absolute positions below the cut; only rotary hosts have
the cut-0 inline equivalence tested here.

The graph deliberately accepts token IDs, not a cached memory tensor. Both
encodings are recomputed every forward so an optimizer update cannot leave a
stale, detached memory in the next update. Full-FT caching needs a separate,
weight-versioned inference contract later. Mixed empty-memory rows avoid
all-padding attention. An entirely absent/empty memory takes the native no-cache
forward directly.

Labels use query positions: prompts, padding and position zero are ignored;
the first answer token must have its prompt predecessor. Loss exposes both a
sum and token count. Complete-window accumulation must divide by the window's
total supervised tokens, not average unequal microbatch means. It never
teaches the first query token from the last memory position.

This is a **native memory-use baseline**, not proof of latent deliberation.
It uses the beta's uncompressed sequence of lower-layer states. A compact
writer, the lattice, latent-step feedback and persistent conversation state
remain distinct factors under the [four-corner scope](../v20/SCOPE.md). The
lattice is retained in the engine, not silently discarded or claimed to be
present in this baseline. First establish useful native readout, then test
those factors against it without changing several mechanisms together.

## What must be kept, learned, and measured

| Keep | Improve through full FT | Add as a separate gate |
| --- | --- | --- |
| Separately written, question-deferred memory; cut-4 starting point | Native writer/reader cooperation and answer-token use | Fresh memory reconstruction after every update |
| Unrelated/absent/random-memory controls | Suppression of irrelevant memory in the native model | Updated-direct versus original-base preservation |
| Stable late training and seed reporting | Passage detail and faithful explanations | Same-input/seed answer banks, blinded order-balanced judgments |
| Full source/receipt provenance and failed results | Native output, not only an added yes/no residual | Full-parameter ownership, BF16 realized changes, fresh-process resume |

The beta's unchanged-weight non-degradation argument **does not transfer**.
An empty-memory forward after FT equals the **updated** host, not the pinned
original. Preserve original-model references and evaluate both updated-direct
and updated-with-memory against them. No unit test can guarantee benchmark
non-regression after training.

## Execution sequence and smallest unmet gates

1. **Graph qualification (this change):** small Mistral, OLMo2, GPT-2 and
   scratch decoders; no-memory native logits/loss/gradients, beta host-path
   parity, writer/query gradients, all-parameter reachability, padding, causal
   labels, BF16 finiteness, activation-checkpoint backward, and ordinary CPU
   AdamW update/replay. See the [local record](../../provenance/engineering/native_memory_full_ft_20261020/README.md).
   This is not production-owner or 7B qualification.
2. **One engine-owned full-update owner (tiny CPU/CUDA qualified):**
   [`NativeFullUpdateOwner`](../../src/latent_workspace/native_owner.py) promotes
   the qualified CPU transport and checkpoint primitives, with verbatim and
   arithmetic parity tests. Its single native partition replaces historical
   bridge-specific ownership; it never imports the frozen package. See the
   [owner contract](NATIVE_OWNER.md) for ordered token-weighted windows,
   FP32 CPU Adafactor masters, tied parameters, realized native cast changes,
   independent snapshots, pre-mutation restore validation and fresh-process
   replay. The [bounded qualification plan](../../configs/v1_0/NATIVE_OWNER_QUALIFICATION.json)
   now selects 203 tests per device, at most 4 GiB CUDA allocation and 900
   seconds, with no retry or 7B dispatch. The [first attempt](../../provenance/engineering/native_owner_qualification_20261020/README.md)
   retained 187/189 CPU passes and two scratch BF16 oneDNN failures; CUDA
   remained undispatched. A separately authorized CPU math-SDPA correction
   added ten guards without dropping the original cases; [attempt 02](../../provenance/engineering/native_owner_qualification_attempt02_20261020/README.md)
   still stopped at 196/199 CPU passes. Explicit CPU oneDNN-off qualification
   adds four policy guards for the next source. A device PASS requires its
   own source-sealed terminal receipt. [Attempt 03](../../provenance/engineering/native_owner_qualification_attempt03_20261020/README.md)
   now passes **203/203 on each device**, including fresh-process FP32/BF16
   owner replay; offline source/manifest/XML verification also passed.
3. **Bounded 7B canary ([contract](NATIVE_7B_CANARY.md), incomplete):**
   pinned original Mistral, native BF16,
   CPU FP32 masters, activation checkpointing, one condition/two complete
   update windows plus fresh-process replay. Freeze source, lengths, memory
   bounds, token budget, runtime/resource caps and stop rules before dispatch.
   Measure this new graph; do not reuse V18's resource qualification as proof.
   The [first real-model attempt](../../provenance/engineering/native_7b_canary_20261020/README.md)
   passed 229/229 tiny checks on each device but stopped before the first
   update: its new harness compared the tree-hash expected digest with the
   legacy hash function. Replay was not dispatched. Preserve this source and
   failure; a scheme-explicit identity repair and newly qualified separate
   attempt are required. Present-cache identity and 7B fit remain unverified.
4. **Full-FT pilot (not launched):** freeze a finite training population and
   recipe only after canary success. Mix relevant-memory answer supervision
   with no-memory preservation examples and irrelevant-memory cases. Select
   any preservation loss/strength and learning rate on training/dev data only;
   neither beta's exposed validation examples nor judge rankings are new gold.
   The exact mixture, objective weights, update count and final holdout remain
   **UNSET**, so this document is not a dispatchable training plan.
5. **Evaluation before scale/release:** compare original direct, original
   latent-memory, updated direct, updated latent-memory, and inline-context
   controls on the same frozen inputs. Retain intact/twin/random/unrelated
   controls and the unchanged Availability endpoint. Use fresh, held-out
   families for new claims; report old exposed sets separately. Freeze public
   benchmark IDs/revisions, paired denominators and the non-regression rule
   before training. Same-seed free generation must score correctness,
   faithfulness and retained detail, not length as quality. Deliberation needs
   an additional matched-capacity/step-dependence assay. No beta replacement
   or upload follows from an engineering pass alone.

The graph/owner implementation and qualification did not run a paid judge,
generation batch, model download, threshold change, weight deletion, automatic
retry, PR merge or Hub publication. The later, separately authorized V16
retirement is recorded below.

## Resource decision, measured 2026-10-20

**Post-retirement check, 08:18:38 UTC:** after Ryō's explicit whole-condition retirement
decision, the [six V16 checkpoint bodies were recorded and deleted](../../provenance/inventory/v16_scientific_retirement_20261020/README.md).
All six hashes matched both at inventory and before deletion; the ledger was
published first. The three retired conditions are `common`,
`raw_matched_control`, and `slot_contrast`, steps 1 and 2. Their 667 historical
evidence files remain unchanged. V18, original Mistral and all other weights,
features and beta artifacts are excluded; the old per-condition retention
rule remains for non-retired conditions. Git cannot reconstruct these deleted
weight bodies.

Available disk space at that check was **243.61 GiB**, RAM **119.61 GiB**; GPU was idle
(10/32,607 MiB; no compute process). The unchanged two-old-checkpoint plus
50-GiB-floor estimate is **104.17 GiB**, leaving **139.44 GiB** of planning
headroom. The storage shortfall is resolved. These snapshots are not a
reservation or proof that the new graph fits.

**Later bounded dispatch:** admission recorded 31.348 GiB free GPU, 118.832 GiB
available host RAM and 241.481 GiB free disk. The [canary](NATIVE_7B_CANARY.md)
stopped on an incorrectly paired identity hash, not an observed OOM. No
7B peak or checkpoint-size measurement was reached. At 10:12:30 UTC the
checkpoint directory was empty and no compute process remained.

**Next:** preserve the incomplete record, then seek a separate recovery
decision for a scheme-explicit identity check and fresh CPU/CUDA qualification
before another bounded 7B dispatch. Do not waive original-model identity or
loosen the frozen resource limits. The two-update/replay gate remains unmet.
This is not the full-FT pilot: training mixture, held-out population and
quality gates still require step 4/5's prospective recipe.

**Earlier check, 06:35:44 UTC:** GPU was idle and both tiny device qualifications
had passed, but filesystem free space was ~82.22 GiB, ~21.95 GiB below the
104.17-GiB planning estimate. See the
[qualified record and remaining gate](../../provenance/engineering/native_owner_qualification_attempt03_20261020/README.md#next-gate-storage-then-a-new-bounded-7b-canary)
and [read-only retirement candidates](../../provenance/inventory/native_ft_candidates_20261020/README.md).
Those original records remain historical. The observations below likewise
predate the authorized retirement and are not current availability.

Furnace was reachable but occupied: RTX 5090, **29,570 / 32,607 MiB** used;
`VLLM::EngineCore` accounted for 29,552 MiB. That workload was left alone.
Host available RAM was 124,931,956,736 bytes; task-filesystem available space
was **91,777,458,176 bytes (85.5 GiB)**. These are point-in-time observations,
not reservations.

The [old 7B pilot](../../provenance/pilots/v18_native_pilot_20261015/README.md)
used about 29.8 GB peak CUDA allocation and 95 GB RSS, with ~29.1 GB per
checkpoint. Its all-parameter CPU-master route establishes prior feasibility,
**not a bound on the new graph**: the new graph carries two lower-layer
branches and a full answer sequence. At 7,248,023,552 parameters, native BF16
weights alone are ~13.5 GiB and CPU FP32 masters ~27.0 GiB, before gradients,
activations, optimizer state, vocabulary logits or checkpoint copies.

At that earlier observation, using the old checkpoint size only for planning,
two checkpoints plus the old 50-GiB free-space floor required about **104.2 GiB**,
~18.7 GiB above the observed free space, before new artifacts. That was the
storage blocker before the separately recorded V16 retirement above, not a
current shortfall. No limits were lowered.
