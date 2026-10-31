# cf-tool 0.4.0 重写计划

工作分支 `v0.4`（发布前删掉本文件）。目标：不再沿用 Go 版 cf-tool 的模型，做一个开箱即用的新版本。

## 1. 为什么要重写（调查结论）

以 Fau 自己的 `~/.config/cf/config` 为例：

- 三个 template 里 `cpp` 和 `cpp17` 都认 `.cpp`，于是每次 `cf test` / `cf submit` 都先问用哪个模板。
- 默认模板 `cpp17` 没有编译脚本，`cf test` 跑的是旧的（或根本不存在的）`./a`；`cpp` 的 after_script 还会把它删掉。`cf doctor` 却报告它“ready”。
- `cpp` 本地用 `-std=c++23` 编译，却以 G++20（id 89）提交：本地能编译的代码到 CF 上可能 CE。
- 0.3.1 的向导写死 `-std=c++20`，却默认选 G++23 提交；把配置目录的绝对路径写进脚本；用户拒绝“替换模板”时，起始代码文件已经写好了。

根源：一个 template 同时管四件事：起始代码、编译运行脚本（`before_script/script/after_script` 和 `$%full%$` 占位符）、提交用的 CF 语言 id、后缀和别名。全部要用户手写。

Go 留下的其他包袱：

- 目录：`cf/contest/2050/a/` 很深，`in1.txt` / `ans1.txt` 和代码混在一起；靠目录名猜题目，还要配 `folder_name`。
- 流程：parse 和 gen 分两步，外加 `gen_after_parse` 开关；每次 test 都重新编译（C++ 每次约 1.5 s），编译产物留在题目目录里，靠 rm 脚本清理。
- 比较：按“每行去首尾空白”，比 CF 的检查器严，多一个空行或空格就判错。
- 界面：命令名 stand / sid / list / watch 难懂；配置是 JSON 加菜单。

其他工具的做法（oj、acc、cargo-compete、cpbooster、cph / cph-ng、CP Editor、CompetiTest.nvim 等）：

- 按扩展名认语言，默认就能用，用户最多改编译器和参数。
- 源文件和输出路径由工具补上，编译和运行分开，没有 before/after 钩子。
- 题目身份记在数据文件里，而不是目录名；测试放在 `tests/`（`.in` 和 `.ans`）。
- 提交语言来自 CF 的实时列表；编译缓存以源码哈希为键，二进制放在源码目录外面。
- 提交的 POST 绝不重发。

xalanq/cf-tool 已归档，issue 里抱怨的正是这几点：两个模板共用一个后缀、语言 id 过期、目录太深。

## 2. 已定的决定（2026-10-31）

- **目录**：每题一个目录，`2050/a/` 下面是 `a.cpp`、`tests/1.in`、`tests/1.ans` 和 `.cf-problem.json`。
- **配置**：以 `~/.config/cf/config.toml` 为主，带注释，所有项都可选；`cf config` 用编辑器打开它；另有 `cf login`、`cf langs` 等命令。
- **命令**：换成新名字；旧名作为隐藏别名，照样能用。
- **0.4.0 一并做**：`cf test --watch`、交互题（`--interactor`）、发布到 PyPI。
- **以后再做**：提交前展开本地 `#include`、用 API 看评测、bits/stdc++.h 预编译头。

## 3. 新设计

### 原则

1. 零配置：按扩展名认语言，用到时才找编译器；不登录也能 get 和 test，到 submit 才就地登录。
2. 只有一个概念：语言。内置默认值，想改哪项只写那一项。
3. 本地和评测机一致：`-std` 跟着提交语言走；比较方式和 CF 默认检查器一样按 token；误差和大小写规则来自题面。
4. 题目目录自描述：用 `.cf-problem.json` 认题，不需要根目录配置。
5. 目录保持干净：编译产物放在缓存里，源码不变就不重编，不需要清理脚本。

### 日常用法

