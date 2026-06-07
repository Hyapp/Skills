#!/usr/bin/env python3
"""
render.py — IR → 飞书云文档渲染器

Usage:
    python plugins/render-feishu/render.py <ir.yaml>

IR format (application/vnd.feishu-doc-ir):
{
  "title": "文档标题",
  "description": "引言（可选）",
  "sections": [
    {"type": "heading1", "content": "1. 总结"},
    {"type": "render-order", "path": "agents/summary-1/result.md"},
    {"type": "sheet", "sheet_ref": "ref_key"},
    ...
  ],
  "context": {
    "sheets": {
      "ref_key": {"headers": [...], "rows": [[...], ...]}
    }
  }
}

render-order pragma: 从 task-compiler 节点输出文件读取内容，
  path 相对于 IR 文件所在目录。

Output (stdout): {"status":"ok","document_token":"...","document_url":"..."}
"""
import csv, json, os, re, sys
from pathlib import Path

import yaml

# Allow running as script (directory name has hyphen, not a valid Python identifier)
_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from utils import get_lark_cli, sh_run, arg
from blocks import render as render_block


def resolve_render_order(sec, base_dir, depth=0):
    """Resolve a render-order pragma: read file, extract text, return as paragraph content.

    Safe against nested render-order chains (depth guard).
    """
    path = sec.get('path', '')
    if not path:
        return '<p>[render-order: no path]</p>'

    target = (base_dir / path).resolve()
    if not target.exists():
        return f'<p>[render-order: file not found: {path}]</p>'

    try:
        raw = target.read_text(encoding='utf-8').strip()
        # Try JSON with text field first (agent output convention)
        if raw.startswith('{') and raw.endswith('}'):
            parsed = json.loads(raw)
            text = parsed.get('text') or parsed.get('content') or raw
        else:
            text = raw
    except (json.JSONDecodeError, OSError):
        text = raw

    bp = sec.get('bold_prefix')
    if bp:
        return f'<p><b>{bp}</b>{text}</p>'
    return f'<p>{text}</p>'


def build_xml(ir, ir_path):
    """Convert IR sections to DocxXML, resolving render-order pragmas."""
    base_dir = ir_path.resolve().parent

    parts = [f'<title>{ir["title"]}</title>']
    if ir.get('description'):
        parts.append(f'<p>{ir["description"]}</p>')

    for sec in ir.get('sections', []):
        st = sec.get('type', '')
        if st == 'render-order':
            parts.append(resolve_render_order(sec, base_dir))
        else:
            xml = render_block(sec)
            if xml:
                parts.append(xml)

    return ''.join(parts)


def fetch_sheet_tokens(doc_token, lc):
    """Fetch document and extract embedded sheet token/sheet-id pairs."""
    r = sh_run(
        f'{lc} docs +fetch --api-version v2 --doc {doc_token} --detail with-ids'
    )
    if r.returncode != 0:
        print(json.dumps({'error': 'doc fetch failed', 'stderr': r.stderr.strip()}),
              file=sys.stderr)
        sys.exit(r.returncode)

    content = json.loads(r.stdout).get('data', {}).get('document', {}).get('content', '')

    # Try token first, then sheet-id first (attribute order varies)
    pairs = re.findall(
        r'<sheet\s+[^>]*\btoken="([^"]+)"[^>]*\bsheet-id="([^"]+)"', content
    )
    if not pairs:
        pairs = re.findall(
            r'<sheet\s+[^>]*\bsheet-id="([^"]+)"[^>]*\btoken="([^"]+)"', content
        )
        pairs = [(t, s) for s, t in pairs]
    return pairs


def fill_sheet(stok, sid, data, lc):
    """Write sheet data via CSV upload. Returns (ok, error_msg)."""
    csv_path = '_tmp_' + os.urandom(4).hex() + '.csv'
    try:
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(data['headers'])
            for row in data['rows']:
                w.writerow(row)
        r = sh_run(
            f'{lc} sheets +csv-put --spreadsheet-token {stok} '
            f'--sheet-id {sid} --start-cell A1 --csv - < {csv_path}'
        )
        return r.returncode == 0, ''
    except Exception as e:
        return False, str(e)
    finally:
        if os.path.exists(csv_path):
            os.unlink(csv_path)


def main():
    if len(sys.argv) < 2:
        print(f'Usage: python {Path(__file__).name} <ir.json>', file=sys.stderr)
        sys.exit(1)

    ir_path = Path(sys.argv[1])
    if not ir_path.exists():
        print(json.dumps({'error': f'IR file not found: {ir_path}'}), file=sys.stderr)
        sys.exit(1)

    ir = yaml.safe_load(ir_path.read_text(encoding='utf-8'))

    lc = get_lark_cli()
    if not lc:
        print(json.dumps({'error': 'lark-cli not found in PATH'}), file=sys.stderr)
        sys.exit(1)

    # ── Build DocxXML (resolve render-order pragmas) ──
    doc_xml = build_xml(ir, ir_path)

    # ── Create document ──
    r1 = sh_run(
        f'{lc} docs +create --api-version v2 '
        f'--title {arg(ir["title"])} '
        f'--content {arg(doc_xml)}'
    )
    if r1.returncode != 0:
        print(json.dumps({'error': 'doc create failed',
                          'stderr': r1.stderr.strip()}), file=sys.stderr)
        sys.exit(r1.returncode)

    doc_out = json.loads(r1.stdout)
    doc_token = doc_out.get('data', {}).get('document', {}).get('document_id', '')
    doc_url = doc_out.get('data', {}).get('document', {}).get('url', '')
    if not doc_token:
        print(json.dumps({'error': 'no document_id in create response'}), file=sys.stderr)
        sys.exit(1)

    # ── Fill sheets ──
    sheet_refs = [s for s in ir.get('sections', []) if s['type'] == 'sheet']
    sheets_result = []

    if sheet_refs:
        sheet_tokens = fetch_sheet_tokens(doc_token, lc)
        sheets_data = ir.get('context', {}).get('sheets', {})

        for idx, sec in enumerate(sheet_refs):
            ref = sec.get('sheet_ref', '')
            data = sheets_data.get(ref) if ref else None
            if not data:
                sheets_result.append({'ref': ref, 'ok': False, 'error': 'no data'})
                continue
            if idx >= len(sheet_tokens):
                sheets_result.append({'ref': ref, 'ok': False,
                                      'error': 'no sheet found in doc'})
                continue

            stok, sid = sheet_tokens[idx]
            ok, err = fill_sheet(stok, sid, data, lc)
            sheets_result.append({
                'ref': ref, 'ok': ok, 'token': stok, 'sheet_id': sid,
                **( {'error': err} if err else {} ),
            })

    # ── Output ──
    result = {
        'status': 'ok',
        'document_token': doc_token,
        'document_url': doc_url,
        'sheets': sheets_result,
    }
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
