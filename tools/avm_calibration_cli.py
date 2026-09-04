"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_context import *


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or apply AVM calibration config_patch to datas/avm/config.json")
    parser.add_argument("--config", type=Path, default=Path("datas/avm/config.json"))
    parser.add_argument("--calibration", type=Path, default=Path("datas/avm/calibration_targets.json"))
    parser.add_argument("--write", action="store_true", help="Write merged config back to --config; default is dry-run preview only")
    parser.add_argument(
        "--target-type",
        dest="target_types",
        choices=["temporal", "global_risk", "risk_flag"],
        action="append",
        help="Only apply patch entries for the selected calibration target type; repeat to include multiple target types",
    )
    parser.add_argument(
        "--target-name",
        dest="target_names",
        action="append",
        help="Only apply patch entries for the selected calibration target name; repeat to include multiple target names",
    )
    args = parser.parse_args()

    result = apply_avm_calibration_patch(
        config_path=args.config,
        calibration_path=args.calibration,
        write_back=args.write,
        target_types=args.target_types,
        target_names=args.target_names,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


__all__ = (
    'main',
)
