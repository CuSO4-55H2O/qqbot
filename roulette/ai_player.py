"""
AI 玩家 —— 自包含推理模块，不依赖 roulette_ai 包。

支持两种模型：
  - 简单人机 (69 维, model_50000.pt) — 第一轮 50k 最优
  - 中等人机 (72 维, model_350000.pt) — 第三轮 350k 最优

用法:
    from roulette.ai_player import AIPlayer
    ai = AIPlayer("roulette/checkpoints/model_50000.pt")     # 简单
    ai = AIPlayer("roulette/checkpoints/model_350000.pt")    # 中等
    msgs = ai.play_turn(game, player_index)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import torch
import torch.nn as nn

if TYPE_CHECKING:
    from roulette.roulette import Game

# ================================================================
# 公共常量
# ================================================================

ACTION_DIM = 17
DEVICE = "cpu"

# ── 道具顺序 ──
ITEM_ORDER = [
    "刀", "灌铅骰子", "烟", "放大镜", "手铐",
    "炸药", "洛欧塞布", "baba", "午时已到", "死亡证明", "生死逆转",
]
ITEM_COUNT = 11

# ── 条件 ──
CONDITION_ORDER = ["knife", "handcuffs", "ban"]

# ── 神器 ──
ARTIFACT_ORDER = ["沃金的手", "整理好的茶具", "莽"]

# ── 训练时使用的模式（15 个）──
ALLOWED_MODES = [1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18]

# ── 道具动作（排除 baba）──
ITEM_ACTION_ORDER = [i for i in ITEM_ORDER if i != "baba"]

# ── 动作名称 ──
_ITEM_ACTION_NAMES = [f"使用{i}" for i in ITEM_ACTION_ORDER]
_MODE_ACTION_NAMES = ["苦肉", "跳过回合"]
_ARTIFACT_ACTION_NAMES = [f"神器:{a}" for a in ARTIFACT_ORDER]
ACTION_NAMES = (
    ["向自己开枪", "向对手开枪"]
    + _ITEM_ACTION_NAMES
    + _MODE_ACTION_NAMES
    + _ARTIFACT_ACTION_NAMES
)

# ── 动作索引 ──
ACTION_SHOOT_SELF     = 0
ACTION_SHOOT_OPPONENT = 1
ACTION_ITEM_OFFSET    = 2
ACTION_HARDSHIP       = 12
ACTION_SKIP_TURN      = 13
ACTION_ARTIFACT_OFFSET = 14

# ── 动作名称到游戏指令 ──
ACTION_TO_GAME_CMD = {}
ACTION_TO_GAME_CMD[ACTION_SHOOT_SELF] = "向自己开枪"
ACTION_TO_GAME_CMD[ACTION_SHOOT_OPPONENT] = "向对手开枪"
for _i, _name in enumerate(ITEM_ACTION_ORDER):
    ACTION_TO_GAME_CMD[ACTION_ITEM_OFFSET + _i] = f"使用{_name}"
ACTION_TO_GAME_CMD[ACTION_HARDSHIP] = "苦肉"
ACTION_TO_GAME_CMD[ACTION_SKIP_TURN] = "跳过回合"
for _j, _art_name in enumerate(ARTIFACT_ORDER):
    ACTION_TO_GAME_CMD[ACTION_ARTIFACT_OFFSET + _j] = f"使用{_art_name}"


# ================================================================
# 权重转换工具
# ================================================================

def _convert_weights_from_bottleneck(sd: dict) -> dict:
    """折叠旧瓶颈层 W2@W1，忽略 ReLU（线性近似）。"""
    new_sd = {}
    v1_w = v1_b = v2_w = v2_b = None
    a1_w = a1_b = a2_w = a2_b = None
    for k, v in list(sd.items()):
        if k == "value_stream.0.weight":
            v1_w = v
        elif k == "value_stream.0.bias":
            v1_b = v
        elif k == "value_stream.2.weight":
            v2_w = v
        elif k == "value_stream.2.bias":
            v2_b = v
        elif k == "advantage_stream.0.weight":
            a1_w = v
        elif k == "advantage_stream.0.bias":
            a1_b = v
        elif k == "advantage_stream.2.weight":
            a2_w = v
        elif k == "advantage_stream.2.bias":
            a2_b = v
        elif k.startswith("value_stream.") or k.startswith("advantage_stream."):
            continue
        else:
            new_sd[k] = v
    if v1_w is not None:
        new_sd["value_stream.weight"] = (v2_w.to(v1_w.device) @ v1_w).to(v1_w.dtype)
        new_sd["value_stream.bias"] = (
            v2_b.to(v1_b.device) + v2_w.to(v1_w.device) @ v1_b
        ).to(v1_b.dtype)
        new_sd["advantage_stream.weight"] = (a2_w.to(a1_w.device) @ a1_w).to(a1_w.dtype)
        new_sd["advantage_stream.bias"] = (
            a2_b.to(a1_b.device) + a2_w.to(a1_w.device) @ a1_b
        ).to(a1_b.dtype)
    return new_sd


# ================================================================
# DuelingDQN —— 自动检测架构
# ================================================================

class DuelingDQN(nn.Module):
    """Dueling Double DQN —— Q(s,a) = V(s) + (A(s,a) - mean(A))

    架构 (use_bottleneck=False):
        shared: Linear(S, 256) → ReLU → Linear(256, 128) → ReLU
        value_stream: Linear(128, 1)
        advantage_stream: Linear(128, 17)
    """

    def __init__(self, state_dim: int = 69, action_dim: int = 17,
                 hidden_dim: int = 256, use_bottleneck: bool = False):
        super().__init__()
        self.state_dim = state_dim
        self.action_dim = action_dim

        self.shared = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 128),
            nn.ReLU(),
        )

        if use_bottleneck:
            self.value_stream = nn.Sequential(
                nn.Linear(128, 64),
                nn.ReLU(),
                nn.Linear(64, 1),
            )
            self.advantage_stream = nn.Sequential(
                nn.Linear(128, 64),
                nn.ReLU(),
                nn.Linear(64, action_dim),
            )
        else:
            self.value_stream = nn.Linear(128, 1)
            self.advantage_stream = nn.Linear(128, action_dim)

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        single = state.dim() == 1
        if single:
            state = state.unsqueeze(0)
        features = self.shared(state)
        value = self.value_stream(features)
        advantage = self.advantage_stream(features)
        q = value + (advantage - advantage.mean(dim=-1, keepdim=True))
        if single:
            q = q.squeeze(0)
        return q

    @torch.no_grad()
    def select_action(self, state: torch.Tensor, mask: torch.Tensor,
                      epsilon: float = 0.0) -> int:
        if epsilon > 0 and torch.rand(1).item() < epsilon:
            valid = mask.nonzero(as_tuple=True)[0]
            if len(valid) == 0:
                return 0
            return valid[torch.randint(len(valid), (1,))].item()

        q = self.forward(state)
        q[~mask] = float("-inf")
        return int(q.argmax(dim=-1).item())


# ================================================================
# BulletKnowledge（Bug 已修复版）
# ================================================================

class BulletKnowledge:
    """追踪每个玩家通过道具/模式获知的私有子弹信息。"""

    __slots__ = ("next_known", "next_value", "last_known", "last_value")

    def __init__(self):
        self.next_known = [False, False]
        self.next_value = [0, 0]
        self.last_known = [False, False]
        self.last_value = [0, 0]

    def mark_next(self, player: int, value: int):
        self.next_known[player] = True
        self.next_value[player] = value

    def mark_last(self, player: int, value: int):
        self.last_known[player] = True
        self.last_value[player] = value

    def clear_next(self, player: int | None = None):
        """Bug 修复：player=None 时清掉**所有**玩家的 next knowledge。
        因为"下一发"是弹夹的客观属性，无论谁开枪，第一颗子弹都被消耗。
        """
        if player is None:
            self.next_known = [False, False]
            self.next_value = [0, 0]
        else:
            self.next_known[player] = False
            self.next_value[player] = 0

    def clear_all(self):
        self.next_known = [False, False]
        self.next_value = [0, 0]
        self.last_known = [False, False]
        self.last_value = [0, 0]

    def flip(self):
        for p in (0, 1):
            if self.next_known[p]:
                self.next_value[p] = 1 - self.next_value[p]
            if self.last_known[p]:
                self.last_value[p] = 1 - self.last_value[p]

    def for_player(self, p: int) -> dict:
        return {
            "next_known": self.next_known[p],
            "next_value": self.next_value[p],
            "last_known": self.last_known[p],
            "last_value": self.last_value[p],
        }


# ================================================================
# StateEncoder —— 69 维（兼容旧模型 model_50000）
# ================================================================

class StateEncoder69:
    """69 维编码器，匹配旧模型（第一轮 50k）。
    不含 smoke_valid / death_timer / genuine_extra_turn。
    """

    MAX_HP_REF       = 18
    MAX_ITEM_REF     = 10
    MAX_GIVE_ITEM    = 2
    MAX_CUR_TURNS    = 20
    MAX_TOTAL_TURNS  = 60
    MAX_BULLET_REF   = 20

    # 偏移量
    OFFSET_HP          = 0
    OFFSET_ITEMS       = 2
    OFFSET_CONDITIONS  = 24
    OFFSET_ARTIFACTS   = 30
    OFFSET_GUN         = 34
    OFFSET_EXTRA_TURN  = 41
    OFFSET_STAGE       = 42
    OFFSET_TURNS       = 45
    OFFSET_MODES       = 47
    OFFSET_PARAMS      = 62
    OFFSET_SCORE       = 65
    OFFSET_POINTS      = 67

    STATE_DIM = 69

    def encode(self, game: Game, player_index: int,
               bullet_info: dict | None = None,
               extra_turn: float = 0.0) -> np.ndarray:
        vec = np.zeros(self.STATE_DIM, dtype=np.float32)
        opp = 1 - player_index

        if bullet_info is None:
            bullet_info = {"next_known": False, "next_value": 0,
                           "last_known": False, "last_value": 0}

        self._encode_hp(game, player_index, opp, vec)
        self._encode_items(game, player_index, opp, vec)
        self._encode_conditions(game, player_index, opp, vec)
        self._encode_artifacts(game, player_index, opp, vec)
        self._encode_gun(game, bullet_info, vec)
        vec[self.OFFSET_EXTRA_TURN] = extra_turn
        self._encode_stage(game, vec)
        self._encode_turns(game, vec)
        self._encode_modes(game, vec)
        self._encode_params(game, vec)
        self._encode_score(game, player_index, opp, vec)
        self._encode_points(game, player_index, opp, vec)
        return vec

    def action_mask(self, game: Game, player_index: int) -> np.ndarray:
        mask = np.zeros(ACTION_DIM, dtype=bool)
        player = game.players[player_index]
        loathebed = player.condition.get("ban", False)

        mask[ACTION_SHOOT_SELF]     = True
        mask[ACTION_SHOOT_OPPONENT] = True

        for i, item_name in enumerate(ITEM_ACTION_ORDER):
            if item_name == "死亡证明":
                continue
            has_it = player.item.get(item_name, 0) >= 1
            has_dp = player.item.get("死亡证明", 0) >= 1
            if item_name == "刀" and player.condition.get("knife", False):
                mask[ACTION_ITEM_OFFSET + i] = False
            elif item_name == "手铐" and player.condition.get("handcuffs", False):
                mask[ACTION_ITEM_OFFSET + i] = False
            else:
                mask[ACTION_ITEM_OFFSET + i] = (has_it or has_dp) and not loathebed

        mask[ACTION_HARDSHIP] = (11 in game.mode_ids and player.hp >= 1)
        mask[ACTION_SKIP_TURN] = self._can_skip_turn(game, player_index)

        if 17 in game.mode_ids:
            for j, art_name in enumerate(ARTIFACT_ORDER):
                mask[ACTION_ARTIFACT_OFFSET + j] = (
                    player.artifacts.get(art_name, 0) >= 1
                )
        return mask

    # ── 各段编码 ──

    def _encode_hp(self, game, p, opp, vec):
        vec[self.OFFSET_HP]     = min(game.players[p].hp   / self.MAX_HP_REF, 1.0)
        vec[self.OFFSET_HP + 1] = min(game.players[opp].hp / self.MAX_HP_REF, 1.0)

    def _encode_items(self, game, p, opp, vec):
        n = len(ITEM_ORDER)
        base = self.OFFSET_ITEMS
        for i, name in enumerate(ITEM_ORDER):
            vec[base + i]     = min(game.players[p].item.get(name, 0)   / self.MAX_ITEM_REF, 1.0)
            vec[base + i + n] = min(game.players[opp].item.get(name, 0) / self.MAX_ITEM_REF, 1.0)

    def _encode_conditions(self, game, p, opp, vec):
        n = len(CONDITION_ORDER)
        base = self.OFFSET_CONDITIONS
        for i, cond in enumerate(CONDITION_ORDER):
            vec[base + i]     = float(game.players[p].condition.get(cond, False))
            vec[base + i + n] = float(game.players[opp].condition.get(cond, False))

    def _encode_artifacts(self, game, p, opp, vec):
        n = len(ARTIFACT_ORDER)
        base = self.OFFSET_ARTIFACTS
        for i, art in enumerate(ARTIFACT_ORDER):
            vec[base + i] = float(game.players[p].artifacts.get(art, 0) >= 1)
        opp_count = sum(1 for art in ARTIFACT_ORDER
                        if game.players[opp].artifacts.get(art, 0) >= 1)
        vec[base + n] = min(opp_count / n, 1.0) if n > 0 else 0.0

    def _encode_gun(self, game, bullet_info, vec):
        base = self.OFFSET_GUN
        total = len(game.gun.magazine)
        ref = self.MAX_BULLET_REF
        vec[base]     = min(game.gun.get_live_num()  / ref, 1.0)
        vec[base + 1] = min(game.gun.get_blank_num() / ref, 1.0)
        vec[base + 2] = min(total / ref, 1.0)
        vec[base + 3] = float(bullet_info["next_known"])
        vec[base + 4] = float(bullet_info["next_value"])
        vec[base + 5] = float(bullet_info["last_known"])
        vec[base + 6] = float(bullet_info["last_value"])

    def _encode_stage(self, game, vec):
        base = self.OFFSET_STAGE
        s = game.stage
        vec[base]     = 1.0 if s == 1 else 0.0
        vec[base + 1] = 1.0 if s == 2 else 0.0
        vec[base + 2] = 1.0 if s == 3 else 0.0

    def _encode_turns(self, game, vec):
        base = self.OFFSET_TURNS
        vec[base]     = min(game.cur_turns   / max(self.MAX_CUR_TURNS, 1),   1.0)
        vec[base + 1] = min(game.total_turns / max(self.MAX_TOTAL_TURNS, 1), 1.0)

    def _encode_modes(self, game, vec):
        base = self.OFFSET_MODES
        for i, mid in enumerate(ALLOWED_MODES):
            vec[base + i] = 1.0 if mid in game.mode_ids else 0.0

    def _encode_params(self, game, vec):
        base = self.OFFSET_PARAMS
        vec[base]     = min(game.max_hp        / self.MAX_HP_REF,     1.0)
        vec[base + 1] = min(game.max_item_num  / self.MAX_ITEM_REF,   1.0)
        vec[base + 2] = min(game.give_item_num / self.MAX_GIVE_ITEM,  1.0)

    def _encode_score(self, game, p, opp, vec):
        base = self.OFFSET_SCORE
        vec[base]     = min(game.score[p]   / 2.0, 1.0)
        vec[base + 1] = min(game.score[opp] / 2.0, 1.0)

    def _encode_points(self, game, p, opp, vec):
        base = self.OFFSET_POINTS
        max_point = 500.0
        vec[base]     = min(game.players[p].point   / max_point, 1.0)
        vec[base + 1] = min(game.players[opp].point / max_point, 1.0)

    def _can_skip_turn(self, game, player_index):
        if 13 not in game.mode_ids:
            return False
        for mode in game.modes:
            if mode.id == 13:
                return not mode.last_skip_used[player_index]
        return False


# ================================================================
# StateEncoder —— 72 维（匹配 R3+ 新模型）
# ================================================================

class StateEncoder72(StateEncoder69):
    """72 维编码器，新增 3 维：烟有效性 / 死亡计时 / 真额外回合。
    匹配第三轮及以后的模型（350k、450k 等）。
    """

    STATE_DIM = 72

    OFFSET_SMOKE_VALID        = 69
    OFFSET_DEATH_TIMER        = 70
    OFFSET_GENUINE_EXTRA_TURN = 71

    def encode(self, game: Game, player_index: int,
               bullet_info: dict | None = None,
               extra_turn: float = 0.0,
               genuine_extra_turn: float = 0.0) -> np.ndarray:
        vec = np.zeros(self.STATE_DIM, dtype=np.float32)
        opp = 1 - player_index

        if bullet_info is None:
            bullet_info = {"next_known": False, "next_value": 0,
                           "last_known": False, "last_value": 0}

        # 逻辑推断子弹知识
        bullet_info = self._apply_bullet_deductions(game, bullet_info)

        self._encode_hp(game, player_index, opp, vec)
        self._encode_items(game, player_index, opp, vec)
        self._encode_conditions(game, player_index, opp, vec)
        self._encode_artifacts(game, player_index, opp, vec)
        self._encode_gun(game, bullet_info, vec)
        vec[self.OFFSET_EXTRA_TURN] = extra_turn
        vec[self.OFFSET_GENUINE_EXTRA_TURN] = genuine_extra_turn
        self._encode_stage(game, vec)
        self._encode_turns(game, vec)
        self._encode_modes(game, vec)
        self._encode_params(game, vec)
        self._encode_score(game, player_index, opp, vec)
        self._encode_points(game, player_index, opp, vec)
        self._encode_smoke_valid(game, player_index, opp, vec)
        self._encode_death_timer(game, vec)
        return vec

    def action_mask(self, game: Game, player_index: int) -> np.ndarray:
        mask = super().action_mask(game, player_index)

        # 已知下一发 → 掩码放大镜
        bullet_info = self._apply_bullet_deductions(game, {
            "next_known": False, "next_value": 0,
            "last_known": False, "last_value": 0,
        })
        # 注意：实际调用时 bullet_info 由外部传入，这里只是标记逻辑推断结果
        # AIPlayer 会在调用 encoder 时传入真实的 bullet_info
        return mask

    def _encode_smoke_valid(self, game: Game, p: int, opp: int, vec: np.ndarray):
        """烟是否有效：hp<对手 且不被阶段3回血封锁"""
        hp = game.players[p].hp
        opp_hp = game.players[opp].hp
        stage3_blocked = (game.stage == 3 and hp <= 4)
        valid = hp < opp_hp and not stage3_blocked
        vec[self.OFFSET_SMOKE_VALID] = float(valid)

    def _encode_death_timer(self, game: Game, vec: np.ndarray):
        """死亡计时倒计时（#16 激活时），/14 归一化"""
        if 16 not in game.mode_ids:
            vec[self.OFFSET_DEATH_TIMER] = 0.0
            return
        from roulette.constant import DEATH_TIMER_LIMIT
        limit = DEATH_TIMER_LIMIT.get(game.stage, 14)
        countdown = max(0, limit - game.cur_turns)
        vec[self.OFFSET_DEATH_TIMER] = min(countdown / 14.0, 1.0)

    def _apply_bullet_deductions(self, game: Game, bullet_info: dict) -> dict:
        """从公开信息逻辑推导下一发子弹。"""
        magazine = game.gun.magazine
        total = len(magazine)
        if total == 0 or bullet_info["next_known"]:
            return bullet_info

        live = game.gun.get_live_num()
        blank = game.gun.get_blank_num()

        if blank == 0:
            return {"next_known": True, "next_value": 1,
                    "last_known": bullet_info["last_known"],
                    "last_value": bullet_info["last_value"]}
        if live == 0:
            return {"next_known": True, "next_value": 0,
                    "last_known": bullet_info["last_known"],
                    "last_value": bullet_info["last_value"]}

        if bullet_info["last_known"]:
            last_val = bullet_info["last_value"]
            if (blank == 1 and last_val == 0) or (live == 1 and last_val == 1):
                return {"next_known": True, "next_value": 1 - last_val,
                        "last_known": bullet_info["last_known"],
                        "last_value": last_val}

        return bullet_info


