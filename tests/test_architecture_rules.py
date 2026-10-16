"""Structural guards for docs/ARCHITECTURE.md: one living engine, frozen history.

Generality must not accumulate outside the engine (in wrappers, runners or new
historical modules) while the engine stays behind. These tests make that
structural: the engine never imports history; history cannot change silently;
new code outside the engine defines no ``nn.Module`` components; every promotion
names its origin hash and a parity test that exists.
"""

import ast
import hashlib
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "latent_workspace"
HISTORY = "latent_workspace_ft_v10"
FROZEN = json.loads((ROOT / "configs/architecture/FROZEN_HISTORY.json").read_text())
PROMOTIONS = json.loads((ROOT / "configs/architecture/PROMOTIONS.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module


def module_classes(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ClassDef):
            bases = {ast.unparse(base) for base in node.bases}
            if bases & {"nn.Module", "torch.nn.Module", "Module"}:
                yield node.name


def test_the_engine_never_imports_history():
    offending = {
        str(path.relative_to(ROOT)): name
        for path in ENGINE.rglob("*.py")
        for name in imported_modules(path)
        if name == HISTORY or name.startswith(HISTORY + ".")
    }
    assert not offending, f"Promote instead of importing history: {offending}"


def test_history_is_frozen():
    actual = {
        str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "src" / HISTORY).glob("*.py"))
    }
    changed = sorted(
        k for k in actual.keys() & FROZEN["history"].keys() if actual[k] != FROZEN["history"][k]
    )
    added = sorted(actual.keys() - FROZEN["history"].keys())
    removed = sorted(FROZEN["history"].keys() - actual.keys())
    assert not (changed or added or removed), (
        "History is frozen; general code belongs in src/latent_workspace. "
        f"changed={changed} added={added} removed={removed}"
    )


def test_src_holds_only_the_engine_and_frozen_history():
    packages = {
        p.name for p in (ROOT / "src").iterdir() if p.is_dir() and (p / "__init__.py").exists()
    }
    assert packages == {"latent_workspace", HISTORY}


def test_new_code_defines_no_components_outside_the_engine():
    grandfathered = set(FROZEN["grandfathered_scripts"])
    offending = {
        str(path.relative_to(ROOT)): sorted(module_classes(path))
        for path in sorted((ROOT / "scripts").glob("*.py"))
        if str(path.relative_to(ROOT)) not in grandfathered and list(module_classes(path))
    }
    assert not offending, f"Components belong in src/latent_workspace: {offending}"


def test_every_promotion_is_pinned():
    stack = (ROOT / "tests" / "test_latent_workspace_stack.py").read_text()
    for entry in PROMOTIONS:
        module, name = entry["engine"].rsplit(".", 1)
        assert hasattr(importlib.import_module(module), name), entry["engine"]
        origin = entry["origin"].split("::")[0]
        assert FROZEN["history"][origin] == entry["origin_sha256"], entry["origin"]
        assert f"def {entry['parity']}(" in stack, entry["parity"]
