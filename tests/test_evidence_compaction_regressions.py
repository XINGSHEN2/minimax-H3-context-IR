from backend.agent import _compact_entity


def feature(name="closure"):
    return {"name": name, "value": "circular clasp with vertical bar",
            "source": "visible", "confidence": 0.9}


def test_invalid_group_does_not_hide_later_valid_evidence():
    result = _compact_entity({"attributes": {
        "legacy": "not a feature list", "components": [feature()]}})
    assert result["attributes"]["components"][0]["name"] == "closure"


def test_invalid_item_does_not_hide_following_features():
    result = _compact_entity({"attributes": {"components": [None, feature()]}})
    assert result["attributes"]["components"][0]["value"] == feature()["value"]


def test_budget_still_limits_valid_features():
    result = _compact_entity({"attributes": {
        "components": [feature(str(i)) for i in range(20)]}})
    assert len(result["attributes"]["components"]) == 16


def test_explicit_uncertainty_is_not_removed_by_high_confidence():
    item = feature()
    item["value"] = "possibly crocodile-embossed"
    result = _compact_entity({"attributes": {"material": [item]}})
    assert result["attributes"]["material"][0]["value"] == item["value"]
