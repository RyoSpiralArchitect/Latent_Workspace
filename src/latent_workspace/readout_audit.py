"""Portable, observational native readout: fixed tokens versus free trajectories.

No candidate head, forced generation, new loss, cache, or hidden-state feedback.
All probabilities are native full-vocabulary FP32 log-softmax, BEFORE sampling
temperature/top-p. Token roles come from a predeclared reference, never from a
model's observed error. A 'content' token is not itself proof of true reasoning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import execution as ex
from . import native_evaluation as ev

SCHEMA = "ltws-native-readout-audit-v1"
STAGES = frozenset({"content", "copy", "binding", "format", "stop", "unclassified"})


def _ids(values, name, *, empty=False):
    ex.require(type(values) is tuple, f"Immutable {name} token tuple required")
    ex.require(empty or bool(values), f"Nonempty {name}")
    ex.require(all(type(x) is int and x >= 0 for x in values), f"Nonnegative {name} token IDs")


@dataclass(frozen=True)
class ReadoutSpec:
    """One reference trajectory. Multi-token answers keep every causal position.

    Stages annotate the *next target token*, not its predecessor. Probe tokens
    are observations only; they never restrict vocabulary or define an oracle.
    IDs must already be encoded under a pinned tokenizer with a stable boundary.
    """

    prefix: tuple[int, ...]
    continuation: tuple[int, ...]
    stages: tuple[str, ...]
    eos: int
    probes: tuple[int, ...] = ()

    def __post_init__(self):
        _ids(self.prefix, "prefix")
        _ids(self.continuation, "continuation")
        _ids(self.probes, "probe", empty=True)
        ex.require(type(self.eos) is int and self.eos >= 0, "Nonnegative EOS token ID")
        ex.require(len(set(self.probes)) == len(self.probes), "Unique probe token IDs")
        ex.require(
            type(self.stages) is tuple
            and len(self.stages) == len(self.continuation)
            and all(s in STAGES for s in self.stages),
            "One declared stage per continuation token",
        )

    def record(self):
        # JSON-normalized for identical in-memory and on-disk comparisons.
        import json

        return json.loads(ex.canonical(asdict(self)))


def _evaluation_only(graph):
    ex.require(not any(m.training for m in graph.modules()), "Readout audit requires eval mode")


def token_readout(logits, *, target, eos, probes=()):
    """Tie-aware native scores. Margins exclude the token being measured.

    ``rank`` is 1 + strictly greater logits. A rank-one tie is NOT a strict win.
    This function neither mutates input nor consumes random numbers.
    """
    import torch

    scores = logits.detach().to(device="cpu", dtype=torch.float32)
    ex.require(
        scores.ndim == 1 and scores.numel() >= 2 and bool(torch.isfinite(scores).all()),
        "Finite one-dimensional native vocabulary with at least two tokens",
    )
    ex.require(
        all(type(i) is int and 0 <= i < scores.numel() for i in (target, eos, *probes)),
        "Observed token outside native vocabulary",
    )
    ex.require(len(set(probes)) == len(probes), "Unique probe token IDs")
    logprobs = scores.log_softmax(-1)
    ex.require(bool(torch.isfinite(logprobs).all()), "Finite native log probabilities")
    top = scores.topk(2).values
    maximum = top[0]

    def measure(token):
        value = scores[token]
        competitor = top[1] if value == maximum else maximum
        return dict(
            token_id=token,
            logit=float(value),
            logprob=float(logprobs[token]),
            rank=1 + int((scores > value).sum()),
            ties=int((scores == value).sum()),
            margin_vs_best_other=float(value) - float(competitor),
        )

    return dict(
        vocabulary=scores.numel(),
        argmax=int(scores.argmax()),
        argmax_ties=int((scores == maximum).sum()),
        target=measure(target),
        eos=measure(eos),
        probes=[measure(i) for i in probes],
    )


def _row(logits, *, step, input_ids, token, eos, probes, stage, native_dtype):
    return dict(
        step=step,
        query_tokens=len(input_ids),
        query_sha256=ex.plan_hash(input_ids),
        stage=stage,
        native_dtype=native_dtype,
        **token_readout(logits, target=token, eos=eos, probes=probes),
    )


def trace_continuation(graph, spec: ReadoutSpec, memory=(), *, guard):
    """Recompute each identical prefix, without showing any future target tokens.

    One forward per reference token; no sampling and no EOS early stop. Full
    recomputation matches ``native_evaluation.generate`` rather than introducing
    a cache or a batched-forward arithmetic confound. Model mode is not changed.
    """
    import torch

    ex.require(type(spec) is ReadoutSpec, "Explicit frozen readout specification")
    _ids(memory, "memory", empty=True)
    _evaluation_only(graph)
    device = next(graph.parameters()).device
    rows = []
    with torch.no_grad():
        for step, token in enumerate(spec.continuation):
            guard(f"readout:{step}")
            prefix = spec.prefix + spec.continuation[:step]
            output = graph(**ev.tensor_batch(prefix, memory, device))
            rows.append(
                _row(
                    output.logits[0, -1],
                    step=step,
                    input_ids=prefix,
                    token=token,
                    eos=spec.eos,
                    probes=spec.probes,
                    stage=spec.stages[step],
                    native_dtype=str(output.logits.dtype),
                )
            )
            del output
    return dict(
        schema=SCHEMA,
        mode="fixed_continuation",
        spec=spec.record(),
        spec_sha256=ex.plan_hash(spec.record()),
        memory_ids=list(memory),
        memory_sha256=ex.plan_hash(memory),
        native_forward_calls=len(rows),
        new_sequences=0,
        rows=rows,
    )


def trace_generation(graph, prefix, memory, *, probes=(), **policy):
    """Observe the existing sampler; do not implement a second generation loop.

    Free histories may diverge. These traces cannot be passed to the matched
    fixed-token contrast below. Forced reference roles are never projected onto
    generated text merely because token indices happen to be equal.
    """
    _ids(prefix, "prefix")
    _ids(memory, "memory", empty=True)
    _ids(probes, "probe", empty=True)
    _evaluation_only(graph)
    ReadoutSpec(prefix, (policy["eos"],), ("stop",), policy["eos"], probes)
    rows = []
    pending = {}

    def finish(token):
        rows.append(
            _row(
                pending["logits"],
                step=len(rows),
                input_ids=pending["input_ids"],
                token=token,
                eos=policy["eos"],
                probes=probes,
                stage="unclassified",
                native_dtype=pending["native_dtype"],
            )
        )
        pending.clear()

    class ObservedGraph:
        # A forwarding view, not an nn.Module or a second owner. Keep at most
        # ONE vocabulary vector, detached/copied to CPU, until the unchanged
        # sampler reveals its chosen token in the next prefix or final result.
        # No sampling is reimplemented and historical source bytes stay intact.
        def parameters(self):
            return graph.parameters()

        def __call__(self, **batch):
            import torch

            ids = tuple(batch["input_ids"][0].tolist())
            observed_memory = tuple(batch["memory_ids"][0].tolist()) if memory else ()
            ex.require(observed_memory == memory, "Memory changed within generation")
            if pending:
                ex.require(ids[:-1] == pending["input_ids"], "Native generation prefix order")
                finish(ids[-1])
            output = graph(**batch)
            pending.update(
                input_ids=ids,
                native_dtype=str(output.logits.dtype),
                logits=output.logits[0, -1].detach().to(device="cpu", dtype=torch.float32).clone(),
            )
            return output

    generated = ev.generate(ObservedGraph(), list(prefix), list(memory), **policy)
    ex.require(
        pending["input_ids"] == prefix + tuple(generated["token_ids"][:-1]),
        "Terminal native generation prefix",
    )
    finish(generated["token_ids"][-1])
    return dict(
        schema=SCHEMA,
        mode="free_generation",
        prefix_ids=list(prefix),
        memory_ids=list(memory),
        memory_sha256=ex.plan_hash(memory),
        eos=policy["eos"],
        probes=list(probes),
        generation=generated,
        native_forward_calls=len(rows),
        new_sequences=1,
        rows=rows,
    )


def _validate_fixed(trace):
    ex.require(
        trace["schema"] == SCHEMA and trace["mode"] == "fixed_continuation",
        "Matched readout requires fixed-continuation traces",
    )
    value = trace["spec"]
    spec = ReadoutSpec(
        tuple(value["prefix"]),
        tuple(value["continuation"]),
        tuple(value["stages"]),
        value["eos"],
        tuple(value["probes"]),
    )
    ex.require(ex.plan_hash(spec.record()) == trace["spec_sha256"], "Readout spec hash")
    ex.require(ex.plan_hash(trace["memory_ids"]) == trace["memory_sha256"], "Memory hash")
    _ids(tuple(trace["memory_ids"]), "memory", empty=True)
    ex.require(
        len(trace["rows"]) == len(spec.continuation) == trace["native_forward_calls"]
        and trace["new_sequences"] == 0,
        "Complete fixed-token readout denominator",
    )
    for i, row in enumerate(trace["rows"]):
        prefix = spec.prefix + spec.continuation[:i]
        ex.require(
            row["step"] == i
            and row["query_sha256"] == ex.plan_hash(prefix)
            and row["query_tokens"] == len(prefix)
            and row["stage"] == spec.stages[i]
            and row["target"]["token_id"] == spec.continuation[i]
            and row["eos"]["token_id"] == spec.eos
            and [p["token_id"] for p in row["probes"]] == list(spec.probes),
            "Fixed-token causal alignment",
        )
    # Refuse NaN/Inf, including values deserialized from a modified receipt.
    ex.canonical(trace)


def compare_fixed(left, right):
    """Right-minus-left at EXACTLY the same query/reference token history.

    Memory may differ. Inline-vs-latent prompts do not share token history and
    must NOT be interpreted as this matched-prefix causal contrast. This is a
    readout comparison, not proof of correct facts or a persistent KV effect.
    """
    _validate_fixed(left)
    _validate_fixed(right)
    ex.require(left["spec"] == right["spec"], "Identical fixed query and continuation required")
    deltas = []
    for a, b in zip(left["rows"], right["rows"], strict=True):
        ex.require(
            a["vocabulary"] == b["vocabulary"] and a["native_dtype"] == b["native_dtype"],
            "Matched vocabulary and native arithmetic required",
        )
        deltas.append(
            dict(
                step=a["step"],
                stage=a["stage"],
                target_logprob=b["target"]["logprob"] - a["target"]["logprob"],
                target_margin=b["target"]["margin_vs_best_other"]
                - a["target"]["margin_vs_best_other"],
                eos_logprob=b["eos"]["logprob"] - a["eos"]["logprob"],
                probe_logprob=[
                    dict(token_id=p["token_id"], delta=q["logprob"] - p["logprob"])
                    for p, q in zip(a["probes"], b["probes"], strict=True)
                ],
            )
        )
    return dict(
        schema="ltws-matched-readout-contrast-v1",
        spec_sha256=left["spec_sha256"],
        left_memory_sha256=left["memory_sha256"],
        right_memory_sha256=right["memory_sha256"],
        tokens=len(deltas),
        deltas=deltas,
        stages={
            stage: dict(
                tokens=sum(r["stage"] == stage for r in deltas),
                target_logprob_sum=sum(r["target_logprob"] for r in deltas if r["stage"] == stage),
            )
            for stage in sorted(set(left["spec"]["stages"]))
        },
        claim="Conditional token evidence only; no correctness, retention or recurrence claim",
    )
