import os
from enum import StrEnum
from typing import NamedTuple


class PluginName(StrEnum):
    FEATURE='feature'
    EVENT_HANDLER='event_handler'
    AFTER_HOOK='after_hook'

class Name(StrEnum):
    GROUP='group'
    PRIVATE='private'
    ARG='arg'

class FeatureName(StrEnum):
    ADMIN='admin'
    READOPTIONS='readoptions'
    DEEPSEEK='deepseek'
    RECORD='record'
    ROULETTE='roulette'
    OPJOKES='opjokes'
    IMAGE='image'
    DICE='dice'
    CAPOO='capoo'
    HSDJOKES='hsdjokes'
    BOTTLE_MAIL='bottle_mail'
    RABBLE='rabble'
    REPEATER_DETECTION= 'repeater_detection'
    REPEAT='repeat'
    DEFINE='define'
    EMOJI_REACTION='emoji_reaction'
    CHAT_RECORD='chat_record'
    CHAT_RAG='chat_rag'
    QUERY_MIAOKA='query_miaoka'
    SMART_ROUTER='smart_router'
    DISHES='dishes'

class EventHandlerName(StrEnum):
    POKE='poke'
    REVOKE='revoke'
    GROUP_DECREASE='group_decrease'

class FeatureSpec(NamedTuple):
    """一个功能的声明式元数据。

    「功能集合」原先散在四处：FEATURE_ALIAS 的中文名、智能路由的 _TARGETS、
    ai_core/router.py 的 _ALLOWED、以及它 prompt 里逐条写的散文说明。加一个可路由
    的功能要同时改四处，漏一处就是静默失效。现在都从这一份派生。

    放在 constant.py（无依赖叶子）而不是插件类上，是因为 ai_core/router.py 也要读它：
    路由 prompt 需要这份清单，而 ai_core 不能反向 import bot（会成环）。
    """

    alias: str                    # 用户可见中文名（「查看设置」显示 + 「打开 X」反查）
    llm_target: str = ''          # 智能路由的目标名；空 = 不可路由
    llm_doc: str = ''             # 给模型的说明，整行原文（含 "- " 前缀），逐字照搬
    llm_order: int = 0            # 在路由 prompt 里的出现顺序；0 = 不进 prompt
    llm_group_only: bool = False  # 只在群聊里列出（目前只有 rag）


# 功能清单：唯一来源。可路由的 8 个按 llm_order 排，与旧 prompt 的行序一致。
FEATURE_MANIFEST: dict[FeatureName, FeatureSpec] = {
    FeatureName.IMAGE: FeatureSpec(
        '图片', 'image', llm_order=1,
        llm_doc="- image（发图片）：用户想要某张群内常用图。可用关键词只有下面这些，"
                "语义最贴近哪个就选哪个，trigger=那个关键词本身：\n    {image_keys}"),
    FeatureName.DICE: FeatureSpec(
        '骰子', 'dice', llm_order=2,
        llm_doc="- dice（掷骰）：想要随机/骰子。trigger=骰子表达式，如 d6、2d8+1、d20；"
                "只许 d/数字/+-*/()。"),
    FeatureName.BOTTLE_MAIL: FeatureSpec(
        '漂流瓶', 'bottle', llm_order=3,
        llm_doc="- bottle（漂流瓶）：捞/砸/扔/查漂流瓶。trigger 取原功能精确指令："
                "捞漂流瓶、砸漂流瓶、扔漂流瓶、漂流瓶海；"
                "用户若给了内容要丢瓶子，则 trigger=丢漂流瓶 <用户内容>。"),
    FeatureName.CAPOO: FeatureSpec(
        '咖波', 'capoo', llm_order=4,
        llm_doc="- capoo：想要咖波图。trigger=咖波 或 capoo。"),
    FeatureName.HSDJOKES: FeatureSpec(
        'hsd笑话', 'hsd', llm_order=5,
        llm_doc="- hsd：想要 hsd 笑话图。trigger=hsd笑话 或 HSD笑话。"),
    FeatureName.OPJOKES: FeatureSpec(
        'op笑话', 'op', llm_order=6,
        llm_doc="- op：想要 op 段子。trigger=op段子。"),
    FeatureName.DEEPSEEK: FeatureSpec(
        'AI对话', 'chat', llm_order=7,
        llm_doc="- chat（直接对话）：用户**明显在点名跟机器人说话**（@了机器人/喊了机器人名/"
                "开口是“ai”这类），而不是泛泛发在群里。"),
    FeatureName.CHAT_RAG: FeatureSpec(
        '群聊问答', 'rag', llm_order=8, llm_group_only=True,
        llm_doc="- rag（查群聊历史）：用户在问“之前/刚才群里聊过什么”这类要翻记录的问题。"),

    # 其余功能只提供显示名，不进路由
    FeatureName.ADMIN: FeatureSpec('管理功能'),
    FeatureName.READOPTIONS: FeatureSpec('查看设置'),
    FeatureName.RECORD: FeatureSpec('记录'),
    FeatureName.ROULETTE: FeatureSpec('轮盘'),
    FeatureName.RABBLE: FeatureSpec('乌合之众'),
    FeatureName.REPEATER_DETECTION: FeatureSpec('复读检测'),
    FeatureName.REPEAT: FeatureSpec('复读'),
    FeatureName.DEFINE: FeatureSpec('定义'),
    FeatureName.EMOJI_REACTION: FeatureSpec('表情回应'),
    FeatureName.CHAT_RECORD: FeatureSpec('聊天记录'),
    FeatureName.QUERY_MIAOKA: FeatureSpec('喵卡查询'),
    FeatureName.SMART_ROUTER: FeatureSpec('智能路由'),
    FeatureName.DISHES: FeatureSpec('吃什么'),
}

