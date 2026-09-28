"""群消息 dict ↔ langchain_core Document 的转换。

    page_content = 消息纯文本
    metadata     = {id, group_id, uin, name, time}（其余业务字段都在 metadata）
顺序语义：窗口消息按 id 升序排列，Document 列表顺序即窗口下标顺序 ——
下游（集群扩展、向量对齐）都按下标取数，所以这个顺序不能乱。
"""

from __future__ import annotations

from langchain_core.documents import Document

# sqlite chat_history 行的字段
MSG_FIELDS = ("id", "group_id", "uin", "name", "content", "time")


def msg_to_doc(msg: dict) -> Document:
    """把一条 chat_history 行 dict 转成 Document。"""
    return Document(
        page_content=str(msg.get("content") or ""),
        metadata={f: msg[f] for f in MSG_FIELDS},
    )


def doc_to_msg(doc: Document) -> dict:
    """Document → 原 chat_history 行 dict（供沿用 chat_rag 精确数学原语时使用）。"""
    return {**{f: doc.metadata[f] for f in MSG_FIELDS if f in doc.metadata}, "content": doc.page_content}


def msgs_to_docs(msgs: list[dict]) -> list[Document]:
    return [msg_to_doc(m) for m in msgs]


def docs_to_msgs(docs: list[Document]) -> list[dict]:
    return [doc_to_msg(d) for d in docs]
