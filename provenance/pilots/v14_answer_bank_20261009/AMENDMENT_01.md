# Pre-answer compatibility amendment

The first execution at commit `78aea23` stopped before generating any answer.
Its original plan and `attempt_01_failed/{STARTED,FAILED}.json` are retained.
The pinned Transformers 5.15 tokenizer returns a `BatchEncoding` by default
from `apply_chat_template`, while the runner expected a list of token IDs.

An offline check on the pinned tokenizer found that explicit `return_dict=False`
returns exactly the same token IDs as the default object's `input_ids` for all
32 ordinary and inline prompts (lengths 32 to 183). This is a return-container compatibility fix, not a prompt,
sampling, weight, or evaluation change. No generated answer was inspected or
used to select the repair.

The retry uses a separately frozen `ANSWER_BANK_RETRY_PLAN.json` and a new output
directory. Cases, model revision, checkpoints, generation settings, judge and
comparison grid are unchanged. The original output is neither overwritten nor
deleted. The runner accepts an explicit plan path so both executions remain
bound to their own plan file and source commit.

All costs in this artifact mean usage-based undiscounted estimates. The actual
invoice amount is unknown. Ordinal score summaries are descriptive, restricted
to changed-answer pairs, and can include scores from order-conflicted pairs;
they are not a count of order-consistent preferences.
