"""
topo_engine.py — 记忆拓扑引擎
参考 Stello 设计：session可分叉、继承digest、跨session推送insight
"""

import json
import random
import string
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


def _gen_id(prefix="sess"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{prefix}_{ts}_{rand}"


@dataclass
class TopoSession:
    id: str
    parent_id: Optional[str] = None
    children_ids: list = field(default_factory=list)
    title: str = "新对话"
    messages: list = field(default_factory=list)
    digest: Optional[str] = None
    insights: list = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "active"  # active / completed

    def add_message(self, role: str, content: str):
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Topology:
    """管理一个space下所有session的拓扑关系"""

    def __init__(self, space_id: str, storage_dir: Path):
        self.space_id = space_id
        self._dir = storage_dir / space_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, TopoSession] = {}
        self._load()

    def _topo_file(self) -> Path:
        return self._dir / "topology.json"

    def _save(self):
        data = {
            "space_id": self.space_id,
            "sessions": {sid: s.to_dict() for sid, s in self.sessions.items()}
        }
        self._topo_file().write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self):
        f = self._topo_file()
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            for sid, sdata in data.get("sessions", {}).items():
                self.sessions[sid] = TopoSession.from_dict(sdata)

    def create_session(self, parent_id: Optional[str] = None, title: str = "新对话") -> TopoSession:
        """创建新session，可指定父节点"""
        sid = _gen_id()
        session = TopoSession(id=sid, parent_id=parent_id, title=title)

        # 如果有父节点，继承digest作为初始context
        if parent_id and parent_id in self.sessions:
            parent = self.sessions[parent_id]
            parent.children_ids.append(sid)
            if parent.digest:
                session.insights.append({
                    "source": parent_id,
                    "type": "inherited_digest",
                    "content": parent.digest,
                    "timestamp": datetime.now().isoformat()
                })

        self.sessions[sid] = session
        self._save()
        return session

    def fork(self, session_id: str, title: Optional[str] = None) -> TopoSession:
        """从指定session分叉出子session"""
        if session_id not in self.sessions:
            raise ValueError(f"Session not found: {session_id}")

        parent = self.sessions[session_id]
        fork_title = title or f"分支: {parent.title}"

        # 先确保父session有digest
        if not parent.digest and parent.messages:
            # 简单截取最后几条消息作为临时digest
            recent = parent.messages[-5:]
            parent.digest = f"[自动摘要] {parent.title}: " + "; ".join(
                m["content"][:50] for m in recent if m["role"] == "user"
            )

        child = self.create_session(parent_id=session_id, title=fork_title)
        self._save()
        return child

    def get_session(self, session_id: str) -> Optional[TopoSession]:
        return self.sessions.get(session_id)

    def update_digest(self, session_id: str, digest: str):
        """更新session的digest（由外部LLM生成后调用）"""
        if session_id in self.sessions:
            self.sessions[session_id].digest = digest
            self._save()

    def put_insight(self, target_id: str, source_id: str, content: str):
        """向目标session推送洞察"""
        if target_id not in self.sessions:
            raise ValueError(f"Target session not found: {target_id}")

        self.sessions[target_id].insights.append({
            "source": source_id,
            "type": "insight",
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self._save()

    def add_message(self, session_id: str, role: str, content: str):
        """向session添加消息"""
        if session_id not in self.sessions:
            raise ValueError(f"Session not found: {session_id}")
        self.sessions[session_id].add_message(role, content)
        # 自动更新title（第一条用户消息）
        s = self.sessions[session_id]
        if s.title == "新对话" and role == "user":
            s.title = content[:30]
        self._save()

    def get_tree(self) -> dict:
        """返回完整拓扑树结构（前端渲染用）"""
        # 找到所有根节点（无parent的session）
        roots = [s for s in self.sessions.values() if s.parent_id is None]

        def build_node(session: TopoSession) -> dict:
            children = [
                build_node(self.sessions[cid])
                for cid in session.children_ids
                if cid in self.sessions
            ]
            return {
                "id": session.id,
                "title": session.title,
                "status": session.status,
                "digest_preview": (session.digest[:60] + "...") if session.digest else None,
                "message_count": len(session.messages),
                "children": children,
                "created_at": session.created_at,
            }

        return {
            "space_id": self.space_id,
            "roots": [build_node(r) for r in roots],
            "total_sessions": len(self.sessions),
        }

    def list_digests(self) -> list:
        """返回所有session的摘要列表"""
        return [
            {
                "id": s.id,
                "title": s.title,
                "digest": s.digest,
                "parent_id": s.parent_id,
                "message_count": len(s.messages),
            }
            for s in self.sessions.values()
        ]

    def get_context_for_session(self, session_id: str) -> str:
        """获取session的完整上下文（含继承的digest和insights）"""
        session = self.sessions.get(session_id)
        if not session:
            return ""

        parts = []

        # 继承的上下文
        if session.insights:
            parts.append("=== 继承的上下文 ===")
            for ins in session.insights:
                if ins["type"] == "inherited_digest":
                    parts.append(f"[父节点摘要] {ins['content']}")
                else:
                    parts.append(f"[洞察 from {ins['source']}] {ins['content']}")

        # 当前session的digest
        if session.digest:
            parts.append(f"\n=== 当前摘要 ===\n{session.digest}")

        return "\n".join(parts)


# ===== Space管理 =====

class TopoManager:
    """管理所有space的拓扑"""

    def __init__(self, storage_dir: Path):
        self._dir = storage_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._topologies: dict[str, Topology] = {}

    def get_or_create_space(self, space_id: str) -> Topology:
        if space_id not in self._topologies:
            self._topologies[space_id] = Topology(space_id, self._dir)
        return self._topologies[space_id]

    def list_spaces(self) -> list:
        spaces = []
        if self._dir.exists():
            for d in self._dir.iterdir():
                if d.is_dir() and (d / "topology.json").exists():
                    topo = self.get_or_create_space(d.name)
                    tree = topo.get_tree()
                    spaces.append({
                        "space_id": d.name,
                        "total_sessions": tree["total_sessions"],
                    })
        return spaces

    def create_space(self, name: str) -> Topology:
        space_id = _gen_id("space")
        topo = Topology(space_id, self._dir)
        # Save metadata
        meta = {"name": name, "created_at": datetime.now().isoformat()}
        (self._dir / space_id / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )
        self._topologies[space_id] = topo
        return topo
