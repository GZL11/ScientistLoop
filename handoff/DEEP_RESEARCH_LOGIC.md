# Deep Research + Plan Card 逻辑详解

> 从用户点击"深度研究"按钮到 Agent 执行完毕的完整代码流程。

---

## 1. 整体流程图

```
用户点击「深度研究」按钮
  │
  ▼
triggerDeepResearch()  ← toggle deepResearchMode
  │
  ▼
用户输入主题，按回车
  │
  ▼
sendMessage()  ← 检测 deepResearchMode === true
  │
  ├── 1. callSessionLLM() → 千帆 LLM 生成 plan JSON
  │       ↓
  ├── 2. 解析 ```json...``` 块 → JSON.parse
  │       ↓
  ├── 3. renderPlanCard(plan, topic) → 显示 Plan Card（编辑/取消/开始）
  │       ↓
  │   用户点击「开始」
  │       ↓
  ├── 4. confirmPlan() → 构建 prompt
  │       ↓
  └── 5. runAgentTask(prompt) → callAgentLLM() → Agent 流式执行
            ↓
        SSE 事件流：thinking → tool_call → tool_result → text → ... → done
```

---

## 2. 阶段 1：触发深度研究

### triggerDeepResearch()

```javascript
let deepResearchMode = false;

function triggerDeepResearch() {
  deepResearchMode = !deepResearchMode;
  const btn = document.getElementById('deepResearchBtn');
  if (deepResearchMode) {
    btn.classList.add('active');                    // 按钮高亮（--primary-light 底色）
    chatInput.placeholder = '输入研究主题...';       // 切换 placeholder
  } else {
    btn.classList.remove('active');
    chatInput.placeholder = '描述你的科研问题...';
  }
}
```

按钮 HTML（在 `input-toolbar` 中）：
```html
<button class="toolbar-icon" id="deepResearchBtn" 
  onclick="triggerDeepResearch()" title="Deep Research"
  style="font-size:12px;width:auto;padding:0 10px;gap:4px;color:var(--gray-500)">
  <svg ...搜索图标.../> 深度研究
</button>
```

---

## 3. 阶段 2：生成 Plan（sendMessage 中的 deepResearchMode 分支）

当用户输入文字并按回车时，`sendMessage()` 检测到 `deepResearchMode === true`：

```javascript
// sendMessage() 中的 deep research 分支（原版 line 2340-2386）
if (deepResearchMode) {
  deepResearchMode = false;  // 立即关闭 toggle
  btn.classList.remove('active');

  // 1. 显示"正在制定调研计划..."动画
  const div = addMsg('assistant', '');
  const target = document.getElementById(`stream-${msgCount - 1}`);
  target.innerHTML = '<div class="thinking"><span class="thinking-pulse"></span> 正在制定调研计划...</div>';

  // 2. 调用 LLM 生成 plan JSON
  let planText = '';
  await callSessionLLM(currentSessionId, PLAN_PROMPT + text,
    (full) => { planText = full; },   // onText: 累积全文
    (full) => { planText = full; }    // onDone: 最终全文
  );

  // 3. 解析 JSON
  if (planText.includes('```json')) {
    const jsonStart = planText.indexOf('```json') + 7;
    const jsonEnd = planText.indexOf('```', jsonStart);
    const plan = JSON.parse(planText.substring(jsonStart, jsonEnd).trim());
    if (plan.steps) {
      target.innerHTML = renderMd(stripJsonBlock(planText));  // 显示确认文字（去掉 JSON 块）
      renderPlanCard(plan, text);  // 渲染 Plan Card
      return;
    }
  }
  // JSON 解析失败 fallback：直接显示原文
  target.innerHTML = renderMd(stripJsonBlock(planText));
}
```

### Plan 生成 Prompt

```
请为以下主题制定一个深度研究计划。要求：
1. 用一句话确认你理解了需求
2. 然后输出一个JSON计划块（用```json包裹），格式：
```json
{
  "intent": "deep_research",
  "title": "简短标题",
  "steps": [
    {"title": "步骤标题", "description": "具体描述"},
    ...
  ]
}
```
steps 根据主题需要通常3-6步，针对性规划。不要问其他问题，直接给出计划。

主题：${用户输入的文字}
```

### Plan JSON 结构

```json
{
  "intent": "deep_research",        // 固定值，区分研究类型
  "title": "GNSS多路径效应ML预测方法调研",  // Plan Card 显示的标题
  "steps": [
    {
      "title": "文献检索",            // 步骤标题（显示为粗体）
      "description": "检索GNSS多路径效应领域的最新ML方法论文"  // 步骤描述
    },
    {
      "title": "方法对比分析",
      "description": "对比CNN、LSTM、GNN等在多路径预测中的性能"
    }
    // ... 通常 3-6 步
  ]
}
```

