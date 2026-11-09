"""Deterministic synthetic interaction fixture. Never real city data."""
from datetime import date, timedelta
import math
from climate import DATA, TERMS, common_report, make_term, methodology, write_json


def build():
    terms = []
    for i, term in enumerate(TERMS):
        records = []
        for year in range(1961, 2026):
            phase = (year - 1961) % 30
            noise = math.sin(phase * 2 * math.pi / 30)
            # Explicitly artificial boundaries; real reports use astronomical dates.
            approx = date(year, 1, 5) + timedelta(days=((i + 2) % 24) * 15)
            shift = (0.1, 1.1, 3.6, .4)[i % 4] if year >= 1996 else 0
            valid = not (i == 23 and 1996 <= year <= 1999)
            records.append({"year": year, "start": approx.isoformat(), "end": (approx + timedelta(days=14)).isoformat(),
                            "valid": valid, "reason": None if valid else "演示：核心变量缺失超过10%",
                            "temperature": 12 + 12 * math.sin(i * math.pi / 12 - 1) + noise + shift if valid else None,
                            "precipitation": max(.1, 1.5 + math.sin(i * math.pi / 12) + noise * .3 + shift * .1) if valid else None,
                            "diurnal_range": 9 + noise * .5 - shift * .2 if valid else None})
        terms.append(make_term(term, records, is_demo=True))
    report = common_report(terms, True)
    report["city"] = {"id": "demo", "name": "样例城", "representative_point": {"latitude": None, "longitude": None, "description": "虚构开发样例，不对应任何真实城市"}, "grid": {"latitude": None, "longitude": None, "elevation": None}}
    report["source"] = {"name": "人工构造开发样例", "url": "", "model": "synthetic", "attribution": "仅用于开发和交互验证", "description": "演示样例，非真实气候结论；曲线与日期均为人工构造。"}
    report["quality"] = {"is_synthetic": True, "warning": "演示样例，非真实气候结论", "annual_dates": "人工近似日期仅用于界面验证，不属于真实节气历表", "complete_terms": 24}
    write_json(DATA / "reports" / "demo.json", report)
    write_json(DATA / "methodology" / "v0.1.json", methodology())
    print(report["summary"])


if __name__ == "__main__":
    build()
