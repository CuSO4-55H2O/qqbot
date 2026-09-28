import asyncio
import random
import time
from . import database as db
from .constant import *
from copy import deepcopy
from typing import Any


ITEM_REGISTRY = {} # type:dict[str,type]
MODE_REGISTRY = {} # type:dict[int,type]
ARTIFACT_REGISTRY = {} # type: dict[str, type]

ACTION_TO_ITEM = {
    2: ITEM_MAGNIFYING_GLASS, 3: ITEM_KNIFE, 4: ITEM_DICE,
    5: ITEM_CIGARETTE, 6: ITEM_HANDCUFFS, 7: ITEM_BOMB,
    8: ITEM_FLIP, 9: ITEM_LOATHEB, 10: ITEM_HIGH_NOON
}

def register_item(cls):
    ITEM_REGISTRY[cls.name] = cls
    return cls

def register_mode(cls):
    cls.name = ALL_MODES[cls.id]  # 从常量字典获取名称
    cls.cmd = MODE_CMDS.get(cls.id, [])  # 获取指令列表，默认为空
    MODE_REGISTRY[cls.id] = cls
    return cls

def register_artifact(cls):
    ARTIFACT_REGISTRY[cls.name] = cls
    return cls

class Player:
    def __init__(self):
        self.hp=0 # type:int
        self.point=0 # type:int
        self.nickname='' # type:str
        self.user_id=0 # type:int

        self.condition=dict.fromkeys(ALL_CONDITIONS,False) # type:dict[str,bool]
        self.item = dict.fromkeys(TOTAL_ITEM_POOL, 0)  # type:dict[str,int]
        self.artifacts=dict.fromkeys(ALL_ARTIFACT, 0)  # type:dict[str,int]

    def item_clear(self):
        for i in TOTAL_ITEM_POOL:
            if i==ITEM_DEATH_PROOF:
                self.point+=self.item[i]*45
            else:
                self.point += self.item[i]*15
            self.item[i]=0

    def show_items(self)->str:
        text = ''
        if self.count_items() != 0:
            text += f'{self.nickname}现在拥有以下道具'
            for i in self.item:
                if self.item[i] != 0:
                    text += '，' + i + '*' + str(self.item[i])
            text+='。'
        return text

    def count_items(self)->int:
        total_item = 0
        for i in self.item:
            total_item += self.item[i]
        return total_item

    def cal_shoot_point(self,game:'Game',ctx:dict[str,Any]):
        if ctx[TARGET]==game.turn and not ctx[IS_LIVE]:
            self.point+=10
        elif ctx[TARGET]!=game.turn and ctx[IS_LIVE]:
            self.point+=6

    def alive(self):
        return self.hp>0

class Gun:
    def __init__(self):
        self.magazine=[] # type:list[int]

    def fire(self)->int:
        return self.magazine.pop(0)

    def check_next(self)->int:
        if len(self.magazine)>0:
            return self.magazine[0]

    def check_last(self)->int:
        if len(self.magazine)>0:
            return self.magazine[-1]

    def reload(self,live_count:int,total_count:int)->str:
        magazine=[1]*live_count+[0]*(total_count-live_count)
        random.shuffle(magazine)
        self.magazine=magazine
        text = f'装弹！装入了{live_count}颗实弹，{total_count - live_count}颗空弹。'
        return text

    def total(self):
        return sum(self.magazine)

    def get_blank_num(self):
        return self.magazine.count(0)

    def flip(self):
        for i in range(len(self.magazine)):
            self.magazine[i]=1-self.magazine[i]

    def get_live_num(self):
        return self.magazine.count(1)

class Item:
    name=None # type:str
    def use(self,game:'Game',extra_information):
        raise NotImplementedError

    def reduce(self,game:'Game',p:int):
        player = game.players[p]
        if player.item[self.name]>=1:
            player.item[self.name]-=1
        else:
            player.item[ITEM_DEATH_PROOF]-=1

    def item_check(self,game:'Game')->bool:
        player = game.players[game.turn]
        if player.condition[CONDITION_LOATHEB]:
            return False
        return self.item_exist(game)

    def item_exist(self,game:'Game')->bool:
        player = game.players[game.turn]
        if player.item[self.name] >= 1 or player.item[ITEM_DEATH_PROOF]>=1:
            return True
        return False


    def use_msg(self,game:'Game',flag:bool):
        player = game.players[game.turn]
        if flag:
            game.text.append(f'{player.nickname}使用了{self.name}。')
        else:
            game.text.append(f'无法使用。')

class Artifact(Item):
    name = None  # type: str

    def item_check(self, game: 'Game') -> bool:
        player = game.players[game.turn]
        if player.artifacts.get(self.name, 0) >= 1:
            return True
        return False

    def reduce(self, game: 'Game', p: int):
        player = game.players[p]
        player.artifacts[self.name] -= 1

    # 可以重写 use_msg，加上华丽的神器特效文字
    def use_msg(self, game: 'Game', flag: bool):
        player = game.players[game.turn]
        if flag:
            game.text.append(f'🌌 【上古神器】降临！{player.nickname} 释放了 【{self.name}】 的力量！')
        else:
            game.text.append(f'神器的力量并没有响应（无法使用）。')

@register_item
class Knife(Item):
    """
    刀：如果下一发子弹是实弹，它的伤害+1。
    """
    name = ITEM_KNIFE
    def use(self,game:'Game',extra_information):
        player=game.players[game.turn]
        if not player.condition[CONDITION_KNIFE]:
            player.condition[CONDITION_KNIFE]=True
            self.reduce(game,game.turn)
            self.use_msg(game,True)
        else:
            self.use_msg(game, False)

