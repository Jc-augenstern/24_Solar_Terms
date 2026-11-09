"""Explicit synthetic all-alive fixture for the no-obituary browser branch."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from climate import TERMS, make_term, report_summary

sample = json.loads((ROOT / 'data/reports/demo.json').read_text(encoding='utf-8'))
for meta, old in zip(TERMS, sample['terms']):
    for row in old['annual']:
        row.update(valid=True, reason=None, temperature=10, precipitation=0, diurnal_range=8)
sample['terms'] = [make_term(meta, old['annual'], is_demo=True) for meta, old in zip(TERMS, sample['terms'])]
sample['summary'] = report_summary(sample['terms'], True)
sample['report_id'] = 'qa-synthetic-all-alive'
assert all(t['score'] == 100 and t['status'] == 'alive' for t in sample['terms'])
(ROOT / 'qa/all-alive-demo.json').write_text(json.dumps(sample, ensure_ascii=False), encoding='utf-8')
