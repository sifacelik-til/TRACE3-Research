"""
CLI wrapper for target emissions profile report generation.
"""

import argparse
from pathlib import Path


from dataset_readers.report_builder import OUT_DIR, build_target_emissions_profile_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build per-year (2014-2024) target Trucost emissions profile report "
            "for a FactSet entity."
        )
    )
    parser.add_argument(
        "--factset_id",
        required=True,
        help="FactSet entity ID of the target company (e.g. 000VJS-E)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output Excel path. Default: data/outputs/dataset_readers/<factset_id>_emissions_profile.xlsx",
    )
    args = parser.parse_args()

    factset_id = args.factset_id.strip()
    output_path = Path(args.output) if args.output else (
        OUT_DIR / f"{factset_id.replace('-', '_')}_emissions_profile.xlsx"
    )

    build_target_emissions_profile_report(factset_id=factset_id, output_path=output_path)


if __name__ == "__main__":
    main()
