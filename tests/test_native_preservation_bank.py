import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "preservation_bank", ROOT / "src/latent_workspace/preservation_bank.py"
)
pb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pb)


class Tokenizer:
    bos_token_id = 1
    eos_token_id = 2

    def encode(self, text, **_):
        return [ord(c) + 10 for c in text]

    def decode(self, ids, **_):
        return "".join(chr(i - 10) for i in ids)

    def apply_chat_template(self, messages, **_):
        prompt = [1, 3, *self.encode(messages[0]["content"]), 4]
        return prompt if len(messages) == 1 else prompt + self.encode(messages[1]["content"]) + [2]


def plan():
    return json.loads((ROOT / "configs/v1_0/PRESERVATION_BANK_01.json").read_text())


def message(i, role="assistant", parent="prompt", tree="tree", text="A useful answer."):
    return dict(
        message_id=i,
        parent_id=parent,
        message_tree_id=tree,
        text=text,
        role=role,
        lang="en",
        review_result=True,
        deleted=False,
        synthetic=False,
        rank=0,
        labels=dict(pii=dict(value=0, count=2), quality=dict(value=0.9, count=2)),
    )


def pair():
    return [message("prompt", "prompter", None, text="A useful question?"), message("answer")]


def candidates(train=None, validation=None, p=None):
    return pb.oasst_candidates(
        train or pair(), validation or [], Tokenizer(), p or plan(), pb.Exclusions([])
    )


def test_mask_and_eos_exactly_follow_full_chat_template():
    rows, _ = candidates()
    row = rows[0]
    assert row["labels"][: row["prompt_tokens"]] == [-100] * row["prompt_tokens"]
    assert row["labels"][-1] == 2
    assert pb.audit(rows, plan())["training_admissions"] == 0


def test_bad_token_boundary_fails_instead_of_guessing():
    class Bad(Tokenizer):
        def apply_chat_template(self, messages, **kwargs):
            ids = super().apply_chat_template(messages, **kwargs)
            if len(messages) > 1:
                ids[1] = 99
            return ids

    with pytest.raises(ValueError, match="prefix"):
        pb.chat_tokens(Bad(), "Q", "A")


@pytest.mark.parametrize(
    "field,value",
    [
        ("synthetic", True),
        ("synthetic", None),
        ("deleted", True),
        ("review_result", False),
        ("rank", 1),
        ("lang", "de"),
    ],
)
def test_unreviewed_synthetic_or_wrong_language_excluded(field, value):
    train = pair()
    train[1][field] = value
    assert not candidates(train)[0]


@pytest.mark.parametrize(
    "labels",
    [
        {},
        {"pii": {"value": 0.1, "count": 2}},
        {"pii": {"value": 0, "count": 1}, "quality": {"value": 0.4, "count": 1}},
    ],
)
def test_missing_annotation_pii_or_low_quality_excluded(labels):
    train = pair()
    train[1]["labels"] = labels
    assert not candidates(train)[0]


def test_official_validation_cannot_be_relabelled_training():
    with pytest.raises(ValueError, match="Official tree"):
        candidates(validation=[message("val")])


def test_followups_without_history_are_not_flattened():
    train = pair()
    train[0]["parent_id"] = "older_turn"
    assert not candidates(train)[0]


def test_over_length_kept_out_without_answer_truncation():
    p = plan()
    p["chat_max_tokens"] = 8
    rows, report = candidates(p=p)
    assert rows == []
    assert report["rejected"]["over_length_no_truncation"] == 1


def test_exact_and_embedded_normalized_span_exclusion():
    e = pb.Exclusions(["zero one two three four five"], span=4)
    assert e.matches("ZERO  one, two three four five")
    assert e.matches("prefix one two three four suffix")
    assert not e.matches("different material")


def test_code_is_tagged_not_executed():
    train = pair()
    train[1]["text"] = "```python\nraise RuntimeError('must never execute')\n```"
    rows, _ = candidates(train)
    assert rows[0]["role"] == "code"
    assert pb.audit(rows, plan())["functional_code_correctness"] == "UNTESTED"


def test_duplicate_questions_are_removed_before_split():
    train = pair()
    train += [
        message("p2", "prompter", None, "tree2", "A useful question?"),
        message("a2", parent="p2", tree="tree2", text="A different reply."),
    ]
    rows, report = candidates(train)
    assert len(rows) == 1
    assert report["rejected"]["duplicate_prompt_or_answer"] == 1


@pytest.mark.parametrize("damage", ["prompt_loss", "changed_label", "group_split", "approval"])
def test_audit_fails_closed(damage):
    rows, _ = candidates()
    if damage == "prompt_loss":
        rows[0]["labels"][1] = rows[0]["input_ids"][1]
    elif damage == "changed_label":
        rows[0]["labels"][-1] = 1000
    elif damage == "approval":
        rows[0]["training_approved"] = True
    else:
        other = copy.deepcopy(rows[0])
        other["row_id"] = "different"
        other["split"] = "dev" if rows[0]["split"] == "train" else "train"
        rows.append(other)
    with pytest.raises(ValueError):
        pb.audit(rows, plan())


def test_source_paths_cannot_escape(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        pb.safe_path(tmp_path, "../outside")


def test_prose_windows_are_native_contiguous_and_no_fake_eos(tmp_path):
    text = "A sufficiently varied prose source " * 40
    (tmp_path / "one.txt").write_text(text)
    doc = dict(
        doc_id="doc1",
        root_work_id="root1",
        content_path="one.txt",
        content_category="essay",
        text_language="en",
        content_sha256=pb.sha(text.encode()),
        license_or_pd_basis={"status": "public_domain"},
    )
    rows, _ = pb.lm_candidates(tmp_path, [doc], Tokenizer(), plan(), pb.Exclusions([]))
    assert len(rows) == 4
    for r in rows:
        assert (
            r["input_ids"][1:]
            == Tokenizer().encode(text)[r["source"]["token_start"] : r["source"]["token_end"]]
        )
        assert 2 not in r["input_ids"] and r["labels"][0] == -100
    assert pb.audit(rows, plan())["rows"] == 4


def test_columnar_labels_are_supported():
    assert pb.labels_dict({"labels": {"name": ["pii"], "value": [0], "count": [3]}}) == {
        "pii": {"value": 0, "count": 3}
    }
