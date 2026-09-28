"""砰砰机器人 AI 能力层。

分层：
    检索链         retrieve.py     顶层入口 retrieve_context() -> (context, status)
                   data.py         群消息 dict ↔ langchain_core Document
                   bm25.py         分词 / BM25 / 多因子打分
                   vectorstore.py  语义路：WindowVectorStore，窗口内全量余弦
                   retrievers.py   传统路打分 QQSparseRetriever + 双路 RRF 融合
                   cluster.py      检索后处理：集群扩展 / 裁剪 / 分组格式化
    调优常量       config.py       检索与聚类的旋钮（单源）
    LLM 调用       llm.py          ChatDeepSeek 构建 + 账户接口 + 用量统计
                   chain.py        公开入口：改写 / RAG 回答 / 普通对话
    agent 通路     agent.py        tool-calling 循环（`**` 群聊聚合 / `%%` 联网搜索）
                   tools.py        工具实现、schema、dispatch、按请求的身份工具
                   web_search.py   博查联网搜索（第三方 REST）
    智能路由       router.py       自然语言 → 某个功能的单步判定

单源约定：调优常量只在 config.py 一处；BM25 / score_message / _expand_cluster 等
排序敏感的原语只在本包一份；prompt 文本写在它服务的那个模块里（没有集中的 prompts.py）。

本模块只做**读**：语料的写入与存储归 chat_rag（依赖单向：ai_core → chat_rag）。
"""

from ai_core.retrieve import retrieve_context

__all__ = ["retrieve_context"]