---

## 4. 阶段 3：渲染 Plan Card

### renderPlanCard(plan, topic)

```javascript
let pendingPlan = null;     // 全局变量，保存当前待确认的计划
let planCardDiv = null;     // 当前 Plan Card 的 DOM 引用

function renderPlanCard(plan, topic) {
  // 移除旧 Plan Card
  if (planCardDiv && planCardDiv.parentNode) planCardDiv.remove();

  // 保存计划数据（后续 confirmPlan 用）
  pendingPlan = { ...plan, topic };

  // 生成 HTML
  const cardDiv = document.createElement('div');
  cardDiv.className = 'msg msg-agent';
  cardDiv.innerHTML = `
    <div class="plan-card" id="activePlanCard">
      <div class="plan-header">
        <div class="plan-title">${plan.title}</div>
        <div class="plan-header-actions" id="planHeaderActions">
          <button onclick="togglePlanEdit()">编辑</button>
          <button onclick="cancelPlan()">取消</button>
          <button onclick="confirmPlan()">开始</button>
        </div>
      </div>
      <div class="plan-steps" id="planSteps">
        ${plan.steps.map((s, i) => `
          <div class="plan-step" id="plan-step-${i}">
            <div class="plan-step-icon" id="plan-step-icon-${i}">${i + 1}</div>
            <span><strong>${s.title}</strong>  ${s.description}</span>
          </div>
        `).join('')}
      </div>
      <!-- 执行时才显示的 footer：状态 + 进度条 + 停止按钮 -->
      <div class="plan-footer" id="planFooter" style="display:none">
        <div class="plan-status" id="planStatus">
          <span id="planStatusText"></span>
        </div>
        <div class="plan-progress-row">
          <div class="plan-progress-bar">
            <div class="plan-progress-fill" id="planProgressFill"></div>
          </div>
          <button class="plan-stop-btn" id="planStopBtn" onclick="stopDeepResearch()">■</button>
        </div>
      </div>
    </div>
  `;

  container.appendChild(cardDiv);
  planCardDiv = cardDiv;
}
```

### Plan Card 状态流转

```
初始态（等待用户操作）：
  ┌─────────────────────────────┐
  │ 标题                编辑 取消 开始 │
  │ ① 文献检索：...              │
  │ ② 方法对比：...              │
  │ ③ 综合报告：...              │
  └─────────────────────────────┘

点击「开始」后（confirmPlan 触发）：
  ┌─────────────────────────────┐
  │ 标题                    更新  │
  │ ① ⟳ 文献检索：...（spinning）│
  │ ② 方法对比：...              │
  │ ③ 综合报告：...              │
  │ 正在研究...                  │
  │ ███████░░░░░░░░░░░░░ 35%  ■ │
  └─────────────────────────────┘

执行完成后：
  ┌─────────────────────────────┐
  │ 标题                    更新  │
  │ ✓ 文献检索：...（done）      │
  │ ✓ 方法对比：...（done）      │
  │ ✓ 综合报告：...（done）      │
  │ Deep Research 完成           │
  │ ████████████████████ 100%    │
  └─────────────────────────────┘
```

---

## 5. 阶段 4：Plan 编辑（可选）

### togglePlanEdit()

用户点"编辑"后进入编辑模式：

```javascript
let isPlanEditing = false;

function togglePlanEdit() {
  isPlanEditing = true;
  chatInput.value = '';
  chatInput.placeholder = '输入调整意见，如：增加一个对比实验步骤';
  chatInput.focus();
  // 输入提示显示当前计划主题 + 取消按钮
  inputHint.innerHTML = `↩ "${pendingPlan.topic.substring(0, 30)}..." ✕`;
}
```

用户输入调整意见后按回车，`sendMessage()` 检测 `isPlanEditing === true`：

```javascript
if (isPlanEditing && pendingPlan) {
  isPlanEditing = false;
  clearEditContext();

  // 用 LLM 生成新的 plan
  await callSessionLLM(currentSessionId,
    `用户希望调整以下研究计划。请根据调整意见更新计划并输出新的JSON。
