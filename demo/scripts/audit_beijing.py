"""Independent spot audit from raw daily values, without importing rating code."""
import csv
import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit():
    report = json.loads((ROOT / "data/reports/beijing.json").read_text(encoding="utf-8"))
    with (ROOT / "data/raw/beijing/daily.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = {row["date"]: {k: float(v) if v else None for k, v in row.items() if k != "date"} for row in csv.DictReader(stream)}
    all_checks = []
    for term_id in ("lichun", "dongzhi"):
        term = next(t for t in report["terms"] if t["id"] == term_id)
        recomputed = []
        for annual in term["annual"]:
            start, end = date.fromisoformat(annual["start"]), date.fromisoformat(annual["end"])
            days = [rows[(start + timedelta(days=i)).isoformat()] for i in range((end - start).days + 1)]
            counts = {key: sum(day[key] is not None for day in days) for key in ("temperature_2m_mean", "temperature_2m_max", "temperature_2m_min", "precipitation_sum")}
            paired = [day["temperature_2m_max"] - day["temperature_2m_min"] for day in days if day["temperature_2m_max"] is not None and day["temperature_2m_min"] is not None]
            valid = all(count / len(days) >= .9 for count in counts.values()) and len(paired) / len(days) >= .9
            assert valid == annual["valid"]
            if not valid:
                continue
            metrics = {"temperature": statistics.mean(d["temperature_2m_mean"] for d in days if d["temperature_2m_mean"] is not None),
                       "precipitation": statistics.mean(d["precipitation_sum"] for d in days if d["precipitation_sum"] is not None),
                       "diurnal_range": statistics.mean(paired)}
            for key, value in metrics.items():
                assert math.isclose(value, annual[key], abs_tol=1e-12), (term_id, annual["year"], key)
            recomputed.append({"year": annual["year"], **metrics})
        distance, checks = 0, []
        for metric, weight in zip(term["metrics"], (.60, .25, .15)):
            key = metric["key"]
            old = [row[key] for row in recomputed if 1961 <= row["year"] <= 1990]
            new = [row[key] for row in recomputed if 1996 <= row["year"] <= 2025]
            assert len(old) == 30 and len(new) == 30
            before, after, std = statistics.mean(old), statistics.mean(new), statistics.stdev(old)
            assert math.isclose(before, metric["baseline"], abs_tol=1e-12)
            assert math.isclose(after, metric["recent"], abs_tol=1e-12)
            assert math.isclose(std, metric["baseline_std"], abs_tol=1e-12)
            distance += weight * abs(after - before) / max(std, .5)
            checks.append({"key": key, "baseline": before, "recent": after, "delta": after-before, "sample_std": std})
        score = 100 / (1 + distance)
        status = "alive" if score >= 70 else "critical" if score >= 40 else "departed"
        assert math.isclose(score, term["score"], abs_tol=1e-12)
        assert status == term["status"]
        all_checks.append({"term": term["name"], "valid_annual_windows": len(recomputed), "metrics": checks, "score": score, "status": status,
                           "window_2025_end": next(a["end"] for a in term["annual"] if a["year"] == 2025)})
    result = {"passed": True, "description": "从原始缓存导出的逐日值独立重算立春与冬至65年度窗口，核对两个30年均值、样本标准差、指数与评级。", "checks": all_checks}
    output = ROOT / "qa/raw_data_audit.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    audit()
