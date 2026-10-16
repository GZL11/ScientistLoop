#!/usr/bin/env python3
"""
AutoResearch Demo 后端
Flask + 百度千帆(OpenAI兼容接口) + SSE流式输出 + 磁盘持久化Session
"""
import json
import os
import random
import string
from datetime import datetime
from pathlib import Path

from flask import Flask, request, Response, send_from_directory, stream_with_context, jsonify
from flask_cors import CORS
from openai import OpenAI
import requests as http_requests  # rename to avoid conflict with flask.request
from topo_engine import TopoManager

app = Flask(__name__, static_folder=None)  # disable built-in static, use manual route
CORS(app)

# ===== 模型配置（OpenAI 兼容接口）=====
# 凭据只从环境变量读，不写进代码。启动前：
#   export LLM_API_KEY=<你的 key>   [export LLM_APP_ID=<你的 appid>]
client = OpenAI(
    api_key=os.environ.get('LLM_API_KEY', ''),
    base_url=os.environ.get('LLM_BASE_URL', 'https://qianfan.baidubce.com/v2'),
    default_headers={'appid': os.environ.get('LLM_APP_ID', '')},
)

MODEL = "qwen3-vl-235b-a22b-thinking"

# ===== WebAgent 后端配置 =====
WEBAGENT_URL = os.environ.get('WEBAGENT_URL', 'http://localhost:8765')

# ===== 持久化路径 =====
DATA_DIR = Path(__file__).parent / "sessions"
DATA_DIR.mkdir(exist_ok=True)
TOPO_DIR = Path(__file__).parent / "topologies"
topo_manager = TopoManager(TOPO_DIR)

# ===== 系统提示词 =====
SYSTEM_PROMPT = """你是「百度伐谋 · AutoResearch」科研智能体。

## 意图判断

收到用户消息后，先判断意图类型：

1. **chat** — 普通问答、闲聊、简短问题。直接回答，不输出JSON。
2. **deep_research** — 需要文献检索、精读分析、综述、调研类任务。关键词：调研、综述、文献、进展、对比分析、现状。
3. **auto_research** — 需要代码复现、模型实现、训练验证、进化搜索类任务。关键词：复现、实现、训练、代码、模型、进化。

## 回复规则

### 如果意图是 chat：
直接用中文回答，专业简洁。不输出任何JSON块。

### 如果意图是 deep_research 或 auto_research：
1. 先用1-2句话确认你理解了用户的需求
2. 然后在回复末尾输出一个JSON计划块（必须用```json包裹），格式严格如下：

```json
{
  "intent": "deep_research",
  "title": "计划标题（简短）",
  "steps": [
    {"title": "步骤1标题", "description": "具体描述"},
    {"title": "步骤2标题", "description": "具体描述"},
    {"title": "步骤3标题", "description": "具体描述"}
  ]
}
```

intent字段只能是 "deep_research" 或 "auto_research"。steps 通常3-5步。

### deep_research 的典型步骤：
1. 文献检索 — 搜索相关论文
2. 精读分析 — 深入阅读核心论文，提取方法和结论
3. 综合报告 — 生成研究报告

### auto_research 的典型步骤：
1. 文献理解 — 阅读目标论文，理解方法
2. 代码复现 — 实现数据处理和模型代码
3. 训练验证 — 训练模型并对比baseline指标
4. 进化搜索 — 使用伐谋进化引擎搜索更优方案

## 风格
- 中文回复，专业简洁
- 不要在JSON之外重复解释步骤内容"""

# ===== 内存缓存（磁盘为主，内存加速） =====
_cache = {}  # session_id -> {"messages": [...]}


def _session_dir(sid):
    return DATA_DIR / sid


def _meta_path(sid):
    return _session_dir(sid) / "meta.json"


def _messages_path(sid):
    return _session_dir(sid) / "messages.json"


def _save_meta(sid, meta):
    d = _session_dir(sid)
    d.mkdir(exist_ok=True)
    _meta_path(sid).write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def _load_meta(sid):
    p = _meta_path(sid)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save_messages(sid, messages):
    _messages_path(sid).write_text(json.dumps(messages, ensure_ascii=False, indent=2))


def _load_messages(sid):
    p = _messages_path(sid)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def _get_messages(sid):
    """内存优先，磁盘兜底"""
    if sid in _cache:
        return _cache[sid]["messages"]
    msgs = _load_messages(sid)
    _cache[sid] = {"messages": msgs}
    return msgs


def _gen_id():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"chat_{ts}_{rand}"


# ===== 路由 =====

_STATIC = Path(__file__).parent / 'static'

