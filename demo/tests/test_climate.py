from datetime import date, timedelta
from pathlib import Path
import math
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from climate import TERMS, classify, display_score, make_term, score_metrics
from build_beijing import aggregate_window, validate_chunk


def annual(year, temperature=10, valid=True):
    return {"year": year, "start": f"{year}-02-04", "end": f"{year}-02-18", "valid": valid,
            "reason": None if valid else "缺失", "temperature": temperature if valid else None,
            "precipitation": 0 if valid else None, "diurnal_range": 10 if valid else None}


def daily_rows(start, days):
    return {(start + timedelta(days=i)).isoformat(): {
        "temperature_2m_mean": 10, "temperature_2m_max": 14,
        "temperature_2m_min": 6, "precipitation_sum": 0} for i in range(days)}


def test_rating_boundaries_use_original_score():
    assert classify(40) == "critical"
    assert classify(70) == "alive"
    assert classify(39.99999) == "departed"
    assert classify(69.99999) == "critical"
    assert classify(None) == "insufficient_data"
    assert display_score(39.99999) == "<40"
    assert display_score(69.99999) == "<70"


def test_fixed_weights_minimum_scale_and_zero_rain():
    records = [annual(y) for y in range(1961, 1991)] + [annual(y, 11) for y in range(1996, 2026)]
    term = make_term(TERMS[0], records)
    # Temperature has sigma=0, denominator .5, weighted D=.6*2=1.2.
    assert math.isclose(term["score"], 100 / 2.2)
    assert term["metrics"][0]["baseline_std"] == 0
    assert term["metrics"][1]["baseline"] == 0
    assert term["status"] == "critical"


def test_sample_standard_deviation_not_population():
    old = [annual(1961 + i, 10 + i) for i in range(30)]
    new = [annual(1996 + i, 12 + i) for i in range(30)]
    term = make_term(TERMS[0], old + new)
    # Sum squared deviations of 0..29 is 2247.5; sample variance divides by 29.
    expected_std = math.sqrt(2247.5 / 29)
    assert math.isclose(term["metrics"][0]["baseline_std"], expected_std)
    assert math.isclose(term["score"], 100 / (1 + .6 * 2 / expected_std))


def test_27_year_boundary_and_no_departed():
    old = [annual(y) for y in range(1961, 1988)]
    new = [annual(y) for y in range(1996, 2023)]
    complete = make_term(TERMS[0], old + new)
    assert complete["score"] == 100
    assert complete["status"] == "alive"
    insufficient = make_term(TERMS[0], old + new[:-1])
    assert insufficient["score"] is None
    assert insufficient["status"] == "insufficient_data"
    assert "26" in insufficient["reason"]


def test_missing_days_90_percent_and_zero_not_missing():
    start = date(2000, 2, 20)
    rows = daily_rows(start, 10)
    rows["2000-02-20"]["precipitation_sum"] = None
    result = aggregate_window(rows, start, date(2000, 3, 1))
    assert result["valid"]
    assert result["precipitation"] == 0
    assert result["expected_days"] == 10  # leap year includes Feb 29
    rows["2000-02-21"]["temperature_2m_mean"] = None
    rows["2000-02-22"]["temperature_2m_mean"] = None
    result = aggregate_window(rows, start, date(2000, 3, 1))
    assert not result["valid"]
    assert result["temperature"] is None


def test_cross_year_assigned_to_start_year():
    start, end = date(2025, 12, 21), date(2026, 1, 5)
    result = aggregate_window(daily_rows(start, 15), start, end)
    assert result["year"] == 2025
    assert result["end"] == "2026-01-04"
    assert result["expected_days"] == 15
    assert result["valid"]


def test_paired_extrema_missing_not_filled():
    start = date(2020, 1, 1)
    rows = daily_rows(start, 10)
    rows["2020-01-01"]["temperature_2m_min"] = None
    rows["2020-01-02"]["temperature_2m_max"] = None
    result = aggregate_window(rows, start, date(2020, 1, 11))
    assert not result["valid"]
    assert "diurnal_pairs=8/10" in result["reason"]


def test_parameter_sensitivity_records_one_parameter_at_a_time():
    records = [annual(y) for y in range(1961, 1991)] + [annual(y, 10.36) for y in range(1996, 2026)]
    term = make_term(TERMS[0], records)
    assert term["sensitivity"]["sensitive"]
    assert len(term["sensitivity"]["checks"]) == 16
    assert all("parameter" in check for check in term["sensitivity"]["changes"])


def test_raw_date_and_unit_validation_fail_closed():
    payload = {"latitude": 39.9, "longitude": 116.4, "timezone": "Asia/Shanghai", "utc_offset_seconds": 28800,
               "daily_units": {"temperature_2m_mean": "°C", "temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm"},
               "daily": {"time": ["2000-01-01"], "temperature_2m_mean": [0], "temperature_2m_max": [2], "temperature_2m_min": [-2], "precipitation_sum": [None]}}
    validated = validate_chunk(payload, "2000-01-01", "2000-01-01")
    assert validated["2000-01-01"]["precipitation_sum"] is None
    payload["daily_units"]["precipitation_sum"] = "inch"
    try:
        validate_chunk(payload, "2000-01-01", "2000-01-01")
    except ValueError as exc:
        assert "单位" in str(exc)
    else:
        raise AssertionError("wrong units accepted")
    payload["daily_units"]["precipitation_sum"] = "mm"
    payload["daily"]["time"] = ["2000-01-02"]
    try:
        validate_chunk(payload, "2000-01-01", "2000-01-01")
    except ValueError as exc:
        assert "日期" in str(exc)
    else:
        raise AssertionError("wrong dates accepted")
