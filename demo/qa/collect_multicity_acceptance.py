"""Combine independently recorded data and actual browser evidence without inflation."""
from __future__ import annotations
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'qa' / 'multicity'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    data = read(OUT / 'data-audit.json')
    browser = read(OUT / 'browser-results.json')
    statuses = {c['id']: c for c in browser['city_statuses']}
    observed = {(c['id'], c['phase']): c for c in browser['cities']}
    persisted = {c['id']: c for c in browser.get('offline_write_restart', [])}
    tasks = read(ROOT / 'data' / 'batch_tasks.json') if (ROOT / 'data' / 'batch_tasks.json').exists() else {}
    result = {
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'scope': '34 registered representative cities; only published genuine reports count as data coverage',
        'data_complete': data['data_complete'], 'registered': 34,
        'data_audit_passed_for_published': data['passed_for_published'],
        'browser_checks_passed': browser['passed'], 'browser_checks': browser['checks'],
        'offline_scope': 'Application-process non-loopback socket denial plus browser external-request blocking; no machine-wide firewall/network changes',
        'test_database': browser['test_database'],
        'latest_task_record_at': tasks.get('updated_at'),
        'browser_external_requests': browser['external_requests'],
        'cities': [],
    }
    lines = ['# 34城逐城实际验收清单', '',
             '以下数据、页面、图表、纪念与图片分别记账。未发布城市的入口与错误提示检查不算真实报告完成。', '',
             '| 城市 | 地区/分类 | 真实数据 | 名册 | 图表 | 纪念 | PNG | 断网冷启动 | 原因 |',
             '|---|---|---|---|---|---|---|---|---|']
    registry = {c['id']: c for c in read(ROOT / 'config' / 'cities.json')['cities']}
    for audit in data['cities']:
        ident = audit['id']; status = statuses.get(ident, {})
        task = tasks.get('cities', {}).get(ident, {})
        current = ROOT / 'data' / 'reports' / f'{ident}.json'
        unchanged = current.exists() and hashlib.sha256(current.read_bytes()).hexdigest() == audit.get('report_sha256')
        online = observed.get((ident, 'online'), {}); offline = observed.get((ident, 'offline'), {})
        if online.get('generated_at') != audit.get('generated_at'): online = {}
        if offline.get('generated_at') != audit.get('generated_at'): offline = {}
        restart = persisted.get(ident, {})
        restart_passed = restart.get('generated_at') == audit.get('generated_at') and restart.get('persisted') is True and restart.get('retry_deduplicated') is True
        item = {
            'id': ident, 'name': audit['name'], 'region': registry[ident]['region'], 'category': registry[ident]['category'],
            'data': audit['data'] if unchanged else ('not_published' if not current.exists() else 'changed_since_audit'),
            'data_status': 'ready' if audit['data'] == 'passed' and unchanged else task.get('status', status.get('data_status', 'not_checked')),
            'browser_observed_status': status.get('data_status', 'not_checked'),
            'reason': task.get('last_error') or status.get('reason', audit.get('error')),
            'cached_slices': task.get('cached_slices', sum(s.get('status') == 'cached' for s in task.get('slices', []))),
            'total_slices': len(task.get('slices', [])), 'resume_at': task.get('resume_at'),
            'recovery': task.get('recovery'),
            'report_sha256': audit.get('report_sha256'),
            'page': online.get('page', 'not_checked'), 'chart': online.get('chart', 'not_checked'),
            'memorial': online.get('memorial', 'not_checked'), 'poster': online.get('poster', 'not_checked'),
            'offline': 'passed' if offline and all(offline.get(k) == 'passed' for k in ('page', 'chart', 'memorial', 'poster', 'offline_new_writes')) and restart_passed else 'not_checked',
            'offline_new_writes': offline.get('offline_new_writes', 'not_checked'),
            'offline_new_writes_after_restart': 'passed' if restart_passed else 'not_checked',
            'raw_audit': audit.get('raw_checks'), 'counts': audit.get('counts'),
            'poster_file': online.get('poster_file'),
        }
        result['cities'].append(item)
        labels = {'passed': '通过', 'not_checked': '未验收', 'not_published': '未发布', 'failed': '失败', 'changed_since_audit': '待重验'}
        cells = [item['name'], f"{item['region']} / {item['category']}"] + [labels.get(item[k], item[k]) for k in ('data','page','chart','memorial','poster','offline')]
        reason = (item['reason'] or '').replace('|', '/').replace('\n', ' ')
        if item['data'] != 'passed' and item['total_slices']:
            reason = f"已缓存{item['cached_slices']}/{item['total_slices']}片；" + reason
        cells.append(reason)
        lines.append('| ' + ' | '.join(cells) + ' |')
    result['all_34_complete'] = browser['passed'] and all(all(c[k] == 'passed' for k in ('data','page','chart','memorial','poster','offline')) for c in result['cities'])
    (OUT / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines += ['', f"真实报告完成 {result['data_complete']}/34 城。全34城验收完成：{'是' if result['all_34_complete'] else '否'}。", '',
              '离线范围：实际后端进程拒绝非 loopback socket，浏览器拦截全部外网请求，保留本机服务。未修改全机网络，也不冒充已物理断网。',
              '离线通过要求包含每个完成城为新节气新增点灯与献花，再次断网冷启动后核对计数、按钮和重复请求幂等。',
              f"本轮浏览器测试SQLite：`{browser['test_database']}`。正式纪念库未用于测试。", '',
              '详细证据：同目录 data-audit.json、browser-results.json，以及每个已完成城市的 roster/detail/chart 截图和 online/offline PNG。']
    (OUT / '城市验收清单.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'data_complete':result['data_complete'],'browser_passed':browser['passed'],'all_34_complete':result['all_34_complete']},ensure_ascii=False))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    main()
