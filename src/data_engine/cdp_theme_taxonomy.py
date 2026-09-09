"""CDP category taxonomy used to classify questionnaire answers into thematic buckets.

Precisely aligned with CDP Climate Change Questionnaire terminology (2014–2025).
Built from the official "Emissions reduction initiatives" (C4.3b), "Energy" (C8),
"Additional metrics" (C9), "Engagement" (C12), and "Land management" (C13) modules.
"""

THEME_PATTERNS = [
    # === C4.3b: Energy efficiency in buildings ===
    (
        "energy_efficiency_buildings",
        [
            r"\benergy efficiency in buildings\b",
            r"\bbuilding fabric\b",
            r"\binsulation\b",
            r"\bdraught proof(ing)?\b",
            r"\bsolar shading\b",
            r"\bBEMS\b",
            r"\bbuilding energy management system\b",
            r"\bHVAC\b",
            r"\bheating,? ventilation\b",
            r"\bair conditioning\b",
            r"\blighting\b",
            r"\bmotors and drives\b",
            r"\bcombined heat and power\b",
            r"\bcogeneration\b",
            r"\bmaintenance program\b",
        ],
    ),

    # === C4.3b: Energy efficiency in production processes ===
    (
        "energy_efficiency_processes",
        [
            r"\benergy efficiency in production processes\b",
            r"\bwaste heat recovery\b",
            r"\bcooling technology\b",
            r"\bprocess optimization\b",
            r"\bcompressed air\b",
            r"\bwastewater treatment\b",
            r"\breuse of (water|steam)\b",
            r"\bmachine/equipment replacement\b",
            r"\bequipment replacement\b",
            r"\bautomation\b",
            r"\belectrification\b",
            r"\bsmart control system\b",
            r"\bfuel switch\b",
        ],
    ),

    # === C4.3b: Low-carbon energy consumption ===
    (
        "low_carbon_energy_consumption",
        [
            r"\blow-carbon energy consumption\b",
            r"\bsolid biofuels?\b",
            r"\bliquid biofuels?\b",
            r"\bbiogas\b",
            r"\bgeothermal\b",
            r"\blarge hydropower\b",
            r"\bsmall hydropower\b",
            r"\bhydropower\b",
            r"\brenewable hydrogen fuel cell\b",
            r"\bsolar heating and cooling\b",
            r"\bsolar PV\b",
            r"\bsolar CSP\b",
            r"\bnuclear\b",
            r"\bwind\b",
            r"\btidal\b",
            r"\bwave\b",
            r"\bfossil fuel plant fitted with CCS\b",
            r"\blow-carbon electricity mix\b",
        ],
    ),

    # === C4.3b: Low-carbon energy generation ===
    (
        "low_carbon_energy_generation",
        [
            r"\blow-carbon energy generation\b",
            r"\bon-site.*(solar|wind|biomass|geothermal|hydro)\b",
            r"\bself-generation\b",
            r"\brenewable energy generation\b",
            r"\binstall.*solar\b",
            r"\binstall.*wind\b",
            r"\binstall.*biogas\b",
        ],
    ),

    # === C8: Energy procurement (PPAs, RECs, GOs) ===
    (
        "energy_procurement",
        [
            r"\bpower purchase agreement\b",
            r"\bPPA\b",
            r"\brenewable energy certificate\b",
            r"\bREC\b",
            r"\bI-REC\b",
            r"\bguarantee of origin\b",
            r"\bGOs?\b",
            r"\benergy attribute certificate\b",
            r"\bgreen tariff\b",
            r"\boff-site renewable\b",
            r"\bvirtual PPA\b",
            r"\bRE100\b",
            r"\belectricity procurement\b",
            r"\brenewable electricity\b",
            r"\bclean electricity\b",
        ],
    ),

    # === C4.3b: Waste reduction and material circularity ===
    (
        "waste_reduction_circularity",
        [
            r"\bwaste reduction and material circularity\b",
            r"\bwaste reduction\b",
            r"\bmaterial circularity\b",
            r"\bcircular economy\b",
            r"\bproduct/component/material reuse\b",
            r"\bproduct/component/material recycling\b",
            r"\bremanufact(uring|ure)\b",
            r"\bwaste minimization\b",
            r"\bzero waste\b",
            r"\bwaste-to-energy\b",
            r"\bwaste to energy\b",
            r"\blandfill diversion\b",
            r"\bcomposting\b",
            r"\bupcycling\b",
            r"\bwaste sorting\b",
            r"\bwaste prevention\b",
            r"\bresource efficiency\b",
        ],
    ),

    # === C4.3b: Fugitive emissions reductions ===
    (
        "fugitive_emissions",
        [
            r"\bfugitive emissions reductions?\b",
            r"\bagricultural methane capture\b",
            r"\bagricultural nitrous oxide reduction\b",
            r"\blandfill methane capture\b",
            r"\boil/natural gas methane leak capture\b",
            r"\bmethane leak capture\b",
            r"\bmethane leak prevention\b",
            r"\brefrigerant leakage reduction\b",
            r"\brefrigerant reduction\b",
            r"\bCCS/U\b",
            r"\bcarbon capture and (storage|utilization)\b",
            r"\bcarbon capture and storage\b",
            r"\bcarbon capture and utilization\b",
            r"\bDAC\b",
            r"\bdirect air capture\b",
        ],
    ),

    # === C4.3b: Non-energy industrial process emissions reductions ===
    (
        "process_emissions",
        [
            r"\bnon-energy industrial process emissions reductions?\b",
            r"\bprocess equipment replacement\b",
            r"\bprocess material substitution\b",
            r"\bprocess material efficiency\b",
            r"\bprocess improvement\b",
            r"\bnew equipment\b",
            r"\bchemical process\b",
            r"\bmanufacturing efficiency\b",
            r"\bindustrial efficiency\b",
        ],
    ),

    # === C4.3b: Company policy or behavioral change ===
    (
        "policy_behavioral_change",
        [
            r"\bcompany policy or behavioral change\b",
            r"\bsite consolidation/closure\b",
            r"\bsite closure\b",
            r"\bchange in purchasing practices\b",
            r"\bresource efficiency\b",
            r"\bwaste management\b",
            r"\bbehavioral change\b",
            r"\bemployee engagement\b",
            r"\bawareness program\b",
            r"\benergy saving campaign\b",
            r"\bconsumer education\b",
            r"\btraining\b",
        ],
    ),

    # === C4.3b: Transportation ===
    (
        "transportation",
        [
            r"\bbusiness travel policy\b",
            r"\bteleworking\b",
            r"\bremote work\b",
            r"\btelecommuting\b",
            r"\bemployee commuting\b",
            r"\bcompany fleet vehicle replacement\b",
            r"\bfleet vehicle replacement\b",
            r"\belectric vehicle\b",
            r"\bEV\b",
            r"\bcompany fleet vehicle efficiency\b",
            r"\bfleet efficiency\b",
            r"\bfleet optimization\b",
            r"\broute optimization\b",
            r"\bshipping efficiency\b",
            r"\blow-carbon logistics\b",
            r"\bsustainable transport\b",
        ],
    ),

    # === C11: Carbon pricing & taxation ===
    (
        "carbon_pricing_tax",
        [
            r"\binternal carbon price\b",
            r"\binternal price on carbon\b",
            r"\bshadow price\b",
            r"\bcarbon pricing\b",
            r"\bcarbon tax\b",
            r"\bcarbon fee\b",
            r"\bemissions trading\b",
            r"\bcap and trade\b",
            r"\bETS\b",
            r"\bmarginal abatement cost curve\b",
        ],
    ),

    # === C4.3c: Investment in emissions reduction ===
    (
        "emissions_reduction_investment",
        [
            r"\bdedicated budget for energy efficiency\b",
            r"\bdedicated budget for low-carbon product R&D\b",
            r"\bdedicated budget for other emissions reduction\b",
            r"\binternal finance mechanisms\b",
            r"\binternal incentives/recognition programs\b",
            r"\blower return on investment\b",
            r"\blower ROI specification\b",
            r"\bfinancial optimization calculations\b",
            r"\bpartnering with governments on technology development\b",
            r"\bcompliance with regulatory requirements/standards\b",
        ],
    ),

    # === C4.1: Targets and performance ===
    (
        "targets_performance",
        [
            r"\babsolute target\b",
            r"\bintensity target\b",
            r"\bnet-zero target\b",
            r"\bnet zero target\b",
            r"\bemissions reduction target\b",
            r"\bbase year\b",
            r"\bbase year emissions\b",
            r"\btarget boundary\b",
            r"\bScope 1 target\b",
            r"\bScope 2 target\b",
            r"\bScope 3 target\b",
            r"\bmethane target\b",
            r"\bmethane reduction target\b",
            r"\bRE100\b",
            r"\bscience-based target\b",
            r"\bSBTi\b",
            r"\b1\.5°C pathway\b",
            r"\bwell below 2°C\b",
        ],
    ),

    # === C12: Supplier engagement ===
    (
        "supplier_engagement",
        [
            r"\bsupplier engagement strategy\b",
            r"\bclimate-related supplier engagement\b",
            r"\bsupplier engagement\b",
            r"\bsupplier training\b",
            r"\bsupplier workshop\b",
            r"\bsupplier scorecard\b",
            r"\bsupplier survey\b",
            r"\bsupplier code of conduct\b",
            r"\bcapacity building\b",
            r"\bcollaboration with suppliers\b",
            r"\bprocurement spend\b",
            r"\bsupplier-related Scope 3\b",
            r"\bsupplier diversification\b",
        ],
    ),

    # === C12: Customer engagement ===
    (
        "customer_engagement",
        [
            r"\bcustomer engagement\b",
            r"\bclient engagement\b",
            r"\bcustomer education\b",
            r"\bstakeholder engagement\b",
        ],
    ),

    # === C12: Value chain engagement (general) ===
    (
        "value_chain_engagement",
        [
            r"\bvalue chain engagement\b",
            r"\bvalue chain on climate\b",
            r"\bupstream engagement\b",
            r"\bdownstream engagement\b",
            r"\bsupply chain engagement\b",
            r"\bscope 3 engagement\b",
            r"\bother partners in the value chain\b",
        ],
    ),

    # === C5/C6: Emissions methodology & data ===
    (
        "emissions_methodology",
        [
            r"\bconsolidation approach\b",
            r"\boperational control\b",
            r"\bfinancial control\b",
            r"\bequity share\b",
            r"\bemissions methodology\b",
            r"\bemission factor\b",
            r"\bGWP\b",
            r"\bglobal warming potential\b",
            r"\bscope 1\b",
            r"\bscope 2\b",
            r"\bscope 3\b",
            r"\blocation-based\b",
            r"\bmarket-based\b",
            r"\bbiogenic emissions\b",
            r"\bbiogenic carbon\b",
        ],
    ),

    # === C7: Emissions breakdown & tracking ===
    (
        "emissions_tracking",
        [
            r"\bemissions breakdown\b",
            r"\bemissions by (source|activity|facility|country)\b",
            r"\bgross emissions\b",
            r"\bnet emissions\b",
            r"\bemissions inventory\b",
            r"\bcarbon footprint\b",
            r"\bGHG inventory\b",
            r"\breport(ing|ed)?\b",
            r"\btrack(ing|ed|s)?\b",
            r"\bmonitor(ing|ed|s)?\b",
            r"\bmeasure(ment|d)?\b",
            r"\bdisclos(e|ure|ed|ing)\b",
            r"\bprogress\b",
            r"\bdata collection\b",
            r"\bmanagement system\b",
            r"\bKPI\b",
        ],
    ),

    # === C10: Verification & assurance ===
    (
        "verification_assurance",
        [
            r"\bverification\b",
            r"\bassurance\b",
            r"\bthird-party verification\b",
            r"\bthird-party assurance\b",
            r"\bexternal audit\b",
            r"\bISO 14064\b",
            r"\bISAE 3000\b",
            r"\bISAE 3410\b",
            r"\blimited assurance\b",
            r"\breasonable assurance\b",
            r"\bdata quality\b",
            r"\baccuracy\b",
            r"\bcompleteness\b",
            r"\bmethodolog(y|ies)\b",
            r"\brestatement\b",
            r"\brestate(ment|d)?\b",
        ],
    ),

    # === C1: Governance ===
    (
        "governance",
        [
            r"\bboard[- ]level\b",
            r"\bboard oversight\b",
            r"\bboard responsibility\b",
            r"\bexecutive[- ]level\b",
            r"\bmanagement[- ]level\b",
            r"\bCEO\b",
            r"\bCFO\b",
            r"\bCSO\b",
            r"\bchief sustainability officer\b",
            r"\bincentiviz(e|ation)\b",
            r"\bexecutive compensation\b",
            r"\bremuneration\b",
        ],
    ),

    # === C2: Risks & opportunities ===
    (
        "risks_opportunities",
        [
            r"\bphysical risk\b",
            r"\btransition risk\b",
            r"\bregulatory risk\b",
            r"\blegal risk\b",
            r"\btechnology risk\b",
            r"\breputation(al)? risk\b",
            r"\bmarket risk\b",
            r"\bacute risk\b",
            r"\bchronic risk\b",
            r"\bclimate-related opportunity\b",
            r"\bresource efficiency\b",
            r"\benergy source\b",
            r"\bproducts and services\b",
            r"\bresilience\b",
            r"\badaptation\b",
            r"\bclimate adaptation\b",
            r"\bclimate resilience\b",
            r"\badapt to climate\b",
        ],
    ),

    # === C3: Business strategy ===
    (
        "business_strategy",
        [
            r"\btransition plan\b",
            r"\bclimate transition plan\b",
            r"\bscenario analysis\b",
            r"\b1\.5°C scenario\b",
            r"\b2°C scenario\b",
            r"\bwell below 2°C\b",
            r"\bTCFD\b",
            r"\bnet-zero\b",
            r"\bnet zero\b",
            r"\bdecarboniz(e|ation)\b",
            r"\blow-carbon economy\b",
            r"\bParis Agreement\b",
            r"\bstrategy\b",
            r"\bfinancial planning\b",
            r"\bcapex\b",
            r"\bopex\b",
        ],
    ),

    # === C3.5: Taxonomies ===
    (
        "taxonomies_frameworks",
        [
            r"\bEU Taxonomy\b",
            r"\btaxonomy\b",
            r"\bclimate bonds taxonomy\b",
            r"\blow-carbon investment\b",
            r"\bLCI registry\b",
            r"\bavoided emissions\b",
            r"\bsustainable finance\b",
            r"\bgreen bond\b",
            r"\bgreen loan\b",
            r"\bTCFD\b",
            r"\bGRI\b",
            r"\bSDG\b",
            r"\bSBTi\b",
            r"\bscience-based target\b",
        ],
    ),

    # === C4.4: Land management practices (Agriculture/Forestry) ===
    (
        "land_management_practices",
        [
            r"\bagriculture or forest management practices\b",
            r"\blow tillage\b",
            r"\bno tillage\b",
            r"\breduced tillage\b",
            r"\bresidue management\b",
            r"\bpermanent soil cover\b",
            r"\bcover crop\b",
            r"\bcontour farming\b",
            r"\bcrop rotation\b",
            r"\bcrop diversity\b",
            r"\bseed variety\b",
            r"\blivestock management\b",
            r"\bmanure management\b",
            r"\bfertilizer management\b",
            r"\bnitrogen-fixing\b",
            r"\bsoil management\b",
            r"\birrigation\b",
            r"\bgreen harvesting\b",
        ],
    ),

    # === C13: Other land management impacts ===
    (
        "land_use_forestry",
        [
            r"\breforestation\b",
            r"\bdeforestation\b",
            r"\bafforestation\b",
            r"\bagroforestry\b",
            r"\benhanced forest regeneration\b",
            r"\bland use change\b",
            r"\bselective logging\b",
            r"\bspecies introduction\b",
            r"\bmaximize carbon capture\b",
            r"\bchange in topography\b",
            r"\bbiodiversity\b",
            r"\bfire control\b",
            r"\brestoration\b",
            r"\brestoration of degraded lands\b",
            r"\bcultivated organic soils\b",
            r"\bforest management\b",
            r"\bcarbon sink\b",
            r"\bsequestration\b",
            r"\bsoil carbon\b",
        ],
    ),

    # === C9: Additional metrics (water, waste, land) ===
    (
        "water_management",
        [
            r"\bwater management\b",
            r"\bwater efficiency\b",
            r"\bwater saving\b",
            r"\bwater withdrawal\b",
            r"\bwater consumption\b",
            r"\bwater reuse\b",
            r"\bwater recycling\b",
            r"\bdrought-resistant\b",
            r"\bwater treatment\b",
            r"\bwastewater\b",
        ],
    ),

    # === C9: Product innovation & R&D ===
    (
        "product_innovation",
        [
            r"\blow-carbon product R&D\b",
            r"\blow-carbon product\b",
            r"\bproduct innovation\b",
            r"\beco-design\b",
            r"\beco design\b",
            r"\bsustainable product\b",
            r"\bgreen product\b",
            r"\bpackaging improvement\b",
            r"\blifecycle assessment\b",
            r"\bLCA\b",
            r"\btake-back program\b",
            r"\brecycling program\b",
            r"\bproduct or service design\b",
        ],
    ),

    # === C11: Offsetting ===
    (
        "offsetting",
        [
            r"\boffset\b",
            r"\bcarbon offset\b",
            r"\bverified carbon\b",
            r"\bcarbon credit\b",
            r"\bcompensation\b",
        ],
    ),

    # === C12.3/C12.4: Policy advocacy & external engagement ===
    (
        "policy_advocacy",
        [
            r"\bpolicy\b",
            r"\badvocacy\b",
            r"\blobby(ing|ed)?\b",
            r"\bregulatory support\b",
            r"\bcarbon regulation\b",
            r"\bclimate policy\b",
            r"\bincentive\b",
            r"\bsubsid(y|ies)\b",
            r"\bgovernment\b",
            r"\btrade association\b",
        ],
    ),

    # === C0: Organization profile ===
    (
        "organization_profile",
        [
            r"\borderganization profile\b",
            r"\brevenue\b",
            r"\bemployees\b",
            r"\bsector\b",
            r"\bindustry\b",
            r"\breporting year\b",
            r"\bcurrency\b",
        ],
    ),
]

