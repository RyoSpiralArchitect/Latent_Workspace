# Native 7B canary prelaunch 01: superseded before CUDA/model dispatch

Source `94aa88a2f59c3ce2f5f3bd5d14c70e09cd71d41e`, 2026-10-20.
The first source passed 248 local tests (228 selected harness/engine plus
20 offline-verifier tests) and **228/228 Furnace CPU qualification tests**,
without failures/errors/skips. Pytest took 46.04 seconds; the wrapper receipt
records 49.438508 seconds. The unchanged [source seal](prelaunch01/SOURCE_SEAL.json)
and [CPU receipt](prelaunch01/qualification/cpu/FINISHED.json) are retained.

**CUDA qualification and every 7B role remain undispatched.** Before dispatch,
inspection of the installed Transformers 5.15 tokenizer API identified that
`apply_chat_template` defaults to `return_dict=True`; the first input encoder
assumed a list. Its tokenization stub did not exercise the real API. With that
default, iterating the result would produce mapping keys instead of token IDs.
This is a prelaunch code defect, not a model-capacity or learning failure.

The next source explicitly requests `return_dict=False`, checks integer IDs,
and adds a real locally initialized fast-tokenizer API regression without a
download. Qualification grows to 229 cases on each device; every original
case remains. It uses a fresh source/worktree/output destination. This record
and the original CPU artifacts must not be rewritten or relabelled.

No 7B loading, backward, update, generation, judge request or deletion occurred
in this prelaunch. The source is retained but not eligible for model dispatch.