原计划主题：${pendingPlan.topic}
原计划步骤：${steps列表}
用户的调整意见：${text}
请输出更新后的JSON计划块（用\`\`\`json包裹），格式同原计划。`,
    onText, onDone
  );

  // 解析新 JSON → 重新渲染 Plan Card
  renderPlanCard(newPlan, pendingPlan.topic);
}
```

### cancelPlan()

```javascript
function cancelPlan() {
  const card = document.getElementById('activePlanCard');
  if (card) card.remove();
  pendingPlan = null;
}
```

### clearEditContext()

```javascript
function clearEditContext() {
  isPlanEditing = false;
  inputHint.textContent = '';
  chatInput.placeholder = '描述你的科研问题...';
}
```

---

## 6. 阶段 5：确认执行

### confirmPlan()

```javascript
async function confirmPlan() {
  if (!pendingPlan) return;
  clearEditContext();

  // UI 切换：隐藏"编辑/取消/开始"，只留"更新"
  headerActions.innerHTML = '<button onclick="togglePlanEdit()">更新</button>';

  // 显示 footer（进度条 + 状态文字）
  planFooter.style.display = '';
  updatePlanCardStatus('正在研究...');
  updatePlanCardProgress(5);

  // 根据 intent 分发
  if (intent === 'deep_research') {
    topbarTitle.innerHTML = `Deep Research · ${topic.substring(0, 30)}...`;
    await runAgentTask(EXECUTION_PROMPT);
  } else if (intent === 'auto_research') {
    topbarTitle.innerHTML = `AutoResearch · ${topic.substring(0, 30)}...`;
    await runAgentTask(topic);
  }
}
```

### 执行 Prompt（发给 Agent 的）

```
请执行以下深度研究任务，按计划逐步完成：

主题：${topic}

计划步骤：
1. 文献检索：检索GNSS多路径效应领域的最新ML方法论文
2. 方法对比分析：对比CNN、LSTM、GNN等在多路径预测中的性能
3. 综合报告：撰写调研总结

请逐步执行，每完成一步输出阶段性结果。不要问交互节奏，直接开始。
```

---

## 7. 阶段 6：Agent 执行（runAgentTask）

### runAgentTask(prompt)

这是核心执行函数。调用 `callAgentLLM` 并通过 callbacks 处理 SSE 事件流：

```javascript
async function runAgentTask(prompt) {
  // 创建 assistant 消息容器
  const div = addMsg('assistant', '');
  const target = document.getElementById(`stream-${msgCount - 1}`);

  // 增量渲染状态
  let currentTextEl = null;        // 当前文字 DOM
  let currentThinkingLabel = null;  // 当前思考标签 DOM
  let currentToolCard = null;       // 当前工具卡片 DOM
  let allOutputText = '';           // 全量输出（用于 plan JSON 检测）
  let phaseText = '';               // 当前阶段文字（tool call 重置）

  startThinking();  // 先显示"深度思考中..."

  await callAgentLLM(prompt, {
    onText,        // 文字增量
    onToolCall,    // 工具调用开始
    onToolResult,  // 工具调用结束
    onInfo,        // 状态信息（路由到思考流）
    onDone,        // 完成
    onError        // 错误
  });
}
```

### Callback 详解

#### onText(fullText, chunk)
```javascript
onText: (full, chunk) => {
  removeStreamingIndicator();
  phaseText += chunk;                              // 累积当前阶段文字

  if (!currentTextEl) {                            // 创建文字块
    currentTextEl = document.createElement('div');
    currentTextEl.className = 'msg-agent-text';
    target.appendChild(currentTextEl);
  }

  // 渲染 Markdown（去掉 JSON 块）+ 流式光标
  currentTextEl.innerHTML = renderMd(stripJsonBlock(phaseText)) + '<span class="streaming-cursor"></span>';
  allOutputText = full;
  showStreamingIndicator();
}
```

#### onToolCall(tc, toolCalls)
```javascript
onToolCall: (tc) => {
  removeStreamingIndicator();

  // 如果之前在思考 → 折叠为思考块
  if (currentThinkingLabel) {
    finishThinking();
  } else if (currentTextEl) {
    // 之前在输出文字 → 定格当前内容
    currentTextEl.innerHTML = renderMd(stripJsonBlock(phaseText));
    currentTextEl = null;
  }

  phaseText = '';      // 重置阶段文字
  allOutputText = '';

  // 合并到同一张工具卡片（不新建）
  if (!currentToolCard) {
    currentToolCard = document.createElement('div');
    currentToolCard.className = 'tool-call-card';
    currentToolCard._tools = [];
    target.appendChild(currentToolCard);
  }
  currentToolCard._tools.push(tc);

  // 检测是否写文件 → 插入文件产物卡片
  maybeInsertFileCard(tc, target);

  // 检测是否文献检索 → 标记待解析
  if (isLiteratureSearch(tc.name)) {
    pendingLiteratureSearch = true;
  }

  // 更新工具卡片 HTML（显示调用计数 + 工具列表）
  updateToolCardHTML(currentToolCard);
}
```

#### onToolResult(resultContent)
```javascript
onToolResult: (resultContent) => {
  activateFileCards(target);        // 文件卡片从"写入中..."变为"点击查看"
  currentToolCard = null;           // 允许下一组工具调用新建卡片

  startThinking();                  // 工具结束后进入思考状态

  // 如果刚才是文献检索 → 解析结果到证据链面板
  if (pendingLiteratureSearch && resultContent) {
    pendingLiteratureSearch = false;
    parseLiteratureResults(resultContent);
  }

  // 进度条 +8%（上限 90%）
  const cur = parseInt(planProgressFill.style.width) || 5;
  planProgressFill.style.width = Math.min(cur + 8, 90) + '%';
}
```

#### onInfo(infoContent)
```javascript
onInfo: (infoContent) => {
  // info 事件路由到思考流（仅在思考状态下追加）
  if (currentTextEl && currentThinkingLabel && infoContent) {
    const clean = infoContent.replace(/\[.*?\]\s*/, '').trim();
    // 过滤系统标记
    if (clean && !clean.startsWith('session_id') && !clean.startsWith('reason=')) {
      currentTextEl.textContent += '\n' + clean;
    }
  }
}
```

#### onDone(fullText)
```javascript
onDone: (full) => {
  removeStreamingIndicator();

  // 折叠最后的思考块
  if (currentThinkingLabel && currentTextEl?.textContent.trim()) {
    finishThinking();
  }

  // 定格最后的文字
  if (currentTextEl?.parentNode) {
    currentTextEl.innerHTML = renderMd(stripJsonBlock(phaseText || full));
  }

  // 更新 Plan Card 状态
  updatePlanCardStatus('Deep Research 完成');
  updatePlanCardProgress(100);  // → 也会隐藏停止按钮
}
```

---

## 8. Plan Card 辅助函数

### updatePlanCardStep(index, status)
```javascript
// status: 'active' | 'done'
function updatePlanCardStep(index, status) {
  const icon = document.getElementById('plan-step-icon-' + index);
  if (status === 'active') {
    icon.className = 'plan-step-icon running';
    icon.innerHTML = '<span class="plan-step-spinner"></span>';  // 旋转动画
  } else if (status === 'done') {
    icon.className = 'plan-step-icon done-icon';
    icon.innerHTML = '✓';  // 白色对勾，深色底
  }
}
```

### updatePlanCardStatus(text) / updatePlanCardProgress(pct)
```javascript
function updatePlanCardStatus(text) {
  document.getElementById('planStatusText').textContent = text;
}