QUESTION_CODE_THEMES = [
    # C0: Introduction / Organization profile
    ("organization_profile", [r"^C0\.", r"^C0\.1$", r"^C0\.2$", r"^C0\.3$", r"^C0\.4$", r"^C0\.5$"]),
    # C1: Governance
    ("governance", [r"^C1\.", r"^C1\.1", r"^C1\.1a$", r"^C1\.1b$", r"^C1\.2$", r"^C1\.2a$", r"^C1\.3$"]),
    # C2: Risks and opportunities
    ("risks_opportunities", [r"^C2\.", r"^C2\.1", r"^C2\.2", r"^C2\.3", r"^C2\.4", r"^C2\.4a$"]),
    # C3: Business strategy
    ("business_strategy", [r"^C3\.", r"^C3\.1", r"^C3\.2", r"^C3\.3", r"^C3\.4", r"^C3\.5", r"^C3\.5a$", r"^C3\.5b$", r"^C3\.5c$"]),
    # C4: Targets and performance
    ("targets_performance", [r"^C4\.", r"^C4\.1", r"^C4\.1a", r"^C4\.1b", r"^C4\.2", r"^C4\.2a", r"^C4\.2b", r"^C4\.2c", r"^C4\.3$", r"^C4\.3a$", r"^C4\.3b$", r"^C4\.3c$", r"^C4\.3d$", r"^C4\.4", r"^C4\.4a", r"^C4\.4b"]),
    # C5: Emissions methodology
    ("emissions_methodology", [r"^C5\.", r"^C5\.1", r"^C5\.1a$", r"^C5\.2", r"^C5\.3$"]),
    # C6: Emissions data
    ("emissions_tracking", [r"^C6\.", r"^C6\.1", r"^C6\.2", r"^C6\.3", r"^C6\.4", r"^C6\.5"]),
    # C7: Emissions breakdown
    ("emissions_tracking", [r"^C7\.", r"^C7\.1", r"^C7\.2", r"^C7\.3", r"^C7\.4", r"^C7\.5", r"^C7\.6", r"^C7\.7", r"^C7\.9", r"^C7\.10"]),
    # C8: Energy
    ("energy_procurement", [r"^C8\.", r"^C8\.1", r"^C8\.2", r"^C8\.2a$", r"^C8\.2b$", r"^C8\.2c$", r"^C8\.2d$", r"^C8\.2e$", r"^C8\.3", r"^C8\.3a$", r"^C8\.3b$", r"^C8\.3c$"]),
    # C9: Additional metrics
    ("water_management", [r"^C9\.", r"^C9\.1", r"^C9\.2", r"^C9\.3"]),
    # C10: Verification
    ("verification_assurance", [r"^C10\.", r"^C10\.1", r"^C10\.1a$", r"^C10\.1b$", r"^C10\.2$", r"^C10\.2a$"]),
    # C11: Carbon pricing
    ("carbon_pricing_tax", [r"^C11\.", r"^C11\.1", r"^C11\.1a$", r"^C11\.2", r"^C11\.2a$", r"^C11\.3", r"^C11\.3a$", r"^C11\.4$"]),
    # C12: Engagement
    ("value_chain_engagement", [r"^C12\.", r"^C12\.1$", r"^C12\.1a$", r"^C12\.1b$", r"^C12\.1c$"]),
    ("supplier_engagement", [r"^C12\.1a$", r"^C12\.1d$", r"^C12\.1e$"]),
    ("customer_engagement", [r"^C12\.1b$", r"^C12\.1c$"]),
    ("policy_advocacy", [r"^C12\.3", r"^C12\.3a$", r"^C12\.4", r"^C12\.4a$"]),
    # C13: Other land management impacts
    ("land_use_forestry", [r"^C13\.", r"^C13\.1", r"^C13\.2", r"^C13\.2a$"]),
    # C14: Portfolio impact (FS only)
    ("emissions_tracking", [r"^C-FS14\.1", r"^C-FS14\.1a$", r"^C-FS14\.1b$", r"^C-FS14\.1c$", r"^C-FS14\.2", r"^C-FS14\.3", r"^C-FS14\.3a$"]),
    # C15: Biodiversity
    ("land_use_forestry", [r"^C15\.", r"^C15\.1", r"^C15\.1a$", r"^C15\.2", r"^C15\.3", r"^C15\.3a$", r"^C15\.4", r"^C15\.4a$", r"^C15\.5", r"^C15\.6$"]),
    # C16: Signoff
    ("verification_assurance", [r"^C16\.", r"^C16\.1$"]),
]

CATEGORY_ORDER = [
    # --- Governance & Strategy ---
    "organization_profile",
    "governance",
    "risks_opportunities",
    "business_strategy",
    "taxonomies_frameworks",

    # --- Targets & Investment ---
    "targets_performance",
    "carbon_pricing_tax",
    "emissions_reduction_investment",

    # --- Emissions Reduction Initiatives (C4.3b) ---
    "energy_efficiency_buildings",
    "energy_efficiency_processes",
    "low_carbon_energy_consumption",
    "low_carbon_energy_generation",
    "energy_procurement",
    "fugitive_emissions",
    "process_emissions",
    "waste_reduction_circularity",
    "transportation",
    "policy_behavioral_change",

    # --- Emissions Measurement & Verification ---
    "emissions_methodology",
    "emissions_tracking",
    "verification_assurance",

    # --- Value Chain Engagement ---
    "supplier_engagement",
    "customer_engagement",
    "value_chain_engagement",

    # --- Land, Nature & Water ---
    "land_management_practices",
    "land_use_forestry",
    "water_management",

    # --- Product & Innovation ---
    "product_innovation",

    # --- Offsetting & Policy ---
    "offsetting",
    "policy_advocacy",
]