"""聊天记录语料与存储：自动记录群聊 + 向量持久化。

前缀路由：`*问题` → 单点检索（BM25+语义双路 → 单次作答）；
          `**问题` → agent 聚合通路（tool-calling 全群扫描，见 ai_core.agent）。

本模块只做**写路径与存储**：消息清洗入库、向量持久化（SQLite chat_vector）、最近上下文。
检索实现与调优常量都在 ai_core —— 本模块不引用它，依赖是单向的（ai_core → chat_rag）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import time

try:
    import numpy as np
    from langchain_core.embeddings import Embeddings
except ImportError:  # 允许在未装新依赖时启动其它机器人功能
    np = None
    Embeddings = object

from constant import DBPath

LOGGER = logging.getLogger(__name__)

DB_ROUTE = DBPath.CHAT_HISTORY
MAX_RECORD_LEN = 300

QUERY_INSTRUCTION = (
    "Retrieve QQ group chat messages that provide evidence relevant to the user's "
    "question, including slang, implied behavior, and conversational context."
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_ROUTE)
    conn.row_factory = sqlite3.Row
    return conn


def _backfill_identity(conn: sqlite3.Connection) -> None:
    """首次建表时从 chat_history 回填身份表；已有数据则跳过。

    身份纯属 chat_history 的派生索引（可随时用这一条 SQL 重建），所以与语料同库。
    """
    if conn.execute("SELECT 1 FROM user_identity LIMIT 1").fetchone() is not None:
        return
    conn.execute(
        "INSERT INTO user_identity (group_id, uin, alias, last_seen) "
        "SELECT group_id, uin, name, MAX(time) FROM chat_history "
        "GROUP BY group_id, uin, name"
    )


def init_db() -> None:
    """建表（幂等）：聊天记录表 + 向量表 + 身份表。"""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                uin      INTEGER NOT NULL,
                name     TEXT    NOT NULL,
                content  TEXT    NOT NULL,
                time     REAL    NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_group ON chat_history(group_id, id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_vector (
                id   INTEGER PRIMARY KEY REFERENCES chat_history(id),
                vec  BLOB NOT NULL,
                time REAL NOT NULL
            )
            """
        )
        # 昵称是展示标签、会变；uin 才是身份。这张表记下每个 uin 用过的每个昵称，
        # 让读侧能把历史行统一显示成最新昵称、也能让"拿旧名提问"照样命中。
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_identity (
                group_id  INTEGER NOT NULL,
                uin       INTEGER NOT NULL,
                alias     TEXT    NOT NULL,
                last_seen REAL    NOT NULL,
                PRIMARY KEY (group_id, uin, alias)
            )
            """
        )
        _backfill_identity(conn)


# ── 清洗与入库 ──────────────────────────────────────────────────────────────

def _clean_content(raw: str) -> str:
    """清洗 CQ 码 → 纯文本，保留语义动作。"""
    text = raw.replace("\r\n", " ").replace("\n", " ")
    text = re.sub(r"\[CQ:reply[^\]]*\]\[CQ:at,qq=\d+,name=([^\]]*)\]", r"@\1", text)
    text = re.sub(r"\[CQ:at,qq=\d+,name=([^\]]*)\]", r"@\1", text)
    text = re.sub(r"\[CQ:reply[^\]]*\]", "[回复]", text)
    text = re.sub(r"\[CQ:image[^\]]*\]", "[图片]", text)
    text = re.sub(r"\[CQ:face[^\]]*\]", "[表情]", text)
    text = re.sub(r"\[CQ:[^\]]*\]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_RECORD_LEN]


def _record_sync(group_id: int, uin: int, name: str, content: str, timestamp: float) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO chat_history (group_id, uin, name, content, time) VALUES (?,?,?,?,?)",
            (group_id, uin, name, content, timestamp),
        )
        try:
            # 身份行与正文同事务写，否则会出现"消息入库了、身份没更新"的不一致
            conn.execute(
                "INSERT INTO user_identity (group_id, uin, alias, last_seen) VALUES (?,?,?,?) "
                "ON CONFLICT(group_id, uin, alias) DO UPDATE SET last_seen = excluded.last_seen",
                (group_id, uin, name, timestamp),
            )
        except sqlite3.OperationalError:
            pass          # 旧库还没建 user_identity：不记身份，不影响正文入库
        return int(cursor.lastrowid)


def _identity_sync(group_id: int) -> tuple[dict[int, str], dict[str, str]]:
    """返回 (uin → 最新昵称, 任一用过的昵称 → 最新昵称)。

    同一 uin 改过名时按 last_seen 倒序，每个 uin 最先出现的那个即最新。
    第二个映射让"拿旧名提问"也能命中（提权按 uin 归属，见 QQSparseRetriever）。
    两个 uin 撞名时，该昵称优先归**当前正用它**的那个人；都没在用才按 use 先后。
    未迁移的旧库没有这张表，返回空——调用方据此退回改造前的行为。
    """
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT uin, alias, last_seen FROM user_identity WHERE group_id=? "
                "ORDER BY last_seen DESC, alias",
                (group_id,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}, {}
    current: dict[int, str] = {}
    for row in rows:
        current.setdefault(int(row["uin"]), str(row["alias"]))   # 倒序 → 首次遇到即最新
    alias_to_current: dict[str, str] = {}
    for row in rows:
        uin, alias = int(row["uin"]), str(row["alias"])
        if current[uin] == alias:
            alias_to_current[alias] = alias        # 仍是某人的现行名 → 归他
        else:
            alias_to_current.setdefault(alias, current[uin])
    return current, alias_to_current


async def record_chat(group_id: int, uin: int, name: str, raw_content: str) -> None:
    """记录一条群消息（异步）。纯占位符消息（纯图/表情/at）丢弃。"""
    content = _clean_content(await _resolve_reply(raw_content))

    # 去掉占位符后无真实文字（纯图/表情/at）→ 不入库
    stripped = re.sub(r"@\S+|\[(?:图片|表情|回复)\]", "", content)
    if not re.search(r"[一-鿿0-9a-zA-Z]", stripped):
        return

    # 昵称去不可见控制字符（如 ‭ LTR 符），空名退化 QQ 号
    import unicodedata
    clean_name = ''.join(
        ch for ch in (name or '') if unicodedata.category(ch) not in ('Cf', 'Cc') and ord(ch) >= 32
    ).strip() or str(uin)

    record_id = await asyncio.to_thread(_record_sync, group_id, uin, clean_name, content, time.time())
    asyncio.create_task(index_record_embedding(record_id), name=f"rag-vector-{record_id}")


async def _resolve_reply(raw: str) -> str:
    """把 reply/at 统一解析成 @昵称：多个 @ 按 qq 去重，不同的人全保留，按出现顺序。

    reply 码调 NapCat 查被回复人；at 码直接用消息里的 qq+name（无 name 退化为 @qq）。
    API 失败或查不到时，reply 保留原码（clean_content 兜底成 [回复]）。
    """
    # 查被回复消息的发送者 (qq, 昵称)；查不到则 reply 保留原码由清洗兜底
    reply_person = None
    reply_match = re.search(r"\[CQ:reply,id=(\d+)[^\]]*\]", raw)
    if reply_match:
        try:
            from helper_fun import get_message
            data = await get_message(reply_match.group(1))
            sender = (data or {}).get("sender", {})
            qq = sender.get("user_id")
            nickname = sender.get("nickname") or sender.get("card")
            if qq is not None and nickname:
                reply_person = (int(qq), str(nickname))
        except Exception:
            LOGGER.debug("无法解析被回复消息", exc_info=True)

    seen: set[int] = set()

    def emit(qq: int, name: str) -> str:
        if qq in seen:
            return ""
        seen.add(qq)
        return f"@{name}"

    def sub(match: re.Match[str]) -> str:
        code = match.group(0)
        if code.startswith("[CQ:reply"):
            return emit(*reply_person) if reply_person else "[回复]"
        at_match = re.match(r"\[CQ:at,qq=(\d+)(?:,name=([^\]]*))?\]", code)
        if not at_match:
            return ""
        qq = int(at_match.group(1))
        return emit(qq, at_match.group(2) or str(qq))

    return re.sub(r"\[CQ:(?:reply|at)[^\]]*\]", sub, raw)


def recent_context_sync(group_id: int, n: int = 30) -> str:
    """取该群最近 n 条消息，格式化为带昵称的文本，用于 query 改写时的指代消解上下文。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name, content FROM chat_history WHERE group_id=? ORDER BY id DESC LIMIT ?",
            (group_id, n),
        ).fetchall()
    return "\n".join(f"{row['name']}: {row['content']}" for row in reversed(rows))


