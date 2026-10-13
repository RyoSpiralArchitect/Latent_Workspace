# V15 native learner: literal generation bank

All strings below are JSON-escaped, preserving whitespace, casing and truncation.
Decode the JSON string to recover exact text; no output is repaired or completed.
Each sequence has a 16-token ceiling. `length` is not valid EOS termination.
The two worlds were exposed during training; these are not holdout results.

## reader / legacy / step 0 / w0 q0 / base

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / legacy / step 0 / w0 q0 / base_inline

[Raw receipt](raw/reader/legacy_0_generation.json); finish `eos`; strict correct `false`.

```json
"no"
```

## reader / legacy / step 0 / w0 q0 / workspace

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / legacy / step 0 / w0 q0 / twin

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / legacy / step 0 / w0 q0 / zero

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / legacy / step 0 / w0 q1 / base

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / legacy / step 0 / w0 q1 / base_inline

[Raw receipt](raw/reader/legacy_0_generation.json); finish `eos`; strict correct `false`.

```json
"Yes"
```

## reader / legacy / step 0 / w0 q1 / workspace

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / legacy / step 0 / w0 q1 / twin

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / legacy / step 0 / w0 q1 / zero

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / legacy / step 0 / w1 q0 / base

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / legacy / step 0 / w1 q0 / base_inline

[Raw receipt](raw/reader/legacy_0_generation.json); finish `eos`; strict correct `true`.

```json
"yes"
```

## reader / legacy / step 0 / w1 q0 / workspace

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / legacy / step 0 / w1 q0 / twin

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / legacy / step 0 / w1 q0 / zero

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / legacy / step 0 / w1 q1 / base

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / legacy / step 0 / w1 q1 / base_inline

[Raw receipt](raw/reader/legacy_0_generation.json); finish `eos`; strict correct `true`.

```json
"no"
```

## reader / legacy / step 0 / w1 q1 / workspace

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / legacy / step 0 / w1 q1 / twin

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / legacy / step 0 / w1 q1 / zero

