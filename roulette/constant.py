ITEM_KNIFE='刀'   # type:str
ITEM_DICE='灌铅骰子'  # type:str
ITEM_CIGARETTE='烟'  # type:str
ITEM_MAGNIFYING_GLASS = "放大镜"  # type:str
ITEM_HANDCUFFS = "手铐"  # type:str
ITEM_BOMB = "炸药"  # type:str
ITEM_LOATHEB = "洛欧塞布"  # type:str
ITEM_BABA = "baba"  # type:str
ITEM_HIGH_NOON = "午时已到"  # type:str
ITEM_DEATH_PROOF = "死亡证明"  # type:str
ITEM_FLIP='生死逆转' # type:str

ARTIFACT_HAND_OF_WOKING='沃金的手'
ARTIFACT_RECKLESSNESS='莽'
ARTIFACT_TIDIED_TEA_SET='整理好的茶具'

IS_LIVE='is_live'  # type:str
DAMAGE='dmg'  # type:str
TARGET='target'  # type:str
MIN_LIVE_BULLET='min_live_bullet'  # type:str
MAX_LIVE_BULLET='max_live_bullet'  # type:str
FULL_BULLET='full_bullet'  # type:str

SHOOT_SELF_CMDS=['向自己开枪','/打0','向自己射击','射击自己']
SHOOT_EMERY_CMDS=['向对手开枪','/打1','向对手射击','射击对手']
SHOOT_CMDS=SHOOT_SELF_CMDS+SHOOT_EMERY_CMDS
USE_CMDS=['使用']
MODE_CMDS={11:['苦肉'],13:['跳过回合'],15:['重置']}
MODE_LIST_CMDS=[cmd for cmds in MODE_CMDS.values() for cmd in cmds]
MAIN_PART_CMDS=SHOOT_CMDS+USE_CMDS+MODE_LIST_CMDS
CHOOSE_MODE_CMDS=['模式','加入轮盘','开始轮盘','退出轮盘','挑战简单人机','挑战中等人机']
END_STAGE_CMDS=['新游戏']
ADVANCED_CMDS=['模式','使用','重置']
ALL_CMDS=CHOOSE_MODE_CMDS+MAIN_PART_CMDS+END_STAGE_CMDS

ITEM_POOL=[ITEM_KNIFE,ITEM_DICE,ITEM_CIGARETTE,ITEM_MAGNIFYING_GLASS,ITEM_HANDCUFFS] # type:list[str]
ITEM_PROBABILITY=[25,20,20,30,15] # type:list[int]
TREASURE_ITEM_POOL=ITEM_POOL+[ITEM_BOMB,ITEM_LOATHEB,ITEM_BABA,
                              ITEM_HIGH_NOON,ITEM_DEATH_PROOF,ITEM_FLIP] # type:list[str]
TREASURE_ITEM_PROBABILITY=ITEM_PROBABILITY+[12,8,5,3,2,10] # type:list[int]
TOTAL_ITEM_POOL=TREASURE_ITEM_POOL # type:list[str]
ALL_ARTIFACT=[ARTIFACT_HAND_OF_WOKING,ARTIFACT_TIDIED_TEA_SET,ARTIFACT_RECKLESSNESS]

VALUE_TO_BULLET={1: '实弹', 0: '空弹'} # type:dict[int:str]

ITEM_NUM={1:0,2:1,3:2}  # type:dict[int:int]

BULLET_FULL_COUNT={1:3,2:5,3:6}  # type:dict[int:int]
MIN_BULLET={1:1,2:2,3:2}  # type:dict[int:int]
MAX_BULLET={1:2,2:3,3:4}  # type:dict[int:int]
MAX_HP={1:3,2:5,3:8}  # type:dict[int:int]

ALL_MODES={1:'西部对决',2:'奇珍异宝',3:'一决胜负',4:'孤注一掷',5:'命运之轮',
           6:'浑水摸鱼',7:'绝地反击',8:'后发制人',9:'乘胜追击',10:'旷日持久',
           11:'生命分流',12:'洞悉先机',13:'以逸待劳',14:'轻装上阵',15:'好运当骰',
           16:'死亡计时',17:'上古神器',18:'回光返照',
           100:'风云变幻'} # type:dict[int:str]

LATECOMER_ITEM_NUM={1:1,2:1,3:2} # type:dict[int:int]
DEATH_TIMER_LIMIT={1: 6, 2: 10, 3: 14} # type:dict[int:int]

CONDITION_KNIFE='knife'  # type:str
CONDITION_HANDCUFFS='handcuffs'  # type:str
CONDITION_LOATHEB='ban'  # type:str

ALL_CONDITIONS=[CONDITION_KNIFE,CONDITION_HANDCUFFS,CONDITION_LOATHEB] # type:list[str]

MAX_ITEM_NUM=10 # type:int

MULTIPLIER_NAME='multiplier'  # type:str
MULTIPLIER_ADDEND='multiplier_addend'  # type:str
MULTIPLIER_FACTOR='multiplier_factor'  # type:str
POINT_NAME='point'  # type:str
BACE_MULTIPLIER=1  # type:float
BACE_POINT=100  # type:float

GAME_STAGE_DISABLE=-1  # type:int
GAME_STAGE_CHOOSE_MODES=0  # type:int
GAME_STAGE_MAIN_PART=1  # type:int
GAME_STAGE_END=2  # type:int