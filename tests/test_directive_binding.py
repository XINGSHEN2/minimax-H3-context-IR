import copy
import unittest

from backend.directive_binding import compile_directive_bindings, derive_binding_graph


def test_binding_graph_derives_all_cross_references_from_semantic_fields():
    payload = {
        "asset_bindings": [
            {"asset_id": "image_1", "role": "product", "inherit": ["geometry"], "exclude": ["background"]},
            {"asset_id": "video_1", "role": "motion", "inherit": ["hand motion"], "exclude": ["identity"]},
        ],
        "subjects": [{"subject_id": "subject_1", "kind": "product", "source_asset_ids": ["image_1"]}],
        "creative_focus": {"primary_subject_id": "subject_1", "primary_asset_id": "image_1", "required_shot_ids": ["01"]},
        "timeline": [{"shot_id": "01", "subject_refs": ["subject_1"], "asset_refs": ["video_1"]}],
        "isolation_rules": [{"binding_id": "model_invented", "allow": ["wrong"], "block": []}],
    }

    derive_binding_graph(payload)

    assert [item["binding_id"] for item in payload["asset_bindings"]] == ["binding_001", "binding_002"]
    assert payload["subjects"][0]["binding_ids"] == ["binding_001"]
    assert payload["creative_focus"]["primary_binding_ids"] == ["binding_001"]
    assert payload["timeline"][0]["subject_refs"] == ["subject_1"]
    assert payload["timeline"][0]["binding_refs"] == ["binding_001", "binding_002"]
    assert "asset_refs" not in payload["timeline"][0]
    assert payload["isolation_rules"] == [
        {"binding_id": "binding_001", "allow": ["geometry"], "block": ["background"]},
        {"binding_id": "binding_002", "allow": ["hand motion"], "block": ["identity"]},
    ]


def test_binding_graph_attaches_primary_subject_to_required_focus_shot():
    payload = {
        "asset_bindings": [{"asset_id": "image_1", "role": "product", "inherit": ["geometry"], "exclude": []}],
        "subjects": [{"subject_id": "subject_1", "kind": "product", "source_asset_ids": ["image_1"]}],
        "creative_focus": {"primary_subject_id": "subject_1", "primary_asset_id": "image_1", "required_shot_ids": ["02"]},
        "timeline": [{"shot_id": "02", "subject_refs": []}],
    }
    derive_binding_graph(payload)
    assert payload["timeline"][0]["subject_refs"] == ["subject_1"]
    assert payload["timeline"][0]["binding_refs"] == ["binding_001"]


def test_object_identity_binding_is_valid_appearance_authority():
    payload = {
        "asset_bindings": [
            {"asset_id": "image_1", "role": "identity", "inherit": ["object identity"], "exclude": []},
            {"asset_id": "image_1", "role": "motion", "inherit": ["fabric motion"], "exclude": []},
        ],
        "subjects": [{"subject_id": "subject_1", "kind": "object", "source_asset_ids": ["image_1"]}],
        "reference_relationships": [{"asset_id": "image_1", "subject_refs": ["subject_1"]}],
        "creative_focus": {"primary_subject_id": "subject_1", "primary_asset_id": "image_1", "required_shot_ids": ["01"]},
        "timeline": [{"shot_id": "01", "subject_refs": ["subject_1"]}],
    }
    derive_binding_graph(payload)
    assert payload["subjects"][0]["binding_ids"] == ["binding_001", "binding_002"]


def test_binding_graph_recovers_related_appearance_source_but_not_structural_source():
    payload = {
        "asset_bindings": [
            {"asset_id": "image_1", "role": "identity", "inherit": ["face"], "exclude": []},
            {"asset_id": "image_2", "role": "outfit", "inherit": ["glasses"], "exclude": []},
            {"asset_id": "video_1", "role": "motion", "inherit": ["performance"], "exclude": ["identity"]},
        ],
        "subjects": [{"subject_id": "subject_1", "kind": "person", "source_asset_ids": ["image_1"]}],
        "reference_relationships": [
            {"asset_id": "image_1", "subject_refs": ["subject_1"]},
            {"asset_id": "image_2", "subject_refs": ["subject_1"]},
            {"asset_id": "video_1", "subject_refs": ["subject_1"]},
        ],
        "creative_focus": {"primary_subject_id": "subject_1", "primary_asset_id": "image_1", "required_shot_ids": ["01"]},
        "timeline": [{"shot_id": "01", "subject_refs": ["subject_1"]}],
    }

    derive_binding_graph(payload)

    assert payload["subjects"][0]["source_asset_ids"] == ["image_1", "image_2"]
    assert payload["subjects"][0]["binding_ids"] == ["binding_001", "binding_002", "binding_003"]


