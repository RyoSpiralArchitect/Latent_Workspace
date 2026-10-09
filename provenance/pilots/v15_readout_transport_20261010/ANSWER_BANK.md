# V15 native-readout transport: complete answer bank

All 64 continuations are shown below in eight matched case/regime groups. No answer has been selected, shortened, corrected, or relabeled.

Strictly correct: **0/64**. Whole-answer unparseable: **64/64**. Length-capped at 64 new tokens: **63/64**; EOS-terminated: **1/64**.

These are two exposed training worlds, not a held-out quality evaluation. The strict parser accepts only the entire stripped answer `yes` or `no` (case-insensitive); lowercase compliance is a separate measure. An initial yes/no token is not rescued as a correct whole answer. Length-capped outputs remain incorrect. No LLM judge was run.

`final_*` and `mean_*` use the retained step-256 final-state and question-mean readers, respectively. `*_twin` targets the counterfactual memory; other conditions target original memory. Zero controls execute their readers and match base exactly. `base_inline` puts facts in a different prompt, so its divergence is not attributed to workspace memory.

First divergence compares generated token IDs with the matched base continuation (both one-based token number and zero-based step are shown). Initial logit and probability shifts compare the selected token against a zero-delta base at the **same prefix**, not against a different inline prompt. Probabilities are native temperature-1 softmax values, distinct from sampling-policy probabilities. All selections use native full-vocabulary logits. Full-prefix recomputation does not carry continuous hidden state or a KV cache.

Historical original twin/intact fact lists were independently permuted; their contrast confounds content and serialization. Neither visible divergence nor a changed probability establishes isolated semantic causality or improved quality.

Sources: [raw generation and token traces](raw/GENERATION.json), [verified scalar summary](SUMMARY.json), [raw feature bindings](raw/FEATURES.json), [SHA/byte inventory](ARTIFACT_INDEX.json). Numeric displays below are rounded; the source JSON retains recorded precision. Rendering does not replay tokenizer decoding.

## World 0, query 0 — greedy

Seed: 0; temperature: 0.0; maximum new tokens: 64.

### Common non-inline prompt

```text
Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Galen ranked above Kestrel? Answer:
```

### Original memory facts (also provided in the inline prompt)

```text
World facts. The ranking is transitive.
- Galen is ranked above Kestrel.
- Kestrel is ranked above Fenn.
- Ione is ranked above Doran.
- Fenn is ranked above Ione.
- Hira is ranked above Galen.
```

### Counterfactual memory facts

```text
World facts. The ranking is transitive.
- Ione is ranked above Doran.
- Kestrel is ranked above Galen.
- Fenn is ranked above Ione.
- Hira is ranked above Kestrel.
- Galen is ranked above Fenn.
```

| Condition | Target | Finish | Tokens | Strict correct | First divergence from base | Initial max absolute Δlogit | Initial Δp(chosen) |
| --- | --- | --- | ---: | --- | --- | ---: | ---: |
| base | yes | length | 64 | false | reference | 0 | 0 |
| base_inline | yes | length | 64 | false | token 1 (step 0) | 0 | 0 |
| final_intact | yes | length | 64 | false | token 1 (step 0) | 0.125 | 0.056039689 |
| final_twin | no | length | 64 | false | none | 0.25 | 0.0828742742 |
| final_zero | yes | length | 64 | false | none | 0 | 0 |
| mean_intact | yes | length | 64 | false | token 1 (step 0) | 0.125 | 0.0560397019 |
| mean_twin | no | length | 64 | false | token 10 (step 9) | 0.25 | 0.082874319 |
| mean_zero | yes | length | 64 | false | none | 0 | 0 |

### base

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.454735261` → `0.454735261`. Sampling-policy probability: `1`.

```text
no

### 1.1.2.

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Galen?
```

### base_inline

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `18` → `18`. Native probability: `0.769504579` → `0.769504579`. Sampling-policy probability: `1`.

```text
yes

Is Kestrel ranked above Fenn? Answer: yes

Is Fenn ranked above Ione? Answer: no

Is Ione ranked above Doran? Answer: yes

Is Fenn ranked above Ione? Answer: no

Is Hira ranked above Galen?
```

### final_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.454735261` → `0.51077495`. Sampling-policy probability: `1`.

