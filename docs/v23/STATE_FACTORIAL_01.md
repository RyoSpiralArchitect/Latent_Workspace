# V23 diagnostic 01: separate the question from the reader

Frozen **V22 step-32** analysis, not V23 training or release. This follows the
[V22 writer factorial](../../provenance/pilots/v22_memory_causality01_20261021/README.md)
and [roadmap](ROADMAP_TO_1_0.md). The former reader label included both lower
question encoding and upper reading. The new additive, architecture-independent
[state interface](../../src/latent_workspace/state_factorial.py) separates them
without changing the differentiable learner or historical execution sources.

## Three intervention factors

- **W:** base/V22 memory token encoding below cut 4.
- **Q:** base/V22 question **and fixed answer-prefix** encoding below cut 4.
- **R:** base/V22 layers 4 onward, final normalization and entire native head.

Use all 96 exposed world rows / 16 groups and every gold next-token position:
623 positions, including later symbol-copy tokens and EOS. For 559 nonempty
positions use eight cells; for 64 absent-memory positions use four Q/R cells.
The resulting 4,728 cells are not independent tasks. All 570 exposed MMLU
questions receive four no-memory Q/R cells (2,280). These are retention
diagnostics, not fresh non-regression confirmation or training examples.

Every cell uses the *same cropped token prefix*, without future answer tokens
or oracle-length padding. Q therefore includes previously fixed answer tokens,
not only the initial natural-language question. At each affected twin's first
different answer token, retain donor-minus-original logits under the common
prefix. No two-choice output restriction is applied. Exact-copy positions and
first-identity positions are reported separately; teacher-forced next-token
agreement is not new free-generation accuracy.

## Qualification and execution

Plan: [STATE_FACTORIAL_01.json](../../configs/v23/STATE_FACTORIAL_01.json).
Fresh-process roles: `base` writes its bank and self-cell references; `v22`
writes its bank and evaluates four W/Q cells per nonempty prefix; `base_cross`
loads base anew and evaluates the other reader's four cells. Empty inputs have
no artificial writer factor. Base self cells are repeated as reload controls:
5,351 world / 2,850 MMLU journal entries include 623/570 duplicate references.

First qualify 216 selected tests on CPU and CUDA, each limited to 4 GiB and
900 s. Four tiny host architectures, BF16/FP32, empty/nonempty self-parity,
independent query/memory interventions, invalid states, exclusive bank writes,
changed-input/body rejection and the actual three-role runner are covered.
At real-model scale, require full-logit native/split self equality at all 1,193
prefixes for both hosts; repeat all 1,193 base self endpoints exactly. Also
require the previous 1,246 cropped world logit hashes and original MMLU scores
to replay. Any mismatch, failed qualification or resource/source guard stops
the trial. No retries or changed thresholds inside the trial.

Only one BF16 7B model is resident at a time. Pinned native PyTorch is needed:
the managed TRT serving interface cannot exchange these cut states or restore
the complete native owner. Its doctor is checked; no managed environment is
modified. V22 is restored with the complete original owner/fingerprint before
the explicit frozen inference transition. Head precision/shape, tokenization,
eager attention and no-cache semantics are unchanged.

Two CPU BF16 activation banks require **less than 7 GiB combined**, conservatively
about 6.5 GiB before deduplication, not new weights. Keep them on Furnace with
full byte/tensor hashes and token-key manifests; publish small receipts and
scores, not multi-gigabyte tensors, to Git. Verify them remotely before
publication and explicitly distinguish remote-only artifacts. No file deletion.
Envelope: 31 GiB GPU admission / 30.5 cap / 0.75 free floor, host 100/24 GiB,
disk 50 GiB floor, two CPU threads, four hours per role. Current admission was
GPU idle, host 119 GiB available, approximately 75 GB disk free.

## Interpretation boundaries

Report all W/Q/R cells, paired repairs/losses, margins and interactions. A
hybrid improvement is a diagnostic clue, not a checkpoint-selection rule.
Q/W share embeddings and lower-layer weights in the real learner: intervention
independence does not create parameter-group independence. R still combines
attention/MLPs/norm/head; this experiment does not locate a particular layer.
No claim of deliberation, multi-turn retention or quality preference follows
from this factorial. Preserve **FAIL / winner:none / non_regression
NOT_ESTABLISHED** and all original results. Zero training, new generations,
judges, checkpoints, deletion, PR/merge or release in this trial.
