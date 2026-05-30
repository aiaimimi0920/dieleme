import unittest
from datetime import date

from src.avm_temporal import TemporalAdjuster, configure_temporal_adjuster, temporal_adjust, temporal_factor


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

    def test_trend_factor_uses_latest_sample_date_by_default(self):
        model = TemporalAdjuster(self.records, current_date=date(2024, 6, 1))
        factor, sample_count = model.trend_factor(
            region={"city": "shanghai", "district": "pudong", "business_area": "zhangjiang"},
            target_date=date(2024, 6, 1),
            clamp=(0.75, 1.25),
        )
        self.assertGreater(factor, 0.99)
        self.assertLessEqual(factor, 1.25)
        self.assertEqual(sample_count, 6)

    def test_trend_factor_can_use_explicit_reference_date(self):
        model = TemporalAdjuster(self.records, current_date=date(2024, 6, 1))
        factor, sample_count = model.trend_factor(
            region={"city": "shanghai", "district": "pudong", "business_area": "zhangjiang"},
            target_date=date(2024, 6, 1),
            reference_date=date(2024, 2, 1),
            clamp=None,
        )
        self.assertGreater(factor, 1.0)
        self.assertEqual(sample_count, 6)

    def test_public_temporal_factor_api(self):
        configure_temporal_adjuster(self.records, current_date=date(2024, 6, 1))
        factor, sample_count = temporal_factor(
            target_date=date(2024, 6, 1),
            region={"city": "shanghai", "district": "pudong", "business_area": "zhangjiang"},
            reference_date=date(2024, 2, 1),
        )
        self.assertGreater(factor, 1.0)
        self.assertEqual(sample_count, 6)

    def test_trend_factor_prefers_neutral_unit_price_when_present(self):
        records = [
            {
                "city": "shanghai",
                "district": "pudong",
                "business_area": "zhangjiang",
                "auction_date": "2024-01-05",
                "unit_price": 10000,
                "_neutral_unit_price": 10000,
            },
            {
                "city": "shanghai",
                "district": "pudong",
                "business_area": "zhangjiang",
                "auction_date": "2024-02-01",
                "unit_price": 10000,
                "_neutral_unit_price": 20000,
            },
        ]
        model = TemporalAdjuster(records, current_date=date(2024, 2, 1))
        factor, sample_count = model.trend_factor(
            region={"city": "shanghai", "district": "pudong", "business_area": "zhangjiang"},
            target_date=date(2024, 2, 1),
            reference_date=date(2024, 1, 1),
            clamp=None,
        )
        self.assertGreater(factor, 1.5)
        self.assertEqual(sample_count, 2)

    def test_trend_factor_respects_time_decay(self):
        no_decay = TemporalAdjuster(self.records, current_date=date(2024, 6, 1), time_decay=1.0)
        decayed = TemporalAdjuster(self.records, current_date=date(2024, 6, 1), time_decay=0.5)

        no_decay_factor, _ = no_decay.trend_factor(
            region={"city": "shanghai", "district": "pudong", "business_area": "zhangjiang"},
            target_date=date(2024, 6, 1),
            reference_date=date(2024, 1, 1),
            clamp=None,
        )
        decayed_factor, _ = decayed.trend_factor(
            region={"city": "shanghai", "district": "pudong", "business_area": "zhangjiang"},
            target_date=date(2024, 6, 1),
            reference_date=date(2024, 1, 1),
            clamp=None,
        )

        self.assertGreater(no_decay_factor, 1.0)
        self.assertGreater(decayed_factor, 1.0)
        self.assertLess(decayed_factor, no_decay_factor)


if __name__ == "__main__":
    unittest.main()
