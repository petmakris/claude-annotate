from skills.walkthrough import steps as steps_module


def good_doc():
    return {
        "question": "how to add a precondition on share",
        "kind": "explain",
        "generated_ts": 1784720471,
        "steps": [
            {"id": 1, "title": "Where sharing starts", "file": "src/Api.java",
             "line": 42, "snippet": "return service.share(id);",
             "role": "context", "markdown": "The REST entry point."},
            {"id": 2, "title": "The precondition gate", "file": "src/Engine.java",
             "line": 114, "snippet": "var failures = preconditions.evaluate(p);",
             "role": "seam", "markdown": "Every Precondition bean runs here."},
        ],
    }


def test_valid_doc_has_no_errors():
    assert steps_module.validate(good_doc()) == []


def test_rejects_missing_snippet():
    doc = good_doc()
    del doc["steps"][0]["snippet"]
    errors = steps_module.validate(doc)
    assert any("snippet" in e for e in errors)


def test_rejects_blank_snippet():
    doc = good_doc()
    doc["steps"][0]["snippet"] = "   "
    assert any("snippet" in e for e in steps_module.validate(doc))


def test_rejects_non_positive_line():
    doc = good_doc()
    doc["steps"][1]["line"] = 0
    assert any("line" in e for e in steps_module.validate(doc))


def test_rejects_unknown_role():
    doc = good_doc()
    doc["steps"][0]["role"] = "wishful"
    assert any("role" in e for e in steps_module.validate(doc))


def test_rejects_duplicate_ids():
    doc = good_doc()
    doc["steps"][1]["id"] = 1
    assert any("duplicate" in e for e in steps_module.validate(doc))


def test_rejects_absolute_or_escaping_paths():
    doc = good_doc()
    doc["steps"][0]["file"] = "/etc/passwd"
    assert any("file" in e for e in steps_module.validate(doc))
    doc["steps"][0]["file"] = "../secrets.txt"
    assert any("file" in e for e in steps_module.validate(doc))


def test_rejects_empty_step_list():
    doc = good_doc()
    doc["steps"] = []
    assert any("at least" in e for e in steps_module.validate(doc))


def test_rejects_bad_kind():
    doc = good_doc()
    doc["kind"] = "vibes"
    assert any("kind" in e for e in steps_module.validate(doc))
