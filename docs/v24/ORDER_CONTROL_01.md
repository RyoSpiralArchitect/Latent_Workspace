# V24 O1: output-order data pilot before another full update

Prepared 2026-11-14 from the [completed FT04/readout result](../../provenance/engineering/v24_recruitment_readout01_20261027/RESULTS_README.md)
and [next-factor decision](NEXT_ENGINE_FACTOR.md). This isolates **O: JSON
target order**. It does not implement S, change the native learner, run 7B,
replace a checkpoint or promote a quality claim.

## Frozen scope

The additive [projection](../../src/latent_workspace/recruitment_order.py)
retains the exact original raw records, executable oracle, train/dev split,
question, external M and inline/workspace routes. With `answer_first`, its
projected rows must exactly reproduce the sealed V24 private token arrays.
With `steps_first`, only present reasoning train/dev targets serialize the
checked `steps` before `answer`; absent/unrelated `answer:null`, all world
targets and all confirmation exclusions are unchanged. The old query-only
causal labels remain on target tokens only. This tests target-order exposure,
not a latent internal S or a new capability.

The [data-only plan](../../configs/v24/ORDER_CONTROL_01.json) pins the V24
bank manifest, public synthetic bank and 32-window schedule. The
[offline probe](../../scripts/probe_v24_order_control.py) checks the complete
original file manifest, tokenizer files/chat template, exact historical
projection, route parity, all target masks, and scheduled exposure before
writing one exclusive result receipt. It forbids model forwards, updates,
saves, judge requests and deletions. The old `FAIL / winner:none /
non_regression NOT_ESTABLISHED` ceiling is unchanged. Its 10-GiB disk
admission is only for this small data-only receipt; it does **not** replace
the 50-GiB floor or the real-save forecast for 7B.

## Exploratory tokenizer observation, before the sealed probe

The pinned Furnace tokenizer was used without a model call or download to
compare compact JSON field orders on the existing **768 raw train/present
reasoning rows**. For arithmetic and register-trace, 512 rows each gain one
token under steps-first; all 256 stable-filter rows retain their token count.
The already frozen 32-window schedule contains 538 row occurrences / 21,112
supervised targets. Of these, 63 occurrences are arithmetic/register present
rows, so the same schedule would expose **21,175** steps-first targets: a
predeclared +63, approximately 0.30%. The data-only probe must replay these
counts exactly; otherwise it fails and no training proceeds.

This is a real tokenizer/serialization effect, not evidence of a learned
benefit. It prevents calling a later 7B comparison *perfectly equal-token* by
changing key order alone. Do not mask a gold-content token, quietly rebalance
the task mixture, or claim that an extra syntax token is irrelevant. A future
learner contrast must either freeze a justified budget-matching control or
carry this measured difference as a stated confound and qualify its claims
accordingly. The existing six exposed development groups are not a fresh
selection or confirmation panel.

## Gates before a scientific 7B O contrast

1. Commit and seal this source, then run the data-only probe once in a new
   Furnace checkout/output. Retain either a completed receipt or a terminal
   failure without overwriting it. Unit tests with a tokenizer double are
   engineering checks; the pinned tokenizer receipt is the actual token
   denominator.
2. Resolve the +63-token budget explicitly, freeze the new source-group
   split and quality panel, and preserve the same initialization, optimizer,
   precision, schedule policy, update count, storage admission, no-retry rule
   and base-preservation floors. O and S remain separate factors. No new
   confirmation leakage or gold answer in a claimed pre-answer result.
3. On 2026-11-14 the Furnace GPU was idle, but the filesystem had only
   **21,263,790,080 free bytes (19.803 GiB)**. Thus the old 50-GiB floor
   fails before even forecasting a new 29-GB final checkpoint. No 7B run may
   start at this state. See the [read-only capacity candidates](../../provenance/inventory/v24_order_control_capacity_20261114/README.md).
4. Once storage and scientific controls qualify, test tiny CPU/CUDA
   update/save/fresh-process replay before any full update. Compare unassisted
   affected target answer **and** independently checked generated steps; keep
   absent, unrelated, same-operation twins, no-memory base tasks and the
   published V23/V24 comparison endpoints separate. No judge or release
   decision follows from the data-only pilot.
