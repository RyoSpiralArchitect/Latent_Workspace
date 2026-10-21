# V22 versus the original host: fixed-checkpoint comparison 01

Ryō requested a comparison with base after the 32-update pilot completed.
This plan is frozen **after training, before these comparison scores**. It is
not a pre-training preregistration, a winning-checkpoint search, or a release gate.
The previous 40 development rows are already exposed and excluded here.

## Arms and provenance

- Original Mistral-7B-Instruct-v0.3 at `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- V22 step 32 from execution `13c1192fc2727d8ca61ee215a927c0cd77f75b16`.
  The 29,004,418,636-byte checkpoint has SHA-256
  `cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68`.
  Check its body, complete owner payload and recorded state before switching
  to inference. Do not relax the training restore contract.
- Both use BF16, eager attention, the same full native vocabulary, cut 4,
  no gradients and no KV cache. Memory and query are re-encoded every token.
  Empty memory must equal the corresponding current host bitwise.

The managed TensorRT-LLM doctor passed on Furnace. This comparison uses the
qualified native PyTorch path because the served backend does not implement
our cut-4 intermediate-state composition and owner checkpoint contract.
Converting only one arm or changing arithmetic would confound the comparison.
No managed environment is modified; this is not a vLLM fallback.

## Frozen panels

See [the machine-readable plan](../../configs/v22/BASE_COMPARISON_01.json).

1. **MMLU regression sentinel:** the previously exposed 570-question V16 panel
   (10 questions in each of 57 subjects, five-shot plain-text prompts).
   Native next-token A/B/C/D scoring, plus strict-tie results; no workspace.
   This is a new V22 measurement of a reused panel, not fresh confirmation.
2. **Held-out worlds:** two grouped test worlds from each of six trained
   families and four OOD linked-location groups: 16 twin groups, 128 raw rows,
   96 distinct memory/query/answer combinations. Both twins remain; redundant
   absent/unrelated controls are aliases, not independent observations.
   No group overlaps any V22 train/dev row. OOD is one held-out family, not
   a broad unseen-task claim. Select groups by fixed hash, never score.
3. On every world input compare **latent memory** with **inline text** for
   each weight arm. Record complete-target teacher-forced NLL separately
   from greedy full-vocabulary generation (24-token cap).
   Exact match ignores only case, whitespace and final periods; it does not
   accept an explanation merely because it starts with the target.
   Thus formatting failures and semantic failures require separate inspection.
4. **Qualitative answer bank:** 12 English prompts (four each reasoning,
   writing and code), two seeds, 256-token cap, temperature 0.7 / top-p 0.9.
   Fresh CPU FP32 sampling RNG per answer, identical prompt/seed across arms.
   Publish every pair, including truncated and unchanged answers. No paid judge.

Totals: 1,140 MMLU scores, 384 world teacher-forced rows, 384 world
generations and 48 free answers (**432 generated sequences**).
Report all planned/completed denominators, ties, EOS/cap rates, paired
base-only losses versus V22-only repairs, and per-mode/family/route results.
World twins/controls are grouped, not 384 independent tasks. Two sampling
seeds are not two training replications.

## Execution and claim ceilings

Tokenization and input sealing happen before any model scoring. A committed
input manifest binds exact IDs. Tiny CPU/CUDA qualification must each pass
138 tests within 4 GiB / 900 seconds before original-base then V22 roles run
in separate fresh processes. Each role is capped at four hours, allocator
30.5 GiB, at least 24 GiB host available and 50 GiB free disk during execution.
Stop on failure; no retries, partial replacement, threshold changes, training,
checkpoint saves, deletion, provider calls or Hub publication.

The historical expression gate remains **FAIL**, winner **none** and
population-level non-regression **NOT_ESTABLISHED** regardless of a small
descriptive win. This run measures current differences, not release readiness.
