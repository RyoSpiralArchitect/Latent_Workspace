#!/usr/bin/env python3
"""Frozen, source-bound toy assay; default invocation does not train.

This supplies factual slots and controlled architecture-owned features. It does
not test tokenization, a real writer, an LLM, or admission by a learner owner.
CPU RSS is an observed fail-closed resource gate, not an OS hard RSS limit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import os
import platform
import resource
import signal
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "scripts/assay_v18_operand_selection.py"
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
}


def sealed_guard(seal_path):
    if not sys.flags.isolated or not sys.pycache_prefix or not sys.dont_write_bytecode:
        raise ValueError("Execute through run_source_sealed.py with -I and fresh pycache")
    cache = Path(sys.pycache_prefix)
    if (
        not cache.is_absolute()
        or not cache.is_dir()
        or cache.is_symlink()
        or cache.resolve().is_relative_to(ROOT)
        or any(cache.iterdir())
    ):
        raise ValueError("Bytecode cache must be a fresh empty directory outside source")
    spec = importlib.util.spec_from_file_location(
        "operand_source_guard", ROOT / "scripts/run_source_sealed.py"
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    seal = json.loads(Path(seal_path).read_text())
    return seal, guard.verify(ROOT, seal, ENTRY)


# The external stdlib launcher validates this entry before execution. This
# second check also precedes all project/third-party imports on an execute path.
if __name__ == "__main__" and "--execute" in sys.argv:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--source-seal", required=True, type=Path)
    boot_args, _ = bootstrap.parse_known_args()
    sealed_guard(boot_args.source_seal)
    os.environ.update(OFFLINE_ENV)

import torch  # noqa: E402
from torch.nn import functional as F  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
from latent_workspace_ft_v10.precision_bridge import PrecisionAwareWorkspaceBridge  # noqa: E402
from latent_workspace_ft_v10.v18_selection_reader import SelectionWorkspaceBridge  # noqa: E402

PLAN_PATH = ROOT / "configs/v18/OPERAND_SELECTION_ASSAY_PLAN.json"
PLAN_FILE_SHA256 = "3cce82a87d8603c7e430e6a33a4c96b70a6a69108486bac2dd29f9cff84acb47"
ORDERS = tuple(itertools.permutations(range(3)))
QUESTIONS = tuple(itertools.permutations(range(3), 2))
RECIPROCALS = ((0, 2), (1, 4), (3, 5))
FACTORS = ("centered_final", "centered_ordered", "centered_symmetric", "raw_ordered")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def load_plan():
    if hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest() != PLAN_FILE_SHA256:
        raise ValueError("Exact frozen plan bytes changed")
    plan = json.loads(PLAN_PATH.read_text())
    if (
        plan["schema"] != "v18-controlled-operand-selection-plan-v1"
        or tuple(plan["factors"]) != FACTORS
        or [plan[k] for k in ("hidden_dim", "workspace_dim", "heads", "slots")] != [32, 32, 2, 3]
        or plan["resources"]["wall_seconds"] != 900
        or plan["resources"]["peak_bytes"] != 4 * 1024**3
    ):
        raise ValueError("Unsupported or changed assay geometry/resource contract")
    return plan


@dataclass(frozen=True)
class Inputs:
    """Forward inputs deliberately have no labels or rank/world metadata."""

    states: torch.Tensor
    memory: torch.Tensor
    mask: torch.Tensor

    def take(self, indices):
        return Inputs(*(value[indices] for value in (self.states, self.memory, self.mask)))

    def to(self, device):
        return Inputs(*(value.to(device) for value in (self.states, self.memory, self.mask)))


@dataclass(frozen=True)
class Population:
    inputs: Inputs
    twin: Inputs
    labels: torch.Tensor
    twin_labels: torch.Tensor
    rows: tuple[dict, ...]
    frames: int


def population(seed, frames):
    """Deterministic facts/codebook; all permutations of a frame stay together.

    The synthetic adapter gives each operand its text-identified codeword and
    gives the final state both codewords in ordered blocks. It never uses rank
    when producing question states. Rank is supplied only in factual slots.
    """
    generator = torch.Generator().manual_seed(seed)
    states, memories, twins, labels, twin_labels, rows = [], [], [], [], [], []
    for frame in range(frames):
        raw = torch.randn(8, 3, generator=generator, dtype=torch.float64)
        raw = raw - raw.mean(dim=0, keepdim=True)
        identities = torch.linalg.qr(raw, mode="reduced").Q.T.float()
        for order_id, ranks in enumerate(ORDERS):
            other_ranks = tuple(1 - rank if rank < 2 else rank for rank in ranks)
            memory = torch.zeros(3, 32)
            twin = torch.zeros_like(memory)
            memory[:, :8] = twin[:, :8] = identities
            for entity, (rank, other_rank) in enumerate(zip(ranks, other_ranks)):
                memory[entity, 16 + rank] = 1
                twin[entity, 16 + other_rank] = 1
            for subject, obj in QUESTIONS:
                hidden = torch.zeros(3, 32)
                hidden[0, :8], hidden[1, :8] = identities[subject], identities[obj]
                hidden[2, :8], hidden[2, 8:16] = identities[subject], identities[obj]
                hidden[:, 31] = 1
                states.append(hidden)
                memories.append(memory)
                twins.append(twin)
                labels.append(0 if ranks[subject] > ranks[obj] else 1)
                twin_labels.append(0 if other_ranks[subject] > other_ranks[obj] else 1)
                rows.append(
                    {
                        "frame": frame,
                        "order": order_id,
                        "subject": subject,
                        "object": obj,
                        "question": f"Is E{subject} ranked above E{obj}? Answer:",
                        "renamed_question": (
                            f"Is Alias{subject + 7} ranked above Alias{obj + 7}? Answer:"
                        ),
                        "ranks": list(ranks),
                        "twin_ranks": list(other_ranks),
                    }
                )
    states = torch.stack(states)
    mask = torch.ones(len(states), 3, dtype=torch.long)
    return Population(
        Inputs(states, torch.stack(memories), mask),
        Inputs(states, torch.stack(twins), mask),
        torch.tensor(labels),
        torch.tensor(twin_labels),
        tuple(rows),
        frames,
    )


def make_reader(seed, factor, device="cpu"):
    if factor not in FACTORS:
        raise ValueError("Unknown factor")
    torch.manual_seed(seed)
    common = PrecisionAwareWorkspaceBridge(32, workspace_dim=32, heads=2, slots=3, max_delta_norm=1)
    common.requires_grad_(False)  # zero up + supplied slots: no common/writer training.
    bridge = SelectionWorkspaceBridge(
        common,
        mode="raw_matched_control" if factor == "raw_ordered" else "slot_contrast",
        interaction_fraction=0.25,
    ).to(device)
    return bridge


def query(states, factor):
    # This explicitly matches CPU-FP32 operand pooling, including on CUDA.
    if factor == "centered_final":
        return states[:, -1:].float()
    operands = states[:, :2].float().to("cpu")
    if factor in ("centered_ordered", "raw_ordered"):
        result = operands[:, :1] - operands[:, 1:2]
    elif factor == "centered_symmetric":
        result = (operands[:, :1] + operands[:, 1:2]) / 2
    else:
        raise ValueError("Unknown factor")
    return result.to(states.device)


def full_vocab_head(states, delta):
    """Fixed full-sequence/full-vocabulary architecture-owned native readout."""
    head = torch.zeros(7, 32, device=states.device, dtype=states.dtype)
    head[0, 30], head[1, 30], head[2:, 31] = 8, -8, -4
    corrected = torch.cat((states[:, :-1], (states[:, -1:].float() + delta).to(states.dtype)), 1)
    return F.linear(corrected, head)[:, -1].float()


def forward(bridge, inputs, factor, *, native_dtype=torch.float32, common_only=False):
    states = inputs.states.to(native_dtype)
    if common_only:
        delta = torch.zeros_like(states[:, -1:], dtype=torch.float32)
    else:
        delta = bridge.parts(
            states[:, -1:].float(), query(states, factor), inputs.memory, inputs.mask
        )["delta"]
    return full_vocab_head(states, delta), delta


def optimizer_for(bridge, plan):
    cfg = plan["training"]
    return torch.optim.AdamW(
        [p for p in bridge.parameters() if p.requires_grad],
        lr=cfg["learning_rate"],
        weight_decay=cfg["weight_decay"],
    )


def update(bridge, inputs, labels, factor, optimizer, plan):
    optimizer.zero_grad(set_to_none=True)
    logits, delta = forward(bridge, inputs, factor)
    cfg = plan["training"]
    loss = cfg["ce_weight"] * F.cross_entropy(logits, labels)
    loss = loss + cfg["residual_squared_norm_weight"] * delta.square().sum(-1).mean()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(
        [p for p in bridge.parameters() if p.requires_grad],
        cfg["gradient_clip"],
        error_if_nonfinite=True,
    )
    optimizer.step()
    return float(loss.detach())


def native_outcomes(logits, labels):
    maximum = logits.max(-1).values
    unique = logits.eq(maximum[:, None]).sum(-1).eq(1)
    prediction = logits.argmax(-1)
    return prediction, prediction.eq(labels) & unique, unique


def summarize(logits, twin_logits, pop):
    pred, correct, unique = native_outcomes(logits, pop.labels)
    twin_pred, twin_correct, twin_unique = native_outcomes(twin_logits, pop.twin_labels)
    affected = pop.labels.ne(pop.twin_labels)
    intact_margin = logits[:, 0] - logits[:, 1]
    twin_margin = twin_logits[:, 0] - twin_logits[:, 1]
    donor_direction = torch.where(pop.twin_labels.eq(0), 1.0, -1.0)
    delta_margin = donor_direction * (twin_margin - intact_margin)
    groups = correct.reshape(-1, 6)
    reciprocal = torch.stack([groups[:, a] & groups[:, b] for a, b in RECIPROCALS], -1)
    flip = correct & twin_correct & pred.ne(twin_pred)
    agreement = pred.eq(twin_pred)
    unaffected = ~affected
    return {
        "unique_worlds": pop.frames * 6,
        "unique_intact_queries": len(pred),
        "paired_queries": len(pred),
        "affected_pairs": int(affected.sum()),
        "unaffected_pairs": int(unaffected.sum()),
        "reciprocal_pairs": reciprocal.numel(),
        "strict_native_correct": int(correct.sum()),
        "strict_native_accuracy": float(correct.float().mean()),
        "ordinary_native_correct": int(pred.eq(pop.labels).sum()),
        "native_ties": int((~unique).sum()),
        "twin_native_ties": int((~twin_unique).sum()),
        "reciprocal_both_correct": int(reciprocal.sum()),
        "reciprocal_both_correct_rate": float(reciprocal.float().mean()),
        "affected_donor_flips": int(flip[affected].sum()),
        "affected_donor_flip_rate": float(flip[affected].float().mean()),
        "affected_donor_positive": int((delta_margin[affected] > 0).sum()),
        "affected_donor_margin_mean": float(delta_margin[affected].mean()),
        "unaffected_strict_correct": int(correct[unaffected].sum()),
        "unaffected_strict_accuracy": float(correct[unaffected].float().mean()),
        "unaffected_prediction_agreement": float(agreement[unaffected].float().mean()),
        "unaffected_absolute_margin_drift_mean": float(
            (twin_margin - intact_margin)[unaffected].abs().mean()
        ),
        "denominator_note": (
            "All six orders are present; twin forwards duplicate unique worlds, "
            "not independent samples."
        ),
    }


def measured(bridge, inputs, factor, device, dtype, guard, *, common_only=False):
    logits, deltas = [], []
    for start in range(0, len(inputs.states), 256):
        guard()
        chunk = inputs.take(slice(start, start + 256)).to(device)
        output, delta = forward(bridge, chunk, factor, native_dtype=dtype, common_only=common_only)
        logits.append(output.cpu())
        deltas.append(delta.cpu())
    return torch.cat(logits), torch.cat(deltas)


@torch.no_grad()
def evaluate(
    bridge,
    factor,
    pop,
    device,
    dtype,
    guard,
    raw_stream=None,
    seed=None,
    split="held_out",
    common_only=False,
):
    logits, delta = measured(
        bridge, pop.inputs, factor, device, dtype, guard, common_only=common_only
    )
    twin_logits, _ = measured(
        bridge, pop.twin, factor, device, dtype, guard, common_only=common_only
    )
    result = summarize(logits, twin_logits, pop)
    result["max_delta_norm"] = float(delta.norm(dim=-1).max())
    if raw_stream is not None:
        for index, row in enumerate(pop.rows):
            raw_stream.write(
                json.dumps(
                    {
                        "seed": seed,
                        "factor": "common_only" if common_only else factor,
                        "split": split,
                        "native_dtype": str(dtype),
                        "case": index,
                        **row,
                        "label": int(pop.labels[index]),
                        "twin_label": int(pop.twin_labels[index]),
                        "logits": logits[index].tolist(),
                        "twin_logits": twin_logits[index].tolist(),
                        "delta_norm": float(delta[index].norm()),
                    },
                    allow_nan=False,
                    sort_keys=True,
                )
                + "\n"
            )
        raw_stream.flush()
    return result


@torch.no_grad()
def controls(bridge, factor, pop, device, guard, atol):
    data = pop.inputs
    original, delta = measured(bridge, data, factor, device, torch.float32, guard)
    repeat, _ = measured(bridge, data, factor, device, torch.float32, guard)
    zero = Inputs(data.states, torch.zeros_like(data.memory), data.mask)
    equal = Inputs(data.states, data.memory[:, :1].expand_as(data.memory).clone(), data.mask)
    _, zero_delta = measured(bridge, zero, factor, device, torch.float32, guard)
    _, equal_delta = measured(bridge, equal, factor, device, torch.float32, guard)
    perm = [2, 0, 1]
    permuted = Inputs(data.states, data.memory[:, perm], data.mask[:, perm])
    perm_logits, _ = measured(bridge, permuted, factor, device, torch.float32, guard)
    unrelated = Inputs(data.states, data.memory.roll(36, 0), data.mask)
    unrelated_logits, unrelated_delta = measured(
        bridge, unrelated, factor, device, torch.float32, guard
    )
    centered = factor != "raw_ordered"
    result = {
        "same_memory_exact": torch.equal(original, repeat),
        "zero_memory_exact_zero_delta": bool(zero_delta.eq(0).all()),
        "equal_slot_exact_zero_delta": bool(equal_delta.eq(0).all()),
        "equal_slot_gate_applicable": centered,
        "permutation_max_logit_error": float((perm_logits - original).abs().max()),
        "permutation_atol": atol,
        "renaming_scope": (
            "Synthetic alias codebook preserves identical features by construction; "
            "tokenizer binding is not tested here."
        ),
        "unrelated_delta_norm_mean": float(unrelated_delta.norm(dim=-1).mean()),
        "unrelated_absolute_logit_change_mean": float((unrelated_logits - original).abs().mean()),
        "unrelated_accuracy": "UNDEFINED_QUERY_ENTITIES_ABSENT",
        "max_delta_norm": float(delta.norm(dim=-1).max()),
    }
    result["pass"] = bool(
        result["same_memory_exact"]
        and result["zero_memory_exact_zero_delta"]
        and (not centered or result["equal_slot_exact_zero_delta"])
        and result["permutation_max_logit_error"] <= atol
        and result["max_delta_norm"] <= 0.25 + atol
    )
    return result


def gates(results, plan):
    limits = plan["gates"]
    keys = {
        "strict_native_accuracy": "strict_native_accuracy_min",
        "reciprocal_both_correct_rate": "reciprocal_both_correct_min",
        "affected_donor_flip_rate": "affected_donor_flip_min",
        "unaffected_strict_accuracy": "unaffected_strict_accuracy_min",
        "unaffected_prediction_agreement": "unaffected_prediction_agreement_min",
    }
    learnable, advantage = [], []
    for seed in plan["model_seeds"]:
        ordered = results[f"{seed}:centered_ordered"]
        final = results[f"{seed}:centered_final"]
        score, baseline = ordered["held_out_float32"], final["held_out_float32"]
        good = ordered["controls"]["pass"] and all(score[k] >= limits[v] for k, v in keys.items())
        learnable.append(good)
        advantage.append(
            good
            and (
                score["strict_native_accuracy"] - baseline["strict_native_accuracy"]
                >= limits["ordered_minus_final_accuracy_min"]
            )
            and all(
                score[k] >= baseline[k]
                for k in (
                    "reciprocal_both_correct_rate",
                    "unaffected_strict_accuracy",
                    "unaffected_prediction_agreement",
                )
            )
        )
    return {
        "toy_learnable_all_seeds": all(learnable),
        "selection_advantage_all_seeds": all(advantage),
        "old_scientific_gate": "FAIL",
        "winner": "none",
        "non_regression": "NOT_ESTABLISHED",
    }


def source_receipt(expected_commit):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()

    head = git("rev-parse", "HEAD")
    if head != expected_commit or len(head) != 40:
        raise ValueError("Exact frozen source commit is required")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Source checkout must be clean, including all untracked files")
    files = git("ls-files", "src", "scripts", "configs", "tests", "pyproject.toml").splitlines()
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
    return {"commit": head, "files": hashes, "aggregate_sha256": digest(hashes)}


def imported_sources(seal, modules=None):
    imported = {}
    script_names = {
        Path(name).stem for name in seal["source_hashes"] if name.startswith("scripts/")
    }
    for name, module in list((sys.modules if modules is None else modules).items()):
        belongs = name.startswith("latent_workspace_ft_v10") or name in script_names
        try:
            metadata = vars(module)
        except TypeError:
            metadata = {}
        filename = metadata.get("__file__")
        if not filename:
            if belongs:
                raise ValueError(f"Project module has no direct source metadata: {name}")
            continue
        if type(filename) is not str or not Path(filename).is_absolute():
            raise ValueError(f"Module file must be explicit and absolute: {name}")
        path = Path(filename).resolve()
        local = path.is_relative_to(ROOT)
        if local and path.relative_to(ROOT).parts[0] in (".venv", "venv") and not belongs:
            continue
        if not (local or belongs):
            continue
        if not local or path.suffix != ".py" or not path.is_file():
            raise ValueError(f"Project import escaped sealed source: {name}")
        relative = path.relative_to(ROOT).as_posix()
        if seal["source_hashes"].get(relative) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"Imported source is not sealed: {name}")
        imported[name] = relative
    required = {
        "src/latent_workspace_ft_v10/v18_selection_reader.py",
        "src/latent_workspace_ft_v10/precision_bridge.py",
        ENTRY,
    }
    if not required <= set(imported.values()):
        raise ValueError("Missing critical imported-source proof")
    return imported


def tensor_fingerprint(tensor):
    value = tensor.detach().cpu().contiguous()
    checksum = hashlib.sha256()
    checksum.update(str(value.dtype).encode())
    checksum.update(str(tuple(value.shape)).encode())
    checksum.update(value.view(torch.uint8).numpy().tobytes())
    return checksum.hexdigest()


def state_fingerprint(bridge):
    checksum = hashlib.sha256()
    for name, tensor in bridge.state_dict().items():
        checksum.update(name.encode())
        checksum.update(tensor_fingerprint(tensor).encode())
    return checksum.hexdigest()


def population_artifacts(output, populations):
    payload, manifest = {}, {}
    for name, pop in populations.items():
        tensors = {
            "states": pop.inputs.states,
            "memory": pop.inputs.memory,
            "mask": pop.inputs.mask,
            "twin_memory": pop.twin.memory,
            "labels": pop.labels,
            "twin_labels": pop.twin_labels,
        }
        payload[name] = {**tensors, "rows": list(pop.rows), "frames": pop.frames}
        manifest[name] = {
            "tensors": {key: tensor_fingerprint(value) for key, value in tensors.items()},
            "rows_sha256": digest(pop.rows),
            "frames": pop.frames,
            "unique_queries": len(pop.labels),
        }
    path = output / "POPULATIONS.pt"
    with path.open("xb") as stream:
        torch.save(payload, stream)
    manifest["file"] = path.name
    manifest["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(output / "POPULATIONS.json", manifest)
    return manifest


class ResourceGuard:
    def __init__(self, plan, device):
        self.start = time.monotonic()
        self.plan, self.device = plan, device

    def snapshot(self):
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss = int(usage if sys.platform == "darwin" else usage * 1024)
        peak = torch.cuda.max_memory_allocated() if self.device == "cuda" else 0
        return {
            "elapsed_seconds": time.monotonic() - self.start,
            "peak_rss_bytes": rss,
            "peak_cuda_allocated_bytes": peak,
        }

    def __call__(self):
        now = self.snapshot()
        limits = self.plan["resources"]
        if now["elapsed_seconds"] > limits["wall_seconds"]:
            raise TimeoutError("Frozen wall-clock bound exceeded")
        if max(now["peak_rss_bytes"], now["peak_cuda_allocated_bytes"]) > limits["peak_bytes"]:
            raise MemoryError("Observed memory bound exceeded")


def run(output, expected_commit, device, source_seal):
    seal, preimport = sealed_guard(source_seal)
    plan = load_plan()
    source = source_receipt(expected_commit)
    if any(seal["source_hashes"].get(name) != value for name, value in source["files"].items()):
        raise ValueError("External seal does not cover the complete assay source population")
    if output.resolve().is_relative_to(ROOT):
        raise ValueError("Artifacts must be outside the sealed source tree")
    if any(os.environ.get(key) != value for key, value in OFFLINE_ENV.items()):
        raise ValueError("Required offline environment was not set before imports")
    imports_before = imported_sources(seal)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "PLAN.json", plan)
    write_json(output / "SOURCE.json", source)
    write_json(output / "PREIMPORT.json", preimport)
    write_json(output / "IMPORTS_BEFORE.json", imports_before)
    write_json(
        output / "STARTED.json",
        {
            "pid": os.getpid(),
            "device": device,
            "plan_sha256": digest(plan),
            "source_sha256": source["aggregate_sha256"],
            "hostname": platform.node(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "offline_environment": OFFLINE_ENV,
            "external_seal_sha256": hashlib.sha256(Path(source_seal).read_bytes()).hexdigest(),
        },
    )
    guard = ResourceGuard(plan, device)
    previous_handler = signal.getsignal(signal.SIGALRM)

    def timeout_handler(_signum, _frame):
        raise TimeoutError("Frozen wall-clock alarm expired")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(plan["resources"]["wall_seconds"])
    try:
        torch.set_num_threads(plan["resources"]["cpu_threads"])
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        if device == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA requested but unavailable")
            clients = subprocess.check_output(
                ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                text=True,
            )
            if any(
                line.strip() and line.strip() != str(os.getpid()) for line in clients.splitlines()
            ):
                raise RuntimeError("GPU has another compute client; refusing contention")
            total = torch.cuda.get_device_properties(0).total_memory
            torch.cuda.set_per_process_memory_fraction(min(1, 4 * 1024**3 / total))
            torch.cuda.reset_peak_memory_stats()
        populations = {name: population(**cfg) for name, cfg in plan["splits"].items()}
        population_receipt = population_artifacts(output, populations)
        train = populations["train"]
        results = {}
        with (output / "CASES.jsonl").open("x", encoding="utf-8") as raw:
            for seed in plan["model_seeds"]:
                for factor in FACTORS:
                    guard()
                    bridge = make_reader(seed, factor, device)
                    initial_fingerprint = state_fingerprint(bridge)
                    trainable = {
                        name: p.numel() for name, p in bridge.named_parameters() if p.requires_grad
                    }
                    optimizer = optimizer_for(bridge, plan)
                    sampler = torch.Generator().manual_seed(7000 + seed)
                    losses = []
                    for _ in range(plan["training"]["updates"]):
                        guard()
                        indices = torch.randint(
                            len(train.labels), (plan["training"]["batch_size"],), generator=sampler
                        )
                        losses.append(
                            update(
                                bridge,
                                train.inputs.take(indices).to(device),
                                train.labels[indices].to(device),
                                factor,
                                optimizer,
                                plan,
                            )
                        )
                    bridge.eval()
                    state_path = output / f"{seed}_{factor}_final_state.pt"
                    with state_path.open("xb") as stream:
                        torch.save(
                            {
                                name: value.detach().cpu().clone()
                                for name, value in bridge.state_dict().items()
                            },
                            stream,
                        )
                    row = {
                        "losses": losses,
                        "updates": len(losses),
                        "initial_state_sha256": initial_fingerprint,
                        "final_state_sha256": state_fingerprint(bridge),
                        "state_file": state_path.name,
                        "state_file_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
                        "trainable_parameter_names_and_counts": trainable,
                        "trainable_parameter_count": sum(trainable.values()),
                    }
                    for split in ("dev", "held_out"):
                        for dtype in (torch.float32, torch.bfloat16):
                            row[f"{split}_{str(dtype).split('.')[-1]}"] = evaluate(
                                bridge,
                                factor,
                                populations[split],
                                device,
                                dtype,
                                guard,
                                raw,
                                seed,
                                split,
                            )
                    row["controls"] = controls(
                        bridge,
                        factor,
                        populations["held_out"],
                        device,
                        guard,
                        plan["evaluation"]["control_atol"],
                    )
                    results[f"{seed}:{factor}"] = row
                    write_json(output / f"{seed}_{factor}.json", row)
                    if source_receipt(expected_commit) != source:
                        raise ValueError("Source changed during execution")
                    sealed_guard(source_seal)
                    imported_sources(seal)
                    del bridge, optimizer
            reference = {}
            for dtype in (torch.float32, torch.bfloat16):
                reference[str(dtype)] = evaluate(
                    None,
                    "centered_final",
                    populations["held_out"],
                    device,
                    dtype,
                    guard,
                    raw,
                    common_only=True,
                )
        guard()
        if source_receipt(expected_commit) != source:
            raise ValueError("Source changed during execution")
        sealed_guard(source_seal)
        write_json(output / "IMPORTS_AFTER.json", imported_sources(seal))
        result = {
            "schema": "v18-controlled-operand-selection-result-v1",
            "plan_sha256": digest(plan),
            "source_sha256": source["aggregate_sha256"],
            "device": device,
            "results": results,
            "common_only_reference": reference,
            "common_only_reference_note": (
                "Frozen-zero engineering reference; not a trained fifth factor."
            ),
            "populations": population_receipt,
            "control_replay_note": (
                "Control scalars are runtime-attested. Saved final states and realized "
                "populations permit recomputation; raw control logits are not archived."
            ),
            "gates": gates(results, plan),
            "resources": guard.snapshot(),
            "claim_ceiling": plan["claim_ceiling"],
            "native_dtype_note": (
                "BF16 rounds supplied hidden states and the full-vocabulary head; "
                "this is not an end-to-end BF16 LLM."
            ),
        }
        write_json(output / "RESULTS.json", result)
        write_json(
            output / "FINISHED.json",
            {
                "status": "COMPLETED",
                "resources": guard.snapshot(),
                "results_sha256": hashlib.sha256(
                    (output / "RESULTS.json").read_bytes()
                ).hexdigest(),
                "cases_sha256": hashlib.sha256((output / "CASES.jsonl").read_bytes()).hexdigest(),
            },
        )
        return result
    except BaseException as error:
        write_json(
            output / "FAILED.json",
            {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
                "resources": guard.snapshot(),
            },
        )
        write_json(output / "FINISHED.json", {"status": "FAILED", "resources": guard.snapshot()})
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="Explicitly execute the frozen study"
    )
    parser.add_argument("--source-commit")
    parser.add_argument("--source-seal", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    plan = load_plan()
    if not args.execute:
        print(
            json.dumps(
                {"status": "DRY_RUN_NO_TRAINING", "plan_sha256": digest(plan), "plan": plan},
                indent=2,
            )
        )
        return
    if (
        not args.source_commit
        or not args.source_seal
        or not args.output
        or not args.output.is_absolute()
    ):
        parser.error("Execute requires --source-commit, --source-seal and absolute fresh --output")
    result = run(args.output, args.source_commit, args.device, args.source_seal)
    print(json.dumps({"status": "COMPLETED", "gates": result["gates"]}, indent=2))


if __name__ == "__main__":
    main()
