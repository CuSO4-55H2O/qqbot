# -*- coding: utf-8 -*-
"""「吃什么」：超管专属的抽签推荐。

触发：超管发「今天吃什么」。从 dishes.db 的预制菜池按两阶段掩码分类分布
抽 (主菜, 副菜?, 柠檬水?)：

    P(主菜, 副菜, 柠檬水) = P(主菜) · P(副菜|主菜) · P(柠檬水|主菜)

  第一阶段：P(主菜=i) ∝ w_i · 掩码 · 冷却因子
      掩码 = is_main 且 ≠ 上一次主菜（硬保证不连中）
      冷却 = exp(−β · e^(−Δn/τ))，Δn = 距上次抽中的调用次数（软压低近期高频菜）
  第二阶段：以主菜的 side_prob 决定是否抽副菜；
      副菜池 = 可作副菜（first_only=0）且与主菜不同商家的菜，
      权重 = w · side_factor（管饱主食作副菜打折）
  柠檬水：独立伯努利。force_drink 的主菜（肯德基/塔斯汀）必带，
      其余按 DRINK_RATE —— 所以它不进副菜竞争池，两个频率约束才不打架。

约束与数据的对应关系全部在 dishes.db 的 dishes 表里（weight / merchant /
is_main / first_only / side_prob / side_factor / force_drink / cooldown_beta），
下面的抽样函数只消费这些字段，加菜改菜不需要动代码。

权限：非超管触发直接放行（return None）——普通人发同样的话会落到后面的
功能（智能路由/RAG），超管走定制路。不登记 AdminMap：那不是管理命令，
登记了反而会被 FeatureAdmin 的总闸拦下普通用户的消息。

零 LLM 调用：不走 check_quota、不落 token_usage。
"""

from __future__ import annotations

import asyncio
import math
import random
import sqlite3
import time

from bot.plugin import Deps, Matcher, register
from bot.request import Reply, Request
from constant import *

# ── 抽样模型（纯函数：只依赖 random/math，不碰 DB、不碰 bot）─────────────────

# 软冷却的记忆长度（单位：调用次数）。隔 τ 次后惩罚衰减到 1/e 量级，
# 约 5~6 次调用后基本恢复正常权重。
TAU = 3.0

# 柠檬水基础概率：平均 15 次出现一次。边际会略高 —— 肯德基/塔斯汀（约 4%
# 主菜概率）强制附带，合计边际约 10.4%。这是设计意图（基础率 + 强制附带），
# 不是 bug；想严格卡 1/15 边际就把这里降到约 0.029。
DRINK_RATE = 1 / 15


def effective_weight(dish: dict, last_picked: dict[str, int], seq: int) -> float:
    """w · 软冷却因子。cooldown_beta 为 NULL（汉堡/柠檬水）或从没中过 → 原权重。

    Δn 用调用序号而不是时间：这个功能的使用间隔极不均匀（可能一天三次也可能
    一周不用），按次数冷却行为才可预期 —— 「隔 N 次恢复」，与真实感受对齐。
    """
    w = dish["weight"]
    beta = dish["cooldown_beta"]
    if beta is None:
        return w
    last = last_picked.get(dish["name"])
    if last is None:
        return w
    dn = seq - last
    if dn <= 0:
        return w
    return w * math.exp(-beta * math.exp(-dn / TAU))


def pick(dishes: list[dict], last_picked: dict[str, int], prev_main: str | None,
         seq: int, rng: random.Random) -> tuple[str, str | None, bool] | None:
    """抽一次。返回 (主菜, 副菜|None, 是否带柠檬水)；池子为空返回 None。

    dishes      dishes 表 is_main=1 的行（dict，含全部约束字段）
    last_picked 菜名 → 最后一次出现（主或副）的调用序号
    prev_main   上一次调用的主菜（硬剔除用）
    seq         本次调用序号
    rng         随机源（测试时传 random.Random(seed) 拿确定性）
    """
    # ── 第一阶段：主菜 ──
    pool = [d for d in dishes if d["weight"] > 0 and d["name"] != prev_main]
    if not pool:
        return None
    weights = [effective_weight(d, last_picked, seq) for d in pool]
    main = rng.choices(pool, weights=weights, k=1)[0]

    # ── 第二阶段：副菜（掩码 = 可作副菜 且 不与主菜同商家）──
    side = None
    if rng.random() < main["side_prob"]:
        side_pool = [
            d for d in dishes
            if not d["first_only"]
            and d["name"] != main["name"]
            and (d["merchant"] is None or d["merchant"] != main["merchant"])
        ]
        if side_pool:
            side_weights = [d["weight"] * d["side_factor"] for d in side_pool]
            side = rng.choices(side_pool, weights=side_weights, k=1)[0]["name"]

    # ── 柠檬水：独立通道，不参与副菜竞争 ──
    drink = bool(main["force_drink"]) or rng.random() < DRINK_RATE

    return main["name"], side, drink