def test_binding_graph_routes_multi_subject_targets_and_worn_product_sources():
    payload = {
        "asset_bindings": [
            {"asset_id": "image_1", "target": "subject_1 identity", "role": "identity", "inherit": ["first face"], "exclude": []},
            {"asset_id": "image_1", "target": "subject_2 identity", "role": "identity", "inherit": ["second face"], "exclude": []},
            {"asset_id": "image_2", "target": "subject_1 eyewear product", "role": "product", "inherit": ["first glasses"], "exclude": []},
            {"asset_id": "image_2", "target": "subject_2 eyewear product", "role": "product", "inherit": ["second glasses"], "exclude": []},
        ],
        "subjects": [
            {"subject_id": "subject_1", "kind": "person", "source_asset_ids": ["image_1"]},
            {"subject_id": "subject_2", "kind": "person", "source_asset_ids": ["image_1"]},
        ],
        "reference_relationships": [
            {"asset_id": "image_1", "subject_refs": ["subject_1", "subject_2"]},
            {"asset_id": "image_2", "subject_refs": ["subject_1", "subject_2"]},
        ],
        "creative_focus": {"primary_subject_id": "subject_1", "primary_asset_id": "image_2", "required_shot_ids": ["01"]},
        "timeline": [{"shot_id": "01", "subject_refs": ["subject_1", "subject_2"]}],
    }

    derive_binding_graph(payload)

    first, second = payload["subjects"]
    assert first["source_asset_ids"] == ["image_1", "image_2"]
    assert second["source_asset_ids"] == ["image_1", "image_2"]
    assert first["binding_ids"] == ["binding_001", "binding_003"]
    assert second["binding_ids"] == ["binding_002", "binding_004"]


class DirectiveBindingCompilerTests(unittest.TestCase):
    def test_applies_a_cited_directive_scope_to_every_citing_binding(self):
        source = {
            "assets": [{"asset_id": "image_1"}],
            "directives": [{
                "directive_id": "d_characters",
                "asset_id": "image_1",
                "target": "character asset appearance",
                "operation": "preserve",
                "scope": ["character appearance"],
                "priority": "hard",
            }],
        }
        payload = {
            "asset_bindings": [
                {"binding_id": "b_woman", "asset_id": "image_1", "role": "identity", "priority": "hard", "source_directive_ids": ["d_characters"], "inherit": ["woman's face"], "exclude": []},
                {"binding_id": "b_man", "asset_id": "image_1", "role": "identity", "priority": "hard", "source_directive_ids": ["d_characters"], "inherit": ["man's coat"], "exclude": []},
            ],
            "isolation_rules": [], "constraints": {}, "timeline": [], "subjects": [],
            "creative_focus": {"primary_binding_ids": []},
        }
        result = compile_directive_bindings(copy.deepcopy(payload), source)
        for binding in result["asset_bindings"]:
            self.assertIn("character appearance", binding["inherit"])

    def test_repairs_contract_and_routes_global_directives(self):
        source = {
            "assets": [{"asset_id": "image_1"}, {"asset_id": "video_1"}],
            "directives": [
                {"directive_id": "d_product", "asset_id": "image_1", "target": "product appearance", "operation": "preserve", "scope": ["shape", "color"], "priority": "hard"},
                {"directive_id": "d_motion", "asset_id": "video_1", "target": "motion and timing", "operation": "transfer", "scope": ["hand actions", "timing"], "priority": "hard"},
                {"directive_id": "d_exclude", "asset_id": "video_1", "target": "reference contamination", "operation": "exclude", "scope": ["person identity", "product appearance"], "priority": "hard"},
                {"directive_id": "d_no_text", "asset_id": "", "target": "visible extras", "operation": "exclude", "scope": ["subtitles"], "priority": "hard"},
            ],
        }
        payload = {"asset_bindings": [
            {"binding_id": "b_product", "asset_id": "image_1", "role": "product", "priority": "soft", "source_directive_ids": ["d_product"], "inherit": [], "exclude": []},
            {"binding_id": "b_fake", "asset_id": "global", "role": "scene", "priority": "hard", "source_directive_ids": ["d_no_text"], "inherit": [], "exclude": []},
        ], "isolation_rules": [], "constraints": {}, "timeline": [], "subjects": [], "creative_focus": {"primary_binding_ids": ["b_product", "b_fake"]}}
        result = compile_directive_bindings(copy.deepcopy(payload), source)
        self.assertNotIn("b_fake", {item["binding_id"] for item in result["asset_bindings"]})
        product = next(item for item in result["asset_bindings"] if item["asset_id"] == "image_1")
        self.assertEqual(product["priority"], "hard")
        self.assertEqual(product["inherit"], ["shape", "color"])
        video = next(item for item in result["asset_bindings"] if item["asset_id"] == "video_1")
        self.assertIn("hand actions", video["inherit"])
        self.assertIn("person identity", video["exclude"])
        rule = next(item for item in result["isolation_rules"] if item["binding_id"] == video["binding_id"])
        self.assertIn("person identity", rule["block"])
        self.assertIn("subtitles", result["constraints"]["prohibit"])


if __name__ == "__main__":
    unittest.main()
