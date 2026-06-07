#!/usr/bin/env python3
"""
build_ir.py — 从数据 JSON 构建 IR（Intermediate Representation）

Usage:
    python build_ir.py --output-dir <output_dir> \\
        --result1 <data1.json> --result2 <data2.json>

Output: IR YAML 写入 <output_dir>/_ir.yaml
Render-order pragma 的 path 相对 output-dir 构造，render 时解析。
"""
import json, sys
from pathlib import Path
import yaml


def parse_args():
    args = {}
    for i, a in enumerate(sys.argv):
        if a == '--output-dir' and i + 1 < len(sys.argv):
            args['output_dir'] = Path(sys.argv[i + 1])
        elif a == '--result1' and i + 1 < len(sys.argv):
            args['result1'] = Path(sys.argv[i + 1])
        elif a == '--result2' and i + 1 < len(sys.argv):
            args['result2'] = Path(sys.argv[i + 1])
    return args


def compute_stats(headers, values):
    numeric_cols = []
    for ci, h in enumerate(headers):
        if ci > 0 and all(v[ci].replace('.', '', 1).lstrip('-').isdigit() for v in values if v[ci]):
            numeric_cols.append(ci)
    rows = []
    for ci in numeric_cols:
        nums = [float(v[ci]) for v in values]
        mean = sum(nums) / len(nums)
        min_val = min(nums)
        max_val = max(nums)
        min_row = next(v[0] for v in values if float(v[ci]) == min_val)
        max_row = next(v[0] for v in values if float(v[ci]) == max_val)
        rows.append({'column': headers[ci], 'mean': round(mean, 2),
                     'min': min_val, 'min_at': min_row,
                     'max': max_val, 'max_at': max_row})
    return rows


def stats_text(label, total_label, total, stats):
    parts = [f'{label}数据总览：{total_label} {total:,}。']
    for s in stats:
        parts.append(
            f'{s["column"]}：均值 {s["mean"]:,.2f}，'
            f'范围 [{s["min"]:,.0f} ~ {s["max"]:,.0f}]'
            f'（最低：{s["min_at"]}，最高：{s["max_at"]}）。'
        )
    return ''.join(parts)


def main():
    args = parse_args()
    output_dir = args.get('output_dir')
    if not output_dir:
        print(json.dumps({'error': '--output-dir required'}), file=sys.stderr)
        sys.exit(1)
    output_dir = output_dir.resolve()

    r1_path = args.get('result1')
    r2_path = args.get('result2')
    if not r1_path or not r1_path.exists():
        print(json.dumps({'error': 'result1 not found'}), file=sys.stderr)
        sys.exit(1)
    if not r2_path or not r2_path.exists():
        print(json.dumps({'error': 'result2 not found'}), file=sys.stderr)
        sys.exit(1)

    d1 = json.loads(r1_path.read_text(encoding='utf-8').strip())
    d2 = json.loads(r2_path.read_text(encoding='utf-8').strip())

    stats1 = compute_stats(d1['headers'], d1['values'])
    stats2 = compute_stats(d2['headers'], d2['values'])

    ir = {
        'version': 1,
        'title': '综合数据报告',
        'description': '本报告包含产品销售与区域客户两组数据的分析。',
        'sections': [
            {'type': 'heading1', 'content': '1. 总结'},
            {'type': 'render-order', 'path': 'agents/summary-1/result.md'},

            {'type': 'heading1', 'content': '2. 产品销售分析'},
            {'type': 'heading2', 'content': '2.1 数据'},
            {'type': 'sheet', 'sheet_ref': 'sales'},
            {'type': 'heading2', 'content': '2.2 总结'},
            {'type': 'render-order', 'path': 'agents/summary-2-2/result.md',
             'bold_prefix': '产品销售数据总览'},

            {'type': 'heading1', 'content': '3. 区域客户分析'},
            {'type': 'heading2', 'content': '3.1 数据'},
            {'type': 'sheet', 'sheet_ref': 'customers'},
            {'type': 'heading2', 'content': '3.2 总结'},
            {'type': 'render-order', 'path': 'agents/summary-3-2/result.md',
             'bold_prefix': '区域客户数据总览'},
        ],
        'context': {
            'sheets': {
                'sales': {
                    'headers': d1['headers'],
                    'rows': d1['values'],
                },
                'customers': {
                    'headers': d2['headers'],
                    'rows': d2['values'],
                },
            },
        },
        '_stats': {
            'sales': stats1,
            'customers': stats2,
            'sales_overview': stats_text('产品销售', '总营收', d1.get('total_revenue', 0), stats1),
            'customers_overview': stats_text('区域客户', '总访客', d2.get('total_visitors', 0), stats2),
        },
    }

    # Write IR to output dir (YAML format)
    ir_path = output_dir / '_ir.yaml'
    ir_path.write_text(
        yaml.dump(ir, allow_unicode=True, default_flow_style=None, sort_keys=False, width=120),
        encoding='utf-8',
    )
    print(json.dumps({'status': 'ok', 'ir_path': str(ir_path)}))


if __name__ == '__main__':
    main()
