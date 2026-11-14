# V24 FT04 crossed-route readout — completed development result

Completed on 2026-10-27. This is an observation of existing checkpoints, not a
new training run, an independent confirmation set, or a release qualification.
The frozen [protocol](../../../docs/v24/RECRUITMENT_READOUT_01.md),
[execution handoff](EXECUTION_HANDOFF.md), literal [result](RESULTS.json),
[token inputs](../../../configs/v24/recruitment_readout01/INPUTS.json.gz),
[synthetic source bank](../v24_recruitment_preparation01_20261023/furnace/raw/data/bank/PUBLIC_SYNTHETIC.json.gz),
and closed [Furnace metadata](furnace/) are separate evidence. Historical
in-progress entries in the handoff and [preparation README](README.md) remain
dated snapshots, not the final state.

## Provenance and denominators

- The original paired FT source is `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`.
  Its inline and workspace arms each completed 32 independent full-parameter
  updates from the original Mistral-7B-Instruct-v0.3, 538 ordered backward rows,
  and 21,112 supervised target tokens. [Training completion and body hashes](../v24_recruitment_ft04_20261023/COMPLETION_RESULTS.md)
  distinguish execution from model quality. Both final weight bodies remain on
  Furnace's SSD; no off-host weight backup is claimed.
- The evaluation source is `425f10d833b25977b09f6954ed3a34f6875e4890`.
  Its 868-file source seal, frozen inputs, tokenizer replay, 441/441 CPU and
  441/441 CUDA tests, independent CPU isolation check, three role terminals,
  dispatcher terminal, input/scoring replay, restore identities, and safety
  floors passed at the original offline replay. The closed dispatcher status is
  `V24_RECRUITMENT_READOUT_COMPLETE_NOT_QUALITY`.
- There are **six** unexposed development source groups: two per arithmetic,
  register-trace, and stable-filter family. Each group supplies correlated
  twin/control cases. The comparison has 36 unique cases per runtime route and
  72 per checkpoint; **216 free generations** are not 216 independent problems.
  Also completed: 432 fixed reference traces, 6,960 fixed forwards, 9,816
  generated-token forwards, and 16,776 total native forwards. No evaluation
  update, save, judge request, weight deletion, or new source acquisition ran.
- The 2026-11-14 local check revalidated the exact 868-file historical source
  seal and replayed all **216/216** strict generation scores against the frozen
  expected cases. The pinned tokenizer's former temporary Mac directory is no
  longer present, so literal tokenizer decoding was **not rerun** on that date;
  the successful original complete replay remains a historical receipt. A
  live Furnace recheck was unavailable at the registered address (SSH timeout),
  which is not evidence of machine power state or changed weight bytes.
- The FT04 training verifier was also replayed against an exact temporary copy
  of the recovered metadata, excluding one later Finder-created `.DS_Store`
  that is absent from the sealed file manifest. Its JSON-normalized output
  matched the saved [offline training receipt](../v24_recruitment_ft04_20261023/OFFLINE_TRAINING_VERIFICATION.json)
  exactly: 856 source files, 64 scientific updates, and terminal status
  `PAIRED_NATIVE_FT_COMPLETE_NOT_QUALITY`. Neither original bundle nor the
  historical receipt was altered; the transient copy was removed afterward.

`RESULTS.json` SHA-256:
`1a35800f29c541028158c115eda621f34cb7d322a4f7e1c58ee78c27739aad38`.
The frozen input gzip is
`2f7132586ab75ceae26367903ef09a1b05509c42b818f86708463b6c4703b68d`;
the source bank gzip is
`36b8fe09f859ee485959ddf252940cdd30bc03c146a05682885ae93217ec7c3d`.

## Unassisted generation

Each cell contains 36 generations. `answer` means strict content correctness,
not merely JSON parsing; `exact` additionally requires the historical joint
score. Absent and unrelated cases expect `answer:null` and have no applicable
step task. A length-capped or unparsed result stays in the denominator.

