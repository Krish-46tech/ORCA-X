import pytest

from app.analysis.statistics import (anomaly, compare_periods, convert_units, describe,
                                     moving_average, seasonal_aggregate, vertical_profile_gradient, z_scores)
from app.data_sources.schema import MarineObservation


def test_descriptive_statistics_report_sample_counts_and_quantiles():
    result = describe([1, 2, None, 4], "°C")
    assert result["n"] == 3 and result["missing"] == 1
    assert result["mean"] == pytest.approx(7/3)
    assert result["median"] == 2
    assert result["units"] == "°C"


def test_anomaly_requires_and_records_a_real_baseline():
    result = anomaly(30, [20, 22, 24], units="°C", baseline_period="1991-2020")
    assert result["baseline_period"] == "1991-2020"
    assert result["anomaly"] == pytest.approx(8)
    with pytest.raises(ValueError):
        anomaly(30, [None])


def test_moving_average_and_z_score_handle_gaps():
    assert moving_average([1, None, 3, 5], 2) == [None, None, None, 4]
    assert z_scores([1, None, 3])[1] is None


def test_period_comparison_and_seasonal_aggregation():
    rows = [{"date":"2020-01-02","x":10},{"date":"2021-01-02","x":12},
            {"date":"2022-07-02","x":20}]
    comparison = compare_periods(rows,"x",("2020-01-01","2020-12-31"),("2021-01-01","2022-12-31"),"°C")
    assert comparison["mean_difference_b_minus_a"] == 6
    seasons = seasonal_aggregate(rows,"x","°C")
    assert seasons["DJF"]["n"] == 2 and seasons["JJA"]["n"] == 1


def test_unit_conversions_reject_incompatible_or_unknown_units():
    assert convert_units(0,"°C","K") == pytest.approx(273.15)
    assert convert_units(10,"m s^-1","kn") == pytest.approx(19.4384, rel=1e-4)
    with pytest.raises(ValueError):
        convert_units(35,"PSU","°C")


def test_vertical_profile_gradient_is_not_described_as_thermocline_fit():
    result = vertical_profile_gradient([{"depth_m":100,"temperature_c":20},{"depth_m":0,"temperature_c":25}])
    assert result["gradient_per_m"] == pytest.approx(-0.05)
    assert "not a fitted thermocline" in result["method"]


def test_standard_observation_schema_preserves_provenance_and_validates_coordinates():
    record = MarineObservation(dataset_id="test", provider="NOAA", original_variable="sst",
        standardized_variable="SST", value=25, original_units="degree_C", standardized_units="°C",
        latitude=10, longitude=70, observation_time="2026-01-01", source_metadata={"count":20})
    assert record.model_dump()["source_metadata"]["count"] == 20
    with pytest.raises(ValueError):
        MarineObservation(dataset_id="test", provider="NOAA", original_variable="sst",
            standardized_variable="SST", value=25, latitude=100)
