# V23 preparation 01: usable data and tiny instruments; outer receipt failed

**Bounded result:** the CPU and CUDA suites each passed **296/296**, and the
tokenizer-only data role completed and replayed. The outer dispatcher then
failed with `KeyError: 'pass_status'`. Its original **INCOMPLETE_NO_RETRY**
receipt is retained; this bundle is not relabeled as an all-green run. Offline
verification independently establishes the child results below. No role was
rerun, no 7B model was loaded, and no model weights or old bundles were changed.

Execution source: [`beda279e3d07e6565831aaceca58f080e1044e4a`](https://github.com/RyoSpiralArchitect/Latent_Workspace/commit/beda279e3d07e6565831aaceca58f080e1044e4a),
with [753 sealed source files](furnace/SOURCE_SEAL.json).
The [design contract](../../../docs/v23/PREPARATION_01.md) distinguishes
instrument qualification from a real-model gradient diagnosis or training.

## Exact scope and denominators

The old bank (8,192 rows / 1,024 groups) is unchanged. The additive bank contains
**4,096 raw rows / 512 groups**; combined raw supply is now 12,288 rows / 1,536
groups. This is a data-preparation count, not an increased training exposure.
Paired absent/unrelated controls contribute 1,024 duplicate rows in the new
bank. They are retained as aliases, not independent examples.

| New split | Groups | Raw rows | Unique rows | Model scores |
| --- | ---: | ---: | ---: | ---: |
| Train | 336 | 2,688 | 2,016 | 0 |
| Development | 56 | 448 | 336 | 0 |
| Confirmation | 56 | 448 | 336 | 0 |
| Whole-family 3-hop OOD | 64 | 512 | 384 | 0 |
| Total | 512 | 4,096 | 3,072 | 0 |

Each of the eight families has 512 raw rows. Identifier style is balanced:
2,048 independent-name rows and 2,048 shared-prefix rows. Twins share rendering
order; affected/unaffected questions read the same memory. Both worlds retain
two irrelevant distractor facts. The oracle, exact regeneration, twin direction,
controls, group completeness and split membership replay. Cross-split and
historical group/text/identifier overlaps are **zero**. All prior 1,024 groups,
including exposed diagnostic groups, are exclusion-only.

The old **linked_location family is now a training candidate** under fresh
identities. It will no longer be structure-OOD after training on this expansion.
The new whole-family holdout follows two ownership edges and then a location
edge. Reserved confirmation/OOD rows have been constructed and token-counted,
not model-evaluated, judged, or used to select a checkpoint.

See [oracle audit](furnace/raw/data/bank/AUDIT.json),
[bank manifest](furnace/raw/data/bank/MANIFEST.json), and the four split files:
[train](furnace/raw/data/bank/train.json.gz),
[development](furnace/raw/data/bank/dev.json.gz),
[confirmation](furnace/raw/data/bank/confirmation.json.gz),
[OOD](furnace/raw/data/bank/ood.json.gz).

## Token-defined objectives and resource boundaries

The pinned Mistral tokenizer preserves every original target token, including
EOS. There is no truncation. The 2,016 unique train rows contain **13,198**
supervised tokens, partitioned before model scoring:

| Oracle-defined contribution | Tokens |
| --- | ---: |
| Distinguishing identity prefix / complete numeric or abstention value | 6,425 |
| Remaining lexical copy | 2,549 |
| Whitespace-only / punctuation / EOS | 4,224 |
| Value–punctuation boundary mixed | 0 |

These are data counts, not measured gradients or reasoning gains. Shared-prefix
names often require the entire value to distinguish the answer, legitimately
leaving no later-copy segment. No universal first-two-token rule is used.

Maximum world query+answer length is 58 tokens; maximum memory length is 163.
**228 raw OOD rows** exceed the previously qualified 128-memory-token axis;
all are retained and flagged. No train/dev/confirmation row exceeds that axis.
Do not infer that the 3-hop panel is resource-qualified from short tests.

The frozen next-audit selection has **84 unique world rows from 14 train groups**
(one per family/style) plus **12** existing English no-memory training rows
(four each instruction/prose/code). Selection is by hash, not model behavior.
Maximum selected lengths are 105 memory / 128 query tokens. The preservation
subset has **932** supervised targets; full 32,768-vocabulary FP32 log-probability
targets would occupy **122,159,104 bytes = 116.5 MiB**, before metadata.

Those targets are **NOT_RUN**. The full-vocabulary KL primitive is tiny-tested,
not connected to the owner. No loss weight, learning rate, sampling mixture,
checkpoint policy or acceptance threshold changed. This small short-context
training subset is not a public capability or non-regression benchmark.

Sources: [preparation summary](furnace/raw/data/PREPARATION.json),
[selection and input hashes](furnace/raw/data/AUDIT_SELECTION.json),
[all row token counts](furnace/raw/data/TOKEN_COUNTS.json.gz),
[unique synthetic train tokens](furnace/raw/data/TRAIN_TOKENS.json.gz).

## Engineering verification and retained failure

| Scope at execution source | Result | Time |
| --- | --- | ---: |
| Furnace CPU selected suite | 296/296; no failures, errors or skips | 45.385 s |
| Furnace CUDA selected suite | 296/296; no failures, errors or skips | 51.042 s |
| Offline tokenizer/data role | Complete, bank replay passed | 4.310 s |
| Outer dispatch | INCOMPLETE_NO_RETRY; missing `pass_status` configuration key | 6.421 s |

CUDA tiny-suite peak allocation was **67,443,200 bytes / 64.319 MiB**, below
the frozen 4 GiB limit. This is not a 7B VRAM forecast. The suites retain original
native loss/update/save/fresh-process replay tests and add trace-on/off bitwise
logit/loss/gradient/RNG parity, state-gradient decomposition, W+Q+direct-R
attribution (including shared/tied weights), full-vocabulary KL, and streaming
objective dot products. Mistral, OLMo2, GPT-2 and scratch tiny hosts are covered.
BF16 independent-path sums are tolerance-qualified, not bitwise identities;
the no-op tracing parity itself is bitwise.

The reference parameter-path/conflict implementation traverses the graph per
parameter. It retains only a few one-tensor gradients at once, but is deliberately
slow and **not approved as an efficient or resource-qualified 7B algorithm**.
Build and qualify the spill-based implementation before using the fixed inputs.

The child [FINISHED](furnace/raw/data/FINISHED.json) and original outer
[FINISHED](furnace/raw/FINISHED.json) remain byte-for-byte intact. After completion,
the current plan gained the missing status key, and runner validation now rejects
a missing/mismatched key **before any work**. Three new local regression cases
pass. This is a post-run receipt-contract fix, not a rerun or a new GPU-qualified
source. The published source seal remains the historical execution source;
all qualified engine bytes still match it exactly.

Local development evidence is not conflated with Furnace: the initial 45-case
run caught one abstention-as-nonce classification bug (fixed before source
freeze); a wrong test filename collected zero tests; the wider Mac run was
193/195 because its two isolated subprocesses could not import
`typing_extensions`. The mandatory Furnace suites pass both replay tests.
The corrected local new-engine/architecture subset passes 57/57, and the
subsequent receipt fix passes 3/3. No environment packages were modified.

## Publication and next step

Furnace skill checks required an idle GPU, a separate source-pinned worktree,
the existing runtime, and preserved old workloads/bundles. Managed-runtime
doctor passed with its existing modelopt warning. Native PyTorch was used only
for the differentiable tiny graph/owner tests; the data role used an offline
tokenizer. No managed-runtime change or external model call occurred.

Remote run:
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v23-preparation01-20261022`.
The [publication manifest](furnace/PUBLICATION_MANIFEST.json) witnesses all
27 included files / 1,095,398 bytes, plus the single omitted private-input body
(12,907 bytes; SHA-256
`9e6bd21685cfcda0a56c9fb8d4f811cc178da1c5d324cd41cfe349375ae3285b`).
That file stays on Furnace because it contains source-owned preservation tokens.
Local replay verifies its hash against the independent role/selection receipts,
not its omitted content. The manifest itself is additional to the 27 files.

The snapshot at 2026-10-21T15:34:41.999266Z recorded an unchanged clean execution
worktree, no recorded workers or GPU compute clients, and 65.75 GiB free disk.
This is not permission to delete weights. All previous checkpoints remain.

Offline replay (no models/tokenizer/network):

```sh
python3 provenance/engineering/v23_preparation01_20261022/verify.py verify \
  --root provenance/engineering/v23_preparation01_20261022/furnace --repo .
```

The next bounded step is a scalable train-only gradient audit with a fresh
resource canary and the fixed base-target condition, then an independently
controlled preservation factor—not blind Q-gradient amplification or bundled
loss/data/LR changes. A full native-update recipe and exact new-objective restart
must qualify separately. Extra latent deliberation, ordinary-base floors and
release still need their own evidence. **FAIL / winner:none /
non_regression NOT_ESTABLISHED** remains unchanged.