[Raw receipt](raw/reader/legacy_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / legacy / step 8 / w0 q0 / base

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / legacy / step 8 / w0 q0 / base_inline

[Raw receipt](raw/reader/legacy_8_generation.json); finish `eos`; strict correct `false`.

```json
"no"
```

## reader / legacy / step 8 / w0 q0 / workspace

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## reader / legacy / step 8 / w0 q0 / twin

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## reader / legacy / step 8 / w0 q0 / zero

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / legacy / step 8 / w0 q1 / base

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / legacy / step 8 / w0 q1 / base_inline

[Raw receipt](raw/reader/legacy_8_generation.json); finish `eos`; strict correct `false`.

```json
"Yes"
```

## reader / legacy / step 8 / w0 q1 / workspace

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is a famous ancient physician, while Kestrel is a"
```

## reader / legacy / step 8 / w0 q1 / twin

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is a famous ancient physician, while Kestrel is a"
```

## reader / legacy / step 8 / w0 q1 / zero

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / legacy / step 8 / w1 q0 / base

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / legacy / step 8 / w1 q0 / base_inline

[Raw receipt](raw/reader/legacy_8_generation.json); finish `eos`; strict correct `true`.

```json
"yes"
```

## reader / legacy / step 8 / w1 q0 / workspace

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / legacy / step 8 / w1 q0 / twin

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / legacy / step 8 / w1 q0 / zero

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / legacy / step 8 / w1 q1 / base

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / legacy / step 8 / w1 q1 / base_inline

[Raw receipt](raw/reader/legacy_8_generation.json); finish `eos`; strict correct `true`.

```json
"no"
```

## reader / legacy / step 8 / w1 q1 / workspace

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / legacy / step 8 / w1 q1 / twin

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / legacy / step 8 / w1 q1 / zero

[Raw receipt](raw/reader/legacy_8_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / query_modulated / step 0 / w0 q0 / base

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / query_modulated / step 0 / w0 q0 / base_inline

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `eos`; strict correct `false`.

```json
"no"
```

## reader / query_modulated / step 0 / w0 q0 / workspace

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / query_modulated / step 0 / w0 q0 / twin

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / query_modulated / step 0 / w0 q0 / zero

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / query_modulated / step 0 / w0 q1 / base

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / query_modulated / step 0 / w0 q1 / base_inline

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `eos`; strict correct `false`.

```json
"Yes"
```

## reader / query_modulated / step 0 / w0 q1 / workspace

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / query_modulated / step 0 / w0 q1 / twin

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / query_modulated / step 0 / w0 q1 / zero

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / query_modulated / step 0 / w1 q0 / base

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / query_modulated / step 0 / w1 q0 / base_inline

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `eos`; strict correct `true`.

```json
"yes"
```

## reader / query_modulated / step 0 / w1 q0 / workspace

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / query_modulated / step 0 / w1 q0 / twin

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / query_modulated / step 0 / w1 q0 / zero

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / query_modulated / step 0 / w1 q1 / base

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / query_modulated / step 0 / w1 q1 / base_inline

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `eos`; strict correct `true`.

```json
"no"
```

## reader / query_modulated / step 0 / w1 q1 / workspace

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / query_modulated / step 0 / w1 q1 / twin

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / query_modulated / step 0 / w1 q1 / zero

[Raw receipt](raw/reader/query_modulated_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / query_modulated / step 8 / w0 q0 / base

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / query_modulated / step 8 / w0 q0 / base_inline

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `eos`; strict correct `false`.

```json
"no"
```

## reader / query_modulated / step 8 / w0 q0 / workspace

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## reader / query_modulated / step 8 / w0 q0 / twin

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## reader / query_modulated / step 8 / w0 q0 / zero

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## reader / query_modulated / step 8 / w0 q1 / base

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / query_modulated / step 8 / w0 q1 / base_inline

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `eos`; strict correct `false`.

```json
"Yes"
```

## reader / query_modulated / step 8 / w0 q1 / workspace

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is a famous ancient physician, while Kestrel is a"
```

## reader / query_modulated / step 8 / w0 q1 / twin

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is a famous ancient physician, while Kestrel is a"
```

## reader / query_modulated / step 8 / w0 q1 / zero

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## reader / query_modulated / step 8 / w1 q0 / base

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / query_modulated / step 8 / w1 q0 / base_inline

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `eos`; strict correct `true`.

```json
"yes"
```

## reader / query_modulated / step 8 / w1 q0 / workspace

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / query_modulated / step 8 / w1 q0 / twin

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / query_modulated / step 8 / w1 q0 / zero

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## reader / query_modulated / step 8 / w1 q1 / base

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / query_modulated / step 8 / w1 q1 / base_inline

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `eos`; strict correct `true`.

```json
"no"
```

## reader / query_modulated / step 8 / w1 q1 / workspace

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / query_modulated / step 8 / w1 q1 / twin

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## reader / query_modulated / step 8 / w1 q1 / zero

[Raw receipt](raw/reader/query_modulated_8_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / frozen / step 0 / w0 q0 / base

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / frozen / step 0 / w0 q0 / base_inline

[Raw receipt](raw/full/frozen_0_generation.json); finish `eos`; strict correct `false`.

```json
"no"
```

## full / frozen / step 0 / w0 q0 / workspace

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / frozen / step 0 / w0 q0 / twin

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / frozen / step 0 / w0 q0 / zero

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / frozen / step 0 / w0 q1 / base

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / frozen / step 0 / w0 q1 / base_inline

[Raw receipt](raw/full/frozen_0_generation.json); finish `eos`; strict correct `false`.

```json
"Yes"
```

## full / frozen / step 0 / w0 q1 / workspace

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / frozen / step 0 / w0 q1 / twin

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / frozen / step 0 / w0 q1 / zero

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / frozen / step 0 / w1 q0 / base

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / frozen / step 0 / w1 q0 / base_inline

[Raw receipt](raw/full/frozen_0_generation.json); finish `eos`; strict correct `true`.

```json
"yes"
```

## full / frozen / step 0 / w1 q0 / workspace

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / frozen / step 0 / w1 q0 / twin

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / frozen / step 0 / w1 q0 / zero

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / frozen / step 0 / w1 q1 / base

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / frozen / step 0 / w1 q1 / base_inline

[Raw receipt](raw/full/frozen_0_generation.json); finish `eos`; strict correct `true`.

```json
"no"
```

## full / frozen / step 0 / w1 q1 / workspace

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / frozen / step 0 / w1 q1 / twin

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / frozen / step 0 / w1 q1 / zero

[Raw receipt](raw/full/frozen_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / frozen / step 2 / w0 q0 / base

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / frozen / step 2 / w0 q0 / base_inline

[Raw receipt](raw/full/frozen_2_generation.json); finish `eos`; strict correct `false`.

```json
"no"
```

## full / frozen / step 2 / w0 q0 / workspace

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## full / frozen / step 2 / w0 q0 / twin

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## full / frozen / step 2 / w0 q0 / zero

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / frozen / step 2 / w0 q1 / base

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / frozen / step 2 / w0 q1 / base_inline

[Raw receipt](raw/full/frozen_2_generation.json); finish `eos`; strict correct `false`.

```json
"Yes"
```

## full / frozen / step 2 / w0 q1 / workspace

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / frozen / step 2 / w0 q1 / twin

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / frozen / step 2 / w0 q1 / zero

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / frozen / step 2 / w1 q0 / base

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / frozen / step 2 / w1 q0 / base_inline

[Raw receipt](raw/full/frozen_2_generation.json); finish `eos`; strict correct `true`.

```json
"yes"
```

## full / frozen / step 2 / w1 q0 / workspace

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / frozen / step 2 / w1 q0 / twin

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / frozen / step 2 / w1 q0 / zero

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / frozen / step 2 / w1 q1 / base

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / frozen / step 2 / w1 q1 / base_inline

[Raw receipt](raw/full/frozen_2_generation.json); finish `eos`; strict correct `true`.

```json
"no"
```

## full / frozen / step 2 / w1 q1 / workspace

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / frozen / step 2 / w1 q1 / twin

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / frozen / step 2 / w1 q1 / zero

[Raw receipt](raw/full/frozen_2_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / full / step 0 / w0 q0 / base

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / full / step 0 / w0 q0 / base_inline

[Raw receipt](raw/full/full_0_generation.json); finish `eos`; strict correct `false`.

```json
"no"
```

## full / full / step 0 / w0 q0 / workspace

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / full / step 0 / w0 q0 / twin

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / full / step 0 / w0 q0 / zero

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"No (as Galen is a historical figure, a physician, and Kest"
```

## full / full / step 0 / w0 q1 / base

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / full / step 0 / w0 q1 / base_inline

[Raw receipt](raw/full/full_0_generation.json); finish `eos`; strict correct `false`.

```json
"Yes"
```

## full / full / step 0 / w0 q1 / workspace

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / full / step 0 / w0 q1 / twin

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / full / step 0 / w0 q1 / zero

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"yes (Galen is not ranked, as he is a historical figure, not"
```

## full / full / step 0 / w1 q0 / base

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / full / step 0 / w1 q0 / base_inline

[Raw receipt](raw/full/full_0_generation.json); finish `eos`; strict correct `true`.

```json
"yes"
```

## full / full / step 0 / w1 q0 / workspace

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / full / step 0 / w1 q0 / twin

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / full / step 0 / w1 q0 / zero

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"Yes, Kestrel is not a person or place, it's a"
```

## full / full / step 0 / w1 q1 / base

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / full / step 0 / w1 q1 / base_inline

[Raw receipt](raw/full/full_0_generation.json); finish `eos`; strict correct `true`.

```json
"no"
```

## full / full / step 0 / w1 q1 / workspace

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / full / step 0 / w1 q1 / twin

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / full / step 0 / w1 q1 / zero

[Raw receipt](raw/full/full_0_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / full / step 2 / w0 q0 / base

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## full / full / step 2 / w0 q0 / base_inline

[Raw receipt](raw/full/full_2_generation.json); finish `eos`; strict correct `false`.

```json
"no"
```

## full / full / step 2 / w0 q0 / workspace

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## full / full / step 2 / w0 q0 / twin

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## full / full / step 2 / w0 q0 / zero

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen was a Roman physician, and Kestrel is a fict"
```

## full / full / step 2 / w0 q1 / base

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen is a well-known ancient physician, while Kestrel"
```

## full / full / step 2 / w0 q1 / base_inline

[Raw receipt](raw/full/full_2_generation.json); finish `eos`; strict correct `false`.

```json
"yes"
```

## full / full / step 2 / w0 q1 / workspace

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen is a well-known ancient physician, while Kestrel"
```

## full / full / step 2 / w0 q1 / twin

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen is a well-known ancient physician, while Kestrel"
```

## full / full / step 2 / w0 q1 / zero

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (Galen is a well-known ancient physician, while Kestrel"
```

## full / full / step 2 / w1 q0 / base

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"yes (based on the data from World Facts, Kestrel is a"
```

## full / full / step 2 / w1 q0 / base_inline

[Raw receipt](raw/full/full_2_generation.json); finish `eos`; strict correct `true`.

```json
"yes"
```

## full / full / step 2 / w1 q0 / workspace

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"yes (based on the data from World Facts, Kestrel is a"
```

## full / full / step 2 / w1 q0 / twin

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"yes (based on the data from World Facts, Kestrel is a"
```

## full / full / step 2 / w1 q0 / zero

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"yes (based on the data from World Facts, Kestrel is a"
```

## full / full / step 2 / w1 q1 / base

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / full / step 2 / w1 q1 / base_inline

[Raw receipt](raw/full/full_2_generation.json); finish `eos`; strict correct `true`.

```json
"no"
```

## full / full / step 2 / w1 q1 / workspace

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / full / step 2 / w1 q1 / twin

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```

## full / full / step 2 / w1 q1 / zero

[Raw receipt](raw/full/full_2_generation.json); finish `length`; strict correct `false`.

```json
"no (assuming we're referring to fictional characters from the \"G"
```
