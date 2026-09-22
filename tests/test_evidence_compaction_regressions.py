from backend.evidence import _compact_entity, build_writer_evidence


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


def test_entity_summary_is_not_repeated_as_an_attribute():
    result = _compact_entity({
        "summary": "A red leather bag with a circular clasp",
        "attributes": {"appearance": [{
            "name": "material", "value": "red leather",
            "source": "visible", "confidence": 0.9,
        }]},
    })
    assert "attributes" not in result


def test_repeated_cross_asset_context_is_lifted_once():
    source = {
        "assets": [
            {"asset_id": "image_1", "media_type": "image"},
            {"asset_id": "image_2", "media_type": "image"},
        ],
        "perception": {"assets": [
            {"asset_id": "image_1", "global_analysis": {
                "scene": "shared film look", "composition": "left subject"}},
            {"asset_id": "image_2", "global_analysis": {
                "scene": "shared film look", "composition": "right subject"}},
        ]},
    }
    result = build_writer_evidence(source)
    assert result["shared_visual_context"] == [{
        "field": "scene", "asset_ids": ["image_1", "image_2"],
        "value": "shared film look",
    }]
    assert all("scene" not in asset.get("global_analysis", {}) for asset in result["assets"])
