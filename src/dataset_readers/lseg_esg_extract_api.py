from __future__ import annotations

import argparse
import datetime as dt
import warnings
from pathlib import Path
from typing import List

import pandas as pd
import lseg.data as ld


def normalize_response_values(df: pd.DataFrame) -> pd.DataFrame:
    """Keep numeric values numeric and reshape long Field/Value responses if needed."""
    if df is None or df.empty:
        return df

    out = df.copy()

    if {"Field", "Value"}.issubset(out.columns):
        id_cols = [c for c in out.columns if c not in {"Field", "Value"}]
        if id_cols:
            out = out.pivot_table(index=id_cols, columns="Field", values="Value", aggfunc="first").reset_index()

    for col in out.columns:
        if col in {"Instrument", "Company Common Name", "UniverseName", "UniverseTRBCIndustryGroup", "UniverseCountryOfDomicile"}:
            continue
        if pd.api.types.is_bool_dtype(out[col]) or pd.api.types.is_numeric_dtype(out[col]):
            continue
        if pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            cleaned = out[col].astype(str).str.strip()
            cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
            cleaned = cleaned.replace({"True": "1", "False": "0"})
            numeric = pd.to_numeric(cleaned, errors="coerce")
            if cleaned.notna().sum() and numeric.notna().sum() / cleaned.notna().sum() >= 0.85:
                out[col] = numeric
            else:
                out[col] = cleaned

    return out

def chunked(values: List[str], size: int) -> List[List[str]]:
    """Split a list into chunks of a specified size."""
    return [values[i:i + size] for i in range(0, len(values), size)]

