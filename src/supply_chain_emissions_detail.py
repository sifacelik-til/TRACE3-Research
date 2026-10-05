"""
CLI wrapper for supply chain emissions detail report generation.
"""

import argparse
from pathlib import Path

from data_engine.report_builder import (
    OUT_DIR,
    build_supply_chain_emissions_detail_report,
    build_target_emissions_profile_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build per-year (2014-2024) supply chain emissions detail report "
            "for a FactSet target entity. Optionally generate both reports in one run."
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
        help="Detail output Excel path. Default: data/outputs/dataset_readers/<factset_id>_supply_chain_detail.xlsx",
    )
    parser.add_argument(
        "--profile_output",
        default=None,
        help=(
            "Optional: if provided, also build target emissions profile report in same run "
            "(shared processing, no duplicate loading)."
        ),
    )
    parser.add_argument(
        "--build_both",
        action="store_true",
        help="Build both detail and profile reports in one run using shared loaded data.",
    )
    args = parser.parse_args()

    factset_id = args.factset_id.strip()
    detail_output = Path(args.output) if args.output else (
        OUT_DIR / f"{factset_id.replace('-', '_')}_supply_chain_detail.xlsx"
    )

    context = build_supply_chain_emissions_detail_report(
        factset_id=factset_id,
        output_path=detail_output,
        reuse_context=None,
    )

    if args.build_both or args.profile_output is not None:
        profile_output = Path(args.profile_output) if args.profile_output else (
            OUT_DIR / f"{factset_id.replace('-', '_')}_emissions_profile.xlsx"
        )
        build_target_emissions_profile_report(
            factset_id=factset_id,
            output_path=profile_output,
            reuse_context=context,
        )


if __name__ == "__main__":
    main()