```text
yes

Is Kestrel ranked above Galen? Answer: no

Is Galen ranked above Eudoxia? Answer: yes

Is Eudoxia ranked above Galen? Answer: no

Is Kestrel ranked above Eudoxia? Answer: yes

Is
```

### final_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.454735261` → `0.537609535`. Sampling-policy probability: `1`.

```text
no

### 1.1.2.

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Galen?
```

### final_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.454735261` → `0.454735261`. Sampling-policy probability: `1`.

```text
no

### 1.1.2.

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Galen?
```

### mean_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.454735261` → `0.510774963`. Sampling-policy probability: `1`.

```text
yes

Is Kestrel ranked above Galen? Answer: no

Is Galen ranked above Eagle? Answer: no

Is Eagle ranked above Galen? Answer: no

Is Kestrel ranked above Eagle? Answer: yes

Is Eagle ranked above Kest
```

### mean_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.454735261` → `0.53760958`. Sampling-policy probability: `1`.

```text
no

### 1.1.10

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Galen?
```

### mean_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.454735261` → `0.454735261`. Sampling-policy probability: `1`.

```text
no

### 1.1.2.

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Galen?
```

## World 0, query 0 — sample211

Seed: 211; temperature: 0.7; maximum new tokens: 64.

### Common non-inline prompt

```text
Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Galen ranked above Kestrel? Answer:
```

### Original memory facts (also provided in the inline prompt)

```text
World facts. The ranking is transitive.
- Galen is ranked above Kestrel.
- Kestrel is ranked above Fenn.
- Ione is ranked above Doran.
- Fenn is ranked above Ione.
- Hira is ranked above Galen.
```

### Counterfactual memory facts

```text
World facts. The ranking is transitive.
- Ione is ranked above Doran.
- Kestrel is ranked above Galen.
- Fenn is ranked above Ione.
- Hira is ranked above Kestrel.
- Galen is ranked above Fenn.
```

| Condition | Target | Finish | Tokens | Strict correct | First divergence from base | Initial max absolute Δlogit | Initial Δp(chosen) |
| --- | --- | --- | ---: | --- | --- | ---: | ---: |
| base | yes | length | 64 | false | reference | 0 | 0 |
| base_inline | yes | length | 64 | false | token 10 (step 9) | 0 | 0 |
| final_intact | yes | length | 64 | false | none | 0.125 | 0.056039689 |
| final_twin | no | length | 64 | false | none | 0.25 | -0.0852419912 |
| final_zero | yes | length | 64 | false | none | 0 | 0 |
| mean_intact | yes | length | 64 | false | none | 0.125 | 0.0560397019 |
| mean_twin | no | length | 64 | false | none | 0.25 | -0.0852419604 |
| mean_zero | yes | length | 64 | false | none | 0 | 0 |

### base

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.454735261` → `0.454735261`. Sampling-policy probability: `0.488832716`.

```text
yes

### Explanation

According to the world facts, Galen's rank is 2, and Kestrel's rank is 5. A ranking of 2 is greater than a ranking of 5. Therefore, Galen is ranked above Kestrel.

###
```

### base_inline

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `18` → `18`. Native probability: `0.769504579` → `0.769504579`. Sampling-policy probability: `0.91875359`.

```text
yes

### Explanation

We can see from the world facts that Galen is ranked above Kestrel.

### Answer Key

1. yes
2. no
3. no
4. no
5. no
6. yes
7. yes
8. yes
```

### final_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.454735261` → `0.51077495`. Sampling-policy probability: `0.574898718`.

```text
yes

### Explanation

According to the world facts, Galen's rank is 2, and Kestrel's rank is 5. A ranking of 2 is greater than a ranking of 5. Therefore, Galen is ranked above Kestrel.

###
```

### final_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.5`. Native probability: `0.454735261` → `0.36949327`. Sampling-policy probability: `0.360729947`.

```text
yes

### Explanation

According to the world facts, Galen's rank is 2, and Kestrel's rank is 5. A ranking of 2 is greater than a ranking of 5. Therefore, Galen is ranked above Kestrel.

###
```

### final_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.454735261` → `0.454735261`. Sampling-policy probability: `0.488832716`.

```text
yes

### Explanation

According to the world facts, Galen's rank is 2, and Kestrel's rank is 5. A ranking of 2 is greater than a ranking of 5. Therefore, Galen is ranked above Kestrel.

###
```

