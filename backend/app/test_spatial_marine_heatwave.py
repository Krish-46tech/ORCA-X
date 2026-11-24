"""Synthetic controlled tests for the grid-cell MHW algorithm (not real-data validation)."""
import numpy as np
import pytest

from app.analysis.spatial_marine_heatwave import detect_spatial_mhw, cell_areas_km2, build_spatial_climatology


def base_grid(n=8):
    dates = [f"2024-06-{d:02d}" for d in range(1, n+1)]
    climate = np.full((366, 2, 2), 20.0)
    threshold = np.full_like(climate, 21.0)
    return dates, climate, threshold


def test_five_day_single_cell_detected_and_other_cells_clear():
    dates, climate, threshold = base_grid()
    sst = np.full((8, 2, 2), 20.5)
    sst[1:6, 0, 0] = 22.0
    out = detect_spatial_mhw(sst, dates, climate, threshold, np.array([10., 11.]), np.array([60., 61.]))
    assert out["valid_cells"] == 4
    assert out["affected_cells"] == 1
    assert out["event_cells"][0]["events"][0]["duration_days"] == 5
    assert out["daily_spatial_coverage"][2]["affected_cells"] == 1


def test_four_days_not_detected_and_multi_event_separated():
    dates, climate, threshold = base_grid(16)
    sst = np.full((16, 2, 2), 20.5)
    sst[0:4, 0, 0] = 22
    sst[7:13, 0, 0] = 23
    out = detect_spatial_mhw(sst, dates, climate, threshold, np.array([10., 11.]), np.array([60., 61.]))
    events = out["event_cells"][0]["events"]
    assert len(events) == 1 and events[0]["start"] == dates[7]
    assert events[0]["maximum_intensity_c"] == pytest.approx(3)


def test_missing_day_breaks_event_and_leap_day_index_is_valid():
    dates = ["2024-02-27", "2024-02-28", "2024-02-29", "2024-03-01", "2024-03-02", "2024-03-03"]
    climate = np.full((366, 2, 2), 20.0); threshold = np.full_like(climate, 21.0)
    sst = np.full((6, 2, 2), 22.0); sst[2, 0, 0] = np.nan
    out = detect_spatial_mhw(sst, dates, climate, threshold, np.array([10., 11.]), np.array([60., 61.]))
    assert all(not (cell["latitude"] == 10.0 and cell["longitude"] == 60.0) for cell in out["event_cells"])


def test_area_weighted_coverage_and_latitude_area():
    dates, climate, threshold = base_grid(5)
    sst = np.full((5, 2, 2), 20.5); sst[:, 0, :] = 22
    out = detect_spatial_mhw(sst, dates, climate, threshold, np.array([0., 60.]), np.array([0., 1.]))
    assert out["area_weighted_percent_affected_any_day"] != pytest.approx(50)
    areas = cell_areas_km2(np.array([0., 60.]), np.array([0., 1.]))
    assert areas[0, 0] > areas[1, 0]


def test_rejects_grid_shape_or_noncontiguous_dates():
    dates, climate, threshold = base_grid(5)
    with pytest.raises(ValueError, match="shape"):
        detect_spatial_mhw(np.zeros((5, 3, 2)), dates, climate, threshold, np.array([10.,11.]), np.array([60.,61.]))
    with pytest.raises(ValueError, match="contiguous"):
        detect_spatial_mhw(np.zeros((2,2,2)), ["2024-01-01", "2024-01-03"], climate, threshold,
                           np.array([10.,11.]), np.array([60.,61.]))


def test_cellwise_baseline_climatology_requires_adequate_years_and_preserves_grid():
    dates = [f"{year}-06-{day:02d}" for year in range(2001, 2021) for day in range(1, 11)]
    baseline = np.zeros((len(dates), 2, 2))
    baseline[:, 0, 0] = 20; baseline[:, 0, 1] = 22
    mean, threshold = build_spatial_climatology(baseline, dates, window_days=1, smooth_days=1)
    assert mean.shape == threshold.shape == (366, 2, 2)
    assert mean[152, 0, 1] - mean[152, 0, 0] == pytest.approx(2)
    with pytest.raises(ValueError, match="years"):
        build_spatial_climatology(baseline[:10], dates[:10], minimum_years=20)
