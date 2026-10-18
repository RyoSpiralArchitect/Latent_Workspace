# LTWS β — free generation from latent memory, judged by LLMs

2026-10-18. Ryō asked for the card to show, beyond the benchmarks, free
generation with the same seed, representative examples where the answers
differ most, and the answers' quality judged by LLMs ("自由生成の同一seedで差分の
大きく出たものを代表例にしつつ。回答の質をllm-as-a-judgeで判定した結果も載せて"),
then for strong models through their APIs ("API使って強いモデルでここは確実に
judgeしにゆこう!"). **Descriptive, run once, not pre-registered.** The
representative examples were chosen by a rule fixed in the generation script
before any judging.

## 1. Generation

- **Script:** [generate_ltws_beta_examples.py](../../../scripts/generate_ltws_beta_examples.py)
  at commit `f3b6c366d89c740843fbdb5926314aa292c30eaf`, run once on Furnace
  ([script](generation/run_generation.sh), [timeline](generation/TIMELINE.log):
  11:03:56Z–11:21:29Z, 1,049 s).
- **Isolation:** the run was isolated (`python -I`). Its only project code was
  the published package itself, Hub revision `2a55dc3e` as downloaded
  (manifest `a2bdba37…34e14c`), and it confirmed that import path.
- **Model:** Mistral-7B-Instruct-v0.3 at `c170c708…`, bf16, SDPA attention, as
  `example.py` loads it. RTX 5090, torch 2.13.0, transformers 5.15.0.
- **Data:** BoolQ validation, the benchmark's file (SHA-256 `dbad2984…88b68`).
  200 questions, a fixed random sample (seed 20261018). 133 of them have the
  answer "yes" (0.665).
- **Prompt:** Mistral's chat template. "Start your answer with Yes or No, then
  explain in one or two sentences." Then the question (and, for the prompt
  condition, the passage).
- **Four ways, one seed per question:** every answer to a question used the
  same sampling seed (20261018 + the BoolQ row index), temperature 0.7, top-p
  0.9, at most 160 new tokens. Sampling ran on the CPU from float32
  probabilities, with a fresh generator per answer.
  - `closed`: the question alone.
  - `latent`: the passage, with a "Passage:" header, as latent memory at
    layer 4, read by Mistral alone. Each step runs the question and the answer
    so far alone through layers 1–4, enters the passage's states before them,
    and lets layers 5–32 continue: the benchmark's path, one token at a time.
  - `latent_empty`: the latent prompt ("Use the passage you were given …")
    with no memory. It separates the passage's content from the instruction
    that mentions it.
  - `prompt`: the passage in the prompt, as usual.
- **Every step recomputed the whole sequence**, without a cache, in every
  condition.
- **Outputs:** [generations.jsonl](generation/generations.jsonl) (each
  question, its label, the passage's SHA-256 and the four answers; the passages
  themselves are not redistributed), [summary.json](generation/summary.json),
  [log](generation/generate.out).

### Verdicts

An answer's verdict is its first word: yes, no or unclear (one closed-book
answer).

| How Mistral gets the passage | Verdict right | Says yes | Mentions "passage" |
| --- | ---: | ---: | ---: |
| not at all (closed book) | 0.625 (125) | 94 | 1 |
| not at all, but asked about "the passage you were given" | 0.610 (122) | 93 | 4 |
| **as latent memory at layer 4, Mistral alone** | **0.840 (168)** | 117 | 13 |
| in the prompt, as usual | 0.825 (165) | 122 | 23 |

Paired, on the same 200 questions:

| Comparison | Both right | Only the first | Only the second | Both wrong |
| --- | ---: | ---: | ---: | ---: |
| latent memory vs closed book | 114 | 54 | 11 | 21 |
| latent memory vs the same prompt without memory | 111 | 57 | 11 | 21 |
| latent memory vs passage in the prompt | 159 | 9 | 6 | 26 |
| passage in the prompt vs closed book | 112 | 53 | 13 | 22 |

- **Latent memory vs closed book:** 54 to 11 on the questions where they
  differ (an exact sign test, one-sided, gives p ≈ 3 × 10⁻⁸; descriptive).
