import json, urllib.request
O = "https://black.memo-ora.com"
def call(m, path, body=None, tok=None):
    req = urllib.request.Request(O + path, method=m, data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json", "user-agent": "Mozilla/5.0 blackmoa-demo", **({"authorization": "Bearer " + tok} if tok else {})})
    try:
        with urllib.request.urlopen(req) as r:
            b = r.read(); return r.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b)
        except Exception: return e.code, {"raw": b[:200]}
