"""Build and execute an offline publication-QA notebook; never dispatch model calls.

Run from the repository root with an isolated tooling environment:
uv run --no-project --python 3.13 --with nbformat==5.11.1 \
  --with nbclient==0.11.0 --with ipykernel==7.4.0 \
  python scripts/build_v15_5_continuation_validation.py

The destination is exclusive. A later --verify run executes the stored notebook
in memory and compares its recorded outputs without overwriting any artifact.
"""

from __future__ import annotations

import argparse
import json
from importlib.metadata import version
from pathlib import Path

import nbformat
from nbclient import NotebookClient

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "provenance/pilots/v15_5_diagnostic_judge_continuation_01_20261010"
DESTINATION = BUNDLE / "VALIDATION.ipynb"


def notebook():
    md, code = nbformat.v4.new_markdown_cell, nbformat.v4.new_code_cell
    cells = [
        md("""# V15.5 continuation 01: offline publication checks

## tl;dr

Share with caveats: the continuation halted after 155 valid diagnoses and four
ambiguous timeouts; 161 requests were never sent. Combined main coverage is
343/512, not a complete study. OpenAI remains blocked and the old gate remains
FAIL. This notebook verifies accounting, provenance, literal outputs and costs;
it does not certify model diagnoses as human gold or authorize a learner run.

## Context & Methods

As of 2026-10-10, Asia/Tokyo. The 512 original outputs cover 16 correlated world
clusters; 32 repeats are measurements of fixed outputs, not extra independent
tasks. Original paid source: `59ac10623c0f088d61481e1cfbb9898c206002b5`;
continuation source: `92bd66a0024f8c4b4442d1addfa4105f60287b96`.

### Key Assumptions

The original and continuation bundles remain accessible in this repository.
Remote weight revision and actual invoice are unknown. Missing observations
are not assumed random. Frozen buckets are hierarchical, not independent
dimensions. No new SQL source, credential, network or inference is needed.

## Data

Sources: this bundle's `analysis/{SUMMARY,LEDGER,ARTIFACT_INDEX}.json`, its raw
call receipts, and the immutable sibling `v15_5_diagnostic_judge_20261010`.
Run from anywhere inside the checkout. All cells are read-only. The repository
`.venv` is unchanged; notebook tooling uses an isolated `uv` environment.

### 1. Load and replay the sealed artifacts
"""),
        code("""import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

repo = next(p for p in (Path.cwd(), *Path.cwd().parents)
            if (p / 'scripts/continue_v15_5_diagnostic_judge.py').is_file())
sys.path.insert(0, str(repo / 'scripts'))
import continue_v15_5_diagnostic_judge as continuation
import run_v15_5_diagnostic_judge as original_runner
import v15_5_diagnostics as diagnostics

root = repo / continuation.ROOT
original_root = repo / continuation.ORIGINAL
receipt = continuation.analysis_artifacts(verify=True)
summary = json.loads((root / 'analysis/SUMMARY.json').read_text())
ledger = json.loads((root / 'analysis/LEDGER.json').read_text())
old_summary = json.loads((original_root / 'analysis/SUMMARY.json').read_text())
plan, data, _seal = original_runner.load_frozen()
assert len(ledger) == len({r['item_id'] for r in ledger}) == 512
assert len({r['family_id'] for r in ledger}) == 16
assert summary['status'] == 'INCOMPLETE_OR_CALIBRATION_BLOCKED'
assert summary['old_expression_gate'] == 'FAIL'
assert summary['providers']['openai'] == old_summary['providers']['openai']
print(json.dumps({'source_files': summary['source_files_verified'],
    'original_bundle_files': summary['continuation']['original_bundle_files_verified'],
    'ledger_rows': len(ledger), 'world_clusters': 16, 'old_gate': 'FAIL'}, sort_keys=True))
"""),
        md("""## Results

### 2. Independently account for every planned request

Read raw receipts from both bundles, reject duplicate request IDs, and compare
their union with the original 1,120-coordinate plan. Unknown execution stays
separate from never dispatched; calibration is not counted twice.
"""),
        code("""planned = {r['request_id']: r
    for provider in original_runner.PROVIDERS
    for phase in ('calibration', 'study')
    for r in diagnostics.requests_for(data, plan, provider, phase)}
seen = {}
for source in (original_root, root):
    for request_path in sorted(source.glob('*/study/calls/*/REQUEST.json')) + sorted(
            source.glob('*/calibration/calls/*/REQUEST.json')):
        request = json.loads(request_path.read_text())
        request_id = request['request_id']
        assert request_id in planned and request == planned[request_id]
        assert request_id not in seen, 'Duplicate paid coordinate across bundles'
        outcome = json.loads((request_path.parent / 'OUTCOME.json').read_text())
        status = (outcome['observation']['status'] if outcome['status'] == 'response_recorded'
                  else outcome['status'])
        seen[request_id] = (request, outcome, status, source.name)
counts = Counter(value[2] for value in seen.values())
counts['not_dispatched'] = len(planned) - len(seen)
assert len(planned) == 1120 and len(seen) == 415
assert dict(counts) == {'valid_diagnosis': 406, 'invalid_judgment': 1,
    'transport_or_recording_ambiguous_no_retry': 8, 'not_dispatched': 705}
assert sum(counts.values()) == 1120
assert all(not key.startswith('openai-study-') for key in seen)
new = [value for value in seen.values() if value[3] == root.name]
assert len(new) == 159
assert Counter(value[2] for value in new) == {'valid_diagnosis': 155,
    'transport_or_recording_ambiguous_no_retry': 4}
assert all((value[0]['provider'], value[0]['phase'], value[0]['replicate'])
           == ('mistral', 'study', 0) for value in new)
print(json.dumps({'all_phases': dict(counts), 'reserved': len(seen),
    'new_reserved': len(new), 'new_never_dispatched': 320-len(new)}, sort_keys=True))
"""),
        md("""### 3. Reconcile denominators and renderer-specific failure categories

These are descriptive model diagnoses, not corrected scores. Separate raw from
native-chat formatting before attributing failure to termination. Preserve all
512 machine outputs, including those lacking a valid model diagnosis.
"""),
        code("""profile = {}
for information in ('inline', 'query_only'):
    rows = [r for r in ledger if r['coordinate']['information'] == information]
    assert len(rows) == 256
    status = Counter(r['diagnoses']['mistral']['status'] for r in rows)
    buckets = Counter(r['diagnoses']['mistral']['bucket'] for r in rows)
    section = summary['primary_inline' if information == 'inline' else 'secondary_query_only']
    assert dict(status) == section['judges']['mistral']['statuses']
    assert dict(buckets) == section['judges']['mistral']['buckets']
    assert sum(buckets.values()) == len(rows)
    assert sum(r['mechanical']['strict_correct'] for r in rows) == section['strict_correct']
    profile[information] = {'planned': len(rows), 'statuses': dict(status),
        'strict_all': section['strict_correct'], 'buckets': dict(buckets)}
native = [r for r in ledger if r['coordinate']['information'] == 'inline'
          and r['coordinate']['renderer'] == 'native_chat']
valid_native = [r for r in native if r['diagnoses']['mistral']['status'] == 'valid_diagnosis']
native_buckets = Counter(r['diagnoses']['mistral']['bucket'] for r in valid_native)
assert len(native) == 128 and len(valid_native) == 87
assert dict(native_buckets) == {'strict_success': 58, 'internal_contradiction': 13,
    'unambiguous_wrong_commitment': 13, 'format_only_candidate_not_rescued': 2,
    'explanation_or_grounding_failure': 1}
assert sum(not r['mechanical']['strict_correct'] for r in valid_native) == 29
print(json.dumps({'information': profile, 'native_inline_valid': len(valid_native),
    'native_inline_valid_buckets': dict(native_buckets)}, sort_keys=True))
"""),
        md("""### 4. Recompute usage from receipts and preserve repeat disagreement

Costs use frozen undiscounted plan rates, not a current price claim or invoice.
The eight timed-out calls have unknown remote execution and billing.
"""),
        code("""usage = {}
for provider in ('mistral', 'openai'):
    values = [value for value in seen.values() if value[0]['provider'] == provider]
    known = [value[1]['usage_receipt'] for value in values
             if value[1].get('usage_receipt', {}).get('status') == 'REPORTED_BY_API']
    actual = {'reserved': len(values), 'reported': len(known),
        'input': sum(r['input_tokens'] for r in known),
        'output': sum(r['output_tokens'] for r in known),
        'cost': str(sum((Decimal(r['usage_based_undiscounted_cost_usd'])
                         for r in known), Decimal(0)))}
    reported = summary['providers'][provider]['usage']
    observed = tuple(actual[k] for k in ('reserved', 'reported', 'input', 'output', 'cost'))
    assert observed == (
        reported['reserved_calls'], reported['calls_with_reported_usage'],
        reported['reported_input_tokens'], reported['reported_output_tokens'],
        reported['reported_usage_undiscounted_cost_usd'])
    usage[provider] = actual
assert sum(v['reported'] for v in usage.values()) == 407
cost = sum(Decimal(v['cost']) for v in usage.values())
assert cost == Decimal('7.73465540')
repeat = summary['providers']['mistral']['repeat_stability']
assert repeat == old_summary['providers']['mistral']['repeat_stability']
assert (repeat['all_four_equal'], repeat['differs'], repeat['invalid_or_missing']) == (25, 6, 1)
print(json.dumps({'usage': usage, 'cost_total': str(cost), 'repeat': repeat}, sort_keys=True))
"""),
        md("""### 5. Verify publication examples, links and literal whitespace

The report's four quoted examples are explicitly selected illustrations, not a
representative sample. All code fences below are matched exactly to stored
learner text. Literal trailing spaces in the large generated panel are retained.
"""),
        code("""import re

report_path = root / 'README.md'
report_text = report_path.read_text()
example_ids = ('89f3d60346a5a601b10c3d20', '9db60525663ff106754b8281',
               '6cdf8806a56e76f4b6c15f97', '330a2cbcd94d10a9b4678dc7')
by_id = {r['item_id']: r for r in ledger}
fences = re.findall(r'```text\\n(.*?)\\n```', report_text, re.S)
assert len(fences) == len(example_ids) == 4
for item_id, literal in zip(example_ids, fences, strict=True):
    assert item_id in report_text and literal == by_id[item_id]['payload']['response_text']
paths = (report_path, root/'EXECUTION_HANDOFF.md', repo/'README.md', repo/'docs/v15/NEXT_STEPS.md')
links = [(p, link) for p in paths for link in re.findall(r'\\]\\(([^)]+)\\)', p.read_text())
         if not re.match(r'[a-z]+:', link)]
targets = [(p.parent/link.split('#')[0]).resolve() for p, link in links]
# The notebook self-link is materialized immediately after this execution.
assert all(p.exists() or p == (root/'VALIDATION.ipynb').resolve() for p in targets)
panel_lines = (root/'analysis/DIAGNOSTIC_PANEL.md').read_text().splitlines()
whitespace = [i for i, line in enumerate(panel_lines, 1)
              if line.endswith((' ', '\\t'))]
print(json.dumps({'literal_examples': len(fences), 'valid_local_links': len(links),
    'preserved_panel_trailing_whitespace_lines': whitespace}, sort_keys=True))
"""),
        md("""## Takeaways

Mechanical replay and accounting pass, but publication is **share with caveats**:
343/512 main diagnoses are available, eight calls remain ambiguous, and 161
Mistral plus 544 OpenAI study coordinates are undispatched. The original invalid
repeat remains invalid. Fixed-repeat disagreement and nonrandom missingness
prevent gold-label and corpus-wide prevalence claims. No substantive quality,
latent-state mechanism, learner improvement or non-regression is established.

Of 87 diagnosed native-chat inline outputs, 29 fail strict scoring: 13 internal
contradictions, 13 unambiguous wrong commitments, two format-only candidates and
one explanation/grounding failure. A termination-only explanation is insufficient
for these observed failures. This motivates separate answer-content and stopping
checks, not immediate training or a repaired old FAIL.
"""),
    ]
    for index, cell in enumerate(cells):
        cell["id"] = f"v15-5-validation-{index:02d}"
    return nbformat.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "validation": {
                "mode": "offline_only",
                "tooling": {name: version(name) for name in ("nbformat", "nbclient", "ipykernel")},
            },
        },
    )


def execute(value):
    nbformat.validate(value)
    result = NotebookClient(
        value,
        timeout=120,
        kernel_name="python3",
        allow_errors=False,
        resources={"metadata": {"path": str(REPO)}},
    ).execute()
    nbformat.validate(result)
    return result


def outputs(value):
    return [cell["outputs"] for cell in value.cells if cell.cell_type == "code"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        stored = nbformat.read(DESTINATION, as_version=4)
        expected = outputs(stored)
        replayed = execute(stored)
        if expected != outputs(replayed):
            raise ValueError("Notebook output replay differs; do not overwrite")
        print(json.dumps({"status": "VERIFIED_NO_NETWORK", "executed_cells": len(expected)}))
        return
    if DESTINATION.exists():
        raise FileExistsError(DESTINATION)
    result = execute(notebook())
    with DESTINATION.open("x", encoding="utf-8") as stream:
        nbformat.write(result, stream)
    print(
        json.dumps(
            {
                "status": "EXECUTED_OFFLINE",
                "executed_cells": len(outputs(result)),
                "path": str(DESTINATION.relative_to(REPO)),
            }
        )
    )


if __name__ == "__main__":
    main()
