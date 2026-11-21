"""Deterministic query parsing and dataset selection, independent of LLM output."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.data_sources.registry import DATASETS


@dataclass
class QueryIntent:
    variables: list[str]
    analysis: list[str]
    regions: list[str]
    periods: list[str]
    needs_literature: bool
    needs_critic: bool
    answer_profile: str
    requested_length: str
    technical_level: str


REGION_NAMES = ["Arabian Sea", "Bay of Bengal", "Indian Ocean", "South China Sea", "Pacific Ocean", "Atlantic Ocean"]


def understand_query(query: str) -> dict:
    q = query.lower()
    vars_: list[str] = []
    def add(variable: str, terms: tuple[str, ...]):
        if any(term in q for term in terms) and variable not in vars_:
            vars_.append(variable)
    add("SST", ("sst", "sea surface temperature", "ocean temperature", "warming", "heat transport", "heatwave", "warm conditions", "temperature"))
    add("CHLOROPHYLL_A", ("chlorophyll", "phytoplankton", "productivity", "ocean color"))
    add("SEA_SURFACE_SALINITY", ("salinity", "saline"))
    add("OCEAN_CURRENT_SPEED", ("currents", "ocean current", "circulation", "heat transport"))
    add("SEA_SURFACE_HEIGHT", ("sea surface height", "altimetry", "ssh"))
    add("OCEAN_TEMPERATURE", ("subsurface", "below the surface", "beneath the ocean surface", "vertical profile", "temperature by depth"))
    add("DISSOLVED_OXYGEN", ("oxygen", "hypoxia", "deoxygenation"))
    add("NITRATE", ("nutrient", "nitrate"))
    add("WIND_SPEED", ("wind", "monsoon"))
    add("SPECIES_OCCURRENCE", ("species", "biodiversity", "organism", "recorded near"))
    add("FISHING_ACTIVITY", ("fishing", "vessel activity", "fishing effort"))
    if any(term in q for term in ("ecosystem stress", "environmental stress", "marine ecosystem")):
        for v in ("SST", "CHLOROPHYLL_A", "SEA_SURFACE_SALINITY", "DISSOLVED_OXYGEN"):
            if v not in vars_:
                vars_.append(v)
    if "productivity" in q and any(term in q for term in ("why", "changing", "change", "declin", "increas")):
        for v in ("SST", "NITRATE", "DISSOLVED_OXYGEN"):
            if v not in vars_:
                vars_.append(v)
    if "marine conditions" in q and "compare" in q:
        for v in ("SST", "CHLOROPHYLL_A", "SEA_SURFACE_SALINITY"):
            if v not in vars_:
                vars_.append(v)
    if not vars_:
        vars_ = ["SST"]
    analysis = []
    for name, terms in {
        "comparison": ("compare", "versus", " vs ", "against", "difference"),
        "anomaly": ("anomal", "unusually", "unusual", "deviation", "normal conditions"),
        "trend": ("trend", "warming", "changed", "change over", "over the last", "long-term"),
        "correlation": ("relationship", "correlat", "correspond", "associated"),
        "causal_investigation": ("why", "affect", "influence", "cause", "explain"),
        "discovery": ("find something interesting", "explore", "discover"),
    }.items():
        if any(term in q for term in terms):
            analysis.append(name)
    regions = [r for r in REGION_NAMES if r.lower() in q]
    periods = re.findall(r"\b(?:19|20)\d{2}\s*(?:-|to|–|—)\s*(?:19|20)\d{2}\b", query)
    needs_literature = any(x in q for x in ("why", "explain", "literature", "research paper", "affect", "mechanism", "stress", "changing"))
    needs_critic = any(x in q for x in ("challenge", "critic", "contradict", "reliable", "verify", "evidence"))
    if "beginner" in q or "from scratch" in q or "simple" in q:
        profile, technical = "beginner", "beginner"
    elif any(x in q for x in ("research report", "academic", "research-level", "comprehensive")):
        profile, technical = "research_report", "scientific"
    elif any(x in q for x in ("exact data", "data only", "raw data")):
        profile, technical = "data_only", "advanced"
    elif "compare" in q or " versus " in q:
        profile, technical = "comparison", "intermediate"
    elif any(x in q for x in ("brief", "briefly", "short answer", "quick")):
        profile, technical = "quick", "intermediate"
    else:
        profile, technical = "scientific_analysis", "intermediate"
    length = "short" if profile == "quick" else "comprehensive" if profile == "research_report" else "balanced"
    return asdict(QueryIntent(vars_, analysis, regions, periods, needs_literature, needs_critic, profile, length, technical))


def select_datasets(query: str) -> dict:
    intent = understand_query(query)
    vars_ = set(intent["variables"])
    selected = []
    high_resolution_sst = any(term in query.lower() for term in ("modis", "high resolution", "high-resolution", "coastal sst", "swath"))
    for ds in DATASETS:
        target = set(ds["variables"])
        if ds["id"] == "noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2" and "SST" in vars_:
            selected.append(ds)
        elif ds["id"] == "MODIS_A-JPL-L2P-v2019.0" and "SST" in vars_ and high_resolution_sst:
            selected.append(ds)
        elif ds["id"] == "nesdisVHNnoaa20chlaDaily" and "CHLOROPHYLL_A" in vars_:
            selected.append(ds)
        elif ds["id"] == "MODISA_L3m_CHL" and "CHLOROPHYLL_A" in vars_ and high_resolution_sst:
            selected.append(ds)
        elif ds["category"] == "long_term_ocean_color" and "CHLOROPHYLL_A" in vars_ and any(t in query.lower() for t in ("seawifs", "sea wi fs", "long-term", "long term", "multi-sensor", "multisensor")):
            selected.append(ds)
        elif ds["category"] == "climatology" and ("anomaly" in intent["analysis"] or "trend" in intent["analysis"] or intent["periods"] or "ecosystem stress" in query.lower()):
            selected.append(ds)
        elif ds["category"] == "salinity" and "SEA_SURFACE_SALINITY" in vars_:
            selected.append(ds)
        elif ds["category"] == "currents_ssh" and bool(vars_.intersection({"OCEAN_CURRENT_SPEED", "OCEAN_CURRENT_DIRECTION", "SEA_SURFACE_HEIGHT"})):
            selected.append(ds)
        elif ds["category"] == "argo" and bool(vars_.intersection({"OCEAN_TEMPERATURE", "OCEAN_SALINITY"})):
            selected.append(ds)
        elif ds["category"] == "biogeochemistry" and bool(vars_.intersection({"NITRATE", "PHOSPHATE", "DISSOLVED_OXYGEN"})):
            selected.append(ds)
        elif ds["category"] == "wind" and "WIND_SPEED" in vars_:
            selected.append(ds)
        elif ds["category"] == "biodiversity" and "SPECIES_OCCURRENCE" in vars_:
            selected.append(ds)
        elif ds["category"] == "fishing" and "FISHING_ACTIVITY" in vars_:
            selected.append(ds)
    if intent["needs_literature"]:
        selected.append({"id":"CROSSREF_WORKS","name":"Crossref scholarly works metadata","provider":"Crossref","category":"literature","variables":[],"status":"IMPLEMENTED_AND_TESTED"})
    if intent["needs_critic"]:
        intent["needs_critic"] = True
    scope_limits = []
    requested_years = [int(year) for period in intent["periods"] for year in re.findall(r"(?:19|20)\d{2}", period)]
    duration_years = [int(n) for n in re.findall(r"(?:past|last|over the last)\s+(\d+)\s+years?", query.lower())]
    requested_span = max([*requested_years, *([duration_years[0]] if duration_years else [])], default=0)
    if (requested_years and max(requested_years) - min(requested_years) >= 1) or requested_span > 1:
        scope_limits.append("The query requests multi-year period analysis, but the live NOAA daily acquisition workflow is limited to 365 days; the actual retrieved dates must be checked before making a period-comparison claim.")
    if len(intent["regions"]) > 1:
        scope_limits.append("The query names multiple regions, while the current research request retrieves one selected region at a time; no multi-region difference is computed yet.")
    return {"intent": intent, "datasets": selected,
            "availability": {"fully_answerable": all(d.get("status") == "IMPLEMENTED_AND_TESTED" for d in selected) and not scope_limits,
                             "selected_count": len(selected),
                             "scope_limitations": scope_limits,
                             "unavailable": [d["id"] for d in selected if d.get("status") in {"UNAVAILABLE", "AUTHENTICATION_REQUIRED", "NOT_IMPLEMENTED", "METADATA_ONLY"}]}}
