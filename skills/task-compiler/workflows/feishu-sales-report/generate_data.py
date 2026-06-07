"""Generate fake sales data (no lark-cli). Output pure-ASCII JSON."""
import json, random, sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

random.seed(42)

products = ['智能手表 Pro', '无线降噪耳机', '机械键盘', '4K 显示器', '便携充电宝', '人体工学椅']
months = ['2026年1月', '2026年2月', '2026年3月']
prices = [2999, 1299, 599, 2499, 199, 1599]

headers = ['产品名称', '月份', '销量', '单价（元）', '销售额（元）']
values = []
for p, pr in zip(products, prices):
    for m in months:
        qty = random.randint(50, 500)
        rev = qty * pr
        values.append([p, m, str(qty), str(pr), str(rev)])

total_revenue = sum(int(v[4]) for v in values)
total_orders = sum(int(v[2]) for v in values)
top = max(values, key=lambda v: int(v[4]))

result = {
    'status': 'ok',
    'total_revenue': total_revenue,
    'total_orders': total_orders,
    'top_product': top[0],
    'top_month': top[1],
    'top_quantity': int(top[2]),
    'top_revenue': int(top[4]),
    'product_count': len(products),
    'month_count': len(months),
    'headers': headers,
    'values': values,
}
print(json.dumps(result, ensure_ascii=True))