@register_item
class Dice(Item):
    """
    灌铅骰子：重新装弹。如果你没有其他道具，随机获取一个。
    """
    name = ITEM_DICE
    def use(self,game:'Game',extra_information):
        player=game.players[game.turn]
        self.reduce(game,game.turn)
        self.use_msg(game,True)
        if all(v == 0 for v in player.item.values()):
            game.give_item(game.turn,1)
            game.text.append(f'{player.nickname}获得了一个道具。{player.show_items()}')
        game.game_reload()

@register_item
class Cigarette(Item):
    """
    烟：如果你的生命值低于对手，恢复一点生命值
    """
    name = ITEM_CIGARETTE
    def use(self,game:'Game',extra_information):
        self.use_msg(game,True)
        if game.players[game.turn].hp<game.players[1-game.turn].hp:
            game.heal(game.turn,1)
        else:
            game.text.append('不满足使用条件。')
        self.reduce(game,game.turn)

@register_item
class MagnifyingGlass(Item):
    """
    放大镜：显示下一颗子弹。
    """
    name = ITEM_MAGNIFYING_GLASS
    def use(self,game:'Game',extra_information):
        self.reduce(game,game.turn)
        self.use_msg(game,True)
    def use_msg(self,game:'Game',flag:bool):
        player = game.players[game.turn]
        game.text.append(f'{player.nickname}使用了{self.name}。')
        game.add_private_text(game.players[game.turn].user_id,
                              f'【放大镜】你看到了下一颗子弹是{VALUE_TO_BULLET[game.gun.check_next()]}。')

@register_item
class Handcuffs(Item):
    """
    手铐：下一次向对手射击不会结束你的回合。如果向自己发射实弹，该效果失效。
    """
    name = ITEM_HANDCUFFS
    def use(self,game:'Game',extra_information):
        player = game.players[game.turn]
        if not player.condition[CONDITION_HANDCUFFS]:
            player.condition[CONDITION_HANDCUFFS] = True
            self.reduce(game,game.turn)
            self.use_msg(game, True)
        else:
            self.use_msg(game, False)

@register_item
class Bomb(Item):
    """
    炸药：造成一点伤害，结束你的回合。
    """
    name = ITEM_BOMB
    def use(self,game:'Game',extra_information):
        game.switch_turn_flag=True
        self.use_msg(game,True)
        game.apply_damage(1-game.turn,1)
        self.reduce(game,game.turn)

@register_item
class Loatheb(Item):
    """
    洛欧塞布：对手下回合无法使用道具。
    """
    name = ITEM_LOATHEB
    def use(self,game:'Game',extra_information):
        game.players[1-game.turn].condition[CONDITION_LOATHEB]=True
        self.use_msg(game,True)
        self.reduce(game,game.turn)

@register_item
class Baba(Item):
    """
    baba：添加一个还没有的模式。（指令：【使用baba#（数字）】）
    """
    name = ITEM_BABA
    def use(self,game:'Game',extra_information):
        try:
            mode_id=int(extra_information)
            if mode_id in MODE_REGISTRY:
                if mode_id not in game.mode_ids:
                    self.reduce(game,game.turn)
                    game.mode_ids.append(mode_id)
                    mode=MODE_REGISTRY[mode_id]()
                    game.modes.append(mode)
                    game.text.append(f'已使用baba，添加模式{mode.name}。')
                    mode.game_start(game)
                else:
                    game.text.append('已存在该模式。')
            else:
                game.text.append('未找到对应模式。')
        except ValueError:
            game.text.append('指令格式错误。')

@register_item
class HighMoon(Item):
    """
    午时已到：双方的生命值设定为1，重新装弹，失去所有道具。
    """
    name = ITEM_HIGH_NOON
    def use(self,game:'Game',extra_information):
        self.reduce(game,game.turn)
        self.use_msg(game,True)
        p1=game.players[0]
        p2=game.players[1]
        game.game_reload()
        p1.item = dict.fromkeys(TOTAL_ITEM_POOL, 0)
        p2.item=dict.fromkeys(TOTAL_ITEM_POOL, 0)
        p1.hp=1
        p2.hp=1
        game.show_hp_flag=True

    def use_msg(self,game:'Game',flag:bool):
        game.text.append('It`s high moon.')

@register_item
class Flip(Item):
    """
    生死逆转：枪中所有子弹效果翻转。
    """
    name=ITEM_FLIP
    def use(self,game:'Game',extra_information):
        game.gun.flip()
        self.use_msg(game,True)
        self.reduce(game,game.turn)

@register_artifact
class HandOfWoking(Artifact):
    name = ARTIFACT_HAND_OF_WOKING
    def use(self,game:'Game',extra_information):
        self.reduce(game, game.turn)
        self.use_msg(game, True)

        p1 = game.players[0]
        p2 = game.players[1]
        old_p1_hp = p1.hp
        p1.hp = p2.hp
        p2.hp = old_p1_hp

        game.text.append('"生命，就像这流沙，在我手中翻转……"')
        game.text.append(f'两股神秘的力量发生碰撞，{p1.nickname} 和 {p2.nickname} 的生命轨迹互换了！')

        game.show_hp_flag = True

@register_artifact
class Recklessness(Artifact):
    name = ARTIFACT_RECKLESSNESS
    def use(self,game:'Game',extra_information):
        self.reduce(game,game.turn)
        self.use_msg(game,True)
        player=game.players[game.turn]

        game.give_item(game.turn,6)

        game.text.append('"管他什么千层套路，老夫今天就是要大力出奇迹！"')
        game.text.append(f'伴随着一阵狂躁的轰鸣声，虚空中裂开一道大口子，整整六件道具'
                         f'如同狂风暴雨般砸进了 {player.nickname} 的怀里！')
        game.text.append(player.show_items())