# ================================================================
# AIPlayer —— 自动检测模型架构和维度
# ================================================================

class AIPlayer:
    """AI 玩家，自动检测 checkpoint 的维度/架构，加载对应编码器。

    用法:
        easy_ai = AIPlayer("checkpoints/model_50000.pt")
        medium_ai = AIPlayer("checkpoints/model_350000.pt")
    """

    def __init__(self, model_path: str):
        # ── 加载权重 ──
        state_dict = torch.load(model_path, map_location=DEVICE, weights_only=True)
        sd = state_dict.get("online_state_dict", state_dict)

        # ── 自动检测维度 ──
        ckpt_dim = sd["shared.0.weight"].shape[1]

        # ── 检测并转换瓶颈 ──
        has_bn = "value_stream.0.weight" in sd
        if has_bn:
            sd = _convert_weights_from_bottleneck(sd)

        # ── 选择编码器 ──
        if ckpt_dim == 72:
            self._is_72 = True
            self._encoder = StateEncoder72()
        else:
            self._is_72 = False
            self._encoder = StateEncoder69()

        # ── 构建/加载模型 ──
        self._model = DuelingDQN(ckpt_dim, ACTION_DIM, 256,
                                  use_bottleneck=False).to(DEVICE)
        self._model.load_state_dict(sd)
        self._model.eval()

        # ── 按游戏隔离的状态（多群聊共享同一 AIPlayer）──
        # 每个游戏独立维护子弹知识/装弹追踪/回合计数
        self._game_states: dict[int, dict] = {}
        # 实例变量在 play_turn 时 swap 为当前游戏状态
        self._bullet = None
        self._prev_magazine_id = None
        self._turn_action_count = 0

    @property
    def state_dim(self) -> int:
        return self._model.state_dim

    # ── 对外接口 ──

    def play_turn(self, game: Game, p: int) -> list[str]:
        """执行 AI 的整个回合，直到回合切换或终局。"""
        all_msgs: list[str] = []

        # ── 按游戏隔离状态（多群聊共享同一 AIPlayer）──
        gid = id(game)
        if gid not in self._game_states:
            self._game_states[gid] = {
                "bullet": BulletKnowledge(),
                "prev_magazine_id": None,
                "turn_action_count": 0,
            }
        gs = self._game_states[gid]

        # 将实例变量 swap 为当前游戏的状态（内部方法均通过 self.xxx 访问）
        saved_bullet = self._bullet
        saved_prev_mid = self._prev_magazine_id
        saved_turn_act = self._turn_action_count
        self._bullet = gs["bullet"]
        self._prev_magazine_id = gs["prev_magazine_id"]
        self._turn_action_count = gs["turn_action_count"]

        try:
            return self._play_turn_impl(game, p, all_msgs)
        finally:
            # 保存回 game state，恢复实例变量
            gs["prev_magazine_id"] = self._prev_magazine_id
            gs["turn_action_count"] = self._turn_action_count
            self._bullet = saved_bullet
            self._prev_magazine_id = saved_prev_mid
            self._turn_action_count = saved_turn_act

    def _play_turn_impl(self, game: Game, p: int, all_msgs: list[str]) -> list[str]:
        """play_turn 的实际逻辑（state 已 swap 到 self）。"""
        self._detect_reload(game, at_turn_start=True)
        self._turn_action_count = 0

        MAX_LOOP = 20
        for _ in range(MAX_LOOP):
            if game.game_stage == 2:
                break
            if game.turn != p:
                break

            extra_turn = min(self._turn_action_count / 10.0, 1.0)

            # 72 维模型的 genuine_extra_turn（布尔编码）
            genuine_extra = 0.0

            if self._is_72:
                bullet_info = self._encoder._apply_bullet_deductions(
                    game, self._bullet.for_player(p)
                )
                state_vec = self._encoder.encode(
                    game, p,
                    bullet_info=bullet_info,
                    extra_turn=extra_turn,
                    genuine_extra_turn=genuine_extra,
                )
                # 掩码：逻辑推断出已知下一发 → 禁用放大镜
                mask = self._encoder.action_mask(game, p)
                if bullet_info.get("next_known", False):
                    mag_idx = ITEM_ACTION_ORDER.index("放大镜")
                    mask[ACTION_ITEM_OFFSET + mag_idx] = False
            else:
                state_vec = self._encoder.encode(
                    game, p,
                    bullet_info=self._bullet.for_player(p),
                    extra_turn=extra_turn,
                )
                mask = self._encoder.action_mask(game, p)

            state_t = torch.from_numpy(state_vec).float().to(DEVICE)
            mask_t = torch.from_numpy(mask.copy()).bool().to(DEVICE)
            action = self._model.select_action(state_t, mask_t, epsilon=0.0)

            msgs = self._execute_action(game, p, action)
            all_msgs.extend(msgs)

            self._detect_reload(game)

            if game.game_stage != 2 and game.turn == p:
                self._turn_action_count += 1
            else:
                self._turn_action_count = 0

            if game.resolve_death():
                all_msgs.append(game.flush_msgs())
                if game.game_stage != 2:
                    game.switch_stage()
                    self._prev_magazine_id = None
                    self._detect_reload(game)
                    all_msgs.append(game.flush_msgs())
                continue

            if game.switch_turn_flag and game.death_state == -1:
                game.end_turn()
                all_msgs.append(game.flush_msgs())

            if game.switch_turn_flag:
                game.start_turn()
                all_msgs.append(game.flush_msgs())
                game.switch_turn_flag = False

        return all_msgs

    # ── 内部 ──

    def _execute_action(self, game: Game, p: int, action: int) -> list[str]:
        from roulette.roulette import ITEM_REGISTRY, ARTIFACT_REGISTRY

        if action == ACTION_SHOOT_SELF:
            game.shoot(p)
            self._on_shoot()
        elif action == ACTION_SHOOT_OPPONENT:
            game.shoot(1 - p)
            self._on_shoot()
        elif action == ACTION_HARDSHIP:
            for mode in game.modes:
                if mode.id == 11:
                    mode.action(game, p, "苦肉")
                    break
        elif action == ACTION_SKIP_TURN:
            for mode in game.modes:
                if mode.id == 13:
                    mode.action(game, p, "跳过回合")
                    break
        elif action >= ACTION_ARTIFACT_OFFSET:
            art_name = ARTIFACT_ORDER[action - ACTION_ARTIFACT_OFFSET]
            if 17 in game.mode_ids:
                artifact_cls = ARTIFACT_REGISTRY.get(art_name)
                if artifact_cls:
                    art = artifact_cls()
                    if art.item_check(game):
                        art.use(game, "")
        elif action >= ACTION_ITEM_OFFSET:
            item_name = ITEM_ACTION_ORDER[action - ACTION_ITEM_OFFSET]
            item_cls = ITEM_REGISTRY.get(item_name)
            if item_cls and item_name != "baba":
                item = item_cls()
                if item.item_check(game):
                    item.use(game, "")

            if item_name == "放大镜" and len(game.gun.magazine) > 0:
                self._bullet.mark_next(p, game.gun.check_next() or 0)
            elif item_name == "灌铅骰子":
                self._bullet.clear_all()
            elif item_name == "生死逆转":
                self._bullet.flip()
        else:
            return [""]

        return [game.flush_msgs()]

    def _on_shoot(self):
        """Bug 修复：开枪后清掉**所有**玩家的下一发知识。
        因为"下一发"是弹夹的客观属性，无论谁开枪都被消耗。
        """
        self._bullet.clear_next(None)

    def _detect_reload(self, game: Game, at_turn_start: bool = False):
        """Bug 修复：用 id() 追踪弹夹对象检测重装。
        gun.reload() 创建新 list → id 变化；
        gun.fire() 原地 pop → id 不变。

        at_turn_start=True 表示在回合开始时调用，此时检测到的重装
        发生在对手回合（回合已翻转），mode 12 的非回合玩家需反向计算。
        """
        current_id = id(game.gun.magazine)
        if self._prev_magazine_id is None:
            was_reload = True
            # 回合开始时首次检测：total_turns>=2 说明对手已行动过，回合已翻转
            turn_flipped = at_turn_start and game.total_turns >= 2
        else:
            was_reload = current_id != self._prev_magazine_id
            # 回合开始时检测到 id 变化 → 重装发生在对手回合
            turn_flipped = at_turn_start and was_reload
        self._prev_magazine_id = current_id

        if was_reload:
            self._bullet.clear_all()
            if 12 in game.mode_ids:
                if turn_flipped:
                    # 当前回合玩家在重装时是非回合玩家 → 他应获得知识
                    non_turn = game.turn
                else:
                    non_turn = 1 - game.turn
                self._bullet.mark_last(non_turn, game.gun.check_last() or 0)