async def recent_context(group_id: int, n: int = 30) -> str:
    """异步取该群最近 n 条消息文本。"""
    return await asyncio.to_thread(recent_context_sync, group_id, n)


# ── 向量：LangChain 封装百炼 + SQLite 存储 ──────────────────────────────────

_EMBED_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "text-embedding-v4")
_EMBED_DIM = int(os.environ.get("RAG_EMBEDDING_DIMENSION", "1024"))
_EMBED_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")
_EMBED_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
_EMBED_BATCH = 10


class BailianEmbeddings(Embeddings):
    """适配 LangChain Embeddings 接口的百炼稠密向量（text_type=document/query）。"""

    def __init__(self, api_key: str, base_url: str, model: str, dimension: int):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = dimension

    def _call(self, texts: list[str], *, text_type: str) -> list[list[float]]:
        import dashscope
        from http import HTTPStatus
        if not texts:
            return []
        dashscope.api_key = self.api_key
        dashscope.base_http_api_url = self.base_url
        kwargs = {
            "model": self.model,
            "input": list(texts),
            "dimension": self.dimension,
            "text_type": text_type,
            "output_type": "dense",
        }
        if text_type == "query":
            kwargs["instruct"] = QUERY_INSTRUCTION
        response = dashscope.TextEmbedding.call(**kwargs)
        if getattr(response, "status_code", None) != HTTPStatus.OK:
            raise RuntimeError(getattr(response, "message", "百炼向量接口调用失败"))
        output = getattr(response, "output", None) or {}
        embeddings = output.get("embeddings", [])
        if len(embeddings) != len(texts):
            raise RuntimeError("百炼向量接口返回数量与输入不一致")
        return [e["embedding"] for e in sorted(embeddings, key=lambda item: int(item.get("text_index", 0)))]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._call(list(texts), text_type="document")

    def embed_query(self, text: str) -> list[float]:
        return self._call([text], text_type="query")[0]


