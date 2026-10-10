# V15.5 native learner: all 80 bounded greedy outputs

Exposed engineering cases only. Both steps and all conditions are retained.
Strict whole-answer scoring, 16-token budget; old gate remains FAIL.

## native_answer / step 0 / w0 q0 / base

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer / step 0 / w0 q0 / base_inline

Strict correct: False; finish: eos; target: 1; tokens: 2.

```text
no
```

## native_answer / step 0 / w0 q0 / workspace

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer / step 0 / w0 q0 / twin

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer / step 0 / w0 q0 / zero

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer / step 0 / w0 q1 / base

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer / step 0 / w0 q1 / base_inline

Strict correct: False; finish: eos; target: 0; tokens: 2.

```text
Yes
```

## native_answer / step 0 / w0 q1 / workspace

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer / step 0 / w0 q1 / twin

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer / step 0 / w0 q1 / zero

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer / step 0 / w1 q0 / base

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer / step 0 / w1 q0 / base_inline

Strict correct: True; finish: eos; target: 1; tokens: 2.

```text
yes
```

## native_answer / step 0 / w1 q0 / workspace

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer / step 0 / w1 q0 / twin

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer / step 0 / w1 q0 / zero

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer / step 0 / w1 q1 / base

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer / step 0 / w1 q1 / base_inline

Strict correct: True; finish: eos; target: 0; tokens: 2.

```text
no
```

## native_answer / step 0 / w1 q1 / workspace

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer / step 0 / w1 q1 / twin

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer / step 0 / w1 q1 / zero

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer / step 8 / w0 q0 / base

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer / step 8 / w0 q0 / base_inline

Strict correct: False; finish: eos; target: 1; tokens: 2.

```text
no
```

## native_answer / step 8 / w0 q0 / workspace

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
no (Galen was a Roman physician, and Kestrel is a fict
```

## native_answer / step 8 / w0 q0 / twin

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (Galen was a Roman physician, and Kestrel is a fict
```

## native_answer / step 8 / w0 q0 / zero

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer / step 8 / w0 q1 / base

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer / step 8 / w0 q1 / base_inline

Strict correct: False; finish: eos; target: 0; tokens: 2.

```text
Yes
```

## native_answer / step 8 / w0 q1 / workspace

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is a famous ancient physician, while Kestrel is a
```

## native_answer / step 8 / w0 q1 / twin

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
yes (Galen is a famous ancient physician, while Kestrel is a
```

## native_answer / step 8 / w0 q1 / zero

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer / step 8 / w1 q0 / base

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer / step 8 / w1 q0 / base_inline

Strict correct: True; finish: eos; target: 1; tokens: 2.

```text
yes
```

## native_answer / step 8 / w1 q0 / workspace

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer / step 8 / w1 q0 / twin

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer / step 8 / w1 q0 / zero

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer / step 8 / w1 q1 / base

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer / step 8 / w1 q1 / base_inline

Strict correct: True; finish: eos; target: 0; tokens: 2.

```text
no
```

## native_answer / step 8 / w1 q1 / workspace

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer / step 8 / w1 q1 / twin

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer / step 8 / w1 q1 / zero

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer_eos / step 0 / w0 q0 / base

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer_eos / step 0 / w0 q0 / base_inline

Strict correct: False; finish: eos; target: 1; tokens: 2.

```text
no
```

## native_answer_eos / step 0 / w0 q0 / workspace

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer_eos / step 0 / w0 q0 / twin

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer_eos / step 0 / w0 q0 / zero

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer_eos / step 0 / w0 q1 / base

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer_eos / step 0 / w0 q1 / base_inline

Strict correct: False; finish: eos; target: 0; tokens: 2.

```text
Yes
```

## native_answer_eos / step 0 / w0 q1 / workspace

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer_eos / step 0 / w0 q1 / twin

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer_eos / step 0 / w0 q1 / zero

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer_eos / step 0 / w1 q0 / base

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer_eos / step 0 / w1 q0 / base_inline

Strict correct: True; finish: eos; target: 1; tokens: 2.

```text
yes
```

## native_answer_eos / step 0 / w1 q0 / workspace

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer_eos / step 0 / w1 q0 / twin

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer_eos / step 0 / w1 q0 / zero

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer_eos / step 0 / w1 q1 / base

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer_eos / step 0 / w1 q1 / base_inline

Strict correct: True; finish: eos; target: 0; tokens: 2.

```text
no
```

## native_answer_eos / step 0 / w1 q1 / workspace

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer_eos / step 0 / w1 q1 / twin

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer_eos / step 0 / w1 q1 / zero

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer_eos / step 8 / w0 q0 / base

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer_eos / step 8 / w0 q0 / base_inline

Strict correct: False; finish: eos; target: 1; tokens: 2.

```text
no
```

## native_answer_eos / step 8 / w0 q0 / workspace

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer_eos / step 8 / w0 q0 / twin

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer_eos / step 8 / w0 q0 / zero

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
No (as Galen is a historical figure, a physician, and Kest
```

## native_answer_eos / step 8 / w0 q1 / base

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer_eos / step 8 / w0 q1 / base_inline

Strict correct: False; finish: eos; target: 0; tokens: 2.

```text
Yes
```

## native_answer_eos / step 8 / w0 q1 / workspace

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer_eos / step 8 / w0 q1 / twin

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer_eos / step 8 / w0 q1 / zero

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
yes (Galen is not ranked, as he is a historical figure, not
```

## native_answer_eos / step 8 / w1 q0 / base

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer_eos / step 8 / w1 q0 / base_inline

Strict correct: True; finish: eos; target: 1; tokens: 2.

```text
yes
```

## native_answer_eos / step 8 / w1 q0 / workspace

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer_eos / step 8 / w1 q0 / twin

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer_eos / step 8 / w1 q0 / zero

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
Yes, Kestrel is not a person or place, it's a
```

## native_answer_eos / step 8 / w1 q1 / base

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer_eos / step 8 / w1 q1 / base_inline

Strict correct: True; finish: eos; target: 0; tokens: 2.

```text
no
```

## native_answer_eos / step 8 / w1 q1 / workspace

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer_eos / step 8 / w1 q1 / twin

Strict correct: False; finish: length; target: 1; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```

## native_answer_eos / step 8 / w1 q1 / zero

Strict correct: False; finish: length; target: 0; tokens: 16.

```text
no (assuming we're referring to fictional characters from the "G
```