@register_artifact
class TidiedTeaSet(Artifact):
    name = ARTIFACT_TIDIED_TEA_SET
    def use(self,game:'Game',extra_information):
        self.reduce(game,game.turn)
        self.use_msg(game,True)

        player=game.players[game.turn]
        player.item[ITEM_DEATH_PROOF]+=3

        game.text.append('"先别急着开枪，不如坐下来喝口茶吧……如果你不介意这是一杯断头茶的话。"')
        game.text.append(
            f'优雅的瓷器碰撞声在死寂的房间里回荡，{player.nickname} 掀开茶碗，赫然发现底下压着三张【死亡证明】！')
        game.text.append(player.show_items())

class Mode:
    id=None # type:int
    name=None # type:str
    cmd=None # type:str
    def __init__(self):
        pass

    def format_mode_effect(self,effect:str)->str:
        return f'受【{self.name}】影响，{effect}'

    def add_to_text(self,game:'Game',effect:str):
        game.text.append(self.format_mode_effect(effect))

    def action(self,game:'Game',p:int,command:str)->bool:
        return False

    def game_start(self,game:'Game'):
        pass

    def stage_start(self,game:'Game'):
        pass

    def after_reload(self,game:'Game'):
        pass

    def before_shoot(self,game:'Game',ctx:dict[str,Any])->dict[str,Any]:
        return ctx

    def after_shoot(self,game:'Game',ctx:dict[str,Any])->dict[str,Any]:
        return ctx

    def turn_start(self,game:'Game'):
        pass

    def turn_end(self,game:'Game'):
        pass

    def settle_score(self,game:'Game',ctx:dict[str,float])->dict[str,float]:
        return ctx

@register_mode
class WesternShowdown(Mode):
    """
    #1【西部对决】回合开始时不再发放道具。
    """
    id=1
    
    def stage_start(self,game:'Game'):
        game.give_item_num=0
        self.add_to_text(game,'本阶段回合开始时不发放道具。')

@register_mode
class RareTreasures(Mode):
    """
    #2【奇珍异宝】道具获得扩展。
    """
    id=2
    
    def game_start(self,game:'Game'):
        game.item_pool=TREASURE_ITEM_POOL
        game.item_probability=TREASURE_ITEM_PROBABILITY
        self.add_to_text(game,'道具池变为特殊道具池。')

@register_mode
class FinalDuel(Mode):
    """
    #3【一决胜负】只有第三阶段。
    """
    id=3
    
    def game_start(self,game:'Game'):
        game.stage=2
        self.add_to_text(game,'只有第三阶段。')

    def settle_score(self,game:'Game',ctx:dict[str,float]) ->dict[str,float]:
        ctx[MULTIPLIER_ADDEND]+=0.75
        return ctx

@register_mode
class AllIn(Mode):
    """
    #4【孤注一掷】结算时，输赢为3倍。
    """
    id=4
    
    def settle_score(self,game:'Game',ctx:dict[str,float]) ->dict[str,float]:
        ctx[MULTIPLIER_FACTOR]*=3
        return ctx

@register_mode
class WheelOfFortune(Mode):
    """
    #5【命运之轮】实弹有15%概率造成双倍伤害。
    """
    id=5
    
    def before_shoot(self,game:'Game',ctx:dict[str,Any]) ->dict[str,Any]:
        if random.randint(1,100)<=15 and ctx[IS_LIVE]:
            ctx[DAMAGE]*=2
            self.add_to_text(game,'子弹伤害翻倍。')
        return ctx

@register_mode
class MuddyWater(Mode):
    """
    #6【浑水摸鱼】玩家有20%概率向错误方向开枪。
    """
    id=6
    
    def before_shoot(self,game:'Game',ctx:dict[str,Any]) ->dict[str,Any]:
        if random.randint(1,100)<=20:
            ctx[TARGET]=1-ctx[TARGET]
            self.add_to_text(game,f'射击方向错了，实际打中{game.players[ctx[TARGET]].nickname}。')
        return ctx

    def settle_score(self,game:'Game',ctx:dict[str,float]) ->dict[str,float]:
        ctx[MULTIPLIER_FACTOR]*=0.3
        return ctx

@register_mode
class DesperateCounter(Mode):
    """
    #7【绝地反击】向自己发射空弹后对对手造成一点伤害。
    """
    id=7
    
    def after_shoot(self,game:'Game',ctx:dict[str,Any]) ->dict[str,Any]:
        if ctx[TARGET]==game.turn and not ctx[IS_LIVE]:
            self.add_to_text(game,'')
            game.apply_damage(1-ctx[TARGET],1)
        return ctx

@register_mode
class LateComer(Mode):
    """
    #8【后发制人】后手玩家在1/2/3阶段开始时获得1/1/2个道具。
    """
    id=8
    
    def stage_start(self,game:'Game'):
        p=1-game.turn
        player=game.players[p]
        game.give_item(p,LATECOMER_ITEM_NUM[game.stage])
        self.add_to_text(game,f'{player.nickname}获得了{LATECOMER_ITEM_NUM[game.stage]}个道具'
                              f'。{player.show_items()}')

@register_mode
class Momentum(Mode):
    """
    #9【乘胜追击】向对手发射实弹后获得一个道具。
    """
    id=9
    
    def after_shoot(self,game:'Game',ctx:dict[str,Any]) ->dict[str,Any]:
        if ctx[TARGET]!=game.turn and ctx[IS_LIVE]:
            player = game.players[game.turn]
            game.give_item(game.turn, 1)
            self.add_to_text(game, f'{player.nickname}获得了1个道具。{player.show_items()}')
        return ctx

@register_mode
class ProtractedWar(Mode):
    """
    #10【旷日持久】每个阶段最大生命值额外增加1点。
    """
    id=10
    
    def stage_start(self,game:'Game'):
        self.add_to_text(game,'最大生命值+1。')
        game.max_hp+=1

