"""Generate fake regional customer data (completely different from product sales)."""
import json, random, sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

random.seed(123)

regions = ['华东', '华南', '华北', '西部']
quarters = ['2026-Q1', '2026-Q2', '2026-Q3']
base_visitors = [85000, 72000, 65000, 38000]

headers = ['区域', '季度', '访问量', '注册数', '订单数', '转化率(%)']
values = []
for i, region in enumerate(regions):
    for q in quarters:
        visitors = int(base_visitors[i] * random.uniform(0.85, 1.15))
        signups = int(visitors * random.uniform(0.03, 0.08))
        orders = int(signups * random.uniform(0.4, 0.7))
        conv = round(orders / visitors * 100, 2)
        values.append([region, q, str(visitors), str(signups), str(orders), str(conv)])

total_visitors = sum(int(v[2]) for v in values)
total_signups = sum(int(v[3]) for v in values)
total_orders = sum(int(v[4]) for v in values)
avg_conv = round(total_orders / total_visitors * 100, 2)

result = {
    'status': 'ok',
    'dataset': 'regional-customers',
    'total_visitors': total_visitors,
    'total_signups': total_signups,
    'total_orders': total_orders,
    'avg_conversion': avg_conv,
    'region_count': len(regions),
    'quarter_count': len(quarters),
    'headers': headers,
    'values': values,
}
print(json.dumps(result, ensure_ascii=True))