```
cf get 2050        # 建 2050/a … 2050/h：样例 + 起始代码（一次请求拿到整场比赛）
cd 2050/a
cf test            # 编译（有缓存）并跑样例；-w 保存即重测
cf submit          # 没登录就当场登录，然后实时显示评测
cf test b          # 在 2050/ 里也行
```

### 目录

```
2050/                  比赛目录
  a/                   题目目录
    a.cpp              起始代码；目录里已有这个语言的代码时不写
    tests/1.in 1.ans   样例；自己加的测试也放这里，任意名字的 .in/.ans 成对
    .cf-problem.json   url、题名、时空限制、交互、误差、大小写、多组样例的分行
```

- **放在哪里**：在比赛或题目目录里运行 `cf get`，新比赛放在当前比赛目录旁边；配置了 `root` 就放在 root 下；否则放在当前目录。
- **其他题型**：gym 用 `<gym id>/`；group 用 `<contest id>/`，group id 记在元数据里；acmsguru 用 `acmsguru/<题号>/`。
- **重跑 `cf get`**：只更新样例和元数据，不碰代码。
- **辅助文件**：`gen.*`、`brute.*`、`checker.*`、`interactor.*` 不当作 test/submit 的候选，`cf stress` 默认就用它们。
- **0.3 的旧目录**（`in1.txt` / `ans1.txt`、`cf/contest/x/y/`）照样能测、能交。散放的 `546D.cpp` 也照旧能用。
- **多个候选文件**：保持现在的规则，一定弹菜单，本题的文件在前，新的在前，标出修改时间。

### 配置文件 `~/.config/cf/config.toml`

用 tomlkit 读写，保留注释。

```toml
language = "cpp"              # cf get 写起始代码用的语言（第一次 cf get 时询问并写入）
# root = "~/codeforces"       # cf get 放比赛的地方（默认：当前目录）
# host = "https://codeforces.com"
# proxy = "socks5://127.0.0.1:1080"   # 默认：跟随环境变量

# [cpp]                       # 每种语言一节，按扩展名
# compiler = "g++-15"         # 默认：自动找（GCC 优先）
# flags = "-DLOCAL"           # 追加到默认参数之后
# submit = "G++20"            # CF 语言：名字（或其中一段）或 id；默认：最新的
# template = "~/cp/template.cpp"
# build = "g++ -std=c++20 {src} -o {exe}"   # 完全自定义：替换内置的编译命令
# run = "{exe}"
```

- **占位符**：编译和运行命令用 `{src}`、`{exe}`、`{dir}`、`{name}`；起始代码用 `{{handle}}`、`{{date}}`、`{{time}}`、`{{problem}}`、`{{name}}`、`{{url}}`。旧的 `$%U%$` 等照样替换。
- **未内置的语言**：写一节 `[hs]`，给出 `build` / `run` / `submit` 即可。

### 语言（languages.py，由 presets.py 和 langs.py 合并而来）

- **内置**：C++、C、Python、Java、Kotlin、Rust、Go。
- **工具链探测**：沿用现在的做法（macOS 的 `/usr/bin` 占位程序、GCC 优先、按版本信息去重），结果按 PATH 缓存在 `STATE_DIR`。
- **C++ 编译参数**：
  - `-std` 取自提交语言（G++17 / 20 / 23 对应 c++17 / 20 / 23，老编译器用 `c++2b`）；
  - 栈开到 256 MB：macOS 用链接参数，Linux 用子进程的 `RLIMIT_STACK`，MinGW 用 `--stack`；
  - clang 的 bits/stdc++.h 在编译时临时加 `-I`，不写进配置。
- **Python**：提交 PyPy 时，本机有 pypy3 就用它跑。
- **提交语言**：先看配置的 `submit`；否则从 CF 实时列表里选本语言最新、最合适的一个（列表缓存 1 天，没有就用内置表）。

### 构建与运行（build.py）