@app.route('/')
def index():
    return send_from_directory(str(_STATIC), 'index.html')


@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory(str(_STATIC), path)


# ---- Session CRUD ----

@app.route('/api/sessions', methods=['POST'])
def create_session():
    """创建新会话，立即落盘"""
    sid = _gen_id()
    title = request.json.get('title', '新对话') if request.json else '新对话'
    meta = {
        "session_id": sid,
        "title": title,
        "created_at": datetime.now().isoformat(),
        "message_count": 0,
    }
    _save_meta(sid, meta)
    _save_messages(sid, [])
    _cache[sid] = {"messages": []}
    return jsonify(meta)


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """列出所有会话（按时间倒序）"""
    sessions = []
    if not DATA_DIR.exists():
        return jsonify([])
    for d in sorted(DATA_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta = _load_meta(d.name)
        if meta:
            # 补充消息数（可能meta里的count过时，从磁盘读）
            msgs = _load_messages(d.name)
            meta["message_count"] = len(msgs)
            # 提取最后一条用户消息作为preview
            user_msgs = [m for m in msgs if m.get("role") == "user"]
            meta["preview"] = user_msgs[-1]["content"][:60] if user_msgs else ""
            sessions.append(meta)
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return jsonify(sessions)


@app.route('/api/sessions/<sid>', methods=['GET'])
def get_session(sid):
    """获取单个会话的完整消息"""
    meta = _load_meta(sid)
    if not meta:
        return jsonify({"error": "not found"}), 404
    messages = _load_messages(sid)
    return jsonify({"meta": meta, "messages": messages})


@app.route('/api/sessions/<sid>', methods=['DELETE'])
def delete_session(sid):
    """删除会话"""
    import shutil
    d = _session_dir(sid)
    if d.exists():
        shutil.rmtree(d)
    _cache.pop(sid, None)
    return jsonify({"status": "ok"})


@app.route('/api/sessions/<sid>/title', methods=['PUT'])
def update_title(sid):
    """更新会话标题"""
    meta = _load_meta(sid)
    if not meta:
        return jsonify({"error": "not found"}), 404
    meta["title"] = request.json.get("title", meta.get("title", ""))
    _save_meta(sid, meta)
    return jsonify({"status": "ok"})


# ---- Chat（流式） ----

@app.route('/api/sessions/<sid>/send', methods=['POST'])
def send_message(sid):
    """向指定session发送消息，SSE流式返回"""
    meta = _load_meta(sid)
    if not meta:
        return jsonify({"error": "not found"}), 404

    data = request.json
    user_msg = data.get('message', '')

    messages = _get_messages(sid)
    messages.append({"role": "user", "content": user_msg})
    _save_messages(sid, messages)  # 用户消息立即落盘

    # 自动更新标题（第一条消息时）
    if meta.get("title") == "新对话" and len([m for m in messages if m["role"] == "user"]) == 1:
        meta["title"] = user_msg[:30]
        _save_meta(sid, meta)

    # 构建LLM消息
    llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    def generate():
        try:
            stream = client.chat.completions.create(
                model=MODEL,
                messages=llm_messages,
                stream=True,
                temperature=0.7,
                top_p=0.8,
            )

            full_response = ""
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning}, ensure_ascii=False)}\n\n"
                if delta.content:
                    full_response += delta.content
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content}, ensure_ascii=False)}\n\n"

            # 保存assistant回复
            messages.append({"role": "assistant", "content": full_response})
            _save_messages(sid, messages)
            meta["message_count"] = len(messages)
            _save_meta(sid, meta)

            # 检测计划JSON
            if '```json' in full_response:
                try:
                    json_start = full_response.index('```json') + 7
                    json_end = full_response.index('```', json_start)
                    plan_json = json.loads(full_response[json_start:json_end].strip())
                    yield f"data: {json.dumps({'type': 'plan', 'content': plan_json}, ensure_ascii=False)}\n\n"
                except (ValueError, json.JSONDecodeError):
                    pass

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ---- 兼容旧接口（Deep Research内部调用用） ----

@app.route('/api/chat', methods=['POST'])
def chat_compat():
    """兼容旧的 /api/chat 接口，用于Deep Research内部步骤调用"""
    data = request.json
    user_msg = data.get('message', '')
    conv_id = data.get('conversation_id', '_internal')

    # 内部调用不持久化，只在内存中
    if conv_id not in _cache:
        _cache[conv_id] = {"messages": []}
    msgs = _cache[conv_id]["messages"]
    msgs.append({"role": "user", "content": user_msg})

    llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs

    def generate():
        try:
            stream = client.chat.completions.create(
                model=MODEL,
                messages=llm_messages,
                stream=True,
                temperature=0.7,
                top_p=0.8,
            )

            full_response = ""
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning}, ensure_ascii=False)}\n\n"
                if delta.content:
                    full_response += delta.content
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content}, ensure_ascii=False)}\n\n"

            msgs.append({"role": "assistant", "content": full_response})
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ---- WebAgent 代理接口（连接OpenCode agent后端，离线时mock） ----

