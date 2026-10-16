### 补充：`arc_web_search`（联网搜索，已启用）

| 工具 | 何时用 |
|------|--------|
| `arc_web_search(query, count, freshness)` | 通用网页搜索（百度 AI 搜索，非学术论文）。**跟 `arc_search_literature` 分工不重叠**：学术论文用那个（真调 arXiv/S2/OpenAlex，有摘要/DOI，能进 references.bib）；本工具查论文库里没有的、会变的信息——工具/框架最新版本与 API 变更、会议官网/CFP/截止日期、复现报错排障、公司技术博客/发布 |