@register_mode
class LifeTap(Mode):
    """
    #11【生命分流】扣除一点生命值以获得一个道具。（指令：【苦肉】）
    """
    id=11

    def action(self,game:'Game',p:int,command:str) ->bool:
        if command==self.cmd[0]:
            player = game.players[game.turn]
            game.give_item(game.turn,1)
            self.add_to_text(game, player.show_items())
            game.apply_damage(game.turn, 1)
            return True
        return False
    def add_to_text(self,game:'Game',effect:str):
        player=game.players[game.turn]
        game.text.append(f'{player.nickname}使用了【苦肉】，获得了一个道具。{effect}')

@register_mode
class SkipTurn(Mode):
    """
    #13【以逸待劳】跳过你的回合以获得一个道具，不能连续两回合使用。（指令：【跳过回合】）
    """
    id=13
    

    def __init__(self):
        super().__init__()
        self.last_skip_used = [False, False]  # 分别记录两个玩家上一回合是否跳过了
        self.skip_used_this_turn = [False, False]  # 本回合是否使用了跳过

    def turn_start(self, game):
        idx = game.turn
        # 重置本回合跳过标记
        self.skip_used_this_turn[idx] = False
        return None

    def turn_end(self, game):
        idx = game.turn
        # 更新 last_skip_used 为本回合是否使用了跳过
        self.last_skip_used[idx] = self.skip_used_this_turn[idx]

    def action(self,game:'Game',p:int,command:str) ->bool:
        if command == self.cmd[0]:
            p=game.turn
            if self.last_skip_used[p]:
                game.text.append(self.format_mode_effect("不能连续两回合使用跳过。"))
                return True
            # 执行跳过逻辑：获得道具，切换回合
            game.give_item(p, 1)
            self.skip_used_this_turn[p] = True
            game.switch_turn_flag=True
            game.text.append(f"{game.players[p].nickname} 跳过回合，获得一个道具。{game.players[game.turn]
                             .show_items()}")
            return True
        return False

@register_mode
class LightLoad(Mode):
    """
    #14【轻装上阵】最多同时拥有三个道具。
    """
    id=14
    
    def stage_start(self,game:'Game'):
        game.max_item_num=3
        self.add_to_text(game,'最大道具数量为3。')

@register_mode
class LuckyDice(Mode):
    """
    #15【好运当骰】每回合可以选择重置一个道具。（指令：【重置（道具名）】）
    """
    id=15
    

    def __init__(self):
        super().__init__()
        self.reset=[False,False]

    def turn_end(self,game:'Game'):
        self.reset = [False, False]

    def stage_start(self,game:'Game'):
        self.reset = [False, False]

    def action(self,game:'Game',p:int,command:str):
        if command.startswith(self.cmd[0]):
            item_name=command[2:]
            if self.reset[p]:
                game.text.append('本回合已重置过。')
            elif item_name in ITEM_REGISTRY:
                item=ITEM_REGISTRY[item_name]()
                if item.item_exist(game):
                    player=game.players[game.turn]
                    item.reduce(game,p)
                    game.give_item(p,1)
                    game.text.append(f'{player.nickname}重置了{item_name}。'+player.show_items())
                    self.reset[p] = True
                else:
                    game.text.append('你没有这个道具。')
            else:
                game.text.append('未知道具。')
            return True
        return False

@register_mode
class DeathTimer(Mode):
    """
    #16【死亡计时】在第1/2/3阶段开始6/10/14个回合后消灭生命值较低的玩家。
    """
    id=16
    

    def turn_end(self, game: 'Game'):
        if game.stage not in DEATH_TIMER_LIMIT:
            return

        if game.cur_turns != DEATH_TIMER_LIMIT[game.stage]:
            return

        p1 = game.players[0]
        p2 = game.players[1]
        self.add_to_text(game,'死亡计时已到。')
        if p1.hp == p2.hp:
            game.apply_damage(0,999)
            game.apply_damage(1, 999)
        elif p1.hp > p2.hp:
            game.apply_damage(1,999)
        else:
            game.apply_damage(0,999)

@register_mode
class AncientArtifact(Mode):
    """
    #17【上古神器】对战开始时，随机获得一件神器。（指令：【使用（神器名）】）
    """
    id=17
    def game_start(self,game:'Game'):
        game.give_artifact(0,1)
        game.give_artifact(1, 1)

@register_mode
class FinalFlare(Mode):
    """
    #18【回光返照】生命值翻倍，每当回合结束时受到1点伤害。
    """
    id=18
    
    def stage_start(self,game:'Game'):
        game.max_hp*=2
        self.add_to_text(game,'最大生命值翻倍。')
    def turn_end(self,game:'Game'):
        self.add_to_text(game, '')
        game.apply_damage(game.turn,1)
        game.show_hp_flag=True

@register_mode
class Foresight(Mode):
    """
    #19【洞悉先机】装弹时非当前回合的玩家得知当前弹夹最后一颗子弹的内容。
    """
    id=12
    def after_reload(self,game:'Game'):
        game.add_private_text(game.players[1-game.turn].user_id,
                              f'【洞悉先机】你看到了最后一颗子弹是{VALUE_TO_BULLET[game.gun.check_last()]}。')

@register_mode
class ChangingTides(Mode):
    """
    #100【风云变幻】对局开始时，随机选择2-5个模式替换本局模式。
    """
    id=100
    
    def settle_score(self,game:'Game',ctx:dict[str,float]) ->dict[str,float]:
        ctx[MULTIPLIER_FACTOR]*=0.6
        return ctx

