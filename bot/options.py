"""配置与权限的存储，以及管理动作的门面。

原先这些是 BotCore 的十个方法，靠一个装着 7 个闭包的 AdminAPI 传给 FeatureAdmin。
现在拆成两个有状态的存储对象：

    OptionsStore  全局开关(options.txt) ⊕ 单群覆盖(group_options.json)
    RosterStore   管理员(administrators.json) 与黑名单(blacklist.json)

`AdminAPI` 只是面向管理功能的一个薄门面，持有上面两个存储 + 插件表，不再是闭包袋。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any

from constant import FeatureName


def _read_json(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: str, data) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class OptionsStore:
    """功能开关：全局模板 + 单群覆盖（覆盖优先）。"""

    def __init__(self, global_path: str, group_path: str) -> None:
        self._global_path = global_path
        self._group_path = group_path
        self._lock = asyncio.Lock()
        self.global_options: dict[str, int] = self._read_global()
        self.group_options: dict[str, dict[str, int]] = self._read_groups()

    # ── 读 ────────────────────────────────────────────────────────────────

    def _read_global(self) -> dict[str, int]:
        options: dict[str, int] = {}
        with open(self._global_path, "r", encoding="utf-8") as f:
            for line in f:
                key, value = line.strip().split("=")
                options[key] = int(value)
        return options

    def _read_groups(self) -> dict[str, dict[str, int]]:
        """读单群覆盖；文件缺失/损坏 → 空（回退全局模板）。"""
        try:
            with open(self._group_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def effective(self, group_id: int) -> dict[str, int]:
        """群消息的生效开关 = 全局模板 ⊕ 该群覆盖。"""
        opts = self.global_options.copy()
        over = self.group_options.get(str(group_id))
        if over:
            opts.update(over)
        return opts

    # ── 写（一律原子写，避免半截文件）──────────────────────────────────────

    def _write_global(self) -> None:
        tmp = self._global_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for k, v in self.global_options.items():
                f.write(f"{k}={v}\n")
        os.replace(tmp, self._global_path)

    def _write_groups(self) -> None:
        tmp = self._group_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.group_options, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._group_path)

    def ensure_keys(self, names) -> list[str]:
        """把「已注册但 options.txt 里没有」的功能补成 =0，返回补了哪些。

        原先新加功能必须手动往 options.txt 补一行，漏了就是静默默认关闭、毫无提示。
        """
        missing = [str(n) for n in names if str(n) not in self.global_options]
        if not missing:
            return []
        for name in missing:
            self.global_options[name] = 0
        self._write_global()
        return missing

    async def set_global(self, name: str, value: int) -> str:
        if name == FeatureName.ADMIN:
            return '不允许关闭管理功能'
        self.global_options[name] = value
        await asyncio.to_thread(self._write_global)
        return '已执行'

    async def set_group(self, group_id: int, name: str, value: int) -> str:
        if name == FeatureName.ADMIN:
            return '不允许关闭管理功能'
        async with self._lock:
            over = self.group_options.get(str(group_id))
            # 只跟该群自己的覆盖比，不看全局模板：全局已开但本群没设置过，仍要落一条覆盖
            if over and over.get(name) == value:
                return f'功能{name}已打开/关闭，请勿重复操作'
            self.group_options.setdefault(str(group_id), {})[name] = value
            await asyncio.to_thread(self._write_groups)
        return '已执行'

    async def reset_group(self, group_id: int, name: str) -> str:
        async with self._lock:
            over = self.group_options.get(str(group_id))
            if over and name in over:
                del over[name]
                if not over:
                    self.group_options.pop(str(group_id), None)
            else:
                return '该群没有此项单群设置'
            await asyncio.to_thread(self._write_groups)
        return '已执行'


class RosterStore:
    """管理员与黑名单。"""

    def __init__(self, admin_path: str, blacklist_path: str) -> None:
        self._admin_path = admin_path
        self._blacklist_path = blacklist_path
        self.admins: list[int] = _read_json(admin_path)
        self.blacklist: list[int] = _read_json(blacklist_path)

    async def set_blocked(self, qq: int, value: int) -> str:
        if value and qq not in self.blacklist:
            self.blacklist.append(qq)
        elif not value and qq in self.blacklist:
            self.blacklist.remove(qq)
        else:
            return '指令错误'
        await asyncio.to_thread(_dump_json, self._blacklist_path, self.blacklist)
        return '已执行'


@dataclass
class AdminAPI:
    """管理功能用的门面。持有的 `plugins` 与 Deps 里的是**同一个可变 dict**。"""

    store: OptionsStore
    roster: RosterStore
    plugins: dict[str, Any] = field(default_factory=dict)

    async def set_option(self, name: str, value: int) -> str:
        return await self.store.set_global(name, value)

    async def group_set_option(self, group_id: int, name: str, value: int) -> str:
        return await self.store.set_group(group_id, name, value)

    async def group_reset_option(self, group_id: int, name: str) -> str:
        return await self.store.reset_group(group_id, name)

    async def block_user(self, qq: int, value: int) -> str:
        return await self.roster.set_blocked(qq, value)

    async def reset_all(self) -> str:
        handlers = [p for p in self.plugins.values() if not p.abstract]
        for plugin in handlers:
            await plugin.reset_cache()
        return f'已清理{len(handlers)}个模块的缓存'

    async def feature_action(self, feature_name: str, action: str, **kwargs) -> str:
        feature = self.plugins.get(feature_name)
        if not feature:
            return f"不存在功能：{feature_name}"
        try:
            return await feature.admin_action(action, **kwargs)
        except Exception as e:      # noqa: BLE001
            return f"操作失败：{str(e)}"
