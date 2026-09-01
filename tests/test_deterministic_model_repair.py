import unittest

from backend.context_ir import (
    normalize_binding_isolation_conflicts,
    normalize_global_constraint_conflicts,
    normalize_primary_subject,
    normalize_subject_appearance_shots,
    normalize_timeline_boundaries,
)


class DeterministicModelRepairTests(unittest.TestCase):
    def test_focus_subject_becomes_the_only_primary(self):
        payload = {
            "creative_focus": {"primary_subject_id": "subject_2"},
            "subjects": [
                {"subject_id": "subject_1", "primary": True},
                {"subject_id": "subject_2", "primary": False},
            ],
        }
        normalize_primary_subject(payload)
        self.assertEqual([item["primary"] for item in payload["subjects"]], [False, True])

    def test_controlled_property_wins_exact_isolation_collision(self):
        payload = {
            "asset_bindings": [{"binding_id": "b1", "inherit": ["motion"], "exclude": ["motion", "identity"]}],
            "isolation_rules": [{"binding_id": "b1", "allow": ["motion"], "block": ["motion", "identity"]}],
        }
        normalize_binding_isolation_conflicts(payload)
        self.assertEqual(payload["asset_bindings"][0]["exclude"], ["identity"])
        self.assertEqual(payload["isolation_rules"][0]["block"], ["identity"])

    def test_timeline_gaps_and_overlaps_are_closed(self):
        payload = {
            "task": {"duration_seconds": 15},
            "timeline": [
                {"start_seconds": 0, "end_seconds": 3},
                {"start_seconds": 3.5, "end_seconds": 7},
                {"start_seconds": 6, "end_seconds": 11},
                {"start_seconds": 11, "end_seconds": 14.5},
            ],
        }
        normalize_timeline_boundaries(payload)
        self.assertEqual(
            [(item["start_seconds"], item["end_seconds"]) for item in payload["timeline"]],
            [(0.0, 3.0), (3.0, 7.0), (7.0, 11.0), (11.0, 15.0)],
        )

    def test_subject_appearance_index_is_derived_from_timeline(self):
        payload = {
            "subjects": [{"subject_id": "subject_1", "appearance_shot_ids": ["99"]}],
            "timeline": [
                {"shot_id": "01", "subject_refs": ["subject_1"]},
                {"shot_id": "02", "subject_refs": []},
            ],
        }
        normalize_subject_appearance_shots(payload)
        self.assertEqual(payload["subjects"][0]["appearance_shot_ids"], ["01"])

    def test_preserve_wins_exact_global_constraint_duplicate(self):
        payload = {"constraints": {"preserve": ["product geometry"], "allow_change": ["product geometry", "lighting"], "prohibit": ["product geometry"]}}
        normalize_global_constraint_conflicts(payload)
        self.assertEqual(payload["constraints"]["allow_change"], ["lighting"])
        self.assertEqual(payload["constraints"]["prohibit"], [])


if __name__ == "__main__":
    unittest.main()
