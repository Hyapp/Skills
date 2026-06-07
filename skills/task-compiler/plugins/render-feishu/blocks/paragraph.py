def render(data):
    c = data.get('content', '')
    bp = data.get('bold_prefix')
    if bp:
        return f'<p><b>{bp}</b>{c}</p>'
    return f'<p>{c}</p>'
