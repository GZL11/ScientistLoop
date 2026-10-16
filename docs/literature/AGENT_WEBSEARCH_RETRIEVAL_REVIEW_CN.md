# Agent 检索路由复盘

> 原因：对于论文名字不全的检索无法成功索引到正确的论文
> 记录一次“论文检索不走 websearch”的问题、根因、修复过程和后续约束，便于后续回看和继续收紧。

## 1. 现象

用户明确在找某篇论文时，agent 没有优先用 OpenCode 原生 `websearch/webfetch`，而是先走了自定义学术检索工具，随后还把弱相关候选当成可用结果展示出来。

典型表现：
- 具体论文名带版本号或缩写时，返回一堆只碰巧命中数字的候选；
- agent 没先问确认，也没先用网页搜索核验；
- `arc_search_literature` 被当成了具体论文查找工具；
- 有些会话里 agent 甚至继续把不相关论文整理成“候选集合”。

## 2. 根因

主要不是单个工具坏了，而是路由边界混乱。

1. `AGENTS.md` 早期写了过强的文献调研入口，主 prompt 会压过 skill 自己的策略。
2. `literature-search` 的描述太宽，既像“查论文”，又像“做综述”。
3. `arc_lookup_paper` / `arc_search_literature` 的职责边界不够清楚。
4. agent 缺少质量门，明显不相关的候选也会被继续展示。
5. `arc_search_literature` 对短 query、版本号、具体论文名的过滤不够强。

## 3. 我们最后定的原则

- 具体论文查找，优先原生 `websearch`，再用 `webfetch` 核验。
- `arc_search_literature` 只负责 topic-level 文献调研、related work、综述式检索。
- `literature-search` 只负责论文检索、候选召回、筛选、来源核验。
- `literature-research` 负责领域理解、子方向聚类、缺口定位、研究方向推荐、idea 排序。
- `AGENTS.md` 只写任务边界，不绑定具体 tool/skill 策略。

## 4. 已做的修复

- 关闭过 `lookup_paper` 子工具，避免具体论文查找继续误走 academic lookup。
- 收窄过 `literature-search` 的职责描述。
- 新增独立 `literature-research` skill。
- 给检索结果加过 soft guardrail，避免明显不相关候选继续扩散。
- 后续又把 `literature-search` 和 `literature-research` 的边界进一步拆开。

## 4.1 原生 websearch 可见性问题

这次复盘里还要单独记一条：**当时运行时没有把 OpenCode 原生 `websearch` 真正暴露给 agent**。

更准确地说，不是“代码里没有 websearch”，也不是“agent 主观不愿意用 websearch”，而是 OpenCode 在工具注册层会按 provider/runtime flag 过滤工具：

- OpenCode 原生 `websearch` 在源码里存在，注册名是 `websearch`，工具列表里对外通常显示为 `search`；
- `webfetch` 是另一个原生工具，注册名是 `webfetch`，工具列表里对外通常显示为 `fetch`；
- 但 `websearch` 只有在 `providerID === opencode`，或者运行时打开 `enableExa` / `enableParallel` 时才会进入 agent 的可用工具列表；
- 如果当前 session 选的是普通 `openai` 类 provider，且没有打开 Exa/Parallel websearch flag，那么 `websearch` 会被 registry 过滤掉；
- prompt、skill、tool 描述里写“web-first”只能影响 agent 的选择顺序，不能让一个没有被注册进工具列表的能力凭空出现。

对应源码逻辑在 OpenCode 的 `tool/registry.ts`：

```ts
export function webSearchEnabled(providerID, flags) {
  return providerID === "opencode" || flags.exa || flags.parallel
}
```

所以当时的真实链路是：

1. 当前 provider/model 组合下，`websearch` 没有进入 agent 可见工具列表。
2. agent 能稳定看到的是项目自定义工具，例如 `arc_lookup_paper` / `arc_search_literature` / `arc_fetch_source`。
3. 具体论文查找虽然应该走网页搜索，但 agent 实际没有原生 `websearch` 可调用。
4. 它只能退到 academic retrieval 路径，导致 InterAgent-1.5 这类“网页搜索第一个结果能命中、学术 API 不一定命中”的 case 失败。

这里还容易混淆另一个工具：项目里的自定义 `web_search`。它不是 OpenCode 原生 `websearch`，而是我们在 `arc.ts` 里封装的百度 AI Search 工具；它只有设置 `AI_SEARCH_KEY` 时才会导出。未设置 `AI_SEARCH_KEY` 时，registry 根本看不到这个 export，agent 也不会知道有这个工具。

这条应该单独记录，因为它和“候选过滤不严”不是一回事：
- 前者是**入口/暴露面**问题；
- 后者是**结果质量门**问题。

### 我们怎么解决的

1. 检查当前 session 的工具调用轨迹：如果只看到 `arc_search_literature`、`arc_lookup_paper`、`arc_fetch_source`，却看不到 `websearch` / `search`，说明原生网页搜索没有暴露给 agent。
2. 检查 OpenCode 启动时的 provider/runtime flag：普通 `openai` provider 默认不会启用原生 `websearch`；需要使用 `opencode` provider，或打开 Exa/Parallel websearch flag。
3. 如果要使用 OpenCode 原生网页搜索，启动服务时保证满足其中一个条件：
   - provider 是 `opencode`；
   - 或运行时开启 `enableExa`；
   - 或运行时开启 `enableParallel`。
4. 如果要使用项目自定义百度搜索工具 `arc_web_search` / `web_search`，则需要设置 `AI_SEARCH_KEY`，并同步运行时；否则这个工具不会出现在 agent 可见工具列表中。
5. 重启 `famou-scientist` / OpenCode 服务后，新开 session 验证。具体论文查找的理想轨迹应是：先出现 `websearch` / `search`，拿到候选 URL 后再用 `webfetch` / `fetch` 核验正文，而不是一上来就只走 `arc_search_literature`。

### 4.2 Exa 和 Parallel 分别是什么

这两个都是 OpenCode 原生 `websearch` 的后端实现，不是我们自定义的学术工具。

- `Exa Web Search`：对应 Exa 提供的搜索服务。它的特点是能做实时网页搜索，并且在检索后抓取网页内容，适合“找网页证据、查最新资料、拿页面正文”这类任务。OpenCode 里当 `enableExa` 打开时，`websearch` 会走这条路径。
- `Parallel Web Search`：对应 `search.parallel.ai` 的 MCP 服务。OpenCode 里当 `enableParallel` 打开时，`websearch` 会走这条路径。它同样是网页搜索后端，只是实现服务不同。

两者在 agent 视角下的作用是一样的：

1. 先通过 `websearch` 找候选网页。
2. 再通过 `webfetch` 抓取目标 URL 的正文。
3. 把网页证据作为后续判断依据。

区别主要在后端供应商和请求路径，不在 agent 的使用方式。

## 5. 经验结论

这类问题本质是“路由优先级”和“语义边界”问题，不是单纯换一个更强的检索工具就能解决。

后续应坚持：
- 不在 `AGENTS.md` 里写死 tool/skill 调用顺序；
- skill 名称和描述要尽量互斥；
- 检索类任务要区分“找一篇论文”和“做一个领域调研”；
- 明显不相关的候选不要继续展示给用户。

## 6. 备注

这份记录只总结“检索路由为什么会跑偏”，不包含后续前端 question 提交问题。