### mean_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.454735261` → `0.510774963`. Sampling-policy probability: `0.574898718`.

```text
yes

### Explanation

According to the world facts, Galen's rank is 2, and Kestrel's rank is 5. A ranking of 2 is greater than a ranking of 5. Therefore, Galen is ranked above Kestrel.

###
```

### mean_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.5`. Native probability: `0.454735261` → `0.3694933`. Sampling-policy probability: `0.360729947`.

```text
yes

### Explanation

According to the world facts, Galen's rank is 2, and Kestrel's rank is 5. A ranking of 2 is greater than a ranking of 5. Therefore, Galen is ranked above Kestrel.

###
```

### mean_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.454735261` → `0.454735261`. Sampling-policy probability: `0.488832716`.

```text
yes

### Explanation

According to the world facts, Galen's rank is 2, and Kestrel's rank is 5. A ranking of 2 is greater than a ranking of 5. Therefore, Galen is ranked above Kestrel.

###
```

## World 0, query 1 — greedy

Seed: 0; temperature: 0.0; maximum new tokens: 64.

### Common non-inline prompt

```text
Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Galen? Answer:
```

### Original memory facts (also provided in the inline prompt)

```text
World facts. The ranking is transitive.
- Galen is ranked above Kestrel.
- Kestrel is ranked above Fenn.
- Ione is ranked above Doran.
- Fenn is ranked above Ione.
- Hira is ranked above Galen.
```

### Counterfactual memory facts

```text
World facts. The ranking is transitive.
- Ione is ranked above Doran.
- Kestrel is ranked above Galen.
- Fenn is ranked above Ione.
- Hira is ranked above Kestrel.
- Galen is ranked above Fenn.
```

| Condition | Target | Finish | Tokens | Strict correct | First divergence from base | Initial max absolute Δlogit | Initial Δp(chosen) |
| --- | --- | --- | ---: | --- | --- | ---: | ---: |
| base | no | length | 64 | false | reference | 0 | 0 |
| base_inline | no | length | 64 | false | token 9 (step 8) | 0 | 0 |
| final_intact | no | length | 64 | false | token 1 (step 0) | 0.125 | 0.0573802007 |
| final_twin | yes | length | 64 | false | none | 0.1875 | 0.0553745072 |
| final_zero | no | length | 64 | false | none | 0 | 0 |
| mean_intact | no | length | 64 | false | token 1 (step 0) | 0.125 | 0.0573800445 |
| mean_twin | yes | length | 64 | false | none | 0.1875 | 0.055389412 |
| mean_zero | no | length | 64 | false | none | 0 | 0 |

### base

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.51517834` → `0.51517834`. Sampling-policy probability: `1`.

```text
yes

Is Galen ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Galen ranked above Galen? Answer: no

Is Kestrel ranked above Einstein? Answer: no

Is Einstein ranked above Kest
```

### base_inline

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `18.625` → `18.625`. Native probability: `0.901914193` → `0.901914193`. Sampling-policy probability: `1`.

```text
yes

Is Galen ranked above Hira? Answer: no

Is Fenn ranked above Ione? Answer: yes

Is Ione ranked above Doran? Answer: yes

Is Doran ranked above Fenn? Answer: no

Is Hira ranked above Galen? Answer
```

### final_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.401221295` → `0.458601496`. Sampling-policy probability: `1`.

```text
no

### 1.1.2.

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Galen ranked above Kestrel?
```

### final_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17.125`. Native probability: `0.51517834` → `0.570552848`. Sampling-policy probability: `1`.

```text
yes

Is Galen ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Galen ranked above Galen? Answer: no

Is Kestrel ranked above Einstein? Answer: no

Is Einstein ranked above Kest
```

### final_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.51517834` → `0.51517834`. Sampling-policy probability: `1`.

```text
yes

Is Galen ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Galen ranked above Galen? Answer: no

Is Kestrel ranked above Einstein? Answer: no

Is Einstein ranked above Kest
```

### mean_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.401221295` → `0.458601339`. Sampling-policy probability: `1`.

```text
no

### 1.1.2.

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Galen ranked above Kestrel?
```

### mean_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17.125`. Native probability: `0.51517834` → `0.570567752`. Sampling-policy probability: `1`.

