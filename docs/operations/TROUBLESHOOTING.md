# famou-scientist 排错与经验记录

> 本文汇总**使用 / 开发过程中**遇到的问题、根因与解决办法,按场景分类,供后来者快速定位。
> 配套阅读:`README.md`(快速上手)、`docs/overview/ARCHITECTURE.md`(架构)。

---

## 一、SSH 连接(连 iCode)

### 1.1 `no matching host key type found. Their offer: ssh-rsa`
- **现象**:push/连 icode 报主机密钥算法不匹配。
- **原因**:OpenSSH 8.8+ 默认禁用 ssh-rsa(SHA-1),而 icode Gerrit 只提供 ssh-rsa **主机密钥**。
- **解决**:`~/.ssh/config` 给该 host 重新启用:
  ```
  Host <内部代码仓库>
      HostKeyAlgorithms +ssh-rsa
      PubkeyAcceptedAlgorithms +ssh-rsa
  ```

### 1.2 `Host key verification failed`
- **现象**:非交互环境连 icode 报主机密钥未验证。
- **原因**:icode 的 host key 不在 `known_hosts`。
- **解决**:`ssh-keyscan -p 8235 <内部代码仓库> >> ~/.ssh/known_hosts`

---

## 二、插件 / 代码开发

### 2.1 `guardrails.ts` 疑似语法错误(实为编码损坏)
- **现象**:怀疑有语法错。
- **结论**:`node --check` 通过,**无语法错**;但护栏③文案里有 2 个损坏字符 `核��`(U+FFFD,应为"核验"),在模板字符串里不影响编译、但运行时会输出乱码。
- **解决**:还原为"核验";全文 U+FFFD 归零。
- **排查工具**:`iconv -f utf-8 -t utf-8 file`(查 UTF-8 合法性)、`grep $'\xEF\xBF\xBD' file`(找 U+FFFD)、`node --check file.ts`(Node 24 擦类型后做权威语法检查)。

### 2.2 ⭐⭐ heartbeat 插件"死活不加载"(排查最久)
- **现象**:新写的 `plugins/heartbeat.ts` 不执行(无 init 日志),serve 还偶发 `ServeError Unexpected error`;连最小化版本、换文件名、换全新配置目录都不加载——但更早的 spike 插件明明加载过。
- **根因**:**全局 opencode 状态被污染**。前面为调试**反复重启 serve 并中途 kill**(很多次在 bootstrap 中途被打断),把 `~/.local/share/opencode/opencode.db` / `storage` 搞进了坏状态,导致**所有**插件都不再加载。
- **解决**:把全局 db/storage 移走再起 serve,插件立刻正常加载("tick fired"):
  ```bash
  mv ~/.local/share/opencode/opencode.db* /tmp/bak/   # 连同 storage/
  ```
  验证 OK 后再把**用户真实 db** 移回(保数据)。
- **经验**:**opencode 插件异常不加载时,先怀疑全局 state,清掉即恢复**。正常使用不会触发,是高频崩溃重启导致的。

### 2.3 `pkill -f "opencode serve"` 把自己杀了(exit 144)
- **现象**:命令里带 `pkill -f "opencode serve"` 时,整条命令异常退出(exit 144),后续操作没执行。
- **原因**:`pkill -f` 按**完整命令行**匹配,而这条 bash 命令行本身就含字符串 "opencode serve",于是 pkill **把运行自己的 shell 也杀了**。
- **解决**:别在同一条命令里 pkill 同名进程;改成**先单独**按精确名/PID kill(`pkill -f "opencode.exe serve"` 或 `kill <pid>`),再在**另一条**命令里做后续操作。

### 2.4 心跳:空闲判定被尾随事件清零
- **现象**:实验完成了,心跳却不注入通知。
- **根因**:用布尔 `idle` 判空闲——`session.idle` 之后还会有 `session.updated`/`message.updated` 等**尾随事件**,把 `idle` 又置回 false,等定时器跑时已不是 true。
- **解决**:改用**时间戳** `lastIdleAt` / `lastRunAt`,仅当"空闲晚于在跑且稳定 GRACE 秒"才注入——尾随事件不动这两个时间戳。