def format_reply(main: str, side: str | None, drink: bool) -> str:
    parts = [f"今天吃【{main}】"]
    if side:
        parts.append(f"配一份【{side}】")
    if drink:
        parts.append("再来一杯柠檬水")
    return "，".join(parts)


# ── 插件本体 ───────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dishes (
    name TEXT PRIMARY KEY, weight REAL NOT NULL, merchant TEXT,
    is_main INTEGER NOT NULL, first_only INTEGER NOT NULL,
    side_prob REAL NOT NULL, side_factor REAL NOT NULL,
    force_drink INTEGER NOT NULL, cooldown_beta REAL);
CREATE TABLE IF NOT EXISTS pick_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    main_dish TEXT NOT NULL, side_dish TEXT,
    drink INTEGER NOT NULL DEFAULT 0, ts REAL NOT NULL);
"""


@register
class FeatureDishes(Matcher):
    name = FeatureName.DISHES
    priority = 15
    abstract = False

    def __init__(self, deps: Deps):
        super().__init__(deps)
        self.db_route = DBPath.DISHES
        self.rng = random.Random()
        # 只建结构、不填数据：菜品约束由 create_dishes_db.py 种子。
        # 全新部署拿到的是空池，走「菜单是空的」兜底而不是启动失败。
        with sqlite3.connect(self.db_route) as conn:
            conn.executescript(_SCHEMA)

    def _load_state(self):
        """读菜池 + 冷却状态（同步，调用方包 to_thread）。只读。"""
        with sqlite3.connect(self.db_route) as conn:
            conn.row_factory = sqlite3.Row
            dishes = [dict(r) for r in
                      conn.execute("SELECT * FROM dishes WHERE is_main=1")]
            seq = (conn.execute("SELECT MAX(seq) FROM pick_history")
                   .fetchone()[0] or 0) + 1
            row = conn.execute(
                "SELECT main_dish FROM pick_history ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_main = row[0] if row else None
            last_picked = dict(conn.execute(
                "SELECT dish, MAX(seq) FROM ("
                "  SELECT main_dish AS dish, seq FROM pick_history"
                "  UNION ALL"
                "  SELECT side_dish, seq FROM pick_history"
                "  WHERE side_dish IS NOT NULL"
                ") GROUP BY dish").fetchall())
        return dishes, seq, prev_main, last_picked

    def _record(self, main: str, side: str | None, drink: bool):
        with sqlite3.connect(self.db_route) as conn:
            conn.execute(
                "INSERT INTO pick_history (main_dish, side_dish, drink, ts)"
                " VALUES (?,?,?,?)",
                (main, side, int(drink), time.time()))
            conn.commit()

    async def match(self, req: Request) -> Reply | None:
        if req.msg.strip() != '今天吃什么':
            return None
        if req.qq != req.super_admin:
            return None

        dishes, seq, prev_main, last_picked = await asyncio.to_thread(
            self._load_state)
        if not dishes:
            return Reply.same_conversation(req, '菜单是空的，先去加点菜吧')

        result = pick(dishes, last_picked, prev_main, seq, self.rng)
        if result is None:
            return Reply.same_conversation(req, '菜单是空的，先去加点菜吧')

        main, side, drink = result
        await asyncio.to_thread(self._record, main, side, drink)
        return Reply.same_conversation(req, format_reply(main, side, drink))