def _is_webagent_online():
    try:
        http_requests.get(f'{WEBAGENT_URL}/api/options', timeout=2)
        return True
    except Exception:
        return False


@app.route('/api/agent/sessions', methods=['POST'])
def agent_create_session():
    """创建agent session（mock模式，或转发到webagent后端）"""
    mock_sid = 'mock_' + _gen_id()
    return jsonify({"session_id": mock_sid, "status": "mock"})


@app.route('/api/agent/sessions', methods=['GET'])
def agent_list_sessions():
    """列出agent sessions"""
    return jsonify([])


@app.route('/api/agent/sessions/<sid>/send', methods=['POST'])
def agent_send_message(sid):
    """发送消息到agent session（mock SSE流式）"""

    user_msg = request.json.get('message', '') if request.json else ''
    topic_short = user_msg[:40].replace('\n', ' ')

    def mock_stream():
        import time
        steps = [
            {"tool": "search_literature", "input": f"搜索: {topic_short}"},
            {"tool": "read_paper", "input": "精读 top-3 论文，提取方法与结论"},
            {"tool": "analyze_data", "input": "对比分析各方法性能指标"},
            {"tool": "write_report", "input": "生成综合研究报告"},
        ]
        # thinking
        yield f"data: {json.dumps({'type': 'text', 'content': ''})}\n\n"
        time.sleep(0.3)

        for i, step in enumerate(steps):
            # tool call
            yield f"data: {json.dumps({'type': 'tool_call', 'tool': step['tool'], 'tool_input': step['input']})}\n\n"
            time.sleep(0.8)
            # tool result
            yield f"data: {json.dumps({'type': 'tool_result', 'content': f'步骤 {i+1} 完成'})}\n\n"
            time.sleep(0.3)

        # Use LLM to generate final text
        llm_messages = [
            {"role": "system", "content": "你是科研智能体。用户提出了一个研究任务，你已经完成了文献检索、精读、分析。请直接输出一份简洁的研究报告（200-400字），包含：1）研究背景 2）主要发现 3）关键方法对比 4）结论。用markdown格式。"},
            {"role": "user", "content": user_msg}
        ]
        try:
            stream = client.chat.completions.create(
                model=MODEL, messages=llm_messages, stream=True, temperature=0.7, top_p=0.8,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'text', 'content': f'（Mock模式）研究报告生成中遇到问题: {e}'}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(
        stream_with_context(mock_stream()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/agent/sessions/<sid>/messages', methods=['GET'])
def agent_get_messages(sid):
    """获取agent session消息历史"""
    try:
        resp = http_requests.get(f'{WEBAGENT_URL}/api/chat/sessions/{sid}/messages', timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route('/api/agent/sessions/<sid>/files', methods=['GET'])
def agent_list_files(sid):
    """列出agent session的workspace文件"""
    try:
        resp = http_requests.get(f'{WEBAGENT_URL}/api/chat/sessions/{sid}/files', timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route('/api/agent/sessions/<sid>/trace', methods=['GET'])
def agent_get_trace(sid):
    """获取agent session的trace"""
    try:
        resp = http_requests.get(f'{WEBAGENT_URL}/api/chat/sessions/{sid}/trace', timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route('/api/agent/status', methods=['GET'])
def agent_status():
    """检查webagent后端是否在线（mock模式始终返回online）"""
    return jsonify({"status": "online", "mode": "mock"})


# ---- 记忆拓扑引擎 API ----

@app.route('/api/topo/spaces', methods=['GET'])
def topo_list_spaces():
    return jsonify(topo_manager.list_spaces())


@app.route('/api/topo/spaces', methods=['POST'])
def topo_create_space():
    name = request.json.get('name', '新知识库')
    topo = topo_manager.create_space(name)
    return jsonify({"space_id": topo.space_id, "name": name})


@app.route('/api/topo/spaces/<space_id>/tree', methods=['GET'])
def topo_get_tree(space_id):
    topo = topo_manager.get_or_create_space(space_id)
    return jsonify(topo.get_tree())


@app.route('/api/topo/spaces/<space_id>/sessions', methods=['POST'])
def topo_create_session(space_id):
    topo = topo_manager.get_or_create_space(space_id)
    parent_id = request.json.get('parent_id') if request.json else None
    title = request.json.get('title', '新对话') if request.json else '新对话'
    session = topo.create_session(parent_id=parent_id, title=title)
    return jsonify(session.to_dict())


@app.route('/api/topo/spaces/<space_id>/sessions/<session_id>', methods=['GET'])
def topo_get_session(space_id, session_id):
    topo = topo_manager.get_or_create_space(space_id)
    session = topo.get_session(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        **session.to_dict(),
        "context": topo.get_context_for_session(session_id),
    })


@app.route('/api/topo/spaces/<space_id>/sessions/<session_id>/send', methods=['POST'])
def topo_send_message(space_id, session_id):
    """向拓扑session发送消息（SSE流式）"""
    topo = topo_manager.get_or_create_space(space_id)
    session = topo.get_session(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404

    user_msg = request.json.get('message', '')
    topo.add_message(session_id, "user", user_msg)

    # 构建LLM消息：system + 继承context + 对话历史
    context = topo.get_context_for_session(session_id)
    system_msg = SYSTEM_PROMPT
    if context:
        system_msg += f"\n\n=== 项目上下文（继承自父节点）===\n{context}"

    llm_messages = [{"role": "system", "content": system_msg}]
    for m in session.messages:
        llm_messages.append({"role": m["role"], "content": m["content"]})

    def generate():
        try:
            stream = client.chat.completions.create(
                model=MODEL,
                messages=llm_messages,
                stream=True,
                temperature=0.7,
                top_p=0.8,
            )
            full_response = ""
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning}, ensure_ascii=False)}\n\n"
                if delta.content:
                    full_response += delta.content
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content}, ensure_ascii=False)}\n\n"

            topo.add_message(session_id, "assistant", full_response)

            # 自动生成digest（每5条消息更新一次）
            if len(session.messages) % 5 == 0 and len(session.messages) >= 5:
                yield f"data: {json.dumps({'type': 'info', 'content': '正在更新摘要...'}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/topo/spaces/<space_id>/sessions/<session_id>/fork', methods=['POST'])