```text
yes

Is Galen ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Galen ranked above Galen? Answer: no

Is Kestrel ranked above Einstein? Answer: no

Is Einstein ranked above Kest
```

### mean_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.51517834` → `0.51517834`. Sampling-policy probability: `1`.

```text
yes

Is Galen ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Galen ranked above Galen? Answer: no

Is Kestrel ranked above Einstein? Answer: no

Is Einstein ranked above Kest
```

## World 0, query 1 — sample211

Seed: 211; temperature: 0.7; maximum new tokens: 64.

### Common non-inline prompt

```text
Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Galen? Answer:
```

### Original memory facts (also provided in the inline prompt)

```text
World facts. The ranking is transitive.
- Galen is ranked above Kestrel.
- Kestrel is ranked above Fenn.
- Ione is ranked above Doran.
- Fenn is ranked above Ione.
- Hira is ranked above Galen.
```

### Counterfactual memory facts

```text
World facts. The ranking is transitive.
- Ione is ranked above Doran.
- Kestrel is ranked above Galen.
- Fenn is ranked above Ione.
- Hira is ranked above Kestrel.
- Galen is ranked above Fenn.
```

| Condition | Target | Finish | Tokens | Strict correct | First divergence from base | Initial max absolute Δlogit | Initial Δp(chosen) |
| --- | --- | --- | ---: | --- | --- | ---: | ---: |
| base | no | length | 64 | false | reference | 0 | 0 |
| base_inline | no | length | 64 | false | token 1 (step 0) | 0 | 0 |
| final_intact | no | length | 64 | false | token 29 (step 28) | 0.125 | 0.0573802007 |
| final_twin | yes | length | 64 | false | token 29 (step 28) | 0.1875 | -0.0551634999 |
| final_zero | no | length | 64 | false | none | 0 | 0 |
| mean_intact | no | eos | 37 | false | token 4 (step 3) | 0.125 | 0.0573800445 |
| mean_twin | yes | length | 64 | false | token 17 (step 16) | 0.1875 | -0.0551544597 |
| mean_zero | no | length | 64 | false | none | 0 | 0 |

### base

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.401221295` → `0.401221295`. Sampling-policy probability: `0.403523826`.

```text
no

1. Which of the following is NOT a type of Galen, the ancient physician?

a) A type of falcon
b) A type of kestrel
c) A type of mallet
d) A type of plant

Answer: c) A type of
```

### base_inline

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `18.625` → `18.625`. Native probability: `0.901914193` → `0.901914193`. Sampling-policy probability: `0.980685754`.

```text
yes

### Explanation

We know that Galen is ranked above Fenn, and Fenn is ranked above Ione, and Ione is ranked above Doran, and Kestrel is ranked above Doran. Therefore, Kestrel is ranked above Galen.

### Hint
```

### final_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.401221295` → `0.458601496`. Sampling-policy probability: `0.490284184`.

```text
no

1. Which of the following is NOT a type of Galen, the ancient physician?

a) A type of gallon
b) A type of sewing needle
c) A type of falcon
d) A type of computer

Answer: d) A type of
```

### final_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.625`. Native probability: `0.401221295` → `0.346057795`. Sampling-policy probability: `0.322185431`.

```text
no

1. Which of the following is NOT a type of Galen, the ancient physician?

a) A type of gallon
b) A type of sewing needle
c) A type of falcon
d) A type of computer

Answer: d) A type of
```

### final_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.401221295` → `0.401221295`. Sampling-policy probability: `0.403523826`.

```text
no

1. Which of the following is NOT a type of Galen, the ancient physician?

a) A type of falcon
b) A type of kestrel
c) A type of mallet
d) A type of plant

Answer: c) A type of
```

### mean_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.875`. Native probability: `0.401221295` → `0.458601339`. Sampling-policy probability: `0.490284181`.

```text
no

A Kestrel is a type of bird, while Galen is a physician. So, Kestrel is not ranked above Galen in any significant list.
```

### mean_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.625`. Native probability: `0.401221295` → `0.346066835`. Sampling-policy probability: `0.32218606`.

```text
no

1. Which of the following is NOT a type of Galen medication?
a) Herbal tincture
b) Synthetic compound
c) Scrub
d) Ointment

Answer: b) Synthetic compound

1. Which of the following is
```

