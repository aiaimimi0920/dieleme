import unittest

from src.avm.engine import risk_adjustment


class RiskAdjustmentTests(unittest.TestCase):
    def test_negative_factors(self):
        features = {
            "occupation": True,
            "allocated": True,
            "enterprise_property_tax": False,
            "long_term_lease": True,
        }
        self.assertAlmostEqual(risk_adjustment(features), -0.25)

    def test_lease_before_mortgage_bonus_with_default_cap(self):
        features = {
            "has_lease_before_mortgage": True,
            "lease_before_mortgage_bonus": 0.05,
        }
        self.assertAlmostEqual(risk_adjustment(features), 0.03)

    def test_lease_before_mortgage_custom_cap(self):
        features = {
            "has_lease_before_mortgage": True,
            "lease_before_mortgage_bonus": 0.05,
            "lease_before_mortgage_cap": 0.04,
        }
        self.assertAlmostEqual(risk_adjustment(features), 0.04)


if __name__ == "__main__":
    unittest.main()