def topo_fork_session(space_id, session_id):
    topo = topo_manager.get_or_create_space(space_id)
    title = request.json.get('title') if request.json else None
    try:
        child = topo.fork(session_id, title=title)
        return jsonify(child.to_dict())
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route('/api/topo/spaces/<space_id>/sessions/<session_id>/digest', methods=['GET'])
def topo_get_digest(space_id, session_id):
    topo = topo_manager.get_or_create_space(space_id)
    session = topo.get_session(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404
    return jsonify({"session_id": session_id, "digest": session.digest, "title": session.title})


@app.route('/api/topo/spaces/<space_id>/sessions/<session_id>/digest', methods=['POST'])
def topo_generate_digest(space_id, session_id):
    """用LLM生成session摘要"""
    topo = topo_manager.get_or_create_space(space_id)
    session = topo.get_session(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404

    # 用LLM生成摘要
    msgs_text = "\n".join(f"{m['role']}: {m['content']}" for m in session.messages[-20:])
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": f"请用3-5句话总结以下对话的核心内容、关键决策和结论：\n\n{msgs_text}"
            }],
            temperature=0.3,
        )
        digest = resp.choices[0].message.content
        topo.update_digest(session_id, digest)
        return jsonify({"session_id": session_id, "digest": digest})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/topo/spaces/<space_id>/insight', methods=['POST'])
def topo_put_insight(space_id):
    """向目标session推送洞察"""
    topo = topo_manager.get_or_create_space(space_id)
    data = request.json
    target_id = data.get('target_id')
    source_id = data.get('source_id', 'manual')
    content = data.get('content', '')
    try:
        topo.put_insight(target_id, source_id, content)
        return jsonify({"status": "ok"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route('/api/topo/spaces/<space_id>/digests', methods=['GET'])
def topo_list_digests(space_id):
    topo = topo_manager.get_or_create_space(space_id)
    return jsonify(topo.list_digests())


if __name__ == '__main__':
    print("=" * 50)
    print("  AutoResearch Demo")
    print(f"  http://localhost:5050")
    print(f"  Sessions: {DATA_DIR}")
    print(f"  WebAgent: {WEBAGENT_URL}")
    # Check webagent status
    try:
        r = http_requests.get(f'{WEBAGENT_URL}/api/options', timeout=3)
        print(f"  Agent Status: ONLINE")
    except Exception:
        print(f"  Agent Status: OFFLINE (启动webagent: cd webagent && python -m runners.ui.server)")
    print("=" * 50)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5080)), debug=False)