### mean_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.75` → `16.75`. Native probability: `0.401221295` → `0.401221295`. Sampling-policy probability: `0.403523826`.

```text
no

1. Which of the following is NOT a type of Galen, the ancient physician?

a) A type of falcon
b) A type of kestrel
c) A type of mallet
d) A type of plant

Answer: c) A type of
```

## World 1, query 0 — greedy

Seed: 0; temperature: 0.0; maximum new tokens: 64.

### Common non-inline prompt

```text
Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Doran? Answer:
```

### Original memory facts (also provided in the inline prompt)

```text
World facts. The ranking is transitive.
- Aster is ranked above Eris.
- Doran is ranked above Aster.
- Joren is ranked above Kestrel.
- Kestrel is ranked above Doran.
- Beryl is ranked above Joren.
```

### Counterfactual memory facts

```text
World facts. The ranking is transitive.
- Aster is ranked above Eris.
- Beryl is ranked above Joren.
- Doran is ranked above Kestrel.
- Kestrel is ranked above Aster.
- Joren is ranked above Doran.
```

| Condition | Target | Finish | Tokens | Strict correct | First divergence from base | Initial max absolute Δlogit | Initial Δp(chosen) |
| --- | --- | --- | ---: | --- | --- | ---: | ---: |
| base | yes | length | 64 | false | reference | 0 | 0 |
| base_inline | yes | length | 64 | false | token 4 (step 3) | 0 | 0 |
| final_intact | yes | length | 64 | false | none | 0.125 | 0.0520364817 |
| final_twin | no | length | 64 | false | none | 0.25 | -0.0859805482 |
| final_zero | yes | length | 64 | false | none | 0 | 0 |
| mean_intact | yes | length | 64 | false | none | 0.125 | 0.0520365244 |
| mean_twin | no | length | 64 | false | none | 0.25 | -0.0859802405 |
| mean_zero | yes | length | 64 | false | none | 0 | 0 |

### base

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.564303309` → `0.564303309`. Sampling-policy probability: `1`.

```text
yes

Is Doran ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked above Doran? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked
```

### base_inline

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `18.25` → `18.25`. Native probability: `0.845203194` → `0.845203194`. Sampling-policy probability: `1`.

```text
yes

### Explanation

The ranking is transitive. If Kestrel is ranked above Doran, then Doran is ranked below Kestrel.

- Kestrel is ranked above Doran.
- Doran is ranked above Aster.
- Aster is ranked above
```

### final_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17.125`. Native probability: `0.564303309` → `0.616339791`. Sampling-policy probability: `1`.

```text
yes

Is Doran ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked above Doran? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked
```

### final_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `16.75`. Native probability: `0.564303309` → `0.478322761`. Sampling-policy probability: `1`.

```text
yes

Is Doran ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked above Doran? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked
```

### final_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.564303309` → `0.564303309`. Sampling-policy probability: `1`.

```text
yes

Is Doran ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked above Doran? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked
```

### mean_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17.125`. Native probability: `0.564303309` → `0.616339833`. Sampling-policy probability: `1`.

```text
yes

Is Doran ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked above Doran? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked
```

### mean_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `16.75`. Native probability: `0.564303309` → `0.478323068`. Sampling-policy probability: `1`.

```text
yes

Is Doran ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked above Doran? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked
```

### mean_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.564303309` → `0.564303309`. Sampling-policy probability: `1`.

```text
yes

Is Doran ranked above Kestrel? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked above Doran? Answer: no

Is Kestrel ranked above Kestrel? Answer: no

Is Doran ranked
```

## World 1, query 0 — sample211

Seed: 211; temperature: 0.7; maximum new tokens: 64.

### Common non-inline prompt

```text
Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Doran? Answer:
```

### Original memory facts (also provided in the inline prompt)

```text
World facts. The ranking is transitive.
- Aster is ranked above Eris.
- Doran is ranked above Aster.
- Joren is ranked above Kestrel.
- Kestrel is ranked above Doran.
- Beryl is ranked above Joren.
```

### Counterfactual memory facts

```text
World facts. The ranking is transitive.
- Aster is ranked above Eris.
- Beryl is ranked above Joren.
- Doran is ranked above Kestrel.
- Kestrel is ranked above Aster.
- Joren is ranked above Doran.
```

