"""Independent evidence check: recompute Beijing statistics using stdlib only."""
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify():
    report = json.loads((ROOT / 'data/reports/beijing.json').read_text(encoding='utf-8'))
    assert report['is_demo'] is False
    assert report['source']['model'].lower() == 'era5'
    assert report['baseline'] == {'start': 1961, 'end': 1990}
    assert report['recent'] == {'start': 1996, 'end': 2025}
    assert len(report['terms']) == 24
    evidence = []
    for term in report['terms']:
        assert term['status'] != 'insufficient_data', term['reason']
        deviations = []
        for m, weight in zip(term['metrics'], [0.60, 0.25, 0.15]):
            old = [a[m['key']] for a in term['annual'] if a['valid'] and 1961 <= a['year'] <= 1990]
            new = [a[m['key']] for a in term['annual'] if a['valid'] and 1996 <= a['year'] <= 2025]
            assert len(old) >= 27 and len(new) >= 27
            old_mean, new_mean = statistics.mean(old), statistics.mean(new)
            std = statistics.stdev(old)
            for actual, expected in [(m['baseline'], old_mean), (m['recent'], new_mean), (m['delta'], new_mean-old_mean), (m['baseline_std'], std)]:
                assert math.isclose(actual, expected, abs_tol=1e-10), (term['name'], m['key'], actual, expected)
            assert m['weight'] == weight
            deviations.append(weight * abs(new_mean-old_mean)/max(std, 0.5))
        score = 100/(1+sum(deviations))
        state = 'alive' if score >= 70 else 'critical' if score >= 40 else 'departed'
        assert math.isclose(term['score'], score, abs_tol=1e-10)
        assert term['status'] == state
        evidence.append({'term': term['name'], 'score': score, 'status': state,
                         'historical_temperature': term['metrics'][0]['baseline'],
                         'recent_temperature': term['metrics'][0]['recent']})
    result = {'passed': True, 'checks': '24节气年度序列独立复算：时期均值、样本标准差、变化量、S与状态', 'terms': evidence}
    (ROOT / 'qa/report_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    verify()
