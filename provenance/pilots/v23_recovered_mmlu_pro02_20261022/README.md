# V23 MMLU-Pro 02 — complete, mixed endpoint results

All **840/840 direct scores and 84/84 reasoning sequences** completed in the
separate cache-reclamation attempt. The dispatcher reports 4,880.54 seconds;
17,005 generated tokens. No training updates, checkpoints, weight deletion or
judge calls occurred in this evaluation. Publication was replayed locally while
Furnace was serving Aether; no new Furnace computation was started.

## Results and paired transitions

| Endpoint | Base | P-off | P-on |
| --- | ---: | ---: | ---: |
| Direct correct / 280 | 92 | 101 | 100 |
| Direct tie-free correct / 280 | 90 | 100 | 99 |
| Top-option ties / 280 | 6 | 2 | 5 |
| Reasoning strict parsed correct / 28 | 11 | 9 | 8 |
| Reasoning EOS-completed correct / 28 | 11 | 9 | 8 |
| Reasoning parsed / 28 | 19 | 21 | 21 |
| Reasoning unparsed / 28 | 9 | 7 | 7 |
| Reasoning EOS / 28 | 27 | 27 | 26 |
| Reasoning capped / 28 | 1 | 1 | 2 |
| Generated tokens | 6,159 | 5,184 | 5,662 |

The source of these counts and **every paired ID**, including both directions,
is [ANALYSIS.json](analysis/ANALYSIS.json). The
[literal bank](analysis/REASONING_BANK.md) contains all 84 outputs, questions,
options, gold labels and frozen example IDs, not only successful illustrations.

| Paired endpoint | Comparison | Candidate-only correct | Reference-only correct | Both correct | Both wrong |
| --- | --- | ---: | ---: | ---: | ---: |
| Direct / 280 | Base → off | 16 | 7 | 85 | 172 |
| Direct / 280 | Base → on | 14 | 6 | 86 | 174 |
| Direct / 280 | Off → on | 2 | 3 | 98 | 177 |
| Tie-free direct / 280 | Base → off | 15 | 5 | 85 | 175 |
| Tie-free direct / 280 | Base → on | 13 | 4 | 86 | 177 |
| Tie-free direct / 280 | Off → on | 2 | 3 | 97 | 178 |
| Reasoning / 28 | Base → off | 1 | 3 | 8 | 16 |
| Reasoning / 28 | Base → on | 0 | 3 | 8 | 17 |
| Reasoning / 28 | Off → on | 0 | 1 | 8 | 19 |

Direct accuracy is 32.86% / 36.07% / 35.71% on this panel. Thus there **are**
base-wrong/FT-correct decisions under this exact protocol, unlike the previous
570-item MMLU panel. They do not show that base is intrinsically unable to solve
those questions. Direct 280-item gains and reasoning 28-item losses must not be
treated as a causal transport experiment: the prompts differ (zero-shot versus
five-shot) and the reasoning panel is a nested subset. On those **same 28 IDs**,
direct correctness is **12/10/11** (tie-free **11/10/11**) before comparing the
reasoning counts. Selection mix itself matters. No statistical non-inferiority
claim, threshold adjustment, checkpoint selection or release follows.

### Category breakdown

Each direct denominator is 20; each reasoning denominator is two. Small cells
are descriptive, not independent evidence that a field has been mastered.

| Category | Direct base/off/on / 20 | Reasoning base/off/on / 2 |
| --- | --- | --- |
| biology | 12 / 12 / 12 | 1 / 0 / 0 |
| business | 8 / 7 / 7 | 1 / 1 / 1 |
| chemistry | 4 / 3 / 3 | 1 / 2 / 1 |
| computer science | 6 / 8 / 8 | 0 / 0 / 0 |
| economics | 5 / 7 / 6 | 0 / 0 / 0 |
| engineering | 2 / 6 / 5 | 0 / 0 / 0 |
| health | 6 / 6 / 7 | 1 / 1 / 1 |
| history | 9 / 9 / 9 | 0 / 0 / 0 |
| law | 5 / 5 / 5 | 0 / 0 / 0 |
| math | 5 / 5 / 5 | 2 / 1 / 1 |
| other | 9 / 9 / 10 | 2 / 1 / 1 |
| philosophy | 5 / 6 / 6 | 0 / 0 / 0 |
| physics | 6 / 7 / 6 | 2 / 2 / 2 |
| psychology | 10 / 11 / 11 | 1 / 1 / 1 |

### What the three shared reasoning losses actually contain

These are analyst inspections of recorded outputs, **not a new scoring rule**.
The frozen parser remains unchanged and all original scores remain reported.
Exact full outputs and contexts are in the literal bank above.