| Condition | Target | Finish | Tokens | Strict correct | First divergence from base | Initial max absolute Δlogit | Initial Δp(chosen) |
| --- | --- | --- | ---: | --- | --- | ---: | ---: |
| base | yes | length | 64 | false | reference | 0 | 0 |
| base_inline | yes | length | 64 | false | token 4 (step 3) | 0 | 0 |
| final_intact | yes | length | 64 | false | none | 0.125 | 0.0520364817 |
| final_twin | no | length | 64 | false | none | 0.25 | -0.0859805482 |
| final_zero | yes | length | 64 | false | none | 0 | 0 |
| mean_intact | yes | length | 64 | false | none | 0.125 | 0.0520365244 |
| mean_twin | no | length | 64 | false | none | 0.25 | -0.0859802405 |
| mean_zero | yes | length | 64 | false | none | 0 | 0 |

### base

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.564303309` → `0.564303309`. Sampling-policy probability: `0.655907649`.

```text
yes

Is Doran ranked below Kestrel? Answer: no

Is Kestrel ranked below itself? Answer: no

Is the rank of Kestrel greater than the number of countries in the world? Answer: no

Is the rank of Kestrel less than the number of
```

### base_inline

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `18.25` → `18.25`. Native probability: `0.845203194` → `0.845203194`. Sampling-policy probability: `0.962408272`.

```text
yes

## Problem 5: [Sudoku](https://projecteuler.net/problem=5)

The Board

The objective of Sudoku is to fill a 9×9 grid with digits so that each column, each row, and each of the nine 3
```

### final_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17.125`. Native probability: `0.564303309` → `0.616339791`. Sampling-policy probability: `0.727962206`.

```text
yes

Is Doran ranked below Kestrel? Answer: no

Is Kestrel ranked below itself? Answer: no

Is the rank of Kestrel greater than the number of countries in the world? Answer: no

Is the rank of Kestrel less than the number of
```

### final_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `16.75`. Native probability: `0.564303309` → `0.478322761`. Sampling-policy probability: `0.530695738`.

```text
yes

Is Doran ranked below Kestrel? Answer: no

Is Kestrel ranked below itself? Answer: no

Is the rank of Kestrel greater than the number of countries in the world? Answer: no

Is the rank of Kestrel less than the number of
```

### final_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.564303309` → `0.564303309`. Sampling-policy probability: `0.655907649`.

```text
yes

Is Doran ranked below Kestrel? Answer: no

Is Kestrel ranked below itself? Answer: no

Is the rank of Kestrel greater than the number of countries in the world? Answer: no

Is the rank of Kestrel less than the number of
```

### mean_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17.125`. Native probability: `0.564303309` → `0.616339833`. Sampling-policy probability: `0.727962206`.

```text
yes

Is Doran ranked below Kestrel? Answer: no

Is Kestrel ranked below itself? Answer: no

Is the rank of Kestrel greater than the number of countries in the world? Answer: no

Is the rank of Kestrel less than the number of
```

### mean_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `16.75`. Native probability: `0.564303309` → `0.478323068`. Sampling-policy probability: `0.530695745`.

```text
yes

Is Doran ranked below Kestrel? Answer: no

Is Kestrel ranked below itself? Answer: no

Is the rank of Kestrel greater than the number of countries in the world? Answer: no

Is the rank of Kestrel less than the number of
```

### mean_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17` → `17`. Native probability: `0.564303309` → `0.564303309`. Sampling-policy probability: `0.655907649`.

```text
yes

Is Doran ranked below Kestrel? Answer: no

Is Kestrel ranked below itself? Answer: no

Is the rank of Kestrel greater than the number of countries in the world? Answer: no

Is the rank of Kestrel less than the number of
```

## World 1, query 1 — greedy

Seed: 0; temperature: 0.0; maximum new tokens: 64.

### Common non-inline prompt

```text
Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Doran ranked above Kestrel? Answer:
```

### Original memory facts (also provided in the inline prompt)

```text
World facts. The ranking is transitive.
- Aster is ranked above Eris.
- Doran is ranked above Aster.
- Joren is ranked above Kestrel.
- Kestrel is ranked above Doran.
- Beryl is ranked above Joren.
```

### Counterfactual memory facts

