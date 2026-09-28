# legacy/ — 三代入口文件存档

这里存的是同一个 QQ 机器人框架在三代里的**入口文件**，按版本号排列：

| 文件 | 版本 | 时间 | 行数 | 入口形态 |
|---|---|---|---|---|
| `1.0_AAA主程序.py` | 1.0 | 2022–2024 | 332 | 模块级 `while True` 轮询 |
| `1.5_AA处理.py` | 1.5 | 2025–2026.04 | 410 | `def handle(rev)`，循环挪进 `main.py` |
| `2.0_handle_function.py` | 2.0 | 2026.05 | 1147 | `BotCore.handle(event)`，功能拆成 16 个 `Feature` 子类 |

功能集合三代几乎没变（骰子、漂流瓶、图片、乌合之众、斗地主、轮盘……），
变的全是**状态放在哪、怎么短路、怎么挂载功能**。

> 存档文件已脱敏：原文里的群号 / QQ / 服务器地址一律替换成
> `1000000001`–`1000000005`、`203.0.113.1` 这类占位值。

---

## 一、六个维度对照

| 维度 | 1.0 | 1.5 | 2.0 |
|---|---|---|---|
| **入口** | 文件里的 `while True` | `main.py` 里调 `handle(rev)` | `BotCore.handle(event)` |
| **收消息** | 手写 socket server，改用标准库 `http.server` | **Flask** | Flask（同 1.5） |
| **单条消息的状态** | ~25 个模块级全局 | 还是全局，但 `handle` 顶部要写两行 `global`，共 13 个名字 | `Context` dataclass，每条消息新建 |
| **短路** | `continue` | `x = 0` + 每处 `and x == 0` | `ctx.flag` + `break` |
| **功能挂载** | 手写 11 行 `from X import *` | 同 1.0 | `Plugin.__subclasses__()` 自动发现 |
| **发送** | 各处直接 `send_msg(...)` | 同 1.0 | `ctx.send_msg` 列表 + `handle` 末尾统一发（**只做了一半**） |
| **包结构** | 19 个平铺文件，零包 | 多一个 `roulette/` | 再多一个 `rabble/` |

---

## 二、每次换代：修了什么，留下什么

### 1.0 → 1.5：从"一段脚本"变成"一个函数"

**动机**：文件太长，入口和逻辑搅在一起。

**代价**：`continue` 是**循环**的关键字，进了函数就用不了 —— 只能自己拿个布尔模拟。
`x` 就是这么来的；13 个 `global` 也是这时冒出来的（状态还是全局的，
但访问它的人从"循环体"变成了"函数"）。

**顺手引入一个真 bug**：

```python
if options["image"] == 1 and x == 0 or mes in ["砰砰机器人帮助", "管理员帮助", '帮助']:
```

`and` 比 `or` 紧，实际是 `(A and B) or C` —— **`or` 那半边完全绕过了 `x`**。
前面功能已经处理过的消息，照样会掉进图片分支。

### 1.5 → 2.0：把全局收进对象

**动机**：`global` 一长串、`x` 一长串，都扩不动了。于是——

- 状态 → `Context`，`global` 消失
- 短路 → `ctx.flag`，`x` 消失
- if/elif 树 → `Plugin` 基类 + 16 个 `Feature` 子类，按 `priority` 排序分发
- 发送 → `ctx.send_msg` 列表，`handle` 末尾统一发出

**留下的三样，一直带到 3.0**：

1. **`ctx.flag` 语义过载。** `Feature.reply` 里写着

   ```python
   if not ctx.flag or not text:
       return
   ```

   `flag` 同时表示"这条消息我接了"和"允许我回复"。于是"接了但不回"**写不出来**——
   忘记置 `flag` 就静默丢消息。（`FeatureBottleMail` 里甚至反过来写：先无条件
   `ctx.flag = True`，不匹配再改回 `False`，就是在绕这个坑。）

2. **`__subclasses__` 要求所有子类被 import 过**，所以 16 个功能只能挤在同一个文件里。

3. **加载器里特判**：`if cls == FeatureAdmin:` 手工塞进 `AdminAPI` ——
   别的插件都无参构造，就它特殊。

---

## 三、可以对着代码验的细节

### 1.0 的病是具体的，不是"命名空间污染"这种课本话

- `stage, group1, players1, cards, remain, turn, k, times, dz = ddz_1()` ——
  斗地主状态是九个平行全局，`group0` / `group1` 都是**单数**：
  **两个群同时开一局会互相串**。乌合之众同理。
- `self = 1000000001` —— 把 `self` 这个名字占成了模块全局。
- 裸 `except: continue`。
- 某个分支写着 `enter_group(rev[flag])`，`flag` 根本没定义 —— 一进就 NameError。
- 某个分支 `f2=1`，赋了从不使用。
- **同一个 zip 里有两个入口文件**（另一个是 `服务器.py`，未存档），
  各自重复声明了同一批全局变量；其中一个 `from 服务器 import *`，自己 import 自己。
  另一个依赖的 `输入.py` 里 `rev_msg()` 已被桩成 `return None` —— 那份是空转的。

### 1.5 开始逐块收拾

- 乌合之众的状态从九个全局变成 `dic2` 一个 dict，按群号分 —— **多群串线从这代开始修**。
- `if '~' in mes: x=1` —— 一个魔法字符当分隔符用（2.0 才命名成 `DELIMITER`）。
- 文件里留着三段 `'''` 注释掉的死代码，占四十多行。

### 2.0 的结构病

- `FeatureQueryMiaoKa` 写 `name = 'query_miaoka'` —— 别人都用枚举，就它裸字符串。
- `EventHandlerGroupDecrease` 绕过 `ctx.send_msg` 直接调 `send_msg(...)`；
  `record.py` / `helper_fun.py` / `roulette.py` 也一样 —— **"统一发送"只做到一半**。
- `Context`（11 字段，给消息）和 `MiniContext`（1 字段，给事件）两个 dataclass 并列。
- 但 `constant.py` 里已经有了**声明式表**的雏形：

  ```python
  class AdminCommandConfig(NamedTuple):
      feature_name: str
      cmd_str: str
      need_args: bool
      super_only: bool

  AdminMap: dict[str, AdminCommandConfig] = { ... }
  ```

  后来 `FEATURE_MANIFEST` 就是这张表的放大版。

---

## 四、四代连起来

```
1.0  while True + 全局变量 + continue
  ↓   把"处理一条消息"抽成函数
1.5  handle(rev) + 全局变量 + 一个 x 标志位
  ↓   把状态收进对象、把分支收成类
2.0  BotCore.handle + Context + Feature 子类 + __subclasses__
  ↓   flag 拆成三态、Context 冻结、显式注册、发送收口
4.x  Request + Outcome + @register + _dispatch
```

每一代都在解上一代留下的那个洞，然后留下自己的。