class Game:
    def __init__(self,group_id:int):
        self.group_id = group_id  # type:int


        self.players=[Player(),Player()] # type:list[Player]
        self.turn=random.randint(0,1) # type:int
        self.time=0 # type:int
        self.stage=0 # type:int
        self.gun=Gun() # type:Gun
        self.total_turns=0 # type:int
        self.cur_turns=0 # type:int
        self.mode_ids=[] # type:list[int]
        self.modes=[] # type:list[Mode]
        self.give_item_num=-1 # type:int
        self.item_pool=[] # type:list[str]
        self.item_probability=[] # type:list[int]
        self.max_item_num=-1 # type:int
        self.bullet_config={FULL_BULLET:0,MIN_LIVE_BULLET:0,MAX_LIVE_BULLET:0} # type:dict[str,int]
        self.switch_turn_flag=False # type:bool
        self.switch_stage_flag=False # type:bool
        self.max_hp=-1 # type:int
        self.text=[] # type:list[str]
        self.loser=self.turn # type:int
        self.score=[0,0] # type:list[int]
        self.show_hp_flag=False # type:bool
        self.death_state=-1 # type:int
        self.game_stage=GAME_STAGE_CHOOSE_MODES # type:int
        self.private_msgs = []  # type: list[tuple[int, str]]
        self.final_score=0 # type:float

    def reset(self):
        self.__init__(self.group_id)

    def join(self,user_id:int,nickname:str)->str:
        for player in self.players:
            if player.user_id==user_id:
                self.text.append('你已加入，请勿重复操作。')
                return self.flush_msgs()
        for player in self.players:
            if player.user_id==0:
                player.user_id=user_id
                player.nickname=nickname
                self.text.append('加入成功。')
                break
        else:
            self.text.append('游戏人数已满。')
        return self.flush_msgs()

    def quit(self,user_id:int)->str:
        for player in self.players:
            if player.user_id==user_id:
                self.text.append('退出成功。')
                player.user_id=0
                return self.flush_msgs()
        else:
            self.text.append('你还没有加入游戏。')
            return self.flush_msgs()

    def verity(self)->bool:
        for i in self.players:
            if i.user_id==0:
                return False
        return True

    def revise_mode(self,user_id,message:str):
        for player in self.players:
            if player.user_id==user_id:
                break
        else:
            self.text.append('你还没有加入游戏。')
            return self.flush_msgs()
        mode_ids=message[3:].replace('，',',').split(',')
        temp_ids=deepcopy(self.mode_ids)
        for mode_id in mode_ids:
            try:
                mode_id=int(mode_id)
                if mode_id in MODE_REGISTRY:
                    if mode_id not in self.mode_ids:
                        self.mode_ids.append(mode_id)
                    else:
                        self.mode_ids.remove(mode_id)
                        self.text.append('已移除模式。')
                        return self.flush_msgs()
            except ValueError:
                self.text.append('指令格式错误。')
                self.mode_ids = temp_ids
                return self.flush_msgs()
        else:
            self.text.append('已添加模式。')
            return self.flush_msgs()

    def _call_modes(self, method_name:str):
        for mode in self.modes:
            getattr(mode, method_name)(self)

    def _call_modes_ctx(self,method_name:str,ctx:dict[str,Any]):
        for mode in self.modes:
            ctx= getattr(mode, method_name)(self,ctx)
        return ctx

    def apply_shoot_effects(self,ctx:dict[str,Any]):
        text=''
        player=self.players[self.turn]

        if player.condition[CONDITION_KNIFE] and ctx[IS_LIVE]:
            ctx[DAMAGE]+=1
            text+='受【刀】影响，伤害+1。'
        if self.turn==ctx[TARGET] and ctx[IS_LIVE] and player.condition[CONDITION_HANDCUFFS]:
            player.condition[CONDITION_HANDCUFFS]=False
            text+=f'由于{player.nickname}向自己开枪且为实弹，【手铐】已失效。'
        if ((self.turn!=ctx[TARGET] or self.turn==ctx[TARGET] and ctx[IS_LIVE])
                and player.condition[CONDITION_HANDCUFFS]):
            player.condition[CONDITION_HANDCUFFS]=False
            text+=f'受【手铐】影响，仍然是{player.nickname}的回合。'
            self.switch_turn_flag=False
        player.condition[CONDITION_KNIFE] = False

        if text!='':
            self.text.append(text)
        return ctx

    def shoot(self,target:int):
        player=self.players[self.turn]
        bullet=self.gun.fire()
        self.text.append(f'{self.players[self.turn].nickname}向{self.players[target].nickname}射击。是{VALUE_TO_BULLET[bullet]}。')
        self.switch_turn_flag=True
        ctx = {
            TARGET: target,
            DAMAGE: bullet,
            IS_LIVE: bullet!=0
        } # type:dict[str,Any]

        ctx=self.apply_shoot_effects(ctx)
        ctx=self._call_modes_ctx('before_shoot',ctx)
        player.cal_shoot_point(self,ctx)

        if self.turn==ctx[TARGET] and not ctx[IS_LIVE]:
            self.switch_turn_flag=False

        self.apply_damage(ctx[TARGET],ctx[DAMAGE])
        if self.death_state!=-1:
            return

        self._call_modes_ctx('after_shoot',ctx)

        if self.death_state!=-1:
            return

        if self.gun.total()!=0:
            self.text.append(f'弹夹中还有{self.gun.get_live_num()}颗实弹，{self.gun.get_blank_num()}颗空弹。')
        else:
            self.game_reload()

    def take_damage(self,target:int,dmg:int):
        player=self.players[target]
        player.hp-=dmg
        text=f'{player.nickname}受到了{dmg}点伤害{'！' if dmg >= 2 else '。'}'
        self.text.append(text)
        if dmg!=0:
            self.show_hp_flag=True

    def heal(self,target:int,amount:int):
        player = self.players[target]
        if self.stage == 3 and player.hp <= 4:
            self.text.append(f"{player.nickname}当前生命值过低，无法恢复。")
            return
        old_hp = player.hp
        player.hp = min(player.hp + amount, self.max_hp)  # 不超过阶段最大生命值
        healed = player.hp - old_hp
        if healed > 0:
            self.text.append(f"{player.nickname}恢复了{healed}点生命值{'！' if healed >= 2 else '。'}")
            self.show_hp_flag = True

    def resolve_death(self):
        """
        在任何可能改变状态的地方调用（伤害/回血/回合结束/道具等）
        """
        # --- 死亡 ---
        if self.death_state != -1:
            if self.death_state == 2:
                self.text.append("双方同时死亡，本阶段重赛。")
                self.stage -= 1
            else:
                dead = self.death_state
                winner = 1 - dead
                self.text.append(f"{self.players[dead].nickname}死亡！")
                self.score[winner] += 1
                self.loser = dead
                self.switch_stage_flag=True

            if 2 in self.score or self.stage >= 3:
                self.finalize_game()

            return True  # 表示"流程终止"

        return False

    def show_hp(self):
        p1=self.players[0]
        p2=self.players[1]
        text=f'当前生命值：{p1.nickname}：{p1.hp}  {p2.nickname}：{p2.hp}'
        self.text.append(text)
        self.show_hp_flag=False

    def game_reload(self):
        live_bullet=random.randint(self.bullet_config[MIN_LIVE_BULLET],
                                   self.bullet_config[MAX_LIVE_BULLET])+self.cur_turns//5
        self.text.append(self.gun.reload(live_bullet,
                                         self.bullet_config[FULL_BULLET]+self.cur_turns//3))
        self._call_modes('after_reload')

    def apply_damage(self,target,dmg):
        self.take_damage(target, dmg)
        if not self.players[0].alive() and not self.players[1].alive():
            self.death_state = 2
        elif not self.players[target].alive():
            self.death_state = target
        else:
            self.death_state = -1

    def game_start(self):
        self.game_stage=GAME_STAGE_MAIN_PART
        self.time=time.time()

        if 100 in self.mode_ids:
            self.text.append("【风云变幻】发动！正在重组本局规则...")
            available_ids = [m_id for m_id in MODE_REGISTRY.keys() if m_id != 100]

            count = random.randint(2, 5)
            new_mode_ids = random.sample(available_ids, min(count, len(available_ids)))

            self.mode_ids = new_mode_ids+[100]
            self.modes = [MODE_REGISTRY[m_id]() for m_id in new_mode_ids]

            names = [ALL_MODES[m_id] for m_id in new_mode_ids]
            self.text.append(f"本局模式已替换为：{'、'.join(names)}")
            self.modes.append(MODE_REGISTRY[100]())
        else:
            self.modes = [MODE_REGISTRY[m_id]() for m_id in self.mode_ids]
            names = [ALL_MODES[m_id] for m_id in self.mode_ids]
            self.text.append(f"本局模式为：{'、'.join(names)}")

        self.item_pool = ITEM_POOL
        self.item_probability=ITEM_PROBABILITY
        self.max_item_num=MAX_ITEM_NUM

        self._call_modes('game_start')

        self.switch_stage()

    def start_turn(self):
        self.cur_turns += 1
        self.total_turns += 1
        player=self.players[self.turn]
        self.text.append(f'当前是第{self.cur_turns}回合（共{self.total_turns}回合）。轮到{player.nickname}行动。')
        if self.give_item_num!=0:
            self.give_item(self.turn, self.give_item_num)
            self.text.append(player.show_items())

        self._call_modes('turn_start')

    def end_turn(self):
        self._call_modes('turn_end')
        self.players[self.turn].condition=dict.fromkeys(ALL_CONDITIONS,False)
        if self.show_hp_flag:
            self.show_hp()
        self.turn = 1 - self.turn

    def switch_stage(self):
        self.stage+=1
        self.death_state=-1
        self.cur_turns =0

        self.players[0].item_clear()
        self.players[1].item_clear()

        description_text={1: '无道具。', 2: '每回合获得一个道具。', 3:
            '每回合获得两个道具，当生命值小于或等于4时，无法恢复生命值。'}
        self.text.append(f'当前是第{self.stage}阶段，{description_text[self.stage]}')

        self.give_item_num = ITEM_NUM[self.stage]
        self.show_hp_flag=False

        self.bullet_config[FULL_BULLET]=BULLET_FULL_COUNT[self.stage]
        self.bullet_config[MIN_LIVE_BULLET]=MIN_BULLET[self.stage]
        self.bullet_config[MAX_LIVE_BULLET]=MAX_BULLET[self.stage]

        self.switch_turn_flag=False
        self.switch_stage_flag=False

        self.max_hp=MAX_HP[self.stage]
        if self.stage!=1:
            self.turn=self.loser

        self._call_modes('stage_start')

        self.text.append(f'每个玩家有{self.max_hp}点生命值。')
        self.players[0].hp=self.max_hp
        self.players[1].hp=self.max_hp

        self.game_reload()
        self.start_turn()

    def give_item(self,p:int,num:int):
        for i in range(num):
            if self.players[p].count_items()<self.max_item_num:
                item_name=random.choices(self.item_pool,weights=self.item_probability,k=1)[0]
                self.players[p].item[item_name]+=1

    def give_artifact(self,p:int,num:int):
        for i in range(num):
            player=self.players[p]
            artifact_name = random.choices(ALL_ARTIFACT, weights=[1]*len(ALL_ARTIFACT), k=1)[0]
            self.players[p].artifacts[artifact_name] += 1
            self.add_private_text(player.user_id, f"你在本局对战中获得了神器：{artifact_name}！")

    def post_action_check(self) -> list[str]:
        msgs = []

        # 阶段 3：检查切换回合
        if self.switch_turn_flag and self.death_state==-1:
            # A. 执行回合结束逻辑 (包含钩子和血量显示)
            self.end_turn()
            msgs.append(self.flush_msgs())

        if self.resolve_death():
            msgs.append(self.flush_msgs())
            if self.game_stage != GAME_STAGE_END:
                self.switch_stage()  # 内部包含 reload 和 start_turn
                msgs.append(self.flush_msgs())  # 这是第二段：新阶段提示

            return msgs  # 流程终止

        if self.switch_turn_flag:

            # B. 执行回合开始逻辑
            self.start_turn()
            msgs.append(self.flush_msgs())

            self.switch_turn_flag = False
        else:
            # 如果不换回合（如向自己开空枪），直接发出当前积压消息
            final = self.flush_msgs()
            if final: msgs.append(final)

        return msgs

    def get_player_index(self,user_id:int)->int:
        if user_id==self.players[0].user_id:
            return 0
        elif user_id == self.players[1].user_id:
            return 1
        else:
            return -1

    def add_private_text(self, user_id: int, msg: str):
        self.private_msgs.append((user_id, msg))

    def flush_private_msgs(self) -> list[tuple[int, str]]:
        msgs = self.private_msgs.copy()
        self.private_msgs = []
        return msgs

    def flush_msgs(self)->str:
        if type(self.text)==list:
            text='\n'.join(self.text)
            self.text=[]
            text+='\n'
            return text
        return ''


    def finalize_game(self):
        self.game_stage=GAME_STAGE_END
        winner=self.players[1-self.loser]
        loser=self.players[self.loser]
        ctx={
            MULTIPLIER_FACTOR:1,
            MULTIPLIER_ADDEND:0,
            POINT_NAME:BACE_POINT
        } # type:dict[str,Any]
        ctx=self._call_modes_ctx('settle_score',ctx)
        if self.stage==2:
            ctx[MULTIPLIER_ADDEND]+=0.5
        if self.stage==1:
            ctx[MULTIPLIER_FACTOR]*=10
        if self.total_turns<=10:
            ctx[MULTIPLIER_ADDEND]+=0.75
        final_point=ctx[POINT_NAME]+winner.point
        final_multiplier=(BACE_MULTIPLIER+ctx[MULTIPLIER_ADDEND])*ctx[MULTIPLIER_FACTOR]
        final_score=round(final_point*final_multiplier,2)
        self.final_score=final_score
        last_time=time.time()-self.time
        names = [ALL_MODES[m_id] for m_id in self.mode_ids]
        mode_text=f"模式：{'、'.join(names)}"
        self.text.append(f'游戏结束。{mode_text}\n'
                         f'分数：{final_point}，倍数：{final_multiplier}\n'
                         f'{winner.nickname}从{loser.nickname}赢得了{final_score}铸币！\n'
                         f'总时长：{round(last_time//60)}分{round(last_time%60)}秒。回合数：{self.total_turns}')

class CommandHandler:
    def __init__(self, game: 'Game',
                 ai_easy=None, ai_easy_user_id: int = -1, ai_easy_nickname: str = "简单人机",
                 ai_medium=None, ai_medium_user_id: int = -1, ai_medium_nickname: str = "中等人机"):
        self.game = game
        self.db_match_id = None       # SQLite 对局记录 id
        # 双 AI 支持
        self._ai_easy = ai_easy
        self._ai_easy_user_id = ai_easy_user_id
        self._ai_easy_nickname = ai_easy_nickname
        self._ai_medium = ai_medium
        self._ai_medium_user_id = ai_medium_user_id
        self._ai_medium_nickname = ai_medium_nickname
        # 当前对局激活的 AI
        self._active_ai = None        # AIPlayer | None
        self._active_ai_user_id = -1  # int

    async def close(self):
        """清理本局游戏占用的资源"""
        self.db_match_id = None

    async def process(self, user_id: int, message: str, nickname: str) -> list[str]:
        replies: list[str] = []

        if message in ALL_CMDS or any(message.startswith(prefix) for prefix in ADVANCED_CMDS):
            stage = self.game.game_stage

            if stage == GAME_STAGE_CHOOSE_MODES:
                replies = await self._process_mode_selection(user_id, message, nickname)
            elif stage == GAME_STAGE_MAIN_PART:
                replies = await self._process_main_game(user_id, message)
            elif stage == GAME_STAGE_END:
                replies = await self._process_game_end(message)
            else:
                return ["游戏状态异常"]
        else:
            return []

        # 检查是否需要 AI 自动出牌
        if self._active_ai is not None:
            ai_p = self.game.get_player_index(self._active_ai_user_id)
            if ai_p != -1 and self.game.turn == ai_p and self.game.game_stage == GAME_STAGE_MAIN_PART:
                ai_msgs = await asyncio.to_thread(
                    self._active_ai.play_turn, self.game, ai_p
                )
                replies.extend(ai_msgs)

        return replies

    def _verification(self,user_id: int, message: str)->str|None:
        p = self.game.get_player_index(user_id)
        if p==-1:
            return '你不是本局游戏的玩家。'
        elif p != self.game.turn:
            return "不是你的回合。"
        return None

    async def _process_main_game(self, user_id: int, message: str) -> list[str]:
        err = self._verification(user_id, message)
        if err:
            return [err]
        p = self.game.get_player_index(user_id)

        async def handle_action_result() -> list[str]:
            msgs = self.game.post_action_check()
            # DB 写入失败不应阻断游戏 —— replay 和结算记录不是核心功能
            if self.db_match_id is not None and msgs:
                combined_text = "\n".join(msgs).strip()
                if combined_text:
                    try:
                        await db.add_event(
                            self.db_match_id,
                            self.game.total_turns,
                            combined_text,
                        )
                    except Exception:
                        # replay 写入失败不阻断游戏
                        pass

            if self.game.game_stage == GAME_STAGE_END and self.db_match_id is not None:
                try:
                    winner_idx = 1 - self.game.loser
                    winner_id = self.game.players[winner_idx].user_id
                    scores = {}
                    if hasattr(self.game, 'final_score'):
                        scores[winner_idx] = self.game.final_score
                        scores[self.game.loser] = -self.game.final_score
                    await db.finish_match(self.db_match_id, winner_id, scores)
                except Exception:
                    pass
                finally:
                    self.db_match_id = None

            return msgs

        for mode in self.game.modes:
            if mode.action(self.game, p, message):
                return await handle_action_result()

        if message in SHOOT_SELF_CMDS:
            self.game.shoot(p)
            return await handle_action_result()

        elif message in SHOOT_EMERY_CMDS:
            self.game.shoot(1 - p)
            return await handle_action_result()

        if message.startswith(USE_CMDS[0]):
            item_name, _, extra_information = message[2:].partition('#')
            if item_name in ITEM_REGISTRY:
                item = ITEM_REGISTRY[item_name]()
                if item.item_check(self.game):
                    item.use(self.game, extra_information)
                    return await handle_action_result()
                else:
                    return ["没有该道具/本回合你被禁用道具。"]

            elif item_name in ARTIFACT_REGISTRY:
                artifact = ARTIFACT_REGISTRY[item_name]()
                if artifact.item_check(self.game):
                    artifact.use(self.game, extra_information)
                    return await handle_action_result()
                else:
                    return ['你没有该神器。']

        return ["无效指令"]

    async def _process_mode_selection(self, user_id: int, message: str, nickname: str) -> list[str]:
        if message == "加入轮盘":
            return [self.game.join(user_id, nickname)]
        elif message == "挑战简单人机":
            if self._ai_easy is None:
                return ["简单人机功能未启用。"]
            self.game.join(self._ai_easy_user_id, self._ai_easy_nickname)
            self._active_ai = self._ai_easy
            self._active_ai_user_id = self._ai_easy_user_id
            return ['已添加简单人机。']
        elif message == "挑战中等人机":
            if self._ai_medium is None:
                return ["中等人机功能未启用。"]
            self.game.join(self._ai_medium_user_id, self._ai_medium_nickname)
            self._active_ai = self._ai_medium
            self._active_ai_user_id = self._ai_medium_user_id
            return ['已添加中等人机。']
        elif message == "退出轮盘":
            return [self.game.quit(user_id)]
        elif message.startswith("模式#"):
            return [self.game.revise_mode(user_id, message)]
        elif message == "开始轮盘":
            if not self.game.verity():
                return ['当前未满2人']

            # ★ 先写数据库，再改游戏状态 —— 避免 DB 失败导致状态不一致
            try:
                match_id = await db.create_match(self.game.group_id, self.game.mode_ids)
                await db.add_players(match_id, [
                    (self.game.players[0].user_id, 0),
                    (self.game.players[1].user_id, 1),
                ])
            except Exception as e:
                return [f"数据库连接失败，请稍后重试。({str(e)[:50]})"]

            self.db_match_id = match_id
            self.game.game_start()
            return [self.game.flush_msgs()]

        # 走到这里 = 以「模式/使用/重置」开头但哪条都不匹配 —— 比如「使用说明」「重置一下密码」
        # 这类普通句子（前缀匹配只看前两个字）。**必须显式 return**：落出函数会隐式返回 None，
        # 一路传到 FeatureRoulette 的列表推导上变成 'NoneType' object is not iterable。
        # 回空 list = 轮盘不接这条，消息继续往后走（智能路由 / 语料库）。
        return []

    async def _process_game_end(self, message: str) -> list[str]:
        if message == "新游戏":
            self.game.reset()
            return ["游戏已重置，可重新开始"]
        return ["游戏已结束，请使用「新游戏」开始下一局"]

    async def fetch_flush_private(self):
        return self.game.flush_private_msgs()

class Manager:
    def __init__(self, ai_user_id: int = -1, ai_nickname: str = "AI对手"):
        self.handlers = {}  # group_id -> CommandHandler
        # 双 AI：简单人机 (50k, 69维) + 中等人机 (350k, 72维)
        self._ai_easy = self._load_ai_player("model_50000.pt")
        self._ai_medium = self._load_ai_player("model_450000.pt")
        # 简单人机用 bot 自己的 QQ 作为虚拟用户
        self._ai_easy_user_id = ai_user_id
        self._ai_easy_nickname =ai_nickname
        # 中等人机用一个相邻 ID
        self._ai_medium_user_id = ai_user_id
        self._ai_medium_nickname = ai_nickname

    @staticmethod
    def _load_ai_player(filename: str):
        import os as _os
        _model_path = _os.path.join(
            _os.path.dirname(__file__), filename
        )
        if _os.path.exists(_model_path):
            from .ai_player import AIPlayer
            return AIPlayer(_model_path)
        return None

    async def get_handler(self, group_id: int) -> CommandHandler:
        if group_id not in self.handlers:
            game = Game(group_id)
            self.handlers[group_id] = CommandHandler(
                game,
                ai_easy=self._ai_easy,
                ai_easy_user_id=self._ai_easy_user_id,
                ai_easy_nickname=self._ai_easy_nickname,
                ai_medium=self._ai_medium,
                ai_medium_user_id=self._ai_medium_user_id,
                ai_medium_nickname=self._ai_medium_nickname,
            )
        return self.handlers[group_id]

class ReplayGenerator:
    @staticmethod
    async def generate(match_id: int) -> str:
        match = await db.get_match(match_id)
        if match is None:
            return "找不到该局对战录像。"

        events = await db.list_events(match_id)
        if not events:
            return "该对局没有任何操作记录。"

        replay_lines = [f"【对局回放】(ID: {match_id})", "-" * 20]
        for event in events:
            replay_lines.append(f"[第{event['turn_num']}回合] {event['content']}")

        return "\n".join(replay_lines)

