import json, shutil, subprocess

_lark_cli = None


def get_lark_cli():
    global _lark_cli
    if _lark_cli is None:
        _lark_cli = next(
            (e for e in ('lark-cli.cmd', 'lark-cli.exe', 'lark-cli') if shutil.which(e)),
            None,
        )
    return _lark_cli


def sh_run(cmd):
    """Run a command via shell=True with UTF-8 output."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                         timeout=60, encoding='utf-8')


def arg(val):
    """Shell-safe argument quoting. Uses JSON encoding to handle
    embedded quotes, newlines, and CJK characters without GBK corruption."""
    return json.dumps(val, ensure_ascii=False)
