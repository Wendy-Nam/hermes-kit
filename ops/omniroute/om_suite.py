"""Combo-level acceptance tests against OmniRoute with the hermes key (never printed).
usage: om_suite.py loop|bigctx|stream|responses|cache [combo...]
  loop       Hermes 25-tool multi-turn loop: read two files, answer in Korean. PASS = answer within 5 turns, no repeat call
  bigctx     ~60k-token prompt (needle at the start), PASS = needle answered
  stream     SSE with tools, PASS = >1 chunk and a tool call or text
  responses  /v1/responses (coder profile api_mode codex_responses), PASS = output text
  cache      same ~8k-token prefix twice with one X-Session-Id: served model + cached_tokens"""
import json, sys, time, urllib.error, urllib.request

BASE, MIG = "http://127.0.0.1:20128", "/docker/omniroute/migrate"
KEY = open("/docker/omniroute/hermes-api-key").read().strip()
TOOLS = json.load(open(f"{MIG}/hermes-tools.json"))
test, combos = sys.argv[1], sys.argv[2:]


def post(path, body, sid="suite", timeout=240, stream=False):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}",
                                        "X-Session-Id": sid, "X-OmniRoute-No-Cache": "true"})
    t = time.time()
    try:
        x = urllib.request.urlopen(r, timeout=timeout)
        return time.time() - t, (x if stream else json.load(x)), None
    except urllib.error.HTTPError as e:
        return time.time() - t, None, f"{e.code} {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:
        return time.time() - t, None, type(e).__name__


FILES = {"/etc/hostname": "hermes-prod\n", "/etc/os-release": 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nVERSION_ID="13"\n'}


def loop(c):
    msgs = [{"role": "system", "content": "You are Hermes, a helpful agent. Use tools when needed."},
            {"role": "user", "content": "read_file로 /etc/hostname 과 /etc/os-release 를 읽고, 호스트 이름과 OS를 한국어 한 문장으로 알려줘."}]
    seen, served, total = [], set(), 0
    for turn in range(1, 6):
        dt, d, err = post("/v1/chat/completions", {"model": c, "messages": msgs, "tools": TOOLS, "max_tokens": 800}, sid=f"loop-{c}")
        total += dt
        if err:
            return f"FAIL turn {turn}: {err}"
        served.add(d.get("model"))
        msg = d["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            text = (msg.get("content") or "").strip().replace("\n", " ")
            ok = "hermes-prod" in text and ("Debian" in text or "데비안" in text)
            return f"{'PASS' if ok else 'WEAK'} {turn} turns {total:.0f}s served={sorted(served)} {text[:70]!r}"
        msgs.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")} | {"content": msg.get("content") or ""})
        for tc in calls:
            args = tc["function"].get("arguments") or "{}"
            try:
                path = json.loads(args).get("path", "")
            except Exception:
                path = ""
            if (tc["function"]["name"], args) in seen:   # same tool with identical arguments = the loop symptom
                return f"FAIL repeated {tc['function']['name']}({args[:60]}) at turn {turn} served={sorted(served)}"
            seen.append((tc["function"]["name"], args))
            out = FILES.get(path) or "\n".join(v for k, v in FILES.items() if k in args) or f"(no such file: {path})"
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
    return f"FAIL no answer after 5 turns served={sorted(served)}"


def bigctx(c):
    filler = "\n".join(f"{i}번째 기록: 오늘도 평범한 하루였다. 특별한 일은 없었고 날씨는 맑았다." for i in range(4200))
    body = {"model": c, "max_tokens": 60, "messages": [
        {"role": "user", "content": "비밀 코드는 '파란고래-7'이다. 기억해.\n\n" + filler + "\n\n맨 처음에 알려준 비밀 코드가 뭐였지? 코드만 답해."}]}
    dt, d, err = post("/v1/chat/completions", body, sid=f"big-{c}")
    if err:
        return f"FAIL {dt:.0f}s {err}"
    text = (d["choices"][0]["message"].get("content") or "").strip()
    u = d.get("usage") or {}
    return f"{'PASS' if '파란고래' in text else 'WEAK'} {dt:.0f}s in={u.get('prompt_tokens')} served={d.get('model')} {text[:40]!r}"


def stream(c):
    body = {"model": c, "stream": True, "tools": TOOLS, "max_tokens": 300,
            "messages": [{"role": "user", "content": "read_file 도구로 /etc/hostname 을 읽어줘."}]}
    dt, x, err = post("/v1/chat/completions", body, sid=f"stream-{c}", stream=True)
    if err:
        return f"FAIL {err}"
    chunks, tool, text, first = 0, False, "", None
    for line in x:
        line = line.decode("utf-8", "replace").strip()
        if not line.startswith("data:") or line == "data: [DONE]":
            continue
        first = first or time.time()
        try:
            delta = json.loads(line[5:])["choices"][0].get("delta") or {}
        except Exception:
            continue
        chunks += 1
        tool = tool or bool(delta.get("tool_calls"))
        text += delta.get("content") or ""
    ok = chunks > 1 and (tool or text.strip())
    return f"{'PASS' if ok else 'FAIL'} chunks={chunks} tool_call={tool} text={text.strip()[:40]!r}"


def responses(c):
    dt, d, err = post("/v1/responses", {"model": c, "input": "한 단어로만 답해: 대한민국의 수도는?", "max_output_tokens": 200})
    if err:
        return f"FAIL {err}"
    out = d.get("output_text") or " ".join(p.get("text", "") for o in d.get("output", []) for p in (o.get("content") or []) if isinstance(p, dict))
    return f"{'PASS' if out.strip() else 'FAIL'} {dt:.1f}s model={d.get('model')} {out.strip()[:40]!r}"


def cache(c):
    prefix = "\n".join(f"규칙 {i}: 사용자의 요청을 정확하고 친절하게 처리한다." for i in range(700))
    res = []
    for q in ("대한민국의 수도는? 한 단어로.", "일본의 수도는? 한 단어로."):
        dt, d, err = post("/v1/chat/completions", {"model": c, "max_tokens": 40, "messages": [
            {"role": "system", "content": prefix}, {"role": "user", "content": q}]}, sid=f"cache-{c}")
        if err:
            return f"FAIL {err}"
        u = d.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or u.get("cache_read_input_tokens")
        res.append(f"{d.get('model')} in={u.get('prompt_tokens')} cached={cached}")
    return " | ".join(res)


for c in combos:
    print(f"{test:9} {c:26} {globals()[test](c)}", flush=True)