| Checkpoint / runtime route | Answer | Affected target | Unaffected control | Absent + unrelated | Parsed | Exact | Length-capped |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base / inline | 7/36 | 4/12 | 3/12 | 0/12 | 18/36 | 0/36 | 14/36 |
| base / workspace | 0/36 | 0/12 | 0/12 | 0/12 | 3/36 | 0/36 | 27/36 |
| inline FT / inline | 21/36 | 0/12 | 9/12 | 12/12 | 36/36 | 21/36 | 0/36 |
| inline FT / workspace | 16/36 | 0/12 | 4/12 | 12/12 | 34/36 | 14/36 | 0/36 |
| workspace FT / inline | 22/36 | 0/12 | 10/12 | 12/12 | 36/36 | 19/36 | 0/36 |
| workspace FT / workspace | 20/36 | 0/12 | 8/12 | 12/12 | 36/36 | 18/36 | 0/36 |

For the same 72 cases per checkpoint, inline FT has 35 base-wrong answer
repairs and five base-correct answer losses; workspace FT has 39 repairs and
four losses. All four FT/route cells nevertheless score **0/12** on affected
target cases. The apparent total-answer gain is dominated by missing/unrelated
null responses and simpler unaffected controls, not the intended multi-step
calculation. The unaffected query asks for a **different, simpler operation**
(for example `d - e` rather than `(a + b) * c`); it is not a matched-difficulty
counterfactual target. The six source groups and their aliases cannot justify
an uncertainty interval or a general ability claim.

The strict scorer does not explain away the affected failure. The FT models
usually produce parsed, EOS-terminated JSON on those rows, but its `answer`
value is wrong. Exact literal examples below are from the existing generation
artifact; expected values come from the executable source bank.

| Frozen row | Expected | Base | Inline FT | Workspace FT |
| --- | --- | --- | --- | --- |
| arithmetic `dev-0000/s0/affected/inline`: `(23+59)*9` | `738` | `738` (steps are prose, not exact) | `1023` | `1648` |
| register `dev-0005/s0/affected/workspace`: `(46+18)*4` | `256` | unparsed/length-capped | `102` | `102` |
| filter `dev-0002/s0/affected/workspace`: cutoff 6 | `["NJWCZ","ZRBPG"]` | all four codes | `["TFMKX","NJWCZ"]` | all four codes |

The arithmetic row's exact scoring texts are: base
`{"steps":["Add a and b, then multiply the result by c","23 + 59 = 82, then 82 * 9 = 738"], "answer":738}`;
inline FT `{"answer":1023,"steps":[76,1023]}`; workspace FT
`{"answer":1648,"steps":[76,1648]}`. These examples illustrate a failure
mode, not a representative sample estimate.

## Fixed-token evidence and interpretation

Token-weighted NLL per token, for the same native training/runtime route and
the same fixed references (lower means higher reference likelihood):

| Reference segment | Base / inline | Inline FT / inline | Workspace FT / workspace |
| --- | ---: | ---: | ---: |
| Own answer-first answer (90 tokens) | 3.590 | 0.903 | 0.914 |
| Own answer-first format (266 tokens) | 2.038 | 0.049 | 0.059 |
| Own answer-first steps (92 tokens) | 3.334 | 0.139 | 0.382 |
| Own steps-first steps (92 tokens) | 4.832 | 0.925 | 1.234 |
| Own steps-first answer (78 tokens) | 0.464 | 0.061 | 0.120 |

These are teacher-forced likelihoods, not independent solutions. In the
historical answer-first training serialization, the gold answer precedes
subsequent gold steps; a low steps NLL can therefore reflect answer-conditioned
continuation. Conversely the steps-first answer NLL is measured **after gold
steps**. The asymmetry is compatible with an intermediate-computation/readout
problem, but does not identify its cause or prove that a latent result was
computed. Own-minus-donor answer-prefix logprob is positive on 8/12 native
inline-FT rows and 5/12 native workspace-FT rows, including syntax/length;
this is not normalized choice accuracy and does not overturn 0/12 free answers.

Plausible, unseparated contributors include answer-first target ordering,
only 2,023 world plus 2,036 reasoning target tokens in the 21,112-token
training schedule, the multi-step target being harder than the controls, and
failure to turn available M into a reliable query-conditioned computation.
Neither a generic route defect nor a single numeric-arithmetic bug is
identified: all three affected families fail, including list filtering, and
the inline-trained model fails affected targets even on its native inline
route. [Next factor and falsification plan](../../../docs/v24/NEXT_ENGINE_FACTOR.md)
keeps those explanations separate before any further full update.

**Unchanged claim ceiling:** old expression gate **FAIL**; `winner: none`;
`non_regression: NOT_ESTABLISHED`. This development result cannot select a
release model or certify broad preservation.
