# famou-demo-handoff

百度伐谋（famou-scientist）前端 demo 交付包。

## 目录结构

```
famou-demo-handoff/
├── README.md
├── demo/                         # 可运行的 demo
│   ├── server.py                 # Flask 后端（mock + WebAgent 代理）
│   ├── AGENT_INTEGRATION.md      # WebAgent 对接协议（SSE 事件格式、路由、启动方式）
│   ├── topo_engine.py            # 拓扑引擎（server.py 依赖）
│   ├── topologies/               # 拓扑数据目录
│   └── static/
│       ├── index.html            # 主界面（单文件，CSS+HTML+JS ~3800行）
│       ├── knowledge_base.html   # 资产管理页
│       ├── quiz_rnaseq.html      # Quiz 翻卡学习（HTML 产物示例）
│       ├── wiki_demo.html        # MoonLog 知识编译日志（HTML 产物示例）
│       ├── rockburst_explainer.html  # 岩爆交互解读（HTML 产物示例）
│       ├── research_paradigms.html   # 研究范式（HTML 产物示例）
│       └── bench_files/          # mock 图片和 CSV
│           ├── heatmap_deg.png
│           ├── volcano_plot.png
│           ├── ma_plot.png
│           ├── pca_plot.png
│           ├── sample_correlation.png
│           ├── DEG_results.csv
│           ├── normalized_counts.csv
│           └── significant_DEGs.csv
├── webagent/                     # WebAgent 源码（前端完整展示需要）
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── README.md
│   └── webagent/runners/ui/      # UI Server（FastAPI，端口 8765）
└── prd/                          # 产品需求文档
    ├── famou-scientist前端界面PRD.md     # 前端界面完整 PRD
    ├── 科研智能体PRD-MoonLog.md          # MoonLog + 产物触发规范
    ├── 科研智能体PRD-DeepResearch.md     # Deep Research 流程
    └── 科研智能体PRD-AutoResearch可视化.md  # AutoResearch 可视化
```

## 启动方式

```bash
cd demo
pip install flask flask-cors openai
python server.py
# 访问 http://localhost:5080
```

依赖：Python 3.8+, Flask, flask-cors, openai（qianfan SDK 可选，mock 模式不需要）

## 关键说明

### Mock 模式

server.py 默认以 mock 模式运行，不需要真实的 LLM API：
- `/api/agent/status` → `{"status":"online","mode":"mock"}`
- `/api/agent/sessions` → 返回 mock session
- `/api/agent/sessions/<sid>/send` → SSE 流，模拟 4 步工具调用 + 报告生成

### WebAgent 启动（完整展示需要）

`webagent/` 目录包含 WebAgent 源码，**仅用于 demo 展示时提供 mock Agent 后端**，不是正式的算法后端。正式版本需要算法团队替换为真实的 Agent 服务，对接协议见 `demo/AGENT_INTEGRATION.md`。

```bash
# 终端 1：启动 WebAgent mock 后端（端口 8765）
cd webagent
pip install -r requirements.txt
python -m webagent.runners.ui.server
# 确认 http://localhost:8765/api/options 返回 200

# 终端 2：启动 demo（端口 5080）
cd demo
python server.py
```

server.py 启动时自动检测 WebAgent 在线状态。如果 WebAgent 未运行，demo 使用内置 mock 模式（hardcoded SSE 流）。

### WebAgent 对接协议

详见 `demo/AGENT_INTEGRATION.md`：
- 两条链路架构图（千帆直连 vs Agent 代理）
- SSE 事件格式（text / tool_call / tool_result / info / done）
- 前端 `callAgentLLM()` 的回调处理

### 数据存储

前端数据全部存在浏览器 localStorage：
- `famou_projects` — 知识库项目列表
- `famou_sessions` — 会话历史

首次访问自动 seed 默认 KB 项目（RNA-Seq 差异表达）和 5 篇 mock 文献。

### HTML 产物示例

`static/` 下的独立 HTML 文件是 agent 生成的产物示例，在主界面实验台中以 iframe 嵌入：

| 文件 | 产物类型 | 对应 bench 卡片类型 |
|------|---------|-------------------|
| quiz_rnaseq.html | Quiz 翻卡 | quiz（紫色渐变） |
| wiki_demo.html | MoonLog 知识日志 | wiki（橙色渐变） |
| rockburst_explainer.html | 交互解读 | interactive（橙色渐变） |
| research_paradigms.html | 研究范式 | interactive |

### PRD 阅读顺序

1. **前端界面PRD** — 整体布局、交互、组件定义
2. **MoonLog PRD** — 夜间编译策略 + 附录 A 产物触发规范（所有 Skill 的产物格式定义）
3. **DeepResearch PRD** — Deep Research 完整流程
4. **AutoResearch PRD** — AutoResearch 可视化
