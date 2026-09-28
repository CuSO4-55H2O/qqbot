"""所有插件模块的显式导入点。

这是唯一的「发现」入口：`@register` 在模块被 import 时执行。所以这里漏掉一个
模块，那个模块里的插件就不会注册 —— BotCore 启动时的清单校验会把这种情况拦下来
（功能集合在 `constant.FEATURE_ALIAS` 里有一份，两边对不上就报错）。

拆成多个文件而不是继续堆在一个大文件里，正是为了这一步：发现机制从
`__subclasses__()` 内省换成显式注册之后，功能才能按域分散而不会静默丢失。
"""

from . import (  # noqa: F401
    admin,
    ai,
    bottle,
    chat_record,
    define,
    events,
    food,
    games,
    media,
    records,
    text,
)
