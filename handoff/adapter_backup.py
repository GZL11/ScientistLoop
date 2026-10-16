#!/usr/bin/env python3
"""
Flask adapter: 将 autoresearch-demo 前端的 API 协议翻译为 opencode API。

前端（static_adapted/index.html）调用本服务的 /api/* 路由，
本服务将请求翻译为 opencode API（通过 server.mjs 代理）。

核心翻译：
- Session CRUD: /api/sessions/* → /oc/session/*
- SSE 流: /api/agent/sessions/:sid/send（per-request SSE）
       → POST /oc/session/:sid/prompt_async + SSE /oc/event
- 文件: /api/agent/sessions/:sid/file → /oc/file/content 或 /raw
"""

import json
import os
import queue
import threading
import time
from pathlib import Path

from flask import Flask, request, Response, send_from_directory, jsonify, stream_with_context
from flask_cors import CORS
import requests as http_requests

app = Flask(__name__)
CORS(app)

# opencode 代理地址（server.mjs）
OC_PROXY = os.environ.get('OC_PROXY', 'http://127.0.0.1:4096')
# 静态文件目录
STATIC_DIR = Path(__file__).parent / 'static_adapted'

# ===================================================================
# 静态文件
# ===================================================================

@app.route('/')
def index():
    return send_from_directory(str(STATIC_DIR), 'index.html')


@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory(str(STATIC_DIR), path)


# ===================================================================
# Session CRUD 翻译
# ===================================================================

def _oc(path, **kw):
    """向 opencode（经 server.mjs 代理）发请求"""
    url = f'{OC_PROXY}/oc{path}'
    return http_requests.request(url=url, timeout=30, **kw)


def _format_session(s):
    """opencode session → demo 前端期望的格式"""
    return {
        'session_id': s.get('id', ''),
        'title': s.get('title', '新对话'),
        'created_at': s.get('createdAt', s.get('created_at', '')),
        'message_count': s.get('messageCount', 0),
        'preview': '',
    }


@app.route('/api/sessions', methods=['POST'])
def create_session():
    """创建会话"""
    title = '新对话'
    if request.json:
        title = request.json.get('title', '新对话')
    try:
        resp = _oc('/session', method='POST',
                    json={'title': title},
                    headers={'Content-Type': 'application/json'})
        if resp.ok:
            data = resp.json()
            return jsonify(_format_session(data))
        return jsonify({'error': resp.text}), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 503


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """列出会话"""
    try:
        resp = _oc('/session?roots=true&limit=30', method='GET')
        if not resp.ok:
            return jsonify([])
        sessions = resp.json()
        result = []
        for s in sessions:
            title = s.get('title', '')
            # 过滤 opencode 自动建的空壳
            if title.startswith('New session'):
                continue
            result.append(_format_session(s))
        result.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return jsonify(result)
    except Exception as e:
        return jsonify([])


@app.route('/api/sessions/<sid>', methods=['GET'])
def get_session(sid):
    """获取会话消息 — 翻译 opencode 消息格式为 demo 格式"""
    try:
        resp = _oc(f'/session/{sid}/message', method='GET')
        if not resp.ok:
            return jsonify({'error': 'not found'}), 404
        oc_messages = resp.json()
        # 翻译消息格式
        messages = []
        for m in oc_messages:
            info = m.get('info', {})
            role = info.get('role', 'assistant')
            parts = m.get('parts', [])
            # 拼接 text parts 为 content
            text_parts = [p.get('text', '') for p in parts if p.get('type') == 'text']
            content = ''.join(text_parts)
            messages.append({'role': role, 'content': content})
        # 获取 session meta
        meta_resp = _oc(f'/session/{sid}', method='GET')
        meta = {}
        if meta_resp.ok:
            s = meta_resp.json()
            meta = _format_session(s) if isinstance(s, dict) else {'session_id': sid}
        else:
            meta = {'session_id': sid, 'title': ''}
        meta['message_count'] = len(messages)
        return jsonify({'meta': meta, 'messages': messages})
    except Exception as e:
        return jsonify({'error': str(e)}), 503


@app.route('/api/sessions/<sid>', methods=['DELETE'])
def delete_session(sid):
    try:
        _oc(f'/session/{sid}', method='DELETE')
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 503


@app.route('/api/sessions/<sid>/title', methods=['PUT'])
def update_title(sid):
    title = request.json.get('title', '') if request.json else ''
    try:
        _oc(f'/session/{sid}', method='PATCH',
            json={'title': title},
            headers={'Content-Type': 'application/json'})
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 503


