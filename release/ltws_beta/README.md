---
license: apache-2.0
base_model: mistralai/Mistral-7B-Instruct-v0.3
base_model_relation: adapter
language:
- en
tags:
- latent-workspace
- latent-memory
- research
---

# mistral-7b-instruct-v0.3-LTWS β

**A frozen Mistral that answers from facts it never saw in its prompt.** You
write the facts once into Mistral's own internal states, after its first four
layers: this is the **latent memory**. Questions asked later are answered from
that memory, through Mistral's own remaining layers plus a small trained
**route** (about 3M parameters). Mistral's weights are not changed.

**Source repository:**
[RyoSpiralArchitect/Latent_Workspace](https://github.com/RyoSpiralArchitect/Latent_Workspace)
on GitHub. It holds the code, the records of every run behind the numbers on
this page, and the scripts that reproduce them.

**β: a research preview.**
- **Narrow:** it works on one synthetic task family, yes/no questions about
  rankings.
- **Not fully established:** its main claim falls short of its pre-registered
  criterion.

Read [What it can and cannot do](#what-it-can-and-cannot-do) before using it.

## At a glance

```text
 facts ──► Mistral layers 1–4 ──► latent memory (states; compute once, cache)
                                        │
 question ──► Mistral layers 1–4 ───────┤
                                        ▼
                   [ memory states ][ question states ]
                                        │
                        Mistral layers 5–32 (unchanged)
                                        │
                    final states at the question's positions
                         │                            │
                         ▼                            ▼
              Mistral's own answer logits     LTWS route (~3M params)
                  (" no" / " yes")            gated residual on " no" / " yes"
                         └──────────────┬─────────────┘
                                        ▼
                                     answer
```

The facts and the question never share a prompt. They are encoded apart, and
meet only from layer 5 on, where the question's positions can attend to the
memory's states.

## Why this exists

Language models usually receive facts as text in their prompt, and re-read
them for every question. **Latent Workspace** is the research program behind
this release. It asks whether a model can keep and use information in its
**own hidden states**: a workspace it writes into and reads from, instead of
its text context. The program looks at such a workspace from four sides:

- whether its content reaches the model's answers (*availability*);
- whether the model can think through it (*deliberation*);
- whether it stays active (*occupancy*);
- what it leaves in the model's behavior (*consequence*).

This β is the program's first artifact in which **memory content measurably
reaches the answers through a latent path**, tested against controls in
pre-registered runs. The release puts that mechanism, its evidence and its
limits in one place, so others can inspect and build on it.

Possible uses of the idea are not shown here. Examples would be memory that is
written once and reused across many questions, or modular memories that can be
swapped. What is shown is that the mechanism works on a controlled task.

## How it works

1. **Writing.** The fact text (a header line, then lines like
   `- A is ranked above B.`) is put in a canonical order and run **alone**
   through Mistral's first four layers. Their outputs are the latent memory:
   one state vector per token. They can be cached and reused for any number of
   questions.
2. **Reading.** The question is rendered with Mistral's chat template and run
   alone through the same four layers. The memory's states are placed before
   the question's states, as earlier positions in the sequence. Mistral's
   remaining 28 layers then run unchanged over both. Below layer 5 the
   question never sees the facts.
3. **The route.** The route reads Mistral's final hidden states at the
   question's positions.
   - It is a small "lattice" of 4 latent steps (workspace width 256, 8
     attention heads).
   - It adds a **gated, low-rank (rank 32) correction** to the two answer
     logits, " no" and " yes".
   - At initialization the correction is exactly zero, so an untrained route
     *is* Mistral.
4. **Content gating.** During training, each question was also read with
   another world's facts that do not answer it (they do not name both of its
   entities). The route's correction on those was pushed toward zero. As a
   result, the route moves answers only when the memory is about the question.
   With the β's mean of routes, random, unrelated or no memory moves the
   answer by 0.01–0.08 in the logit gap; the right memory moves it by 4.2.
5. **Three routes, averaged.** Three routes were trained with different seeds,
   and the β answers with the mean of their logits.

### Why layer 4?

Before building the route, the project measured *how deep* a separately
written memory can enter frozen Mistral and still be read. The memory was put
in at layer 0, 4, 8 or 16, and the same held-out test was used throughout
(accuracy with the right memory; chance is 0.50):

| Memory enters at | Mistral alone | Mistral + a route |
| ---: | --- | --- |
| layer 0 (the facts as a text prefix) | 0.74–0.76, content reaches answers | 0.85–0.90 |
| **layer 4** | 0.58–0.60, content does not reach answers | **0.79–0.83**, content reaches answers in 2 of 3 seeds |
| layer 8 | 0.50–0.52 | 0.52–0.65 |
| layer 16 | 0.52–0.53 | 0.50–0.51 |

Layer 4 is the deepest point where memory states, computed without ever seeing
the question, can still be read. The β's two later refinements, content gating
and a stable end of training, made that reading consistent across seeds.

## How it was evaluated

- **The task:**
  - Each synthetic world ranks six names, drawn from a pool of twelve,
    through five "X is ranked above Y" facts. Eight yes/no questions are
    asked about it.
  - Every world has a twin in which one adjacent pair is swapped. Two of the
    eight questions concern that pair, so their right answer changes with the
    swap.
- **The key test, a "flip":** the same question gets the original facts'
  answer under the original facts, and the swapped facts' answer under the
  swapped facts. Flips are counted on 256 such questions in 128 held-out
  world pairs.
- **The criterion ("content reaches answers"):**
  - at least 26 flips;
  - at least 20 more than under a control memory of random states with the
    same size and norm;
  - a one-sided sign test over worlds at α = 0.001.
- **The process:** every design and criterion was frozen before its run. Each
  run executed once from sealed code and was verified offline. Failed and
  negative results are published with the rest.

## Results

### The latent-memory task

All figures are on the 128 held-out world pairs.

| System | Accuracy, right memory | Accuracy, random memory | Flips / under random memory | Worlds in the memory's direction | Verdict |
| --- | --- | --- | --- | --- | --- |
| Mistral alone, facts as text in the prompt | 0.74–0.76 | 0.50 | 55 / 6 | 90 of 128 | content reaches answers |
| Mistral alone, latent memory at layer 4 | 0.58–0.60 | 0.50 | 44 / 3 | 54 of 128 | not established |
| **LTWS β, mean of the three routes** | 0.85–0.86 | 0.50 | 65 / 4 | 85 of 128 | content reaches answers |
| each route alone (seeds 1 / 2 / 3) | 0.84–0.85 | 0.50 | 58 / 4, 59 / 4, 60 / 4 | 83, 85, 80 of 128 | yes, yes, no |

**The pre-registered criterion was not met.** It required *every* route alone
to pass, and seed 3 is two worlds short on the sign test. The mean's reading
was descriptive in that run; it was chosen as the β's default afterwards.

Accuracy by kind of question:

| Questions | LTWS β | Mistral, facts as text | Mistral, latent memory alone | No memory |
| --- | --- | --- | --- | --- |
| the adjacent pair the swap reverses (2 per world) | 0.55 / 0.57 | 0.58 | 0.53 | 0.52 |
| ... answered right under both versions (of 256) | 65 | 55 | 44 | — |
| other pairs, "Does X outrank Y?" (1–4 steps apart) | 0.93 | 0.77 | 0.59 | 0.53 |
| the top and bottom of the ranking ("Is X ranked above Y?") | 1.00 | 0.89 | 0.65 | 0.55 |

- **Unchanged relations:** most of the β's accuracy comes from relations the
  swap leaves unchanged. It reads them from the memory; without memory they
  are near chance.
- **Multi-step relations:** facts state only adjacent pairs, so pairs 2–4
  steps apart need chaining. The β answers them at 0.90–0.97.
- **The hard case is the pair the swap reverses.** The β answers both versions
  right for 65 of 256 such questions. Mistral reading the same facts as text
  manages 55, and random memory 4.

### No degradation: without memory, the β is Mistral

The β adds memory; it does not change Mistral. Without a memory, it runs
Mistral's own forward pass on Mistral's own weights, and nothing is added to
that computation. Its outputs are Mistral's by construction.

- **Checked on standard benchmarks:** each item was scored twice, with the
  plain transformers forward and through the β's host wrapper. The logits were
  **identical on every item, bit for bit** (2,742 of 2,742), so on ordinary
  tasks the β's scores are Mistral's own.
- **Protocol:** the letter with the highest next-token logit after "Answer:".
  The numbers are not comparable to leaderboards that use other protocols.

| Benchmark | Base Mistral | LTWS β |
| --- | --- | --- |
| MMLU (570-question subset, 5-shot) | 0.625 | 0.625 (identical on 570 / 570 items) |
| ARC-Challenge (test, 0-shot) | 0.784 | 0.784 (identical on 1,172 / 1,172) |
| HellaSwag (1,000-item validation sample, 0-shot) | 0.723 | 0.723 (identical on 1,000 / 1,000) |

### A real passage as latent memory: BoolQ

BoolQ asks yes/no questions about a Wikipedia passage. Here the passage
reached Mistral in four ways (3,270 validation questions; always answering
"yes" scores 0.622):

| How Mistral gets the passage | Accuracy |
| --- | --- |
| not at all (closed book) | 0.668 |
| in the prompt, as usual | 0.850 |
| **as latent memory at layer 4, Mistral alone (no route)** | **0.831** |
| as latent memory at layer 4, with the β's routes | 0.803 |

- **Close to the prompt:** frozen Mistral reads a real passage held as latent
  memory almost as well as from its prompt, 0.831 against 0.850. That is 90%
  of the passage's benefit over closed book.
  - Nothing was trained for this: Mistral's own layers 5–32 read states written
    at layer 4.
  - It is a first sign that the mechanism carries natural text, not only
    synthetic facts.
- **The routes do not transfer:** they were trained only on synthetic
  rankings, and they lower BoolQ accuracy. Use the packaged routes and API
  for the ranking task only.
- **How it was run:** once, descriptively, with about ±1.3 points of
  uncertainty per figure. The
  [benchmark script](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/scripts/bench_ltws_beta.py)
  shows how to hold your own text as latent memory with Mistral alone.

### Free generation: Mistral writes from a passage it holds as latent memory

The scores above read one token. Here Mistral **writes** its answer: yes or
no, then a short explanation. 200 BoolQ questions (a fixed random sample) were
each answered four ways, **with the same sampling seed** (temperature 0.7,
top-p 0.9). The answers to a question differ only in how its passage reached
Mistral.

| How Mistral gets the passage | Verdict right (first word) |
| --- | --- |
| not at all (closed book) | 0.625 |
| not at all, but asked about "the passage you were given" | 0.610 |
| **as latent memory at layer 4, Mistral alone** | **0.840** |
| in the prompt, as usual | 0.825 |

- **Latent memory vs closed book:** where their verdicts differ, latent memory
  is right 54 times and closed book 11.
- **The content does it:** asked about "the passage you were given" without a
  memory, Mistral answers like closed book. The gain comes from what the
  memory holds.
- **Latent memory vs the prompt:** level, 9 to 6 where they differ.

**Answer quality, judged by three LLMs.** GPT-6.1 Sol (OpenAI, medium
reasoning), Gemini 3.8 Flash (Google) and Mistral Large 4 (Mistral AI)
compared the answers in pairs, blind. Each judge saw the passage, the
question, the correct answer and two answers, never how the answers were
made. Every pair was judged in both orders, and a preference counts only if
both orders agree.

| Comparison (200 questions) | Judge | First better | Tie | Second better | Orders disagree |
| --- | --- | ---: | ---: | ---: | ---: |
| **latent memory vs closed book** | GPT-6.1 Sol | **166** | 0 | 31 | 3 |
| | Gemini 3.8 Flash | **163** | 5 | 22 | 10 |
| | Mistral Large 4 | **163** | 1 | 25 | 11 |
| latent memory vs passage in the prompt | GPT-6.1 Sol | 43 | 24 | **116** | 17 |
| | Gemini 3.8 Flash | 34 | 41 | **114** | 11 |
| | Mistral Large 4 | 37 | 13 | **114** | 36 |
| passage in the prompt vs closed book (a control) | GPT-6.1 Sol | **167** | 2 | 21 | 10 |
| | Gemini 3.8 Flash | **170** | 8 | 19 | 3 |
| | Mistral Large 4 | **171** | 2 | 20 | 7 |

- **Better than closed book, beyond the verdict:** each judge prefers the
  latent-memory answer on over 80% of questions, and all three agree on 153.
  Where both answers have the right verdict (114 questions), the judges still
  prefer latent memory 92–94 times, against 10–18: its explanations use the
  passage.
- **Not as good as the prompt:** the verdicts are level, but each judge
  prefers the passage-in-prompt answer about three times as often (114–116
  against 34–43), mostly where both verdicts are right. The judges' reasons
  point to details: from latent memory, Mistral keeps the answer and the gist,
  but renders specifics less exactly and adds claims the passage does not
  support.
- **The control behaves as expected:** the passage in the prompt beats closed
  book by a similar margin.
- **How it was run:** once, descriptively. Gemini 3.1 Pro was tried first and
  ran into the provider's request limit after 242 of 1,200 judgments; that
  partial run is kept in the record and used nowhere. The
  [record](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/provenance/beta/ltws_beta_generation_20261018/README.md)
  has every answer, every judge's reply and the scripts.

**Examples: where the answers differ most.** A rule fixed before any judging
chose them: among questions where closed book and latent memory reach
different verdicts, the largest changes in Mistral's first-token belief in the
correct answer. It took the three largest gains and the largest loss. All
answers to a question share one sampling seed. The passages are from BoolQ
(CC BY-SA 3.0, drawn from Wikipedia), summarized here.

**1. "Did australia fight in the battle of the somme?"** Correct: yes.
*The passage:* Australian divisions joined the Somme offensive within its
first weeks; the 5th Division fought at Fromelles on 19 July 1916.

- **Closed book:** "No, Australia did not fight in the Battle of the Somme,
  which was a major battle of World War I fought by the armies of the British
  Empire and France against the German Empire. Australia was part of the
  British Empire at the time, but their forces were primarily engaged in the
  Gallipoli campaign and later on the Western Front, but not specifically in
  the Battle of the Somme."
- **Latent memory:** "Yes, Australia did fight in the Battle of the Somme. The
  battle began on 1 July 1916, and four divisions of the Australian and New
  Zealand Army Corps (ANZAC) were involved in the fighting, with the 5th
  Australian Division participating in the Battle of Fromelles on 19 July 1916.
  The Battle of Fromelles was a prelude to the main Battle of the Somme, which
  lasted from July to November 1916."
- **Passage in the prompt:** "Yes, Australia did fight in the Battle of the
  Somme. The 5th Division of the Australian and New Zealand Army Corps (ANZAC)
  participated in the Battle of Fromelles, which was part of the larger Battle
  of the Somme, on 19 July 1916. Despite not being involved in the disastrous
  first day on the Somme, four divisions of the Australian Imperial Force (AIF)
  were committed to the battle within three weeks of the Allied offensive."
- **Judges:** all three prefer latent memory to closed book. All three
  prefer the prompt's answer to latent memory's: from latent memory, Mistral
  calls the four divisions ANZAC where the passage says AIF, and calls
  Fromelles a "prelude" to the Somme, which the passage does not say.

**2. "Do all the numbers on a roulette wheel add up to 666?"** Correct: yes.
*The passage:* the numbers 0 to 36 on a roulette wheel sum to 666, the
"Number of the Beast".

- **Closed book:** "No, the numbers on a standard roulette wheel do not add up
  to 666. A European roulette wheel has numbers 1 through 36 (for a total of
  678), and one green 0. An American roulette wheel has numbers 1 through 36, a
  0, and a 00, for a total of 668. Neither version adds up to 666."
- **Latent memory:** "Yes, the total sum of all the numbers on a standard
  roulette wheel (0-36) is 666. This includes both the red and black numbers,
  but does not include the green 0. The number 0 is not included in the sum of
  666, but its absence does not prevent the total of all other numbers from
  equaling 666."
- **Passage in the prompt:** "Yes, according to the passage, the sum of all
  the numbers on the roulette wheel (from 0 to 36) is 666. However, it's
  important to note that this is a fictional anecdote and the actual sum of
  numbers on a traditional roulette wheel (0, 32 red numbers, and 16 black
  numbers) does not equal 666."
- **Judges:** all three prefer latent memory to closed book, whose sums are
  wrong. GPT-6.1 Sol and Gemini also prefer it to the prompt's answer, which
  calls the fact fictional; Mistral Large 4's two orders disagree. Latent
  memory's own slip, leaving 0 out, does not change the sum.

**3. "Is soho in the west end of london?"** Correct: yes. *The passage:* the
West End has no official boundary; a 2005 Westminster City Council report
counted Soho among its areas.

- **Closed book:** "No, Soho is not in the West End of London. Soho is located
  centrally in London, between Mayfair to the west, Oxford Street to the north,
  Chinatown to the east, and Covent Garden to the south. The West End refers to
  the areas of London's central district that are primarily dominated by
  commercial, entertainment, and residential premises, which includes
  locations such as Piccadilly Circus, Regent Street, and Leicester Square, but
  not Soho."
- **Latent memory:** "Yes, Soho is in the West End of London. According to the
  passage, the West End includes Soho as one of its constituent parts."
- **Passage in the prompt:** "Yes, Soho is in the West End of London.
  According to the Westminster City Council's 2005 report, Soho is one of the
  areas included in the definition of the West End."
- **Judges:** all three prefer latent memory to closed book. Gemini and
  Mistral prefer the prompt's answer, which names the council's 2005 report as
  the source; GPT-6.1 Sol's two orders disagree.

**4. The largest loss: "Can you run on a dropped third strike in little
league?"** Correct, by BoolQ's label: no. *The passage:* in Little League's
Tee-Ball and Minor League divisions the batter is out on any third strike; in
the Major Division and the older divisions, the batter may try for first base
when the third strike is not caught.

- **Closed book:** "No, in little league baseball, a dropped third strike
  results in the batter being called out and does not allow the runner-up on
  base to advance or the batter to reach base. The runner can only advance if
  the ball is put into play or there is an error."
- **Latent memory:** "Yes, in Little League (or the Major Division), Junior,
  Senior, and Big League divisions, a batter may attempt to advance to first
  base on an uncaught third strike. This rule does not apply in Tee-Ball and
  Minor League divisions."
- **Passage in the prompt:** "Yes, in the Major Division of Little League,
  Junior, Senior, and Big League divisions, as well as in Little League Major
  Division Softball and many other youth baseball leagues such as the USSSA, a
  batter may attempt to advance to first base on an uncaught third strike. This
  is not the case in Tee-Ball and Minor League divisions of Little League, where
  a batter is out after the third strike regardless of whether the pitched ball
  is caught cleanly by the catcher."
- **Judges:** told that the correct answer is "no", all three prefer closed
  book: their instructions put the verdict first. The two passage-reading
  answers restate the passage's rule for the Major Division and older
  divisions, and GPT-6.1 Sol notes that the latent-memory explanation is the
  more faithful one.

## Use

```bash
pip install -r requirements.txt
python example.py
```

[`example.py`](example.py) loads Mistral at the pinned revision (bf16, SDPA
attention). It writes a new world's facts as latent memory, then asks the
same questions three ways: with the facts, with one adjacent pair swapped, and
with no memory. The core of it:

```python
from latent_workspace import DecoderHost, package

descriptor, routes = package.load(".")  # checks every file's hash and each route
reader = package.LatentMemory(DecoderHost(model), tokenizer, descriptor, routes)
memory = reader.write(facts)  # "World facts. ...\n- A is ranked above B.\n..."
result = reader.read("Is A ranked above B? Answer:", memory)
result["answer"], result["mean"]  # "yes" / "no", and the [no, yes] logits
```

- **Facts:** a header line, then one `- X is ranked above Y.` line per fact.
- **Questions:** they end with ` Answer:`, as in training ("Is X ranked above
  Y? Answer:" or "Does X outrank Y? Answer:").
- **The loader:** the `latent_workspace` package in this repository, copied
  unchanged from the source repository. It needs only torch, transformers and
  safetensors.

Output of `example.py` (checked run, CUDA). The third question is answered
wrongly under both memories: the right answer is "no", from Aster > Joren >
Cyra.

```text
Is Aster ranked above Joren? Answer:     memory=facts    answer=yes (yes - no = +1.62)
Is Aster ranked above Joren? Answer:     memory=swapped  answer=no  (yes - no = -0.69)
Is Aster ranked above Joren? Answer:     memory=none     answer=yes (yes - no = +2.73)
Is Luma ranked above Doran? Answer:      memory=facts    answer=yes (yes - no = +5.44)
Is Luma ranked above Doran? Answer:      memory=swapped  answer=yes (yes - no = +4.01)
Is Luma ranked above Doran? Answer:      memory=none     answer=yes (yes - no = +1.97)
Does Cyra outrank Aster? Answer:         memory=facts    answer=yes (yes - no = +2.91)
Does Cyra outrank Aster? Answer:         memory=swapped  answer=yes (yes - no = +1.14)
Does Cyra outrank Aster? Answer:         memory=none     answer=no  (yes - no = -1.46)
```

## What it can and cannot do

- **Can:** answer yes/no ranking questions from facts held only as latent
  memory, in the format above. It leaves answers alone when the memory is not
  about the question.
- **Shown, not packaged:** frozen Mistral alone can read a natural passage held
  as latent memory at layer 4, and answer questions about it in free text
  (BoolQ, above). The scripts linked there do this; the package's API covers
  the ranking task only.
- **Task family only:**
  - synthetic ranking worlds (six entities from a pool of twelve, five facts
    each);
  - the two question forms above, in English;
  - yes/no answers.
- **Weak on the fine distinction:** when two fact sets differ only in one
  adjacent pair, it answers that pair right under both about one time in four.
- **Not provided:**
  - general question answering through the β's API;
  - text generation through the route (the routes only adjust " no" / " yes");
  - any claim about reasoning, intelligence, safety or quality beyond what is
    measured here.
- **Inherited:** the upstream model's limitations, including its lack of
  moderation mechanisms.
- **Memory hygiene:** memory is read as given. Conflicting or untrusted facts
  are not detected.

## Training

- **Data:** the frozen model's states on 256 synthetic world pairs, both the
  original and the swapped facts. The held-out worlds above were never used.
- **Routes:**
  - three seeds, each trained on CPU in FP32: 512 updates of 32 questions;
  - AdamW at 3e-4, the learning rate decaying linearly after update 256;
  - choice-normalized cross-entropy over " no" / " yes", plus content gating
    at weight 0.3.

## Records

- **The task results** come from sealed, offline-verified runs. Their
  breakdowns (by kind of question, by number of steps) were computed afterwards
  from those runs' records.
- **The package** was checked in a fresh environment: it reproduces those
  runs' scores and verdicts end to end, from text.
- **The benchmarks, the free generation and the LLM judgments** were run once
  with the published package and recorded with their scripts, settings and
  every judge's reply.

The records are in the source repository,
[RyoSpiralArchitect/Latent_Workspace](https://github.com/RyoSpiralArchitect/Latent_Workspace):

- [the β package and its checks](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/docs/v20/BETA_PACKAGE.md);
- [the routes' run (V20 A5)](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/provenance/pilots/v20_a5_stable_route_20261018/README.md);
- [content gating (V20 A4)](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/provenance/pilots/v20_a4_gated_route_20261017/README.md);
- [the depth ladder (V20 A2)](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/provenance/pilots/v20_a2_depth_ladder_20261016/README.md);
- [the benchmarks above](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/provenance/beta/ltws_beta_benchmarks_20261018/README.md);
- [the free generation and its LLM judges](https://github.com/RyoSpiralArchitect/Latent_Workspace/blob/main/provenance/beta/ltws_beta_generation_20261018/README.md).

## License

Apache-2.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)), © 2026 Ryo Higa /
RyoSpiralArchitect.

- **The loader code:** its copy here is Apache-2.0. In the
  [source repository](https://github.com/RyoSpiralArchitect/Latent_Workspace)
  the same code is AGPL-3.0-or-later.
- **Mistral-7B-Instruct-v0.3:** Apache-2.0 by Mistral AI, and not
  redistributed here. This work is not affiliated with or endorsed by Mistral
  AI.