def build_fields() -> List[str]:
    """List of fields to extract."""

    # return [ "TR.COGSActValue","TR.F.InvntTurnover", "TR.EUTaxTotalRevenue", "TR.NAICSSector",  "TR.NAICSInternationalIndustry","TR.CompanyNumEmploy"]
    return [
        # Identifiers
        "TR.CommonName", "TR.ISIN",

        # Financials
        "TR.Revenue", "TR.CompanyNumEmploy", "TR.TR.F.SalesPerEmp",
        "TR.GrossProfit", "TR.OperatingProfit", "TR.COGSActValue","TR.F.InvntTurnover",
        "TR.EUTaxTotalRevenue", "TR.NAICSSector",  "TR.NAICSInternationalIndustry","TR.CompanyNumEmploy",

        # ESG Scores
        "TR.ESGScore", "TR.TRESGScore",

        # TPI Questions
        "TR.TPIMQ1", "TR.TPIMQ2", "TR.TPIMQ3", "TR.TPIMQ4", "TR.TPIMQ5",
        "TR.TPIMQ6", "TR.TPIMQ7", "TR.TPIMQ8", "TR.TPIMQ9", "TR.TPIMQ10",
        "TR.TPIMQ11", "TR.TPIMQ12", "TR.TPIMQ13", "TR.TPIMQ14", "TR.TPIMQ15",
        "TR.TPIMQ16", "TR.TPIMQ17", "TR.TPIMQ18", "TR.TPIMQ19", "TR.TPIMQ20",
        "TR.TPIMQ21", "TR.TPIMQ22", "TR.TPIMQ23",

        # Climate and Emissions
        "TR.ClimatePolicyStatement", "TR.PolicyEmissions", "TR.ClimateCommitment",
        "TR.InternalCarbonPricing", "TR.InternalCarbonPriceTonne",
        "TR.ClimateChangeRisksandOpportunitiesStrategy", "TR.TransitionPlanOffsets",

        # Long-Term Targets
        "TR.LTPercentageofGHGEmissionCoveredbyTargetSet1", "TR.LTGHGEmissionBaseYearSet1",
        "TR.LTGHGEmissionTargetYearSet1", "TR.LTGHGEmissionPercentageReductionTargetedSet1",
        "TR.EmissionsTargetType", "TR.EmissionsTargetAnnualReduction",
        "TR.EmissionReductionTargetPctage", "TR.EmissionReductionTargetYear",

        # Emissions Data
        "TR.Scope1EstTotal", "TR.Scope1EstMethod", "TR.Scope2EstTotal", "TR.Scope2EstMethod",
        "TR.Scope3EstTotal", "TR.Scope3EstUpstreamTotal", "TR.Scope3EstUpstreamMethod",
        "TR.CarbonIntensityperEnergyProduced",

        # Energy
        "TR.PolicyEnergyEfficiency", "TR.TargetsEnergyEfficiency", "TR.EnergyCommitment",
        "TR.EnergyUseTotal", "TR.EnergyUseIndirect", "TR.EnergyPurchasedDirect",
        "TR.EnergyProducedDirect", "TR.ElectricityPurchased",
        "TR.AnalyticElectricityPurchasedPerTonneofAluminumProduction",
        "TR.AnalyticElectricityPurchasedPerTonneofChlorineProduction",
        "TR.ElectricityProduced", "TR.ElectricityProducedfromOtherRenewables",
        "TR.ElectricityProducedfromSolar", "TR.ElectricityProducedfromWind",
        "TR.TotalEnergyUseDatafromProperties", "TR.AnalyticEnergyUse",
        "TR.TotalRenewableEnergy", "TR.RenewEnergyUse", "TR.RenewEnergyPurchased",
        "TR.RenewEnergyProduced", "TR.FleetFuelConsumption",

        # Resources
        "TR.AnalyticResourceRedPolicy", "TR.PolicyResourceEfficiency",
        "TR.PolicySustainablePackaging", "TR.AnalyticResourceRedTargets",
        "TR.TakebackRecyclingInitiatives", "TR.EnvMaterialsSourcing", "TR.EMSCertifiedPct",
        "TR.ISO14000", "TR.AnalyticEnvExpenditures", "TR.LifeCycleAnalysis", "TR.AnalyticEnvRD",

        # Waste
        "TR.AnalyticWasteRecyclingRatio", "TR.WasteRecycledTotal", "TR.WaterPollutantEmissions",
        "TR.SOxEmissions", "TR.VOCEmissions", "TR.AnalyticNOxEmissions",

        # Supply Chain
        "TR.PolicyEnvSupplyChain", "TR.SupplierEnvironmentalCommitment",
        "TR.SupplierEnvironmentalPolicyCommunication", "TR.SupplierEnvironmentalPolicyTraining",
        "TR.SupplierEnvironmentalDueDiligence", "TR.SupplierEnvironmentalRiskAssessment",
        "TR.EnvSupplyChainMgt", "TR.EnvSupplyChainMonitoring", "TR.EnvSupplyChainTermination",

        # Products and Innovations
        "TR.RevenueEnvProducts", "TR.PercentageGreenProducts", "TR.EnvProducts",
        "TR.EcoDesignProducts", "TR.CleanEnergyProducts", "TR.AnalyticProductImpactMin",
        "TR.WaterTechnologies", "TR.HybridVehicles",

        # CDP and CSR
        "TR.CDPClimatePolicyStatement", "TR.CDPClimateCommitment", "TR.CDPPolicyEmissions",
        "TR.CSRReporting", "TR.CSRReportingExternalAudit", "TR.CSRReportingScope",
        "TR.CDPMembershipofBusinessAssociations", "TR.CDPInternalCarbonPricing",
        "TR.CDPInternalCarbonPriceTonne", "TR.CDPTransitionPlanSetofActions",
        "TR.CDPTransitionPlanOffsets", "TR.CDPEnergyCommitment"
    ]


def build_screen_universe() -> str:
    return "SCREEN(U(IN(Equity(active,public,private,primary))), TR.TRESGScore>=0)"