- **The instruction alone does nothing:** without the memory, the latent
  prompt answers like closed book (0.610).
- **Latent memory vs the prompt:** 9 to 6, no detectable difference in this
  sample.
- **Single-token BoolQ agrees:** these match the benchmark's single-token
  scoring on all 3,270 questions (closed 0.668, latent 0.831, prompt 0.850),
  [record](../ltws_beta_benchmarks_20261018/README.md).

### Representative examples: the rule

Fixed in the script before any judging, and computed by it
([summary.json](generation/summary.json), `selection`):

- **Candidates:** questions where the closed-book and latent-memory verdicts
  differ.
- **Ranking:** by the change in Mistral's first-token belief in the gold
  answer, from closed book to latent memory. The belief is the probability of
  a yes-token over yes- and no-tokens at the first step.
- **Chosen:** the three largest gains (latent memory right, closed book not)
  and the largest loss (the reverse).
- **Result:** gains #474, #769 and #835, loss #229. Their belief changes all
  round to ±1.00; the ranking used the unrounded values. There were 54 gain
  and 11 loss candidates.

## 2. Judging

- **Script:** [judge_ltws_beta_examples.py](../../../scripts/judge_ltws_beta_examples.py),
  run on the Mac from this repository ([commands](judge/run_judges.sh),
  [timeline](judge/TIMELINE.log)).
- **The plan, frozen before any call** ([PLAN.json](judge/PLAN.json),
  [REQUESTS.jsonl](judge/REQUESTS.jsonl)):
  - 1,200 requests per judge: 200 questions × 3 pairs × 2 orders;
  - the pairs: latent memory vs closed book, latent memory vs passage in the
    prompt, and passage in the prompt vs closed book (a control);
  - the template's SHA-256 `5e9eebf6…`, the requests' `87b6732d…`, the
    generations' `863898a5…`.
- **Blind:** each judge saw the passage, the question, the correct answer and
  two answers, never how the answers were made. Its instructions put the
  verdict first, then faithfulness to the passage, and style only last.
- **Order rule:** every pair was judged with each answer first once (AB and
  BA). A preference counts only if both orders agree after mapping back to
  conditions. Orders that disagree are reported apart, never as a tie.
- **Keys:** read from the environment only and never recorded. Checked after
  the runs: no recorded file contains any key value.
- **API trials first:** before each full run, six calls on the smoke test's
  answers ([canary/](canary/)) checked each provider's request and reply
  format.

| Judge | Setting | Ran (UTC) | Valid replies | Tokens in / out | Retried |
| --- | --- | --- | ---: | ---: | ---: |
| `gpt-6.1-sol` (OpenAI) | reasoning effort medium, 8,000-token cap, strict JSON schema | 11:22:32–11:34:10 | 1,200 / 1,200 | 536,618 / 78,224 | 0 |
| `mistral-large-4` (Mistral AI) | temperature 0.2, 16,000-token cap, strict JSON schema | 11:22:40–12:21:58 | 1,200 / 1,200 | 571,818 / 2,424,572 | 2 |
| `gemini-3.8-flash` (Google) | default thinking, 16,000-token cap, JSON schema | 12:23:49–12:41:15 | 1,200 / 1,200 | 519,272 / 346,574 | 59 |

- **Clean replies:** each judge's every reply named the requested model and
  finished normally. Every reply parsed as strict JSON.
- **Gemini 3.1 Pro, incomplete:** `gemini-3.1-pro-preview` was the first
  Gemini judge (started 11:31:30Z). It returned 242 valid judgments. From
  11:42Z every call ended in HTTP 429 after all its attempts, for 40 minutes.
  That fits a daily quota of about 250 requests (242 plus its six trial
  calls); the provider did not say. It was stopped by hand at
  12:23Z with 287 failed calls, and Gemini 3.8 Flash, Gemini's newest model
  and V14's Gemini judge, was run in its place. The partial run is kept in
  [incomplete/](judge/incomplete/gemini_gemini-3.1-pro-preview/) and used
  nowhere.
