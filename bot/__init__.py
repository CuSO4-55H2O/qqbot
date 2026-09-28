"""机器人的核心层。

    request.py   一次请求的输入与输出形状（Request / Reply / Outcome）
    options.py   功能开关与权限的存储（OptionsStore / RosterStore / AdminAPI）
    plugin.py    插件基类（Plugin / Feature / Matcher / EventHandler）+ 注册表 + Deps
    cq.py        CQ 码解析与图片落库
    core.py      组合根 + 调度核心（BotCore）
    plugins/     具体功能实现，按域分文件
"""
