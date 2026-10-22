"""Pure-Python tests for VLA (waypoint-head) divergence metrics."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


_MODULE_PATH = (Path(__file__).parent.parent / "vicone" / "labr7" / "radeis" /
                "report" / "metrics.py")
_SPEC = importlib.util.spec_from_file_location("metrics_under_test", _MODULE_PATH)
M = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(M)

# Station 0 clean prediction and a station 1 attack prediction from the v024
# Warehouse evaluation (frozen query_best.pt head, actual Isaac frames).
BASE = [[1.2962, 0.0034], [2.5805, 0.0119], [3.847, 0.0231], [5.1101, 0.0292],
        [6.3728, 0.0344], [7.6329, 0.045], [8.8876, 0.062], [10.1089, 0.0776]]
ATTACK = [[1.2766, -0.0448], [2.5481, -0.1408], [3.8129, -0.2764], [5.0885, -0.4853],
          [6.3541, -0.7679], [7.608, -1.1292], [8.8731, -1.3896], [10.102, -1.6248]]


def _rec(intent, wp, stop=0.001):
    return {"action_token": intent, "waypoints": wp, "waypoint_dt_s": 0.8,
            "stop_probability": stop, "logit_margin": None}


class WaypointShiftTests(unittest.TestCase):
    def test_real_turn_right_shift(self):
        s = M.waypoint_shift(BASE, ATTACK, 0.8, 0.6)
        self.assertAlmostEqual(s["fde"], 1.7024, places=3)
        self.assertAlmostEqual(s["ade"], 0.7694, places=3)
        self.assertAlmostEqual(s["heading_deg"], -9.58, places=1)
        # first |y| > 0.6 m is waypoint 5 (y = -0.768) → 5 × 0.8 s
        self.assertAlmostEqual(s["corridor_exit_s"], 4.0)

    def test_identical_paths(self):
        s = M.waypoint_shift(BASE, BASE)
        self.assertEqual((s["ade"], s["fde"], s["corridor_exit_s"]), (0.0, 0.0, None))

    def test_missing_path(self):
        self.assertIsNone(M.waypoint_shift(None, ATTACK))


class VlaDivergenceTests(unittest.TestCase):
    def test_intent_flip_is_behavior_change(self):
        d = M.station_divergence(_rec("direction_straight", BASE),
                                 _rec("direction_right", ATTACK), "vla", 0.5)
        self.assertTrue(d["behavior_changed"] and d["intent_flip"])
        self.assertFalse(d["path_drift"] or d["vla_fallback"] or d["traj_flag"])
        self.assertAlmostEqual(d["severity"], round(0.6 + 0.4 * 1.7024 / 4.0, 3), places=3)

    def test_path_drift_without_flip(self):
        d = M.station_divergence(_rec("direction_straight", BASE),
                                 _rec("direction_straight", ATTACK), "vla", 0.5)
        self.assertFalse(d["behavior_changed"])
        self.assertTrue(d["path_drift"])
        self.assertAlmostEqual(d["severity"], round(0.4 * 1.7024 / 4.0, 3), places=3)

    def test_small_shift_is_robust(self):
        d = M.station_divergence(_rec("direction_straight", BASE),
                                 _rec("direction_straight", BASE), "vla", 0.5)
        self.assertFalse(d["behavior_changed"] or d["path_drift"])
        self.assertEqual(d["severity"], 0.0)

    def test_no_waypoints_falls_back_to_action(self):
        d = M.station_divergence({"action_token": "Forward"}, {"action_token": "Stop"}, "vla")
        self.assertTrue(d["vla_fallback"] and d["behavior_changed"])
        self.assertNotIn("fde", d)

    def test_vlm_mode_ignores_waypoints(self):
        d = M.station_divergence(_rec("Forward", BASE), _rec("Forward", ATTACK), "vlm")
        self.assertNotIn("fde", d)
        self.assertFalse(d["behavior_changed"])


if __name__ == "__main__":
    unittest.main()
