import math
import unittest

from src.avm_weighting import (
    compute_location_weights,
    distance_weight_km,
    location_multiplier,
    normalize_weights,
)


class AvmWeightingTest(unittest.TestCase):
    def test_distance_weight_gaussian_monotonic(self):
        near = distance_weight_km(0.1, method="gaussian")
        far = distance_weight_km(2.8, method="gaussian")
        self.assertGreater(near, far)

    def test_distance_weight_idw_bounded(self):
        w0 = distance_weight_km(0.0, method="idw")
        w10 = distance_weight_km(10.0, method="idw")
        self.assertGreaterEqual(w0, 0.05)
        self.assertLessEqual(w0, 1.0)
        self.assertGreaterEqual(w10, 0.05)
        self.assertLessEqual(w10, 1.0)

    def test_location_multiplier_rules(self):
        base = location_multiplier(False, False, True)
        same_community = location_multiplier(True, False, True)
        same_business = location_multiplier(False, True, True)
        cross_district = location_multiplier(False, False, False)

        self.assertGreater(same_community, base)
        self.assertGreater(same_business, base)
        self.assertLess(cross_district, base)

    def test_normalization(self):
        w = normalize_weights([0.9, 0.1])
        self.assertAlmostEqual(sum(w), 1.0, places=6)
        self.assertGreater(w[1], 0.0)

    def test_compute_location_weights(self):
        comps = [
            {
                "distance_km": 0.2,
                "same_community": True,
                "same_business_area": True,
                "same_district": True,
            },
            {
                "distance_km": 2.0,
                "same_community": False,
                "same_business_area": False,
                "same_district": False,
            },
        ]
        weights = compute_location_weights(comps)
        self.assertAlmostEqual(sum(weights), 1.0, places=6)
        self.assertGreater(weights[0], weights[1])


if __name__ == "__main__":
    unittest.main()
