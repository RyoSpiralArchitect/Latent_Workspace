# Readout PR review: provenance correction and the next migration gate

Client date: 2026-10-13. Review of
[`1e95284054cb3e846bd51b02099f81b9702f5b74`](https://github.com/RyoSpiralArchitect/Latent_Workspace/pull/11).
This is an additive post-result note, not a replacement execution receipt.

## External review finding

The completed [Codex review](https://github.com/RyoSpiralArchitect/Latent_Workspace/pull/11#pullrequestreview-5504602111)
reported one [P2 finding](https://github.com/RyoSpiralArchitect/Latent_Workspace/pull/11#discussion_r4259503127):
the historical audit's `--untracked-files=no` check cannot exclude importable
untracked source. With a plain `python scripts/...` launch, a `scripts/torch.py`
could execute before the in-script check. Enumerated source hashes do not close
that gap. We accept the finding. It does **not** prove such contamination
occurred, but the historical receipt is not proof that it was impossible.

The old audit source, source seal and all measured rows remain byte-for-byte
unchanged. Their full-logit replay is still replay evidence; it must not be
retrospectively upgraded to a stronger pre-import cleanliness guarantee.
The old direct launch command is a historical record, not the approved template
for a new run. No old run is repeated to manufacture a replacement receipt.

## Additive correction for future execution

`scripts/run_source_sealed.py` is a standard-library, **pre-import** launcher.
It requires isolated Python, checks tracked edits and **all untracked files**,
checks ignored importable files and symlinks under repository import roots,
and binds both itself and the selected entry to a committed source seal. It
launches isolated Python with a fresh bytecode-cache prefix, so old repository
bytecode cannot bypass the source check. The new runner must include this
launcher in its own new seal; old source seals are not edited or reused.

```sh
python -I scripts/run_source_sealed.py \
  --seal /absolute/path/to/new-run-source-seal.json \
  --entry scripts/the_new_qualified_runner.py --check-only
```

The named runner is deliberately a placeholder: this does not authorize or
start another experiment. A real invocation requires its own fixed entry,
inputs, budget, source commit and seal. The interpreter and installed packages
are still a separately qualified runtime, not sandboxed or cryptographically
attested by this guard. Exclusive ownership of the execution checkout remains
required; this is not protection from a concurrent malicious writer.

## Follow-up qualification, not a precision or semantic change

The next owner must bind the native adapter, context-feature binding, native
dtype, module modes, buffer/schema identities, gradient-checkpointing policy,
optimizer policy, original-reference identity and **autograd graph-sharing
policy**. Matching forward values and an isolated answer/EOS backward is not
enough to certify a complete pair objective or next update.

The local pre-migration investigation has already reproduced a reason for this
last requirement: the old pair objective shares one live question-prefix graph
across intact/twin/unrelated outputs. Calling the outer model independently for
every condition reproduces scalar losses but can change native gradient
rounding/order under full updates. This is our separate local analysis, **not a
second finding by the external reviewer**. It needs its own persistent test and
matched one-window/next-update evidence before migration can be called exact.

No semantic promotion, threshold relaxation, new generations or judge calls
follow from review completion. **Old FAIL / winner:none / original-base
non-regression NOT_ESTABLISHED remain unchanged.** The PR stays draft and is
not merged by this task.