# ===================================================================
# Agent 路由（SSE 协议翻译核心）
# ===================================================================

@app.route('/api/agent/sessions', methods=['POST'])
def agent_create_session():
    """创建 agent session — 直接创建 opencode session"""
    title = '新对话'
    if request.json:
        title = request.json.get('title', '研究任务')
    try:
        resp = _oc('/session', method='POST',
                    json={'title': title},
                    headers={'Content-Type': 'application/json'})
        if resp.ok:
            data = resp.json()
            return jsonify({'session_id': data.get('id', ''), 'status': 'created'})
        return jsonify({'error': resp.text}), resp.status_code
    except Exception as e:
        return jsonify({'error': f'连接失败: {e}'}), 503


@app.route('/api/agent/sessions', methods=['GET'])
def agent_list_sessions():
    """列出 agent sessions"""
    return list_sessions()


@app.route('/api/agent/status', methods=['GET'])
def agent_status():
    """检查后端是否在线"""
    try:
        resp = _oc('/config', method='GET')
        if resp.ok:
            cfg = resp.json()
            return jsonify({'status': 'online', 'options': cfg})
        return jsonify({'status': 'online', 'options': {}})
    except Exception as e:
        return jsonify({'status': 'offline', 'error': str(e)})


@app.route('/api/agent/sessions/<sid>/send', methods=['POST'])
def agent_send_message(sid):
    """
    SSE 协议翻译核心:
    1. POST /oc/session/:sid/prompt_async（发送 prompt，fire-and-forget）
    2. 打开 SSE /oc/event 监听事件
    3. 翻译事件格式并写入 response stream
    """
    data = request.json or {}
    message = data.get('message', '')
    print(f'[adapter] === agent_send_message sid={sid[:12]} msg={message[:30]}', flush=True)

    def sse_translate():
        print(f'[adapter] sse_translate 开始执行', flush=True)
        # 维护增量状态
        text_state = {}      # {part_id: last_text}
        tool_state = {}      # {part_id: last_status}
        reasoning_state = {} # {part_id: last_text}
        done = False
        event_queue = queue.Queue()
        connected = threading.Event()

        def listen_events():
            """在后台线程监听 opencode SSE 事件（手动解析 iter_content，避免 iter_lines 拆断长行）"""
            try:
                print(f'[adapter] SSE 连接 {OC_PROXY}/oc/event ...', flush=True)
                resp = http_requests.get(
                    f'{OC_PROXY}/oc/event',
                    stream=True,
                    timeout=(5, 300),
                    headers={'Accept': 'text/event-stream'}
                )
                print(f'[adapter] SSE 连接成功 status={resp.status_code}', flush=True)
                if not resp.ok:
                    print(f'[adapter] SSE 连接失败: {resp.status_code} {resp.text[:200]}', flush=True)
                    event_queue.put({'_error': f'SSE {resp.status_code}'})
                    return
                connected.set()

                buf = ''
                data_lines = []
                for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
                    if done:
                        break
                    if not chunk:
                        continue
                    buf += chunk
                    while '\n' in buf:
                        line, buf = buf.split('\n', 1)
                        line = line.rstrip('\r').strip()
                        if line.startswith('data:'):
                            data_lines.append(line[5:].lstrip())
                        elif line == '' and data_lines:
                            raw = ''.join(data_lines)
                            data_lines = []
                            try:
                                ev = json.loads(raw)
                                event_queue.put(ev)
                            except json.JSONDecodeError:
                                print(f'[adapter] JSON 解析失败: {raw[:200]}', flush=True)
                        elif line == '':
                            data_lines = []
            except Exception as e:
                print(f'[adapter] SSE 错误: {e}', flush=True)
                event_queue.put({'_error': str(e)})
            finally:
                connected.set()
                print('[adapter] SSE 监听结束', flush=True)
                event_queue.put(None)  # sentinel

        # 启动事件监听线程
        listener = threading.Thread(target=listen_events, daemon=True)
        listener.start()

        # 等 SSE 连接就绪再发 prompt（避免事件丢失）
        connected.wait(timeout=5)
        if not connected.is_set():
            print('[adapter] SSE 连接超时', flush=True)
            yield f"data: {json.dumps({'type': 'error', 'content': 'SSE 连接超时'})}\n\n"
            return

        # 发送 prompt（fire-and-forget）
        try:
            body = {'parts': [{'type': 'text', 'text': message}]}
            # 尝试获取模型配置
            try:
                cfg_resp = _oc('/config', method='GET')
                if cfg_resp.ok:
                    cfg = cfg_resp.json()
                    model_str = cfg.get('model', '')
                    if model_str and '/' in model_str:
                        idx = model_str.index('/')
                        body['model'] = {
                            'providerID': model_str[:idx],
                            'modelID': model_str[idx+1:]
                        }
            except:
                pass

            print(f'[adapter] 发送 prompt 到 /session/{sid}/prompt_async ...', flush=True)
            prompt_resp = _oc(
                f'/session/{sid}/prompt_async',
                method='POST',
                json=body,
                headers={'Content-Type': 'application/json'}
            )
            print(f'[adapter] prompt 响应: {prompt_resp.status_code}', flush=True)
            if not prompt_resp.ok and prompt_resp.status_code != 204:
                err_text = prompt_resp.text[:200]
                print(f'[adapter] prompt 失败: {err_text}', flush=True)
                yield f"data: {json.dumps({'type': 'error', 'content': f'prompt 失败: {prompt_resp.status_code} {err_text}'})}\n\n"
                return
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'发送失败: {e}'})}\n\n"
            return

        # 消费事件队列，翻译协议
        idle_timeout = 300  # 最长等待 5 分钟
        start_time = time.time()

        while not done:
            try:
                ev = event_queue.get(timeout=2)
            except queue.Empty:
                if time.time() - start_time > idle_timeout:
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                # 发 keepalive
                yield ": keepalive\n\n"
                continue

            if ev is None:
                # 监听线程结束
                print(f'[adapter] 监听线程结束，done={done}', flush=True)
                if not done:
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break

            if '_error' in ev:
                print(f'[adapter] 事件错误: {ev["_error"]}', flush=True)
                yield f"data: {json.dumps({'type': 'error', 'content': ev['_error']})}\n\n"
                break

            ev_type = ev.get('type', '')
            props = ev.get('properties', {})
            ev_sid = props.get('sessionID', '')

            # 只处理当前 session 的事件
            if ev_sid and ev_sid != sid:
                continue

            print(f'[adapter] 事件: type={ev_type} sid={ev_sid[:8] if ev_sid else "?"} (等待sid={sid[:8]})', flush=True)

            # 只处理当前 session 的事件
            if ev_sid != sid:
                continue

            if ev_type == 'message.updated':
                # 记录消息角色，忽略用户消息的后续 parts
                info = props.get('info', {})
                msg_id = info.get('id', '')
                role = info.get('role', '')
                if role == 'user':
                    # 标记这个 message 是用户的，后续 part 跳过
                    text_state[f'_role_{msg_id}'] = 'user'

            elif ev_type == 'message.part.updated':
                part = props.get('part', {})
                if not part:
                    continue

                part_id = part.get('id', '')
                msg_id = part.get('messageID', '')
                part_type = part.get('type', '')
                state = part.get('state', {}) or {}
                status = state.get('status', '')

                # 跳过用户消息的 parts
                if text_state.get(f'_role_{msg_id}') == 'user':
                    continue

                if part_type == 'text':
                    current_text = part.get('text', '')
                    prev_text = text_state.get(part_id, '')
                    if len(current_text) > len(prev_text):
                        delta = current_text[len(prev_text):]
                        text_state[part_id] = current_text
                        yield f"data: {json.dumps({'type': 'text', 'content': delta}, ensure_ascii=False)}\n\n"

                elif part_type == 'reasoning':
                    current_text = part.get('text', '')
                    prev_text = reasoning_state.get(part_id, '')
                    if len(current_text) > len(prev_text):
                        delta = current_text[len(prev_text):]
                        reasoning_state[part_id] = current_text
                        # 路由到 info（会被前端的 thinking stream 处理）
                        yield f"data: {json.dumps({'type': 'info', 'content': delta}, ensure_ascii=False)}\n\n"

                elif part_type == 'tool':
                    tool_name = part.get('tool', 'unknown')
                    tool_input = state.get('input', {})
                    tool_output = state.get('output', state.get('error', ''))
                    prev_status = tool_state.get(part_id, '')

                    if status in ('pending', 'running') and prev_status not in ('pending', 'running'):
                        # 新 tool call 开始
                        tool_state[part_id] = status
                        tool_input_str = json.dumps(tool_input, ensure_ascii=False) if isinstance(tool_input, dict) else str(tool_input or '')
                        yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_name, 'tool_input': tool_input_str}, ensure_ascii=False)}\n\n"

                    elif status == 'completed' and prev_status != 'completed':
                        tool_state[part_id] = status
                        content = ''
                        if tool_output is not None:
                            content = tool_output if isinstance(tool_output, str) else json.dumps(tool_output, ensure_ascii=False)
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name, 'content': content}, ensure_ascii=False)}\n\n"

                    elif status == 'error' and prev_status != 'error':
                        tool_state[part_id] = status
                        error_msg = state.get('error', 'unknown error')
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name, 'content': f'[错误] {error_msg}'}, ensure_ascii=False)}\n\n"

                    else:
                        tool_state[part_id] = status

            elif ev_type == 'session.error':
                error_msg = props.get('error', str(props))
                yield f"data: {json.dumps({'type': 'error', 'content': error_msg}, ensure_ascii=False)}\n\n"

            elif ev_type == 'session.idle':
                done = True
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

            elif ev_type == 'session.next.step.started':
                pass

        done = True

    return Response(
        stream_with_context(sse_translate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@app.route('/api/agent/sessions/<sid>/messages', methods=['GET'])
def agent_get_messages(sid):
    """获取 agent session 消息历史"""
    try:
        resp = _oc(f'/session/{sid}/message', method='GET')
        if resp.ok:
            return jsonify(resp.json()), 200
        return jsonify([]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 503


@app.route('/api/agent/sessions/<sid>/files', methods=['GET'])
def agent_list_files(sid):
    """列出 workspace 文件"""
    path = request.args.get('path', '')
    try:
        resp = _oc(f'/file?path={path}', method='GET')
        if resp.ok:
            return jsonify(resp.json()), 200
        return jsonify([]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 503


@app.route('/api/agent/sessions/<sid>/file', methods=['GET'])
def agent_get_file(sid):
    """获取文件内容 — 代理到 /oc/file/content 或 /raw"""
    file_path = request.args.get('path', '')
    if not file_path:
        return 'missing path', 400

    # 判断是否二进制（图/PDF 等）— 走 /raw 路由（server.mjs 直接读盘）
    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
    binary_exts = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'pdf',
                   'docx', 'doc', 'pptx', 'xlsx', 'svg'}

    if ext in binary_exts:
        # 代理到 /raw 路由（server.mjs 直接从磁盘读取二进制文件）
        try:
            resp = http_requests.get(
                f'{OC_PROXY}/raw?path={file_path}',
                stream=True, timeout=30
            )
            return Response(
                resp.iter_content(chunk_size=8192),
                status=resp.status_code,
                headers=dict(resp.headers)
            )
        except Exception as e:
            return f'file error: {e}', 500
    else:
        # 文本文件 — 用 /oc/file/content
        try:
            resp = _oc(f'/file/content?path={file_path}', method='GET')
            if resp.ok:
                # 文本响应
                return Response(resp.text, mimetype='text/plain; charset=utf-8')
            return 'not found', 404
        except Exception as e:
            return f'file error: {e}', 500


@app.route('/api/agent/sessions/<sid>/trace', methods=['GET'])
def agent_get_trace(sid):
    """获取 trace（opencode 没有单独 trace，返回消息）"""
    return agent_get_messages(sid)


# ===================================================================
# 兼容路由（demo 前端可能调用）
# ===================================================================

@app.route('/api/sessions/<sid>/send', methods=['POST'])
def session_send(sid):
    """
    demo 前端的 callSessionLLM 走这个路由。
    我们直接转发到 agent_send_message（统一走 opencode agent）。
    """
    return agent_send_message(sid)


@app.route('/api/chat', methods=['POST'])
def chat_compat():
    """兼容旧 /api/chat — 不应该被调用，返回空"""
    def gen():
        yield f"data: {json.dumps({'type': 'text', 'content': '请使用新对话功能。'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    return Response(gen(), mimetype='text/event-stream')


# ===================================================================
# 启动
# ===================================================================

PORT = int(os.environ.get('ADAPTER_PORT', 5050))
HOST = os.environ.get('ADAPTER_HOST', '127.0.0.1')

if __name__ == '__main__':
    print(f'[adapter] v2 启动 http://localhost:{PORT}  (OC_PROXY={OC_PROXY})', flush=True)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