### 2.5 心跳:wake 消息被 agent 当"可疑注入"
- **现象**:后台定时器注入"请回复 PONG"式命令,agent 警惕地拒答(虽证明了能叫醒)。
- **解决**:wake 消息写成**中性的系统状态通知**("[系统通知·实验心跳] 实验 X 已完成,请查 …"),agent 会自然去 `arc_experiment_status`,不触发防注入警惕。

### 2.6 同步阻塞:`arc_run_experiment` 用 `spawnSync`
- **现象**:长实验会把 master agent 卡死(默认 300s 还会超时挂)。
- **解决**:加 `is_async` 后台模式(detached 进程 + 信号文件)+ `arc_experiment_status` 查状态 + heartbeat 自动叫醒。详见 ARCHITECTURE 3.1/3.2′。

### 2.7 ⭐⭐ 长会话"逐轮回空白"——自定义 provider 缺 `limit.context` 致 auto-compact 从不触发(排查最值得记)
- **现象**:某条长研究轨迹(电池 SOC)做到中段,agent **每一轮都回空**(web 上只剩"研究助手"空气泡,心跳通知、用户追问都没有任何回复)。
- **排查路径**(可复用):读 opencode 的 `~/.local/share/opencode/opencode.db`(sqlite)该会话最近消息——
  发现 `arc_run_experiment` 那轮 input≈20.1 万 token 还能正常出文本(output=844),工具结果回灌后
  **input 卡在 23.4 万不动、output 恒为 0、`finishReason` 由 `unknown` 变 `length`**。`length`+全 0 token =
  **请求 prompt 已超模型上下文上限,网关在生成前就拒了,一个字吐不出**。
- **根因**:`anthropic-gateway/glm-5.1` 这种**自定义 provider 的模型在 models.dev 目录里匹配不到**,
  配置又没写 `limit.context`。opencode 的自动 compact 按「当前 token ≥ `limit.context` × ~0.9」触发,
  **缺 `limit` 则上限视为 0 → 阈值永到不了 → 压缩从不启动**(日志全程零 compact 记录),上下文一路裸奔到撞墙。
  叠加:models.dev 拉取**超时失败 146 次**(直连外网需代理),连名称兜底也没了。
- **解决**:给自定义 provider 的每个模型在 `~/.config/opencode/opencode.jsonc` 显式写 `limit`:
  ```jsonc
  "glm-5.1": { "name": "GLM-5.1", "limit": { "context": 200000, "output": 64000 } }
  ```
  `context` 取模型真实窗口保守值(glm/claude 这套网关实测 ~20 万 → 写 200000,阈值≈18 万就自动压缩)。
- **经验**:① **自定义/内部网关的模型必须手写 `limit.context`**,这是 auto-compact 能否工作的前提
  (官方 provider 走 models.dev 不用写)。② `compact` 不是"窗口变短",是把早期历史**总结压缩**腾出空间;
  `output` 是单次回复上限、与触发压缩无关(它越大,留给输入的空间越小、压缩来得越早)。
  ③ 已撑爆的会话救不回(再发也超限),**新开会话**续,产物都在盘上。

### 2.8 文献检索工具单次输出过大,加速上下文撑爆
- **现象**:与 2.7 同一轨迹,`arc_search_literature` **单次返回 ~49K 字符**(15 篇 × 全量摘要 + 5 作者 + `indent=2`),
  多次检索累积 ~25 万字符常驻上下文,是把上下文吹大的**主因**之一。
- **根因**:工具返回会原样进入对话上下文,并在之后**每一轮**随历史重发;摘要全文 + 缩进 JSON 体积巨大且无必要。
- **解决**(工具输出截断,`tool/arc.ts`):`search_literature` 交回模型前瘦身——摘要截 **280 字**、作者 **4 个+et al.**、
  去 `indent`(compact JSON);单次 ~49K→~9K(降 ~80%),承重文献要全文再用 `arc_fetch_source` 按需取。
  实验侧同理:`experiment_status` 完成分支的 stdout/stderr 改 **head+tail 截断**(全量留 `runner.log`)。