```text
World facts. The ranking is transitive.
- Aster is ranked above Eris.
- Beryl is ranked above Joren.
- Doran is ranked above Kestrel.
- Kestrel is ranked above Aster.
- Joren is ranked above Doran.
```

| Condition | Target | Finish | Tokens | Strict correct | First divergence from base | Initial max absolute Δlogit | Initial Δp(chosen) |
| --- | --- | --- | ---: | --- | --- | ---: | ---: |
| base | no | length | 64 | false | reference | 0 | 0 |
| base_inline | no | length | 64 | false | token 4 (step 3) | 0 | 0 |
| final_intact | no | length | 64 | false | token 1 (step 0) | 0.1875 | 0.056586594 |
| final_twin | yes | length | 64 | false | none | 0.25 | 0.0852877664 |
| final_zero | no | length | 64 | false | none | 0 | 0 |
| mean_intact | no | length | 64 | false | token 1 (step 0) | 0.1875 | 0.0565865733 |
| mean_twin | yes | length | 64 | false | token 29 (step 28) | 0.25 | 0.0852878955 |
| mean_zero | no | length | 64 | false | none | 0 | 0 |

### base

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.625` → `16.625`. Native probability: `0.47179714` → `0.47179714`. Sampling-policy probability: `1`.

```text
yes

Is Kestrel ranked above Doran? Answer: no

Is Kestrel ranked above Eagle? Answer: no

Is Eagle ranked above Kestrel? Answer: no

Is Eagle ranked above Falcon? Answer: no

Is Falcon ranked above E
```

### base_inline

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17.625` → `17.625`. Native probability: `0.672002121` → `0.672002121`. Sampling-policy probability: `1`.

```text
yes

### Explanation

The ranking is transitive. If A is ranked above B and B is ranked above C, then A is ranked above C.

- Aster is ranked above Eris.
- Doran is ranked above Aster.
- Kestrel is ranked above
```

### final_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.5` → `16.625`. Native probability: `0.416359514` → `0.472946108`. Sampling-policy probability: `1`.

```text
no

### 1.1.2.

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Eagle?
```

### final_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.625` → `16.875`. Native probability: `0.47179714` → `0.557084906`. Sampling-policy probability: `1`.

```text
yes

Is Kestrel ranked above Doran? Answer: no

Is Kestrel ranked above Eagle? Answer: no

Is Eagle ranked above Kestrel? Answer: no

Is Eagle ranked above Falcon? Answer: no

Is Falcon ranked above E
```

### final_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.625` → `16.625`. Native probability: `0.47179714` → `0.47179714`. Sampling-policy probability: `1`.

```text
yes

Is Kestrel ranked above Doran? Answer: no

Is Kestrel ranked above Eagle? Answer: no

Is Eagle ranked above Kestrel? Answer: no

Is Eagle ranked above Falcon? Answer: no

Is Falcon ranked above E
```

### mean_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.5` → `16.625`. Native probability: `0.416359514` → `0.472946088`. Sampling-policy probability: `1`.

```text
no

### 1.1.2.

Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Kestrel ranked above Eagle?
```

### mean_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.625` → `16.875`. Native probability: `0.47179714` → `0.557085035`. Sampling-policy probability: `1`.

```text
yes

Is Kestrel ranked above Doran? Answer: no

Is Kestrel ranked above Eagle? Answer: yes

Is Eagle ranked above Kestrel? Answer: no

Is Eagle ranked above Falcon? Answer: no

Is Falcon ranked above E
```

### mean_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.625` → `16.625`. Native probability: `0.47179714` → `0.47179714`. Sampling-policy probability: `1`.

```text
yes

Is Kestrel ranked above Doran? Answer: no

Is Kestrel ranked above Eagle? Answer: no

Is Eagle ranked above Kestrel? Answer: no

Is Eagle ranked above Falcon? Answer: no

Is Falcon ranked above E
```

## World 1, query 1 — sample211

Seed: 211; temperature: 0.7; maximum new tokens: 64.

### Common non-inline prompt

```text
Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is Doran ranked above Kestrel? Answer:
```

### Original memory facts (also provided in the inline prompt)

```text
World facts. The ranking is transitive.
- Aster is ranked above Eris.
- Doran is ranked above Aster.
- Joren is ranked above Kestrel.
- Kestrel is ranked above Doran.
- Beryl is ranked above Joren.
```

### Counterfactual memory facts