# 事件处理器的显示名。它们没有插件类、不进路由清单，所以单列。
EVENT_HANDLER_ALIAS: dict[str, str] = {
    EventHandlerName.POKE: '戳一戳',
    EventHandlerName.REVOKE: '撤回提示',
    EventHandlerName.GROUP_DECREASE: '退群提醒',
}

# 仅用于「查看设置」的显示别名，不改任何 FeatureName/EventHandlerName 的值
FEATURE_ALIAS: dict[str, str] = {
    **{k: v.alias for k, v in FEATURE_MANIFEST.items()},
    **EVENT_HANDLER_ALIAS,
}

# 别名反查：让「打开 智能路由」这类中文指令也能用。中英都认，查不到就原样返回交给调用方判合法
FEATURE_ALIAS_REVERSE: dict[str, str] = {v: str(k) for k, v in FEATURE_ALIAS.items()}

# 路由目标名 → FeatureName（今 FeatureSmartRouter._TARGETS）
LLM_TARGETS: dict[str, str] = {
    v.llm_target: k for k, v in FEATURE_MANIFEST.items() if v.llm_target
}

# 路由 prompt 里按顺序给出的各功能说明（今 ai_core/router.py 里逐条手写的那段）
ROUTABLE_SPECS: list[FeatureSpec] = sorted(
    (v for v in FEATURE_MANIFEST.values() if v.llm_target),
    key=lambda v: v.llm_order,
)


class RecordMode(StrEnum):
    VIEW = 'view'          # 查看当前记录（格式化转发）
    RAW = 'raw'            # 查看原始 forward 消息内容
    SEARCH = 'search'      # 按 QQ 号搜索记录（含归档）
    ARCHIVED = 'archived'  # 查看归档记录


class AdminCMD(StrEnum):
    ARCHIVE_RECORD='归档记录'
    END_ROULETTE='结束轮盘'

class AdminCommandConfig(NamedTuple):
    feature_name: str
    cmd_str: str
    need_args: bool
    super_only: bool

#第三个参数是否需要额外参数，第四个是否需要超级管理员权限
AdminMap:dict[str,AdminCommandConfig]={
    AdminCMD.ARCHIVE_RECORD:AdminCommandConfig(
        feature_name=FeatureName.RECORD,
        cmd_str=AdminCMD.ARCHIVE_RECORD,
        need_args=False,
        super_only=False),
    AdminCMD.END_ROULETTE:AdminCommandConfig(
        feature_name=FeatureName.ROULETTE,
        cmd_str=AdminCMD.END_ROULETTE,
        need_args=False,
        super_only=False)
}

DELIMITER='~'
DEEPSEEK_API_KEY=os.environ.get('DEEPSEEK_API_KEY', '')
BOCHA_API_KEY=os.environ.get('BOCHA_API_KEY', '')
SUPERADMIN=int(os.environ.get('SUPER_ADMIN_QQ', 0))

# 「暗锅题数」查询用的外部服务。可选项：没配就是这条指令不可用。
# 原先 URL 和 token 都硬编码在 bot/plugins/admin.py 里。
BLACKPOT_API_URL = os.environ.get('BLACKPOT_API_URL', '')
BLACKPOT_TOKEN = os.environ.get('BLACKPOT_TOKEN', '')


