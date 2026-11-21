"""The attachment's 16 required dataset-selection scenarios."""
from app.query.understanding import select_datasets


def selected(query):
    result = select_datasets(query)
    return {item["id"] for item in result["datasets"]}, result["intent"]


def test_sixteen_query_selection_scenarios():
    cases = [
        ("Analyze sea surface temperature in the Arabian Sea.", {"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2"}),
        ("Compare sea surface temperature in the Arabian Sea from 2005–2015 and 2016–2026.", {"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2", "WOA23"}),
        ("Is the Arabian Sea experiencing unusually warm conditions?", {"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2", "WOA23"}),
        ("Analyze the relationship between SST and chlorophyll.", {"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2", "nesdisVHNnoaa20chlaDaily"}),
        ("Compare Arabian Sea and Bay of Bengal marine conditions.", {"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2", "nesdisVHNnoaa20chlaDaily", "SMAP_RSS_L2_SSS_NRT_V6"}),
        ("How do currents influence heat transport?", {"cmems_mod_glo_phy_anfc_0.083deg_P1D-m", "noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2"}),
        ("Is warming occurring beneath the ocean surface?", {"ARGO_GDAC", "noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2"}),
        ("What marine species have been recorded near this location?", {"OBIS_OCCURRENCES"}),
        ("Analyze fishing activity in this marine region.", {"GFW_4WINGS"}),
        ("Investigate the relationship between wind and chlorophyll after monsoon.", {"NOAA_ASCATA_WIND", "nesdisVHNnoaa20chlaDaily"}),
        ("Find environmental anomalies in the Indian Ocean.", {"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2", "WOA23"}),
        ("Explain why marine productivity may be changing.", {"nesdisVHNnoaa20chlaDaily", "noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2", "CROSSREF_WORKS", "GLOBAL_ANALYSISFORECAST_BGC_001_028"}),
        ("Compare current conditions against historical normal conditions.", {"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2", "WOA23"}),
        ("Analyze subsurface temperature and salinity.", {"ARGO_GDAC"}),
        ("Investigate potential marine ecosystem stress.", {"CROSSREF_WORKS", "WOA23", "nesdisVHNnoaa20chlaDaily", "noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2"}),
        ("Challenge your previous analysis.", set()),
    ]
    for query, expected in cases:
        ids, intent = selected(query)
        assert expected.issubset(ids), (query, expected - ids)
        if "2005" in query:
            assert len(intent["periods"]) == 2
        if "Challenge" in query:
            assert intent["needs_critic"] is True


def test_sst_uses_the_minimum_sufficient_product_by_default():
    ids, _ = selected("Analyze sea surface temperature in the Arabian Sea.")
    assert ids == {"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2"}