```text
World facts. The ranking is transitive.
- Aster is ranked above Eris.
- Beryl is ranked above Joren.
- Doran is ranked above Kestrel.
- Kestrel is ranked above Aster.
- Joren is ranked above Doran.
```

| Condition | Target | Finish | Tokens | Strict correct | First divergence from base | Initial max absolute Δlogit | Initial Δp(chosen) |
| --- | --- | --- | ---: | --- | --- | ---: | ---: |
| base | no | length | 64 | false | reference | 0 | 0 |
| base_inline | no | length | 64 | false | token 1 (step 0) | 0 | 0 |
| final_intact | no | length | 64 | false | token 1 (step 0) | 0.1875 | 0.056586594 |
| final_twin | yes | length | 64 | false | token 1 (step 0) | 0.25 | 0.0852877664 |
| final_zero | no | length | 64 | false | none | 0 | 0 |
| mean_intact | no | length | 64 | false | token 1 (step 0) | 0.1875 | 0.0565865733 |
| mean_twin | yes | length | 64 | false | token 1 (step 0) | 0.25 | 0.0852878955 |
| mean_zero | no | length | 64 | false | none | 0 | 0 |

### base

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `2538`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `13.875` → `13.875`. Native probability: `0.0301609821` → `0.0301609821`. Sampling-policy probability: `0.0103833759`.

```text
No

Question 17:
Which of the following is the world's largest bird?

A) The bald eagle
B) The king penguin
C) The emu
D) The ostrich

Answer: D) The ostrich

Ex
```

### base_inline

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `17.625` → `17.625`. Native probability: `0.672002121` → `0.672002121`. Sampling-policy probability: `0.845789275`.

```text
yes

Some facts that support this answer:

- Kestrel is ranked below Doran.
- The ranking statement is transitive.
- The ranking of Aster is above Eris.
- The ranking of Doran is above Aster.
- The ranking of Joren is above
```

### final_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.5` → `16.625`. Native probability: `0.416359514` → `0.472946108`. Sampling-policy probability: `0.528496254`.

```text
no

### 17.22 If the player has a lot of experience, they will be able to answer the ranking question correctly.

This statement is true because the player has access to the world facts, which they can use to determine the correct answer to the ranking question.

### 
```

### final_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.625` → `16.875`. Native probability: `0.47179714` → `0.557084906`. Sampling-policy probability: `0.652605839`.

```text
yes

If you are stuck, find the answer key in the back of the book.

## 4. Identifying the Ranking Statement

### Reading Comprehension

Ranking statements are statements that compare two or more items in a particular order. They can be used to describe a
```

### final_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `2538`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `13.875` → `13.875`. Native probability: `0.0301609821` → `0.0301609821`. Sampling-policy probability: `0.0103833759`.

```text
No

Question 17:
Which of the following is the world's largest bird?

A) The bald eagle
B) The king penguin
C) The emu
D) The ostrich

Answer: D) The ostrich

Ex
```

### mean_intact

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `1476`; native top-1 changed: **true**.

Initial selected-token logit, same-prefix base → condition: `16.5` → `16.625`. Native probability: `0.416359514` → `0.472946088`. Sampling-policy probability: `0.528496253`.

```text
no

### 17.22 You are given a list of numbers. Use the world facts to decide whether the ranking statement is true. If it is false, answer no; if it is true, answer yes. Output exactly one lowercase word: no or yes.

Is the number 
```

### mean_twin

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `5849`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `16.625` → `16.875`. Native probability: `0.47179714` → `0.557085035`. Sampling-policy probability: `0.652605842`.

```text
yes

If you are stuck, find the answer key in the back of the book.

## 4. Identifying the Ranking Statement

### Reading Comprehension

Ranking statements are statements that compare two or more items in a particular order. They can be used to describe a
```

### mean_zero

Whole-answer parse: **unparseable**; lowercase compliant: **false**. Initial selected token ID: `2538`; native top-1 changed: **false**.

Initial selected-token logit, same-prefix base → condition: `13.875` → `13.875`. Native probability: `0.0301609821` → `0.0301609821`. Sampling-policy probability: `0.0103833759`.

```text
No

Question 17:
Which of the following is the world's largest bird?

A) The bald eagle
B) The king penguin
C) The emu
D) The ostrich

Answer: D) The ostrich

Ex
```