- **Outputs:** [SUMMARY.json](judge/SUMMARY.json), and per judge its setting,
  every reply as parsed (`calls.jsonl`) and every raw response (`raw.jsonl.gz`, gzip).
  The judges' replies sometimes quote a few words of a passage.

### Results

Counts of the 200 questions; a preference counts only if both orders agree.

| Comparison | Judge | First better | Tie | Second better | Orders disagree |
| --- | --- | ---: | ---: | ---: | ---: |
| latent memory vs closed book | GPT-6.1 Sol | 166 | 0 | 31 | 3 |
| | Gemini 3.8 Flash | 163 | 5 | 22 | 10 |
| | Mistral Large 4 | 163 | 1 | 25 | 11 |
| latent memory vs passage in the prompt | GPT-6.1 Sol | 43 | 24 | 116 | 17 |
| | Gemini 3.8 Flash | 34 | 41 | 114 | 11 |
| | Mistral Large 4 | 37 | 13 | 114 | 36 |
| passage in the prompt vs closed book | GPT-6.1 Sol | 167 | 2 | 21 | 10 |
| | Gemini 3.8 Flash | 170 | 8 | 19 | 3 |
| | Mistral Large 4 | 171 | 2 | 20 | 7 |

Across the three judges:

| Comparison | Majority (2 of 3 or more) | All three agree |
| --- | --- | --- |
| latent memory vs closed book | latent 164, closed 24, tie 1; no majority or orders disagree 11 | latent 153, closed 18 |
| latent memory vs passage in the prompt | latent 37, prompt 113, tie 22; no majority or orders disagree 28 | latent 24, prompt 91, tie 10 |
| passage in the prompt vs closed book | prompt 168, closed 20, tie 3; no majority or orders disagree 9 | prompt 162, closed 16, tie 1 |

- **Beyond the verdict:** latent memory vs closed book, split by whose verdict
  is right:
  - where only one answer has the right verdict, every judge prefers that
    answer (54 latent, 11 closed book);
  - where both are right (114 questions), the judges prefer latent memory 94,
    93 and 92 times, against closed book 18, 10 and 13 (GPT-6.1 Sol, Gemini,
    Mistral).
- **The prompt's advantage is in the details:** where a judge prefers the
  passage in the prompt over latent memory (114–116 times), both verdicts are
  right in 95–98 of those cases. Its reasons point to the latent-memory
  answer's details: claims the passage does not support, specifics rendered
  less exactly, a source left out.
- **The judges agree with each other** far more than they disagree. On the
  main comparison, 171 of the 200 questions get the same order-consistent
  outcome from all three judges.

### The representative examples

| Question | Latent vs closed book | Latent vs prompt |
| --- | --- | --- |
| #474 Australia at the Somme (gain) | latent, all three | prompt, all three: from latent memory, "ANZAC" where the passage says AIF, and Fromelles called a "prelude" |
| #769 roulette numbers sum to 666 (gain) | latent, all three | latent for GPT-6.1 Sol and Gemini (the prompt's answer calls the fact fictional); Mistral's orders disagree |
| #835 Soho in the West End (gain) | latent, all three | prompt for Gemini and Mistral (it names the council's 2005 report); GPT-6.1 Sol's orders disagree |
| #229 dropped third strike (loss) | closed book, all three: the label's "no" comes first in their instructions | latent for GPT-6.1 Sol and Gemini, prompt for Mistral |

On #229, the latent-memory and prompt answers both restate the passage's rule
for the Major Division and older divisions and answer "yes". GPT-6.1 Sol's
reasons note that the latent-memory explanation is the more faithful one.

## What this adds to the card

- **Free text, not only a token:** with a passage held only as layer-4
  states, frozen Mistral writes answers whose verdicts match the prompt's
  (0.840 against 0.825) and that three judges from three providers prefer to
  closed book's on over 80% of questions.
- **An honest gap:** the same judges prefer the prompt's answers about three
  times as often as latent memory's. Read from layer 4, the passage's gist
  survives better than its exact details.
- **Still descriptive:** run once, on 200 questions, by a protocol fixed only
  for this record. The examples come from a rule fixed before judging.
