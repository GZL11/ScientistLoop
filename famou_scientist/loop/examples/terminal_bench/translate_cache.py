"""Translate Solver closing texts to concise Chinese via the claude CLI, with a
persistent cache so each text is translated once."""
import hashlib, json, os, subprocess, sys
from pathlib import Path

CACHE = Path(__file__).with_name("agent_text_translations.json")
MODEL = os.environ.get("FAMOU_TRANSLATE_MODEL", "claude-opus-5")
BATCH = 12

def _key(t): return hashlib.sha1(t.encode("utf-8")).hexdigest()
def load(): return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
def save(c): CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")

PROMPT = ("下面是若干段 AI Agent 在完成科研任务某一轮后写的英文总结。请把每一段翻译成简洁的中文摘要，"
          "保留测试名、文件名、数值和专业术语原文，每段不超过 120 个汉字，只说它做了什么、发现了什么、决定了什么。"
          "严格只输出一个 JSON 数组，元素顺序与输入一致，每个元素是一个字符串。输入（JSON 数组）：\n")

def translate_missing(texts):
    cache = load(); todo = [t for t in dict.fromkeys(texts) if t and _key(t) not in cache]
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        try:
            # cwd=/tmp: started inside the repo the CLI scans the multi-GB .famou tree and hangs.
            out = subprocess.run(["claude", "--bare", "--print", "--model", MODEL, "--output-format", "json",
                                  PROMPT + json.dumps(chunk, ensure_ascii=False)],
                                 capture_output=True, text=True, timeout=240, env=env, cwd="/tmp").stdout
            result = json.loads(out).get("result", "")
            s = result[result.find("["): result.rfind("]") + 1]
            zh = json.loads(s)
            if not isinstance(zh, list) or len(zh) != len(chunk): raise ValueError("length mismatch")
        except Exception as exc:  # keep going; untranslated texts stay English
            print(f"translate batch {i//BATCH} failed: {exc}", file=sys.stderr, flush=True); continue
        print(f"translate batch {i//BATCH} ok ({len(chunk)})", file=sys.stderr, flush=True)
        for t, z in zip(chunk, zh): cache[_key(t)] = str(z).strip()
        save(cache)
    return cache

def zh(text, cache=None):
    cache = cache if cache is not None else load()
    return cache.get(_key(text), text)