function updatePlanCardProgress(pct) {
  document.getElementById('planProgressFill').style.width = pct + '%';
  if (pct >= 100) {
    document.getElementById('planStopBtn').style.display = 'none';
  }
}
```

### stopDeepResearch()
```javascript
function stopDeepResearch() {
  drStopped = true;
  isStreaming = false;
  updatePlanCardStatus('已暂停');
  document.getElementById('sendBtn').disabled = false;
}
```

---

## 9. 关键变量索引

| 变量 | 类型 | 作用 |
|------|------|------|
| `deepResearchMode` | boolean | "深度研究"按钮 toggle 状态 |
| `pendingPlan` | object \| null | 当前待确认的计划 `{intent, title, steps[], topic}` |
| `planCardDiv` | DOM \| null | 当前 Plan Card 的 DOM 引用 |
| `isPlanEditing` | boolean | 是否处于 plan 编辑模式 |
| `planEditing` | boolean | (历史遗留) 另一个编辑标志 |
| `drStopped` | boolean | 用户是否手动暂停了执行 |
| `pendingLiteratureSearch` | boolean | 上一个 tool call 是否是文献检索（等 result 时解析） |
| `currentSessionId` | string | 当前 session ID（LLM + Agent 共用） |
| `agentSessionId` | string | (仅原版) 独立的 Agent session ID |

---

## 10. 两版差异速查

| 环节 | 原版（autoresearch-demo） | 适配版（famou-scientist） |
|------|--------------------------|--------------------------|
| Plan 生成 | `callSessionLLM` → 千帆 qwen3 直连 | `callSessionLLM` → adapter → opencode agent |
| Plan 生成速度 | 快（LLM 直连，无工具调用） | 慢（走 agent，可能触发工具） |
| Agent 执行 | `callAgentLLM` → WebAgent (独立 agentSessionId) | `callAgentLLM` → adapter → opencode (共用 currentSessionId) |
| Session 出错重置 | `agentSessionId = null` 后重建 | 无此机制 |
| 错误处理 | 无 try-catch | 有完整 try-catch |