def write_field_description_document(universe: str, fields: List[str], params: dict, output_path: Path) -> None:
    """Write a field mapping document: requested TR field -> output column label."""
    rows = []
    for field in fields:
        out_col = ""
        status = "ok"
        error_message = ""
        try:
            probe = ld.get_data(universe=universe, fields=[field], parameters=params)
            if probe is not None and not probe.empty:
                cols = [c for c in probe.columns if c != "Instrument"]
                if cols:
                    out_col = cols[0]
            else:
                status = "no_data"
        except Exception as exc:
            status = "error"
            error_message = str(exc)
        rows.append(
            {
                "requested_field": field,
                "output_column": out_col,
                "field_description": out_col or "No output column returned for this field",
                "status": status,
                "error_message": error_message,
            }
        )
    doc = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.to_csv(output_path, index=False)


def main() -> None:
    """Extract ESG data for the screened universe and write field-description documentation."""
    parser = argparse.ArgumentParser(description="Extract LSEG ESG universe data across years.")
    parser.add_argument(
        "--start-year",
        type=int,
        default=2014,
        help="First fiscal year to extract",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=dt.datetime.now().year - 1,
        help="Last fiscal year to extract",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=Path(r"C:\Users\scelik\Desktop\TRACE3Code\data\raw\LSEG\lseg_active_universe_10y.csv"),
        help="Combined output CSV path",
    )
    parser.add_argument(
        "--field-doc-file",
        type=Path,
        default=Path(r"/data/raw/LSEG/lseg_active_universe_field_descriptions.csv"),
        help="Field description document output path",
    )
    parser.add_argument(
        "--write-year-files",
        action="store_true",
        help="Also write one CSV per year next to the output file",
    )
    args = parser.parse_args()

    if args.start_year > args.end_year:
        raise SystemExit("start-year must be <= end-year")

    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    pd.set_option("future.no_silent_downcasting", True)

    output_file = args.output_file
    start_year = args.start_year
    end_year = args.end_year
    if output_file.exists():
        output_file.unlink()
    temp_year_files = []

    ld.open_session("desktop.workspace")

    try:
        universe = build_screen_universe()
        fields = list(dict.fromkeys(build_fields()))
        field_doc_written = False

        for year in range(start_year, end_year + 1):
            print(f"--- Extracting fiscal year {year} ---", flush=True)
            params = {
                "SDate": f"{year}-01-01",
                "EDate": f"{year}-12-31",
                "Frq": "Y",
                "Curn": "USD",
                "RH": "In",
                "CH": "Fd",
            }

            try:
                year_df = ld.get_data(universe=universe, fields=fields, parameters=params)
            except Exception as exc:
                print(f"  Year {year} failed: {exc}", flush=True)
                continue

            if year_df is not None and not year_df.empty:
                year_df = normalize_response_values(year_df)
                year_df["FiscalYear"] = year
                year_df = year_df.loc[:, ~year_df.columns.duplicated()].copy()
                if not field_doc_written:
                    write_field_description_document(universe, fields, params, args.field_doc_file)
                    print(f"Wrote field description document: {args.field_doc_file}", flush=True)
                    field_doc_written = True
                year_file = output_file.parent / f"lseg_active_universe_{year}.csv"
                if args.write_year_files:
                    year_df.to_csv(year_file, index=False)
                    temp_year_files.append(year_file)
                else:
                    temp_year_files.append(year_df)
                print(f"Rows for {year}: {len(year_df)}", flush=True)
            else:
                print(f"No data for {year}", flush=True)

    finally:
        ld.close_session()

    if not temp_year_files:
        raise RuntimeError("No data extracted for any year.")

    if args.write_year_files:
        combined = pd.concat((pd.read_csv(p, low_memory=False) for p in temp_year_files), ignore_index=True, sort=False)
    else:
        combined = pd.concat(temp_year_files, ignore_index=True, sort=False)
    if {"Instrument", "FiscalYear"}.issubset(combined.columns):
        combined = combined.sort_values(["Instrument", "FiscalYear"], kind="stable")
    combined.to_csv(output_file, index=False)
    print(f"Saved: {output_file}", flush=True)


if __name__ == "__main__":
    main()