- **`biology:3462` — format loss, not an observed factual reversal.** Base starts
  `The answer is (F) Sodium citrate is added to prevent coagulation.` Both FT
  arms start `F. Sodium citrate is added to prevent coagulation.` All choose
  the gold option in visible text, but the bare `F.` is outside the strict
  final-marker contract. It stays unparsed in the published endpoint.
- **`other:5622` — explanation-to-option binding error.** Off says
  `Carmen should buy more units of good Y and fewer units of good X. The answer is (F).`
  The stated direction matches gold **B**; F says the opposite. On likewise
  explains more Y/less X but ends `The answer is (F).` This is not fixed by
  accepting a different answer marker. Base ends `The answer is (B).`
- **`math:9037` — arithmetic/termination failure.** Base ends
  `The answer is (J).` (gold 840), without a sound derivation. Off derives 315
  then ends `The answer is (C).` (whose printed value is 1050). On produces
  incorrect factorial arithmetic followed by a long zero run, reaching the
  1,024-token cap. A correct final option is not proof of valid reasoning;
  neither are fluent intermediate equations.

Conversely, **`chemistry:4250`** is off's one base-wrong/FT-correct reasoning
repair: off computes approximately 0.1404 mol and ends `The answer is (E).`
Base fails to recognize the equivalent scientific-notation option; on computes
the same approximate value but ends `The answer is (G).` This also illustrates
the need to separate quantity calculation from selecting its option label.

## Frozen protocol and provenance

- Original Mistral-7B-Instruct-v0.3 versus the matched 32-update off/on states.
  Restore receipts match the already-published comparison; original named
  hashes and before/after native hashes match. No new weights were created.
- TIGER-Lab/MMLU-Pro revision `b189ec765aa7ed75c8acfea42df31fdae71f97be`,
  MIT; 12,032 test / 70 validation source rows. A frozen hash selection uses
  20 per category; two per category are nested reasoning probes. Pretraining
  contamination is UNKNOWN. This is **not** an official leaderboard result.
- Direct: zero-shot chat, one-token option scoring, BF16/eager, deterministic
  first-max tie selection, with separate tie-free results. Reasoning: five
  same-category examples, greedy temperature 0 / top-p 1, seed 20261022,
  cap 1,024, EOS 2, full-prefix decoding, no KV cache. Prompts are not truncated
  and shots are not reduced. Every arm uses the same tokenized input bytes.
- Both protocols use the native **empty-memory/direct route**. Neither is a
  causal test of latent-workspace use. An unparsed completion is not necessarily
  factually wrong; capped/ambiguous/missing markers are never guessed or retried.
- Compute source: `b2f569740636e2cffb80e4091323d551ea7de4c2`,
  [804-file source seal](furnace/SOURCE_SEAL.json),
  [dispatcher terminal](furnace/raw/FINISHED.json).
  [315/315 CPU and 315/315 CUDA qualification](verify_qualification.py), with
  zero skips/errors/failures; CPU isolation PASS, 153 observed samples. Those
  are historical Furnace tests, not newly run GPU qualification.
- The [earlier stopped attempt](../v23_recovered_mmlu_pro01_20261022/README.md)
  remains unchanged. All three arms were evaluated afresh under the separately
  authorized cache-only repair. The new base direct journal happens to match
  its old 280 rows byte-for-byte; no old rows were spliced in.
- All **17,005** generation boundaries retain identical live allocation before
  and after reclamation. The original resource floors are unchanged. Minimum
  observed free GPU bytes are 17,301,504,000 / 17,452,498,944 / 17,452,498,944.
  These are sampled observations, not a guarantee for a co-running workload.

## Offline reproduction

From the repository root, with a local copy of the four pinned tokenizer files:

```sh
CUDA_VISIBLE_DEVICES='' PYTHONPATH=src:scripts python3 -B \
  provenance/pilots/v23_recovered_mmlu_pro02_20261022/analyze.py verify \
  --tokenizer /absolute/path/to/pinned-tokenizer
```

The verifier rebuilds all prompts/tokens, every choice/tie/margin/parse/stop
decision, literal decoding, source archives, terminal manifests, input identity,
checkpoint fingerprints, cache boundaries and paired IDs. It does **not** run
model forwards or reconstruct full-vocabulary log probabilities from the
choice-only logits. [Analysis manifest](analysis/MANIFEST.json) preserves exact
literal trailing spaces. Use `write` only in a fresh analysis directory, never
to overwrite a result. Old expression gate **FAIL**, winner **none**,
non-regression **NOT_ESTABLISHED**. No export or release.