# ---- NapCat 连接参数 ----
# 全部来自环境变量，**不留兜底值**。原先 output.py 和 helper_fun.py 各自硬编码一份，
# 后来收口到这里但保留了兜底；兜底的坏处是「忘了配」不报错，表现为静默连到错误的
# 地址、或继续用一个早该作废的 token，排查半天才发现是兜底在起作用。缺了就直接抛。
#
# 容器里由 docker-compose 的 env_file 注入；本机跑先在项目根目录 `set -a && source .env`。
# 换服务器 / 首次部署见 setup-napcat.sh，它会把这三个键写进 .env。
def _env_required(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(
            f"缺少环境变量 {name}。容器里检查 docker-compose 的 env_file；"
            f"本机跑先在项目根目录执行 `set -a && source .env`") from None


NAPCAT_HOST = _env_required('NAPCAT_HOST')
NAPCAT_PORT = int(_env_required('NAPCAT_PORT'))
NAPCAT_TOKEN = _env_required('NAPCAT_TOKEN')
NAPCAT_BASE_URL = f"http://{NAPCAT_HOST}:{NAPCAT_PORT}"

# 机器人自己的 QQ 号与显示名**不在这里**：它从 NapCat 的 get_login_info 现取
# （helper_fun.read_id，BotCore.init_async 启动时调一次），然后随发送调用显式传下去，
# 见 output.BotIdentity。原先这里是两个硬编码常量，换账号得改代码。


# ---- 数据文件路径 ----
# 全部锚在 __file__ 上，不看进程 CWD。原先写 '../database/x.db'、'../json/x.json' 这类相对串，
# 以及拿 os.path.dirname(os.getcwd()) 现拼的媒体目录：换个目录启动都不会报错，
# 只会静默读写到另一处的空文件上，表现得像"数据全丢了"。
# 锚定后容器里解析到 /app/文件/ 下的挂载卷，除 roulette 外都和旧写法指向同一个文件。
_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
_DB_DIR = os.path.join(_ROOT, 'database')


class DBPath(StrEnum):
    """所有 SQLite 库的落点。成员值就是绝对路径，可直接喂 sqlite3.connect。

    ⚠️ 加成员时别让两个成员的值撞车 —— Enum 会把值相同的后来者当别名静默丢掉。
    """
    CHAT_HISTORY  = os.path.join(_DB_DIR, 'chat_history.db')
    RECORD        = os.path.join(_DB_DIR, 'record.db')
    DEFINE        = os.path.join(_DB_DIR, 'define.db')
    BOTTLE_MAIL   = os.path.join(_DB_DIR, 'bottle_mail.db')
    POSTED_IMAGES = os.path.join(_DB_DIR, 'posted_images.db')
    MIAOKA        = os.path.join(_DB_DIR, 'miaoka.db')
    TOKEN_USAGE   = os.path.join(_DB_DIR, 'token_usage.db')
    DISHES        = os.path.join(_DB_DIR, 'dishes.db')
    # 原先是 roulette/roulette.db（dirname(__file__)）。那个目录在镜像里、不在挂载卷上，
    # 所以每次 docker build + deploy 新容器都会连库一起丢掉。挪进挂载卷。
    ROULETTE      = os.path.join(_DB_DIR, 'roulette.db')


class JsonPath(StrEnum):
    """文件/json/ 下被代码引用的文件。"""
    RECORD         = os.path.join(_ROOT, 'json', '记录.json')
    COUNT          = os.path.join(_ROOT, 'json', '次数.json')
    ARCHIVED       = os.path.join(_ROOT, 'json', '归档记录.json')
    BLACKLIST      = os.path.join(_ROOT, 'json', '黑名单.json')
    COIN           = os.path.join(_ROOT, 'json', '铸币.json')
    ADMINISTRATORS = os.path.join(_ROOT, 'json', 'administrators.json')
    GROUP_OPTIONS  = os.path.join(_ROOT, 'json', 'group_options.json')


class DocPath(StrEnum):
    """文件/文档/ 下被代码引用的文本。"""
    IMAGE_TXT = os.path.join(_ROOT, '文档', 'image.txt')
    OP_JOKES  = os.path.join(_ROOT, '文档', 'op段子.txt')
    OPTIONS   = os.path.join(_ROOT, '文档', 'options.txt')
    RABBLE    = os.path.join(_ROOT, '文档', '乌合之众.txt')
    ROULETTE  = os.path.join(_ROOT, '文档', '俄罗斯轮盘.txt')


class MediaDir(StrEnum):
    """文件/ 下的媒体目录。用来拼 CQ 的 file:/// 路径，本身不是文件。"""
    IMAGE = os.path.join(_ROOT, '图片')
    CAPOO = os.path.join(_ROOT, 'capoo')
    HSD   = os.path.join(_ROOT, 'hsd笑话')