- **经验**:工具输出是上下文增长的隐形大头。**默认只回"够判断/够选择"的最小信息,大块全文按需另取**;
  分子方向多次窄查询比一次超宽查询更省上下文。与 2.7 的 `limit`/compact 是互补两道防线(一个少灌、一个兜底)。

### 2.9 GLM 经网关偶发 `</think>` 泄漏到正文——实为 2.7 撑爆的副作用,非协议 bug
- **现象**:同一条撑爆轨迹里,assistant 正文出现**孤立的 `</think>`** 及半截英文思考(露好几处);
  一度怀疑是 GLM 推理标签没被剥离的协议适配问题。
- **排查**:① 从 sqlite 抠出 4 条泄漏原文,全部落在 2.7 的撑爆区间(output≈0、`finishReason`=length);
  ② 直接 `curl` 该网关(famou 同款 Anthropic 协议)实测**流式正常返回独立 `thinking`/`thinking_delta` 通道**
  (86 个 thinking_delta + 12 个 text_delta),**没有把 `<think>` 内联进 text**;
  ③ 本地 opencode 1.17.11 二进制重度处理 `reasoning_content`(547 处)+ Anthropic `reasoningContent` 结构化块。
- **结论(根因)**:网关协议本身正确、正常态不漏。`</think>` 泄漏是**上下文撑爆下输出畸形**的症状——
  thinking 块流式中途断裂、未正常闭合,残片(含 think 模板的 `</think>` 字面量)漏进 text。
  **根治 = 解决 2.7(配 limit + 工具截断)**,不撑爆就不畸形,泄漏自然消失。**无需改网关或换 provider 接法**。
