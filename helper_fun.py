import json
import httpx
from constant import JsonPath, NAPCAT_BASE_URL, NAPCAT_TOKEN

base_url = NAPCAT_BASE_URL

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        headers = {'Content-Type': 'application/json'}
        if NAPCAT_TOKEN:
            headers['Authorization'] = f'Bearer {NAPCAT_TOKEN}'
        _client = httpx.AsyncClient(headers=headers, timeout=30.0)
    return _client


async def read_id():
    client = await get_client()
    response = await client.post(f"{base_url}/get_login_info")
    data = response.json()
    return data["data"]["user_id"],data["data"]["nickname"]


async def coin():
    with open(JsonPath.COIN, 'r') as f:
        bank = json.load(f)
    return bank


async def get_message(id):
    client = await get_client()
    payload = json.dumps({
        "message_id": id
    })
    response = await client.post(f"{base_url}/get_msg", data=payload)
    return response.json()['data']


async def get_user_nickname(user_id: int) -> str:
    """
    根据 QQ 号获取用户昵称
    """
    client = await get_client()
    url = f"{base_url}/get_stranger_info"
    payload = {
        "user_id": user_id
    }
    try:
        resp = await client.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'ok' and 'data' in data:
                nickname = data['data'].get('nickname')
                if nickname:
                    return nickname
            elif 'nickname' in data:
                return data['nickname']
        return "未知昵称"
    except Exception as e:
        print(f"get_user_info 请求失败: {e}")
        return "未知昵称"
