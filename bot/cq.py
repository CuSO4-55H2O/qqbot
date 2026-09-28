from __future__ import annotations

import asyncio
import base64
import os
import re
import httpx

from constant import *


# 查看定义长起来会走合并转发，而转发节点里没有"对应人物"，CQ at 码渲染不出来。
# 列表里统一换成纯文本 @昵称（昵称取 at 码自带的 name，码里没带就退回 qq 号）。
_CQ_AT = re.compile(r"\[CQ:at,qq=(\d+)(?:,name=([^\]]*))?\]")


def _at_to_text(text: str) -> str:
    return _CQ_AT.sub(lambda m: f"@{m.group(2) or m.group(1)}", text)


# 文件类元素（图片/语音/视频）在合并转发里靠 NapCat 下载，URL（QQ 的 rkey 临时链接）
# 一过期整条消息都发不出去。所以定义时就把图片字节抓下来入库，正文只留 [img:N] 占位。
_FILE_TEXT = {"image": "[图片]", "record": "[语音]", "video": "[视频]"}
_CQ_FILE = re.compile(r"\[CQ:(image|record|video)[^\]]*\]")
_CQ_IMAGE_ATTRS = re.compile(r"\[CQ:image,([^\]]*)\]")
_IMG_PLACEHOLDER = re.compile(r"\[img:(\d+)\]")
_MEDIA_MAX_BYTES = 5 * 1024 * 1024


def _strip_files(text: str) -> str:
    """文件类 CQ 码 → 文字占位（不动 [img:N] 占位符）。"""
    return _CQ_FILE.sub(lambda m: _FILE_TEXT[m.group(1)], text)


async def _fetch_image(attrs: str) -> bytes | None:
    """从一个 [CQ:image,...] 的属性串里取图片字节，取不到返回 None。

    三个来源，按可靠性排：码里已内联的 base64 / NapCat 给的本地路径 / url。
    url 是 rkey 临时链接，定义那一刻通常还有效；注意存进来时被 HTML 转义过
    （`&amp;`），不还原的话服务端会回 invalid rkey。
    """
    kv = dict(p.split("=", 1) for p in attrs.split(",") if "=" in p)
    file_val = (kv.get("file") or "").strip()
    url = (kv.get("url") or "").replace("&amp;", "&").strip()
    try:
        if file_val.startswith("base64://"):
            return base64.b64decode(file_val[len("base64://"):])
        if file_val and not file_val.startswith("{") and os.path.exists(file_val):
            with open(file_val, "rb") as f:
                return f.read()
        if url.startswith("http"):
            resp = await asyncio.to_thread(httpx.get, url, timeout=15, follow_redirects=True)
            if resp.status_code == 200:
                return resp.content
    except Exception as exc:
        print(f"[定义] 取图失败: {exc}")
    return None


async def _extract_media(content: str) -> tuple[str, list[str], int]:
    """把正文里的 CQ 图片抽成入库素材，返回 (新正文, base64列表, 失败数)。

    抽到的位置换成 [img:N]，取不到字节的（链接已死/超上限）换成文字占位。
    """
    matches = list(_CQ_IMAGE_ATTRS.finditer(content))
    if not matches:
        return content, [], 0
    media: list[str] = []
    failed = 0
    parts: list[str] = []
    last = 0
    for m in matches:
        parts.append(content[last:m.start()])
        last = m.end()
        raw = await _fetch_image(m.group(1))
        if raw and len(raw) <= _MEDIA_MAX_BYTES:
            parts.append(f"[img:{len(media)}]")
            media.append(base64.b64encode(raw).decode())
        else:
            parts.append(_FILE_TEXT["image"])
            failed += 1
    parts.append(content[last:])
    return "".join(parts), media, failed
