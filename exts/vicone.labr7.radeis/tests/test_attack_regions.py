"""Pure-Python tests for patch metadata and attention-region calculations."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


_MODULE_PATH = (Path(__file__).parent.parent / "vicone" / "labr7" / "radeis" /
                "vlm" / "attack_regions.py")
_SPEC = importlib.util.spec_from_file_location("attack_regions_under_test", _MODULE_PATH)
AR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(AR)

_SI_SPEC = importlib.util.spec_from_file_location(
    "sample_index_under_test", _MODULE_PATH.parent / "sample_index.py")
SI = importlib.util.module_from_spec(_SI_SPEC)
_SI_SPEC.loader.exec_module(SI)
_SAMPLES = Path(__file__).parent.parent / "data" / "test_samples"


def _shipped(cat, sign):
    return SI.load_sample_index(str(_SAMPLES))[cat][sign]


class PatchMetadataTests(unittest.TestCase):
    def test_case_info_folder_is_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            sign = Path(tmp) / "go_forward"
            case = sign / "go_forward_mod" / "2" / "2.1"
            image = case / "patch.png"
            (case / "info").mkdir(parents=True)
            image.touch()
            baseline = sign / "go_forward.png"
            baseline.touch()
            (case / "info" / "patch_info.json").write_text(json.dumps({
                "target_model": "vlm", "attack_type": "noise_like_patch",
                "image_size": [256, 256], "bbox": [64, 64, 193, 193],
            }))

            metadata, errors = AR.load_attack_patch_metadata({
                "baseline": str(baseline), "attacks": {"1": str(image)}})

            self.assertEqual(errors, [])
            self.assertEqual(metadata["1"]["patch_bbox"], [64, 64, 193, 193])
            self.assertEqual(metadata["1"]["patch_source_rel"], "2/2.1/patch.png")
            self.assertEqual(metadata["1"]["patch_attack_type"], "noise_like_patch")

    def test_missing_case_info_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "s_mod" / "1" / "1.1" / "x.png"
            image.parent.mkdir(parents=True)
            image.touch()
            metadata, errors = AR.load_attack_patch_metadata({
                "baseline": str(Path(tmp) / "s.png"), "attacks": {"1": str(image)}})
            self.assertEqual(metadata, {})
            self.assertEqual(len(errors), 1)

    def test_shipped_samples_all_resolve(self):
        for signs in SI.load_sample_index(str(_SAMPLES)).values():
            for entry in signs.values():
                for policy, attacks in entry["attacks_by_policy"].items():
                    if not attacks:
                        continue
                    metadata, errors = AR.load_attack_patch_metadata(dict(entry, attacks=attacks))
                    self.assertEqual(errors, [])
                    self.assertEqual(set(metadata), set(attacks))
                    # every case listed for a policy must declare that policy in patch_info.json
                    self.assertEqual(set(AR.attacks_for_model(attacks, metadata, policy)), set(attacks),
                                     f"{entry['label']} {policy}")


class AttackFilterTests(unittest.TestCase):
    def test_filter_by_target_model(self):
        attacks = {"1": "a.png", "2": "b.png", "3": "c.png"}
        meta = {"1": {"patch_target_model": "vlm"}, "2": {"patch_target_model": "vla"}}
        self.assertEqual(AR.attacks_for_model(attacks, meta, "vla"), {"2": "b.png"})
        # "3" has no metadata: legacy case, counts as VLM
        self.assertEqual(AR.attacks_for_model(attacks, meta, "vlm"), {"1": "a.png", "3": "c.png"})

    def test_case_valid_for_both_policies(self):
        attacks = {"1": "a.png", "2": "b.png", "3": "c.png"}
        meta = {"1": {"patch_target_model": "vlm"}, "2": {"patch_target_model": "vla"},
                "3": {"patch_target_model": ["vlm", "VLA"]}}
        self.assertEqual(AR.attacks_for_model(attacks, meta, "vla"), {"2": "b.png", "3": "c.png"})
        self.assertEqual(AR.attacks_for_model(attacks, meta, "vlm"), {"1": "a.png", "3": "c.png"})
        self.assertEqual(AR.target_models({"patch_target_model": []}), ["vlm"])

    def test_shipped_go_forward_sequences(self):
        entry = _shipped("traffic", "go_forward")
        for policy, expected in (("vlm", ["2.4", "1.3", "3.5", "4.2", "5.1", "6.4"]),
                                 ("vla", ["7.1", "3.1", "4.1", "6.4"])):
            attacks = entry["attacks_by_policy"][policy]
            meta, _ = AR.load_attack_patch_metadata(dict(entry, attacks=attacks))
            self.assertEqual([meta[i]["patch_case_id"] for i in AR.sequence(attacks)], expected)


class SampleIndexTests(unittest.TestCase):
    def _index(self, tmp, entry):
        Path(tmp, "index.json").write_text(json.dumps({"categories": {"c": {"s": entry}}}))
        return SI.load_sample_index(tmp)["c"]["s"]["attacks_by_policy"]

    def test_policy_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            by = self._index(tmp, {"baseline": "s.png", "vlm": {"1": "a.png"}})
            self.assertEqual(by["vlm"], {"1": str(Path(tmp, "a.png"))})
            self.assertEqual(by["vla"], {})          # no "vla" block: nothing to test in VLA

    def test_legacy_attacks_block_feeds_both_policies(self):
        with tempfile.TemporaryDirectory() as tmp:
            by = self._index(tmp, {"baseline": "s.png", "attacks": {"1": "a.png"}})
            self.assertEqual(by["vlm"], by["vla"])

    def test_sequence_is_numeric(self):
        self.assertEqual(AR.sequence({"10": 0, "2": 0, "1": 0, "7.r2": 0}), ["1", "2", "10", "7.r2"])


class CycleAttacksTests(unittest.TestCase):
    def test_one_case_fills_four_slots(self):
        attacks, meta = AR.cycle_attacks({"7": "a.png"}, {"7": {"patch_bbox": [1, 2, 3, 4]}}, 4)
        self.assertEqual(list(attacks), ["7", "7.r2", "7.r3", "7.r4"])
        self.assertEqual(sorted(attacks), list(attacks))   # stations.assign_sign sorts keys
        self.assertEqual(meta["7.r3"], {"patch_bbox": [1, 2, 3, 4]})

    def test_enough_cases_unchanged(self):
        attacks, _ = AR.cycle_attacks({"1": "a", "2": "b"}, {}, 2)
        self.assertEqual(attacks, {"1": "a", "2": "b"})

    def test_cycle_keeps_sequence(self):
        attacks, _ = AR.cycle_attacks({"2": "b", "1": "a"}, {}, 4)
        self.assertEqual(list(attacks), ["1", "2", "1.r2", "2.r2"])


class ProjectionMappingTests(unittest.TestCase):
    QUAD = [[100, 400], [500, 400], [500, 100], [100, 100]]

    def test_full_texture_maps_to_full_sign(self):
        self.assertEqual(
            AR.map_texture_bbox_to_frame(
                self.QUAD, [0, 0, 256, 256], [256, 256], [640, 480]),
            [100, 100, 500, 400],
        )

    def test_localized_patch_maps_with_top_left_image_origin(self):
        self.assertEqual(
            AR.map_texture_bbox_to_frame(
                self.QUAD, [64, 64, 192, 192], [256, 256], [640, 480]),
            [200, 175, 400, 325],
        )


class AttentionMetricTests(unittest.TestCase):
    HEATMAP = {"grid_w": 2, "grid_h": 2, "data": [[1.0, 2.0], [3.0, 4.0]]}

    def test_native_grid_mass_for_one_cell(self):
        mass = AR.attention_mass_in_bbox(self.HEATMAP, [0, 0, 50, 50], [100, 100])
        self.assertAlmostEqual(mass, 0.1)

    def test_fractional_cell_overlap(self):
        mass = AR.attention_mass_in_bbox(self.HEATMAP, [25, 0, 50, 50], [100, 100])
        self.assertAlmostEqual(mass, 0.05)

    def test_relocation_metrics(self):
        self.assertEqual(
            AR.relocation_metrics(0.1, 0.25),
            {"aram": 0.25, "baseline_aram": 0.1, "tram": 2.5, "ads": 0.15},
        )

    def test_zero_baseline_has_no_finite_tram(self):
        result = AR.relocation_metrics(0.0, 0.25)
        self.assertIsNone(result["tram"])
        self.assertEqual(result["ads"], 0.25)


if __name__ == "__main__":
    unittest.main()