_embeddings: BailianEmbeddings | None = None


def _get_embeddings() -> BailianEmbeddings | None:
    """懒加载；未配置 API key 时返回 None（检索退化为纯 BM25）。"""
    global _embeddings
    if not _EMBED_API_KEY:
        return None
    if _embeddings is None:
        _embeddings = BailianEmbeddings(_EMBED_API_KEY, _EMBED_BASE_URL, _EMBED_MODEL, _EMBED_DIM)
    return _embeddings


def _vec_to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _embed_query_vec(query: str):
    """生成 query 向量；向量服务不可用返回 None。"""
    try:
        emb = _get_embeddings()
        if emb is None:
            return None
        return emb.embed_query(query)
    except Exception as exc:
        LOGGER.warning("RAG query 向量化失败，跳过语义分: %s", exc)
        return None


def _get_doc_vecs_sync(group_id: int, ids: list[int]) -> dict[int, np.ndarray]:
    """按 id 批量取该群候选的向量（BLOB→numpy）。"""
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, vec FROM chat_vector WHERE id IN ({placeholders})", ids
        ).fetchall()
    return {int(r["id"]): _blob_to_vec(r["vec"]) for r in rows}


def _embed_doc_vecs(group_id: int, messages: list[dict]):
    """给候选消息批量取向量，返回 {id: vec}。向量服务不可用或全缺失返回 None。"""
    try:
        emb = _get_embeddings()
        if emb is None:
            return None
        ids = [int(m["id"]) for m in messages]
        vec_map = _get_doc_vecs_sync(group_id, ids)
        if not vec_map:
            return None
        return {int(m["id"]): vec_map.get(int(m["id"])) for m in messages}
    except Exception as exc:
        LOGGER.warning("RAG 候选向量读取失败，跳过语义分: %s", exc)
        return None


def _index_vec_sync(record_id: int, vec_blob: bytes, timestamp: float) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO chat_vector (id, vec, time) VALUES (?,?,?)",
            (record_id, vec_blob, timestamp),
        )


def _get_content_sync(record_id: int):
    with _connect() as conn:
        return conn.execute(
            "SELECT content FROM chat_history WHERE id=?", (record_id,)
        ).fetchone()


def _pending_vector_ids_sync(limit: int) -> list[int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM chat_history WHERE id NOT IN (SELECT id FROM chat_vector) "
            "ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    return [int(r["id"]) for r in rows]


def _get_vectors_sync(ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, content FROM chat_history WHERE id IN ({placeholders})", ids
        ).fetchall()
    return {int(r["id"]): str(r["content"]) for r in rows}


async def index_record_embedding(record_id: int) -> None:
    """后台给一条新记录生成向量存 SQLite；失败只打日志不阻断。"""
    try:
        emb = _get_embeddings()
        if emb is None:
            return
        row = await asyncio.to_thread(_get_content_sync, record_id)
        if row is None or not row["content"]:
            return
        vec = emb.embed_documents([row["content"]])[0]
        await asyncio.to_thread(_index_vec_sync, record_id, _vec_to_blob(vec), time.time())
    except Exception as exc:
        LOGGER.warning("聊天记录 %s 向量化失败: %s", record_id, exc)


async def backfill_embedding(limit: int | None = None) -> dict[str, int]:
    """给历史未向量化记录补向量，可重复执行。返回 (indexed, failed)。"""
    if _get_embeddings() is None:
        return {"indexed": 0, "failed": 0}
    remaining = limit if limit is not None else int(os.environ.get("RAG_BACKFILL_LIMIT", "2000"))
    indexed = 0
    failed = 0
    while remaining > 0:
        ids = await asyncio.to_thread(_pending_vector_ids_sync, min(_EMBED_BATCH, remaining))
        if not ids:
            break
        content_map = await asyncio.to_thread(_get_vectors_sync, ids)
        texts = [content_map[i] for i in ids if i in content_map]
        try:
            vectors = _get_embeddings().embed_documents(texts)
            for i, vec in zip(ids, vectors):
                await asyncio.to_thread(_index_vec_sync, i, _vec_to_blob(vec), time.time())
            indexed += len(vectors)
        except Exception as exc:
            LOGGER.warning("RAG 向量回填失败: %s", exc)
            failed += len(ids)
            break
        remaining -= len(ids)
    return {"indexed": indexed, "failed": failed}


async def init_embeddings() -> None:
    """启动初始化：确认向量服务可用后后台回填历史向量。"""
    if _get_embeddings() is None:
        LOGGER.info("RAG 向量服务未配置（无 DASHSCOPE_API_KEY），检索将走纯 BM25")
        return
    asyncio.create_task(backfill_embedding(), name="rag-vector-backfill")