- **缓存**：放在 `$XDG_CACHE_HOME/cf/build/<key>/`，key 是源码、编译命令和编译器版本的哈希；源码里有 `#include "…"` 时每次重编；超过 7 天的缓存自动清掉。
- **路径**：`{src}` 用真实路径（修正 `../a.cpp`、`tools/gen.py` 跑错文件的 bug）。
- **运行**：
  - 用独立进程组，超时就杀掉整棵进程树，杀掉后不再无限期等待输出；
  - 输出设上限，超过判 OLE；
  - 统计 CPU 时间和整棵进程树的峰值内存。

### 测试（judge.py）

- **比较**：默认按 token 比较；题面写了误差或允许任意大小写时，自动放宽。
  - 大小写的识别要收紧，不能把 “In any case, …” 这种说法当成“任意大小写”。
  - `--strict` 逐行比较（0.3 的行为），`-e` / `-i` 手动放宽，`--checker CMD` 按 testlib 的参数顺序调用。
- **输出**：每个测试一行 ✓/✗、时间、内存，超限的标出来；失败时左右对照，多组样例只显示出错的那一组。
- **记录结果**：按源码哈希记下测试结果，`cf submit` 发现这份代码的样例没过时会先问一句。
- **`--watch`**：保存代码或测试后自动重新编译、重跑，Ctrl-C 退出。
- **`--add` / `--accept`**：保留。新加的测试按编号接着排，对拍失败的存成 `tests/stress-<seed>`。
- **交互题**：`cf test --interactor X`，题目目录里有 `interactor.*` 时自动使用。
  - 交互器按 testlib 约定以 `interactor <input> <output>` 运行，标准输入输出和你的程序对接；
  - 结果看交互器的退出码：0 通过，1 WA，2 PE，3 FAIL；
  - 没有交互器时，像现在一样提示不能评测。

### Codeforces 这一侧（cf_tool/codeforces/）

- **保留**：三级登录、Cloudflare 处理、完整 cookie 记录、页面解析、提交、listen、contests、pick、CP Editor 兼容。这些都实测过。
- **会话**：会话文件不变，升级后不用重新登录。
- **获取**：`cf get <比赛>` 一次请求 `/contest/<id>/problems` 拿到所有题（已验证现有解析器能处理这个页面），拿不到时退回逐题请求。

review 发现的问题，在这一阶段修复：

1. **服务器出错被当成掉线**：5xx 和 429 页面当作正文处理，被误认为登录失效，于是清掉 cookie 重登，最后弹出浏览器窗口。改为当作网络错误，退避后重试。
2. **提交可能被重发**：提交的 POST 超时后会自动重发。改为绝不重发；结果不明时去 `/my` 查有没有新提交。
3. **并发请求写回旧 cookie**：并发请求结束时，会把旧 cookie 写回 jar。请求和 jar 的修改之间要加锁。
4. **过 Cloudflare 时可能顶掉登录态**：浏览器导出的匿名 JSESSIONID 可能顶掉已登录的会话。过检查时只采用 Cloudflare 的 cookie 和 UA，需要实测确认。
5. **listen 的安全性**：
   - 加 socket 超时，只收 JSON，拒绝网页（http/https Origin）发来的请求；
   - 不是题目的 URL 直接拒绝，不再覆盖当前目录的样例。
6. **其他小问题**：
   - Rich 会把 `:x:` 变成 emoji，改用 `Console(emoji=False)`；
   - clone 遇到 Ctrl-C 要及时停下，500 秒的等待要能打断；
   - 浏览器重启失败时，第一个 Chrome 没有退出。

### 命令

| 命令 | 作用 |
| --- | --- |
| `cf get <比赛\|题目\|URL> [-l 语言]` | 建目录、下样例、写起始代码（取代 parse + gen） |
| `cf race <比赛>` | 倒计时，开赛后执行 get 并打开题面 |
| `cf test [题\|文件] [测试…]` | 跑样例：`-w` / `--add` / `--accept` / `-e` / `-i` / `--strict` / `--checker` / `--interactor` |
| `cf stress [gen] [brute] [solution]` | 对拍：`-n` / `--seed` |
| `cf submit [题] [文件] [-l 语言]` | 提交并实时显示评测 |
| `cf status [题] [--all]` | 你的提交，实时刷新（取代 watch） |
| `cf open [题\|比赛] [--standings\|--last]` | 在浏览器里打开（取代 stand / sid） |
| `cf problems [比赛]` | 比赛的题目和通过人数（取代 list） |
| `cf new [名字]` | 用模板新建代码文件（取代 gen） |
| `cf login` / `cf logout` | 登录、退出 |
| `cf langs [--all]` | 每种语言用哪个编译器、提交成什么、起始代码在哪 |
| `cf config` | 用编辑器打开 config.toml，改完检查一遍 |
| `cf contests` / `pick` / `listen` / `pull` / `clone` / `doctor` / `upgrade` / `completion` | 保留 |