- **各家模型 reasoning 在 opencode 的适配现状(调研沉淀)**:
  | 类别 | reasoning 怎么传 | opencode 表现 |
  |---|---|---|
  | Anthropic 原生(claude-*) | `thinking` 结构化块 | ✅ 原生折叠,最稳 |
  | 经 Anthropic 网关的 GLM(本项目这套) | 实测走 `thinking_delta` 块 | ✅ 正常态不漏;仅撑爆畸形时漏 |
  | OpenAI 式(gpt-5/o 系、deepseek-r1) | `reasoning_content` 字段 | ✅ opencode 重度支持 |
  | 纯内联 `<think>`(自部署 vLLM/Ollama 的 GLM/DeepSeek/Qwen) | text 里裸 `<think>…</think>` | ⚠️ **社区高发坑**:1.17.11 已移除 `extractReasoningMiddleware`,流式开头易丢 `<think>` 开标签致漏(opencode #7779/#15380)。**本项目走网关、不属此类** |
- **经验**:出现疑似"协议/格式" bug 时,先 `curl` 探真实响应形态再下结论;别把撑爆的**衍生症状**当成独立根因去改无关的接法。

### 2.10 长会话"越聊越说英文"——语言漂移,compact 是最大放大器
- **现象**:同一条长轨迹做到中段,assistant **从中文逐渐漂成全英文**回复(解释/分析整段英文),
  且常与 2.9 的思考泄漏同时出现。
- **根因**(两条,叠加):
  ① **AGENTS.md 此前没有任何"用中文回复"的显式指令**——中文全靠"文件是中文 + 用户说中文"
     隐式带出来,没有硬指令兜底;上下文里堆的英文(文献摘要/代码/工具返回/英文 reasoning)越来越多,
     把输出分布往英文带,**指令存在感被稀释**就漂。
  ② **compact 是最大放大器**:opencode 自动压缩生成的**总结往往是英文**,等于把"语言锚点"
     直接换成英文,compact 之后几乎必漂(原始中文指令的权重又被进一步冲淡)。
- **解决**(两处互补,常态 + 节点强化):
  - **基线**:`AGENTS.md` 身份准则后补「交流语言」硬指令——默认全程中文,代码/命令/路径/
    API 名/专有名词保留英文,发现自己漂英文立刻切回。每轮随 system 重发。
  - **compact 节点强化**:新增 `plugins/language.ts`,挂 `experimental.session.compacting` 钩子
    (compact 前触发、可定制压缩 prompt),往压缩 prompt 追加 context 指令,要求生成总结的模型
    **① 用中文写总结**(压缩后的锚点就是中文)**② 在总结末尾原样保留一条常驻"后续用中文回复"指令**
    (把语言要求嵌进被压缩后的上下文,持续约束往后每一轮)。即"每次 compact 后重新强调中文",
    且治本——掐断"英文总结 → 漂移"这条链。逃生阀 `ARC_LANG_OFF=1`、改语言 `ARC_REPLY_LANG`、
    调试 `ARC_LANG_DEBUG=<file>`(compact 时写 `injected lang=中文 sid=...` 可验证钩子真触发)。
- **经验**:① **靠"文件是中文"隐式维持语言不可靠**,要有一条显式硬指令。
  ② compact 这类"重写上下文"的节点是语言/风格漂移的高发点——能定制其 prompt 就让它**用目标语言产出**,
  比事后纠偏更稳(opencode 的 `experimental.session.compacting` 钩子专为此设:`context` 追加、`prompt` 整体替换)。
  ③ 与 2.9 同源:不撑爆 + 锚定中文,泄漏与漂移一并少。

### 2.11 web 上出现一条不是我发的"你"气泡(`Continue if you have next steps…`)
- **现象**:web 对话流里冒出一条顶着**"你"**头像的消息,内容是英文
  `Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.`,
  用户并没发过它;且**每次出现都意味着刚发生过一次 compact**。
- **根因**:这是 **opencode 内置行为**——compact 成功后,它自动注入一条
  `synthetic:true` + `metadata.compaction_continue:true` 的 **user-role** 合成消息,把 agent"续上"继续干活
  (对应 plugin 钩子 `experimental.compaction.autocontinue`)。官方 TUI / share 客户端认得 `synthetic` 标记会自己滤掉;
  我们这套**自研零构建 React 前端**没处理这个标记 → 当成普通"你"的气泡渲染了出来。
- **解决**(`assets/web/src/app.tsx`,纯前端识别,不改后端):
  - 新增 `isCompactionContinue(m)`:**双保险**识别——① 结构化标记(`info` 或任意 `part` 上的
    `synthetic` / `metadata.compaction_continue`);② 文本兜底 `includes("Continue if you have next steps")`
    (防标记没被 GET /message 序列化、或文本前缀有变)。
  - 渲染层 `if (isCompactionContinue(m)) return null` **直接不渲染**(它纯是内部续推信号、对用户零信息量,
    不像心跳那样还值得显示成淡灰行);历史回放(↑/↓)也排除它。
- **经验**:自研前端要主动处理 opencode 的 `synthetic` 内部消息(compact 续推、未来可能还有别的),
  别无脑把所有 user-role 消息当用户输入显示。识别用"结构化标记优先 + 文本兜底"最稳。

### 2.12 ⭐⭐ web 消息发出去很久没回复、**刷新后才出现**——compact 期间 SSE 假死
- **现象**:web 上发完消息,界面一直转圈/无回复,**手动刷新页面**回复才蹦出来(说明回复**早生成完了**,
  只是没推到浏览器)。高发于长会话(触发了 compact)。
- **根因**(opencode 的设计盲区,非我们的 bug):
  ① compact 是一次**长 LLM 调用**(把整段历史总结),期间**不发**任何 `message.part.delta` /
     `message.part.updated` / `session.next.step.started`,前端的 `activityRef` 停止增长;
  ② 此时经代理的 SSE 连接易**假死**(TCP 看似活着但无数据;标签页后台/代理 idle/网络抖动触发),
     而浏览器 `EventSource` 的自动重连"sloppy",`onopen`/`onerror` 可能几十秒都不触发 →
     **客户端根本不知道自己断了** → 收不到 `session.idle`(清 busy 的唯一可靠收口)→ busy 卡死。
  - **为什么 opencode 原生兜底没救回来**:opencode 的 `/event` SSE **故意不做 `Last-Event-ID` 断线续传/事件持久化**
    (官方设计:write-then-publish + **幂等全量事件** + 单连接内有序),它的官方解法是
    "**断线后用 REST 重新拉一次全量状态**"(即我们的 `reconcile()` = `GET /message`)。但它把
    "**何时该去拉**"完全甩给客户端,而 EventSource 假死时客户端**判断不出该拉** → 兜底永不触发。
    这正是社区已立的 bug(sst/opencode #25657:"long-running tasks silently lose UI updates when the SSE
    stream drops — proxy idle, tab backgrounded, network blip; server keeps working, client never catches up"),
    社区结论:"automatic SSE reconnection is sloppy and **a heartbeat is a must-have**"。
- **解决**(`assets/web/src/app.tsx`,补"该什么时候拉"的触发时机,拉法仍用官方推荐的 REST 全量补齐):
  - **看门狗主动 reconcile**:无活动累计 ~12s 起、每 ~12s 主动 `reconcile(sid)` 一次(= 自动"刷新")。
    正常生成持续有 delta → `ticks` 不断被重置、**永不触发**,对正常流零开销。
  - **`visibilitychange` / `focus` 补齐**:标签页切回前台/窗口重聚焦且会话 busy → 立即 reconcile。
  - **关键一行修 `isGenerating`**:compact 续推合成消息 role 是 `user`(见 2.11),若 reconcile 恰在
    "合成消息已落库、assistant 回复未开始"的过渡窗口拉到消息,末尾是 user → 按 `role!=="assistant"` 会**误清 busy**;
    故把"末尾是合成续推消息"也视为仍在生成。
  - **`onerror` 不动**:它在每次重连尝试时高频触发且连接未恢复,此时 reconcile 无意义;"断后补齐"已由
    `onReopen`(重连成功)覆盖,真正的"假死盲区"由上面看门狗 + 可见性兜住。
- **经验**:① **opencode 官方就是"工程缝补"派**——`/event` 不做 replay,靠"幂等全量事件 + 断线后 REST 重拉"。
  我们用的 `reconcile`(REST 全量补齐)**正是它推荐的机制**,不是绕路。② 它只差在"**没人告诉客户端该拉了**";
  EventSource 自动重连在假死场景不可靠,**主动心跳(定时 reconcile + 可见性补齐)是必需品**,这点社区已成共识。
  ③ 与 2.11 同源(都由 compact 触发);改动只在自研前端,不碰 opencode 后端。

---

## 三、身份(角色设定)

### 3.1 自我介绍"暧昧、像在躲问题"
- **现象**:被追问身份时,agent 说"我不会告诉你底层用什么技术或模型——这是我的边界"。
- **问题**:解释"我不说什么"本身就在暗示"有东西在藏",显得暧昧被动——恰恰最该避免。
- **解决**:改 `AGENTS.md` 身份准则为**笃定 + 自然**:被问/被怼都只平和重申"我是 Famou-scientist,你的科研搭子",自然把话题带回研究;**绝口不提 opencode/ARC/模型**(提了就是破绽),底线是"自然地从不提及",而非"郑重声明拒绝提及"。

---

## 四、使用中发现的研究流程缺口 → 新增的 skill/机制

> 这一节不是"bug",而是**用户在实际用 famou-scientist 做研究的过程中,发现 opencode 作为科研
> agent 的能力缺口**。每个缺口都催生了对应的 skill 或机制——记录"问题从哪来、为什么加它"。

### 4.1 实验结论会悄悄跑偏、和最初假设对不上 → `research-reflection`
- **使用中发现**:agent 越做越细,但写论文前**没人回头检验"最后的结论到底支不支持最初那个假设"**;
  失败要 PIVOT/REFINE 时也缺少结构化的归因,容易绕圈、丢初心。
- **新增**:`research-reflection` skill——回到 `hypotheses.md` 做 SUPPORTS/PARTIAL/CONTRADICTS 三态
  对齐判定,不支持就归因定位,并把「假设回顾/结果/现象/对齐/归因/下一步」六块按轮次落盘 `reflection.md`。
- **形态**:soft skill(跑后复盘)。

### 4.2 想法失败后反射式甩"创新性不足的后续" → `novelty-gate`
- **使用中发现**:一个想法效果不好,opencode 很容易**随手提一个换超参/换数据集的增量方向**,看似在推进,
  实则用一串小修小补**消耗用户耐心**。
- **新增**:`novelty-gate` skill——提新假设/后续方向前自检(机制级差异/不与文献或历史重复/达最小贡献单元);
  没真新意就深挖或**如实说"这条路创新见底了"**,不硬凑。
- **形态**:soft skill(假设阶段 + PIVOT/REFINE 时)。

### 4.3 长实验把 agent 卡死 + 跑完不主动查 → 异步执行 + 心跳
- **使用中发现**:(a) 代码搭好后**跑实验会把 master agent 长时间阻塞**,用户没法继续对话;
  (b) opencode **后台起了实验也不会主动去看完成没**,往往要用户问起才发现早跑完了。
- **新增**:`arc_run_experiment(is_async=true)` detached 后台执行 + `arc_experiment_status` 查状态
  + **心跳通知 plugin**(完成自动叫醒空闲 agent)+ `async-experiment-execution` skill(分流阈值/
  心跳纪律/防冷启动)。
- **形态**:tool + plugin(自动)+ soft skill。

### 4.4 代码和规划有 gap、opencode 注意不到 → `code-plan-review`
- **使用中发现**:写出来的实验代码**和最初规划有出入**,opencode 自己发现不了,往往**实验跑完再看代码
  才注意到**(且这是 AI Scientist 类系统的通病:静默子采样/换更易数据集且不声明)。
- **新增**:`code-plan-review` skill——**跑实验前**起独立 reviewer 子 agent 逐项核对代码⇄规划
  (数据/条件/baseline/协议/超参),要求代码打印真实配置 + assertion 自证,fail-closed 改对再跑。
- **形态**:soft skill + 独立 subagent(跑前审查)。

> 这四项合起来,把 famou 的审查闭环补全成对称结构:**假设阶段** `novelty-gate` → **跑实验前**
> `code-plan-review` → **跑实验后** `research-reflection` → **写论文后** `peer-review`(已有),
> 全程叠加确定性 hook(质量门/引用门/数字门)做硬底线。

---

## 五、关键机制认知(踩坑后沉淀)

| 主题 | 结论 |
|------|------|
| **OpenCode 配置是合并不是替换** | `OPENCODE_CONFIG_DIR`(出能力)与全局 `~/.config/opencode/opencode.jsonc`(出 provider/key)**合并**生效,故 famou "不碰任何 key"。 |
| **插件目录** | `<config>/plugins/`(复数)会被自动扫描加载(guardrails/heartbeat 都在此);skill 经 `opencode.json` 的 `skills.paths` 注册。 |
| **skill 加载 = 渐进式披露** | L1 启动时只把每个 skill 的 name+description(~100 token)进 system prompt;L2 正文在 agent 调原生 skill 工具时**按需**加载;L3 引用的脚本/资源用到才加载。 |
| **何时 load skill** | 由 LLM 在**每个生成步**像普通工具调用一样**语义判断**(非定时、非关键词正则);一轮内可 0/1/多次。所以 frontmatter 的 `description`/`trigger-keywords` 极重要,AGENTS.md 流程指令是兜底。 |
| **soft skill vs hard hook** | 需判断的(设计/写作/创新性/复盘)→ skill(软,可能漏);确定性校验(引用真伪/实验数字/质量门)→ hook(硬,自动触发跳不过)。 |
| **自定义 provider 必须写 `limit.context`** | auto-compact 按「token ≥ `limit.context`×~0.9」触发;自定义/内部网关模型在 models.dev 查不到,缺 `limit` → 上限视为 0 → 永不压缩 → 长会话撑爆吐空(见 2.7)。官方 provider 走 models.dev 可免。 |
| **工具输出是上下文增长隐形大头** | 工具返回原样进上下文且每轮重发;默认只回"够判断"的最小信息,大块全文按需另取(见 2.8)。截断 + auto-compact 是互补两道防线。 |
| **compact 会重写"语言/风格锚点"** | 自动压缩的总结默认可能用英文,会把语言锚点换掉致漂移。`experimental.session.compacting` 钩子可定制压缩 prompt(`context` 追加 / `prompt` 替换),让总结**用目标语言产出**并在其中嵌常驻语言指令——比事后纠偏稳(见 2.10)。 |
| **opencode 的 `/event` SSE 不做断线续传** | 官方**故意**不实现 `Last-Event-ID`/事件持久化,设计是 write-then-publish + **幂等全量事件** + 单连接内有序;断线的官方解法=**REST 重拉全量状态**(即 `reconcile`/`GET /message`)。盲区:它把"何时该拉"甩给客户端,而 EventSource 假死时客户端判断不出 → 需自研**主动心跳**(定时 reconcile + 可见性补齐)兜底(见 2.12;社区 bug sst/opencode #25657)。 |
| **心跳叫醒可行性** | 已实测:插件里后台 `setInterval` 调 `client.session.prompt` 能叫醒空闲 agent(触发新一轮响应)。 |
| **调试技巧** | headless 用 `opencode serve --port X --log-level DEBUG`;插件可设 `ARC_HEARTBEAT_DEBUG=<file>` 开调试日志、`ARC_HEARTBEAT_MS` 调心跳周期。 |

---

## 附:常用排错命令速查

```bash
# headless 起服务调试（看插件/LLM 行为）
opencode serve --port 5599 --log-level DEBUG

# 测 SSH 认证成谁
ssh -i ~/.ssh/<key> -o IdentitiesOnly=yes -o BatchMode=yes \
    -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
    -p 8235 <user>@<内部代码仓库>    # 看 banner "Hi, xxx"

# 插件不加载时：清全局 state（先备份）
mv ~/.local/share/opencode/opencode.db* /tmp/ocbak/

# TS 语法体检
node --check path/to/file.ts

# 查某会话是否上下文撑爆（看 input token / finishReason / output）——定位"逐轮回空白"
python3 - <<'PY'
import sqlite3, json
con = sqlite3.connect("file:%s/.local/share/opencode/opencode.db?mode=ro&immutable=1" % __import__("os").path.expanduser("~"), uri=True)
S = "ses_xxx"   # 换成目标会话 id
for mid, data in con.execute("SELECT id,data FROM message WHERE session_id=? ORDER BY time_created DESC LIMIT 6", (S,)):
    d = json.loads(data); t = d.get("tokens") or {}
    print(d.get("role"), "finish=", d.get("finishReason"), "in=", t.get("input"), "out=", t.get("output"))
PY

# 探网关真实 reasoning 形态（确认 thinking 块 vs 内联 <think>）
curl -sS -N "$ANTHROPIC_BASE_URL/v1/messages" -H "authorization: Bearer $ANTHROPIC_AUTH_TOKEN" \
  -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"glm-5.1","max_tokens":256,"stream":true,"messages":[{"role":"user","content":"hi"}]}' \
  | grep -oE '"type":"[a-z_]+"' | sort | uniq -c

# 跑资产测试
/opt/miniconda/envs/famou/bin/python -m pytest famou_scientist/tests/test_plugin_assets.py -q

# 探 /event SSE 是否在推事件 / 是否假死（定位"发完很久无回复、刷新才出现"，见 2.12）
# 一个终端挂着收事件，另一个终端给会话发 prompt，看这边有没有 message.part.delta 流进来；
# 长时间只剩心跳无 delta = 假死/漏推，前端需 reconcile(REST 全量) 兜底。
curl -sN http://127.0.0.1:4097/event | grep -oE '"type":"[a-z._]+"'
```
