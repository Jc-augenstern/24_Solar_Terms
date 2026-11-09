"""Frozen v0.1 climate portrait method. No network access in this module."""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
METHOD_VERSION = "v0.1"
BASELINE = {"start": 1961, "end": 1990}
RECENT = {"start": 1996, "end": 2025}
WARNING = "本作品以历史气候差异生成艺术评级；‘已故’不代表节气在天文学上消失。"
DEMO_WARNING = "演示样例，非真实气候结论"
METRICS = (
    ("temperature", "平均气温", "℃", .60, .5),
    ("precipitation", "日均降水量", "mm/日", .25, .5),
    ("diurnal_range", "平均昼夜温差", "℃", .15, .5),
)
TERM_ROWS = [
    ("lichun", "立春"), ("yushui", "雨水"), ("jingzhe", "惊蛰"),
    ("chunfen", "春分"), ("qingming", "清明"), ("guyu", "谷雨"),
    ("lixia", "立夏"), ("xiaoman", "小满"), ("mangzhong", "芒种"),
    ("xiazhi", "夏至"), ("xiaoshu", "小暑"), ("dashu", "大暑"),
    ("liqiu", "立秋"), ("chushu", "处暑"), ("bailu", "白露"),
    ("qiufen", "秋分"), ("hanlu", "寒露"), ("shuangjiang", "霜降"),
    ("lidong", "立冬"), ("xiaoxue", "小雪"), ("daxue", "大雪"),
    ("dongzhi", "冬至"), ("xiaohan", "小寒"), ("dahan", "大寒"),
]
TERMS = [{"id": ident, "name": name, "season": "春夏秋冬"[i // 6],
          "order": i + 1, "longitude": (315 + 15 * i) % 360}
         for i, (ident, name) in enumerate(TERM_ROWS)]
STATUS_NAMES = {"alive": "健在", "critical": "病危", "departed": "已故", "insufficient_data": "资料不足"}


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def classify(score: float | None, low=40.0, high=70.0):
    if score is None or not math.isfinite(score):
        return "insufficient_data"
    return "alive" if score >= high else "critical" if score >= low else "departed"


def display_score(score):
    if score is None:
        return "—"
    display = f"{score:.2f}"
    if score < 40 and float(display) >= 40:
        return "<40"
    if score < 70 and float(display) >= 70:
        return "<70"
    return display


def score_metrics(metrics, weights=None, minima=None):
    if any(m["baseline"] is None or m["recent"] is None for m in metrics):
        return None
    weights = weights or [m["weight"] for m in metrics]
    minima = minima or [m["minimum_scale"] for m in metrics]
    distance = sum(w * abs(m["delta"]) / max(m["baseline_std"], minimum)
                   for m, w, minimum in zip(metrics, weights, minima))
    return 100.0 / (1.0 + distance)


def sensitivity(metrics, score):
    if score is None:
        return {"sensitive": False, "changes": [], "checks": [], "note": "资料不足，不计算敏感性。"}
    original = classify(score)
    checks = []
    for i, metric in enumerate(metrics):
        for factor in (.9, 1.1):
            weights = [m["weight"] for m in metrics]
            weights[i] *= factor
            weights = [w / sum(weights) for w in weights]
            result = score_metrics(metrics, weights=weights)
            checks.append({"parameter": f"weight.{metric['key']}", "factor": factor,
                           "score": result, "status": classify(result)})
            minima = [m["minimum_scale"] for m in metrics]
            minima[i] *= factor
            result = score_metrics(metrics, minima=minima)
            checks.append({"parameter": f"minimum_scale.{metric['key']}", "factor": factor,
                           "score": result, "status": classify(result)})
    for boundary in (40, 70):
        for delta in (-5, 5):
            status = classify(score, low=boundary + delta) if boundary == 40 else classify(score, high=boundary + delta)
            checks.append({"parameter": f"threshold.{boundary}", "delta": delta, "score": score, "status": status})
    changes = [c for c in checks if c["status"] != original]
    return {"sensitive": bool(changes), "changes": changes, "checks": checks,
            "note": "一次仅改变一个参数；敏感性不是统计置信度。"}


def culture(term):
    name, lon = term["name"], term["longitude"]
    fact = f"{name}对应太阳黄经{lon}°。二十四节气把太阳周年视运动分为每15°一段。"
    if name in ("立春", "立夏", "立秋", "立冬"):
        fact += f"在传统节气划分中，它标示{term['season']}季的开始。"
    elif name in ("春分", "秋分"):
        fact += "它是传统历法中的分点，表达昼夜时长接近的季节节点。"
    elif name == "夏至":
        fact += "它标示北半球一年中白昼最长的时节。"
    elif name == "冬至":
        fact += "它标示北半球一年中白昼最短的时节。"
    else:
        fact += "节气命名保存了古代中原地区的天气与农事经验。"
    fact += "名称不等于这座城市当天必然出现的天气或物候。"
    return {"text": fact, "source_name": "香港天文台《二十四节气》",
            "source_url": "https://www.hko.gov.hk/tc/gts/time/24solarterms.htm"}


def make_term(term, annual, is_demo=False):
    historic = [a for a in annual if a["valid"] and 1961 <= a["year"] <= 1990]
    current = [a for a in annual if a["valid"] and 1996 <= a["year"] <= 2025]
    enough = len(historic) >= 27 and len(current) >= 27
    metrics = []
    for key, name, unit, weight, minimum in METRICS:
        old = [a[key] for a in historic]
        new = [a[key] for a in current]
        old_mean = statistics.mean(old) if old else None
        new_mean = statistics.mean(new) if new else None
        std = statistics.stdev(old) if len(old) >= 2 else None
        metrics.append({"key": key, "name": name, "unit": unit, "baseline": old_mean,
                        "recent": new_mean, "delta": new_mean - old_mean if old_mean is not None and new_mean is not None else None,
                        "baseline_std": std, "recent_std": statistics.stdev(new) if len(new) >= 2 else None,
                        "minimum_scale": minimum, "scale": max(std, minimum) if std is not None else minimum,
                        "weight": weight, "baseline_n": len(old), "recent_n": len(new)})
    score = score_metrics(metrics) if enough else None
    reason = None if enough else f"历史期有效{len(historic)}年，近期有效{len(current)}年；任一时期不足27年，不生成确定评级。"
    prefix = "演示样例：" if is_demo else ""
    if enough:
        change = metrics[0]["delta"]
        summary = f"{prefix}时段平均气温较历史期变化{change:+.2f}℃。"
    else:
        summary = prefix + reason
    portrait = (f"{prefix}1961—1990年有效年度中，时段平均气温{metrics[0]['baseline']:.2f}℃，"
                f"日均降水{metrics[1]['baseline']:.2f}mm/日，平均昼夜温差{metrics[2]['baseline']:.2f}℃。") if historic else "历史有效样本不足，无法建立气候画像。"
    return {**term, "status": classify(score), "score": score, "score_display": display_score(score),
            "reason": reason, "summary": summary, "culture": culture(term), "historical_portrait": portrait,
            "metrics": metrics, "annual": annual, "sensitivity": sensitivity(metrics, score)}


def report_summary(terms, is_demo, city_name="北京"):
    counts = Counter(t["status"] for t in terms)
    prefix = DEMO_WARNING + "。" if is_demo else f"{city_name}代表点 ERA5 再分析："
    text = "、".join(f"{STATUS_NAMES[s]}{counts[s]}项" for s in STATUS_NAMES)
    strongest = max((t for t in terms if t["score"] is not None), key=lambda t: abs(t["metrics"][0]["delta"]), default=None)
    detail = f"{strongest['name']}时段平均气温变化{strongest['metrics'][0]['delta']:+.2f}℃。" if strongest else ""
    return prefix + text + "。" + detail


def common_report(terms, is_demo, city_id="beijing", city_name="北京"):
    return {"schema_version": "1.0", "report_id": "demo-v0.1" if is_demo else f"{city_id}-era5-v0.1",
            "is_demo": is_demo, "data_status": "demo" if is_demo else "ready",
            "baseline": BASELINE, "recent": RECENT, "method_version": METHOD_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(), "summary": report_summary(terms, is_demo, city_name),
            "review_status": "计算与自动质量检查已完成，文化及叙事待团队人工审阅" if not is_demo else "仅交互开发样例",
            "artistic_notice": WARNING, "terms": terms}


def methodology():
    return {"version": METHOD_VERSION, "title": "旧候相似指数 v0.1", "object": "城市代表点在某节气时段的历史气候画像",
            "notice": WARNING, "formula": "d = |近期均值 − 历史均值| / max(历史样本标准差, 最小尺度)；D = 0.60 d温度 + 0.25 d降水 + 0.15 d昼夜温差；S = 100 / (1 + D)",
            "baseline": BASELINE, "recent": RECENT,
            "metrics": [{"key": k, "name": n, "unit": u, "weight": w, "minimum_scale": m} for k,n,u,w,m in METRICS],
            "thresholds": [{"status": "alive", "rule": "S ≥ 70"}, {"status": "critical", "rule": "40 ≤ S < 70"}, {"status": "departed", "rule": "S < 40"}],
            "missing_data": "任一核心变量有效日数不足窗口日数90%，整年该节气窗口无效。昼夜温差还要求同日最高温和最低温成对有效率至少90%。任一比较期有效年度少于27年，不生成确定评级。缺失不补零。",
            "annual_window": "Skyfield solar_terms + JPL DE421，逐年计算交节时间并转换为北京时间固定UTC+08:00。统计交节日（含）至下一交节日（不含）；按起始交节公历年归档。日粒度近似忽略交节当天不足一天的时刻差异。",
            "timezone": "北京时间 UTC+08:00；请求时区 Asia/Shanghai，校验返回 utc_offset_seconds=28800。固定+08解释避免历史夏令时改变气候日窗口。",
            "statistics": "先计算每年度窗口的三个日平均指标，再对有效年度等权平均。标准差采用历史有效年度指标的样本标准差，分母 n−1。",
            "rounding": "评级使用未舍入值；显示两位小数，若舍入跨越40或70分界，则显示<40或<70。",
            "sensitivity": "一次仅改变一个参数：各权重及最小尺度±10%（权重重新归一），两条边界分别±5分；发生状态变化标记参数敏感。不是统计置信度。",
            "limitations": ["再分析不是气象站实测，代表点不是全市平均。", "1996—2025是本作品近期比较窗口，不是WMO标准常年期。", "指数是艺术规则，不代表消失比例、死亡概率或因果归因。", "无已故评级时生成家乡守候卡；不编造死亡年份。"],
            "sources": [{"name": "Open-Meteo Historical Weather API / ERA5", "url": "https://open-meteo.com/en/docs/historical-weather-api"}, {"name": "Skyfield Solar terms", "url": "https://rhodesmill.org/skyfield/almanac.html#solar-terms"}, {"name": "香港天文台：二十四节气", "url": "https://www.hko.gov.hk/tc/gts/time/24solarterms.htm"}]}


if __name__ == "__main__":
    write_json(DATA / "methodology" / "v0.1.json", methodology())
