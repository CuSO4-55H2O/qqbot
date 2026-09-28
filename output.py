import asyncio
import random
import re
import base64
from dataclasses import dataclass

import httpx
from constant import DELIMITER, Name, NAPCAT_BASE_URL, NAPCAT_TOKEN


@dataclass(frozen=True)
class BotIdentity:
    """机器人自己的 QQ 号与显示名，合并转发里每个节点的署名用它。

    原先这是 constant.py 里两个硬编码常量（BOT_UIN / BOT_NAME），换账号要改代码。
    现在由 BotCore 启动时从 NapCat 的 get_login_info 取，再随发送调用一路显式传进来
    —— 不做模块级缓存，省得又出现一份「谁都能改、谁都看不见」的状态。
    """

    uin: int
    name: str


_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        headers = {'Authorization': f'Bearer {NAPCAT_TOKEN}'} if NAPCAT_TOKEN else {}
        _client = httpx.AsyncClient(headers=headers, timeout=30.0)
    return _client


def auto_convert_images_to_base64(msg_text):
    if not isinstance(msg_text, str):
        return msg_text

    pattern = r'(\[CQ:(?:image|record|video).*?file=)([^,\]]+)(.*?\])'

    def replacer(match):
        prefix = match.group(1)
        raw_path = match.group(2)
        suffix = match.group(3)

        if raw_path.startswith('base64://') or raw_path.startswith('http'):
            return match.group(0)

        clean_path = re.sub(r'^file:/+', '/', raw_path) if raw_path.startswith('file:') else raw_path
        clean_path = clean_path.replace('\\', '/')

        if re.match(r'^/[a-zA-Z]:/', clean_path):
            clean_path = clean_path[1:]
        elif not clean_path.startswith('/') and not re.match(r'^[a-zA-Z]:/', clean_path):
            clean_path = '/' + clean_path

        clean_path = re.sub(r'/+', '/', clean_path)

        try:
            with open(clean_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode('utf-8')
            return f"{prefix}base64://{b64_data}{suffix}"
        except Exception as e:
            print("\n" + "!" * 50)
            print(f"警告：拦截器读取图片失败！")
            print(f"原始抓取路径: {raw_path}")
            print(f"清洗后实际去找的路径: {clean_path}")
            print(f"系统报错原因: {e}")
            print("!" * 50 + "\n")
            return match.group(0)

    return re.sub(pattern, replacer, msg_text)


async def _post(endpoint, payload):
    client = await get_client()
    response = await client.post(f'{NAPCAT_BASE_URL}/{endpoint}', json=payload)
    return response


_B64_PAYLOAD = re.compile(r'base64://[A-Za-z0-9+/=]+')

# 切分期的折叠：把 base64 载荷当成固定 200 字符来算长度，切完再按原样还原。
# 不折的话，一张图（base64 后十几万字符）自己就把「段」撑爆，于是切点必然落在它后面
# —— 每张图独占一段，一段也装不下别的东西。折叠后图片按 200 字符参与排布，一段能装进
# 好几条内容，图也不会被单独切出来。
# 填充用 '.'：它不在 base64 字母表里，所以 `base64://.` 只可能是我们自己造的占位，
# 绝不会撞上真载荷 —— 还原时才能靠这个特征按出现顺序替换回去。
_MASK_LEN = 200
_MASK_CHAR = '.'
_MASK_PREFIX = 'base64://' + _MASK_CHAR
_MASK_RE = re.compile(re.escape(_MASK_PREFIX) + '+')


def _mask_payloads(text: str) -> tuple[str, list[str]]:
    """把每个 base64 载荷折成 200 字符占位。返回（折叠后的串, 原载荷按出现顺序）。"""
    originals: list[str] = []

    def sub(m):
        originals.append(m.group(0))
        return _MASK_PREFIX + _MASK_CHAR * (_MASK_LEN - len(_MASK_PREFIX))

    return _B64_PAYLOAD.sub(sub, text), originals


def _unmask(text: str, pending) -> str:
    """把占位换回真载荷。pending = iter(载荷列表)，由调用方在段循环外建一次 ——
    占位在整串里的先后就是载荷的先后，所以迭代器必须跨段共享、不能每段重来。"""
    return _MASK_RE.sub(lambda m: next(pending), text)


def custom_split(input_str, me: BotIdentity):
    masked, payloads = _mask_payloads(input_str)
    if DELIMITER in masked:
        result = masked.split(DELIMITER)
    else:
        result = []
        i = j = 0
        a = 2000
        while i < len(masked):
            if masked[i] == '[':
                end_idx = masked.find(']', i)
                if end_idx - j > a * 0.6:
                    result.append(masked[j:end_idx + 1])
                    i = j = end_idx + 1
                else:
                    i = end_idx
            elif i % a == 0 and i != 0:
                result.append(masked[j:i + 1])
                j = i = i + 1
            elif i == len(masked) - 1:
                result.append(masked[j:])
                break
            else:
                i += 1
    pending = iter(payloads)
    for i in range(len(result)):
        result[i] = auto_convert_images_to_base64(_unmask(result[i], pending))

    return [{"type": "node", "data": {"uin": me.uin, "name": me.name, "content": i}}
            for i in result if i]


async def send_group_original(mes, group):
    await _post('send_group_forward_msg', {"group_id": group, "messages": mes})
    print(f"发送 {group} {mes}")


async def send_group(a, group, me: BotIdentity):
    a = auto_convert_images_to_base64(a)
    await _post('send_group_forward_msg',
                {"group_id": group, "messages": custom_split(a, me)})
    print(f"发送 {group} {a}")


async def send_private(a, qq, me: BotIdentity):
    a = auto_convert_images_to_base64(a)
    await _post('send_private_forward_msg',
                {"user_id": qq, "messages": custom_split(a, me)})
    print(f"发送 {qq} {a}")


async def group_poke(qq, group):
    res = await _post('group_poke', {"user_id": qq, "group_id": group})
    print(res.text)


def _visible_len(msg: str) -> int:
    """判定「该不该走合并转发」时用的长度：base64 载荷不算。

    否则一张内联的图片/语音必然把原始串顶过 1024，单张图片也会被误判成长消息。
    """
    return len(_B64_PAYLOAD.sub('base64://', msg))


async def send_msg(resp_dict, me: BotIdentity):
    await asyncio.sleep(random.uniform(0.01, 0.03))
    msg_type = resp_dict['msg_type']
    number = resp_dict['number']
    msg = resp_dict['msg'].rstrip('\n')

    visible = _visible_len(msg)
    if (visible > 280 and "CQ:image" not in msg and "CQ:at" not in msg) \
            or visible > 1024 or DELIMITER in msg:
        if msg_type == Name.GROUP:
            await send_group(msg, number, me)
        elif msg_type == Name.PRIVATE:
            await send_private(msg, number, me)
    else:
        endpoint = 'send_group_msg' if msg_type == Name.GROUP else 'send_msg'
        msg = auto_convert_images_to_base64(msg)
        payload = {'message': msg}
        if msg_type == Name.GROUP:
            payload['group_id'] = number
        else:
            payload['user_id'] = number

        await _post(endpoint, payload)
        text = f"发送 POST /{endpoint} {payload}"
        if len(text) < 2000:
            print(text)
        else:
            print(text[:200])


async def recall(group, msg_id, qq):
    await _post('send_group_forward_msg', {"group_id": group, "messages": [{"type": "node", "data": {
        'uin': qq, 'id': msg_id}}]})
    print(f"撤回 {group} {msg_id}")


async def set_msg_emoji_like(message_id: int, emoji_id: str):
    await _post('set_msg_emoji_like', {"message_id": message_id, "emoji_id": emoji_id})
    print(f"贴表情 message_id={message_id} emoji_id={emoji_id}")
