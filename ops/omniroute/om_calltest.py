"""One real chat call per model/combo with the hermes key (read from file, never printed).
usage: om_calltest.py <base> <model>..."""
import json, sys, time, urllib.error, urllib.request

base, models = sys.argv[1], sys.argv[2:]
key = open("/docker/omniroute/hermes-api-key").read().strip()
for m in models:
    body = {"model": m, "messages": [{"role": "user", "content": "한 단어로만 답해: 대한민국의 수도는?"}], "max_tokens": 64}
    r = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                        "X-Session-Id": "calltest"})
    t = time.time()
    try:
        with urllib.request.urlopen(r, timeout=120) as x:
            d = json.load(x)
            h = {k.lower(): v for k, v in x.headers.items()}
            msg = (d.get("choices") or [{}])[0].get("message", {})
            text = (msg.get("content") or msg.get("reasoning_content") or "").strip().replace("\n", " ")
            print(f"{m:28} 200 {time.time() - t:5.1f}s served={d.get('model')} via={h.get('x-omniroute-selected-connection-id', '')[:8]} {text[:40]!r}")
    except urllib.error.HTTPError as e:
        print(f"{m:28} {e.code} {time.time() - t:5.1f}s {e.read().decode('utf-8', 'replace')[:200]}")
    except Exception as e:
        print(f"{m:28} ERR {time.time() - t:5.1f}s {type(e).__name__}")
