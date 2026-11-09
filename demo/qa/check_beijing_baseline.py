"""Read-only comparison with the protected, pre-extension Beijing snapshot."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT.parent / 'output' / 'baselines' / 'beijing-20261029-before-34cities'


def rows(path):
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as conn:
        return {table: conn.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in ('tributes', 'request_keys')}


def main():
    before = json.loads((BASELINE / 'baseline.json').read_text(encoding='utf-8'))
    checks = []
    for relative, expected in before['sha256'].items():
        name = relative.replace('\\', '/')
        if name in ('data/reports/beijing.json', 'data/reports/demo.json', 'data/methodology/v0.1.json', 'data/raw/beijing/request_manifest.json', 'data/raw/beijing/daily.csv') or name.startswith('data/raw/beijing/era5_') or name.startswith('data/raw/astronomy/'):
            current = ROOT / relative
            actual = hashlib.sha256(current.read_bytes()).hexdigest()
            checks.append({'file': name, 'unchanged': expected == actual})
    original = rows(BASELINE / 'tributes.sqlite3')
    current = rows(ROOT / 'data' / 'tributes.sqlite3')
    result = {'passed': all(c['unchanged'] for c in checks) and current == original,
              'files': checks, 'formal_database_unchanged': current == original,
              'formal_tribute_rows_before': len(original['tributes']), 'formal_tribute_rows_after': len(current['tributes']),
              'baseline_directory': str(BASELINE)}
    out = ROOT / 'qa' / 'multicity'; out.mkdir(parents=True, exist_ok=True)
    (out / 'beijing-baseline-regression.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
