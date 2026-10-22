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
        samples = Path(__file__).parent.parent / "data" / "test_samples"
        index = json.loads((samples / "index.json").read_text())
        for signs in index["categories"].values():
            for entry in signs.values():
                if not entry.get("attacks"):
                    continue
                metadata, errors = AR.load_attack_patch_metadata({
                    "baseline": str(samples / entry["baseline"]),
                    "attacks": {k: str(samples / v) for k, v in entry["attacks"].items()}})
                self.assertEqual(errors, [])
                self.assertEqual(set(metadata), set(entry["attacks"]))


class AttackFilterTests(unittest.TestCase):
    def test_filter_by_target_model(self):
        attacks = {"1": "a.png", "2": "b.png", "3": "c.png"}
        meta = {"1": {"patch_target_model": "vlm"}, "2": {"patch_target_model": "vla"}}
        self.assertEqual(AR.attacks_for_model(attacks, meta, "vla"), {"2": "b.png"})
        # "3" has no metadata: legacy case, counts as VLM
        self.assertEqual(AR.attacks_for_model(attacks, meta, "vlm"), {"1": "a.png", "3": "c.png"})

    def test_shipped_go_forward_has_one_vla_case(self):
        samples = Path(__file__).parent.parent / "data" / "test_samples"
        entry = json.loads((samples / "index.json").read_text())["categories"]["traffic"]["go_forward"]
        attacks = {k: str(samples / v) for k, v in entry["attacks"].items()}
        meta, errors = AR.load_attack_patch_metadata({"baseline": str(samples / entry["baseline"]), "attacks": attacks})
        self.assertEqual(errors, [])
        self.assertEqual(list(AR.attacks_for_model(attacks, meta, "vla")), ["7"])
        self.assertEqual(len(AR.attacks_for_model(attacks, meta, "vlm")), 6)


class CycleAttacksTests(unittest.TestCase):
    def test_one_case_fills_four_slots(self):
        attacks, meta = AR.cycle_attacks({"7": "a.png"}, {"7": {"patch_bbox": [1, 2, 3, 4]}}, 4)
        self.assertEqual(list(attacks), ["7", "7.r2", "7.r3", "7.r4"])
        self.assertEqual(sorted(attacks), list(attacks))   # stations.assign_sign sorts keys
        self.assertEqual(meta["7.r3"], {"patch_bbox": [1, 2, 3, 4]})

    def test_enough_cases_unchanged(self):
        attacks, _ = AR.cycle_attacks({"1": "a", "2": "b"}, {}, 2)
        self.assertEqual(attacks, {"1": "a", "2": "b"})


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