- 隐藏别名：parse→get、gen→new、watch→status、list→problems、stand→open --standings、sid→open --last。
- CP Editor 约定不变：`cf --version` 输出 `cf-tool v0.4.0`；`cf submit <cid> <idx> <file>`；不是终端时输出 `status: …` 行。

### 迁移

- **配置**：0.3 的 JSON 配置在第一次运行时自动转成 config.toml，`~/.cf/config` 的结构相同，一并支持。
  - 带过去：默认语言、各语言的起始代码路径、提交语言 id、host、proxy。
  - 不带过去：编译脚本，改为自动生成。转换时列出丢掉了什么；旧文件原样保留。
- **起始代码**：模板文件不用改，旧占位符照样替换。
- **Go 版**：不再导入 `~/.cf/session`（Go 版早已无法登录）。

## 4. 代码结构

```
cf_tool/
  cli/            按命令分组：__init__（分组、别名、报错）、problems、testing、submitting、account、setup、misc
  settings.py     config.toml、默认值、校验、迁移
  languages.py    语言表、工具链探测、-std、CF 语言选择、起始代码
  workspace.py    题目和比赛目录、元数据、测试文件、目标解析、候选文件（取代 args / codefiles / problem / templates）
  build.py        缓存编译、进程运行（进程组、输出上限、时间、内存）
  judge.py        比较、单个测试、test 流程、watch、交互器
  stress.py  listen.py  views.py  ui.py  errors.py
  codeforces/     client gateway http browser pages session crypto
```

另外：

- 去掉“Port of cmd/xxx.go”和 Go 兼容分支（Go cookie jar 和旧会话格式的读取、`folder_name`、根目录查找）。
- 测试按模块重写，新增全场题面页面的 fixture。
- CLAUDE.md、README、CHANGELOG 重写。

## 5. 阶段（每阶段测试全绿、black 和 flake8 干净后在 v0.4 分支提交，不推送）

0. **准备**（已完成）：建 v0.4 分支；修好 dev venv（把旧的 0.2.0 安装换成 editable 安装）；加 tomlkit 依赖；写本计划。
1. **核心模型**：settings（含迁移）、languages、workspace、build，各自配测试。
2. **命令迁到新核心**：
   - 依次切换：get、race、listen、new、pick；test（含 watch、交互器）、stress；submit、status、login、logout；open、problems、pull、clone、contests。
   - 修复上面列出的网络层问题，删掉旧模块。
3. **体验**：
   - langs、config、doctor、completion；
   - 首次运行问语言、就地登录、提交前提醒；
   - 统一输出风格和报错文案。
4. **文档和发布准备**：
   - README、CHANGELOG、CLAUDE.md，版本号改为 0.4.0；
   - CI 增加 PyPI 发布 workflow（trusted publishing）。
5. **验收**（需要 Fau 在场）：
   - 全部测试，toolchain 测试（CI 上的 Linux 和 macOS），live 测试；
   - 用你的终端在练习题上真实登录、提交一次；
   - 然后由你决定合并、tag、Release、PyPI。

## 6. 无人值守时的规则

- 只在 v0.4 分支上提交，不 push，不打 tag，不发布。
- 不登录，不提交；网络只访问公开页面，用于 live 测试。
- 1Password 锁定时无法签名，所以无人值守期间的提交不签名。Fau 回来后再统一补签，或合并成几个签名提交，然后才合进 main。
