import unittest
from datetime import date

from src.avm_temporal import TemporalAdjuster, configure_temporal_adjuster, temporal_adjust


class TemporalAdjustTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"city": "shanghai", "district": "pudong", "business_area": "zhangjiang", "auction_date": "2024-01-05", "unit_price": 10000},
            {"city": "shanghai", "district": "pudong", "business_area": "zhangjiang", "auction_date": "2024-02-01", "unit_price": 10500},
            {"city": "shanghai", "district": "pudong", "business_area": "zhangjiang", "auction_date": "2024-03-12", "unit_price": 11000},
            {"city": "shanghai", "district": "pudong", "business_area": "zhangjiang", "auction_date": "2024-04-06", "unit_price": 11500},
            {"city": "shanghai", "district": "pudong", "business_area": "zhangjiang", "auction_date": "2024-05-21", "unit_price": 12000},
            {"city": "shanghai", "district": "pudong", "business_area": "zhangjiang", "auction_date": "2024-06-08", "unit_price": 12500},
        ]

    def test_adjust_upward_trend(self):
        model = TemporalAdjuster(self.records, current_date=date(2024, 6, 1))
        adjusted = model.temporal_adjust(
            price=1_000_000,
            subject_date="2024-01-01",
            region={"city": "shanghai", "district": "pudong", "business_area": "zhangjiang"},
        )
        self.assertGreater(adjusted, 1_100_000)

    def test_fallback_to_district_level(self):
        model = TemporalAdjuster(self.records, current_date=date(2024, 6, 1))
        adjusted = model.temporal_adjust(
            price=1_000_000,
            subject_date="2024-01-01",
            region={"city": "shanghai", "district": "pudong", "business_area": "unknown"},
        )
        self.assertGreater(adjusted, 1_000_000)

    def test_public_api(self):
        configure_temporal_adjuster(self.records, current_date=date(2024, 6, 1))
        adjusted = temporal_adjust(
            1_000_000,
            "2024-02-01",
            {"city": "shanghai", "district": "pudong", "business_area": "zhangjiang"},
        )
        self.assertGreater(adjusted, 1_000_000)


if __name__ == "__main__":
    unittest.main()
