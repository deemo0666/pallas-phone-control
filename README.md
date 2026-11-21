# 在 Pallas 的本机 shell 安装手机操控

这是可选的 Pallas 插件和 siboot 0.18.0 的实验分支。签装器在 Pallas 的 ARM64 Linux 内运行，0.5.4 起签装器把组件连到运行开通流程的那个 Pallas（按插件所在的数据容器在已装 App 中查找），不再限定 TestFlight 版的 App 标识、签名和版本；同一台设备上装了多个 Pallas（例如 TestFlight 版和测试版）时，组件同时为每个开通过的 Pallas 服务：每个 Pallas 一把密钥、一个回环端口，签装时保留此前已连上的 Pallas。测试宿主具备本机 bash、Bonjour 配对服务广播和 Linux 端口转发。测试宿主与发行版 Pallas 使用不同的 App 标识。

## 在 Pallas 安装

在带 SiBoot 隧道扩展的 Pallas 中，导入 0.6.1 插件，在本机对话里说「开通手机操控」。首次使用时允许 iOS 添加「Pallas · SiBoot」VPN 配置即可。旧版宿主可沿用 LocalDevVPN。插件注册技能 `phone-control-setup`，agent 加载后按 `setup.sh` 报告的状态一步一步带用户完成，已满足的步骤自动跳过。

1. **安装。** 按对应入口操作：
   - 插件市场（发布后）：Pallas 切到本机引擎，「全部功能 → 插件 → 插件市场」搜「手机操控」，安装。
   - 离线导入：把插件 ZIP 存到「文件」（WodeiPad 用 `pallas-siboot-runner-wodeipad.zip`，其他设备用 `pallas-siboot-runner.zip`），在 0.4.0（8）中，切到本机引擎，打开「全部功能 → 插件 → 导入 → 离线插件包 → 选择插件包文件」，选择 ZIP 后点「导入并启用」。在 0.3.4（7）中，先在「文件」里点 ZIP 解压。Pallas 切到本机引擎，打开「全部功能 → 插件 → 已安装 → 导入桌面插件目录」，选择解压后直接包含 `package.json` 的文件夹，点「导入并启用」。

   若已装旧版同名插件，请先卸载，再导入 0.6.1。0.5.0 起包名由 `pallas-siboot-probe` 改为 `pallas-phone-control`。装新包前必须先在插件详情卸载旧的 `pallas-siboot-probe`，否则两个插件会同时写状态页配置、同时排续期。签装状态和续期计划保存在插件目录之外，卸载不会丢。
2. **开通。** 在本机对话里说「开通手机操控」。agent 自己执行检查、探测端口、启动签装、跟踪进度和最后的验证，只在系统要求本人操作时交给用户，每次一步。首次在系统提示中允许本机隧道、允许「本地网络」、在本机签装页登录 Apple 账号、到「设置 → 隐私与安全性 → 开发者模式 → 其他设备」点「Pair with siboot」并输入锁屏密码和状态页上的六位码、打开「设置 → 手机操控」的开关。Apple 账号、密码和双重认证码只在签装页填写，技能要求 agent 不在聊天里索要或复述。
3. **验收。** 组件装好后，agent 用 `iphone_screen` 打开计算器按 37 × 19，读到 703 即完成，再报告组件到期时间和自动续期状态。也可以在「设置 → 手机操控」点「试一下手机操控」。

如果刚从 0.3.1 更新，执行器仍可直接使用；要让 0.3.4 自己负责续期，仍需在 0.3.4 内完成一次签装，以便它保存自己的配对记录、Apple 会话和签装回执。说「开通手机操控」即可，agent 看到没有本机续期记录会重新签装。

### 引导脚本

技能的内容在 `SKILL.md`，加载时把 `{{DIR}}` 换成当前版本的目录。`setup.sh` 是 agent 用的入口，每条命令最后一行是 `next: <步骤>`：

```sh
sh /root/workspace/siboot-runner-0.6.1/setup.sh status
sh /root/workspace/siboot-runner-0.6.1/setup.sh start [--port N] [--new-login]
sh /root/workspace/siboot-runner-0.6.1/setup.sh wait [秒]
```

- `status` 报告插件状态页、后台任务、当前阶段、签装目录是否可写、是否已有配对记录和 Apple 会话、组件到期时间、自动续期，并在需要时探测 VPN 和端口。步骤有 `start`、`renew`、`tunnel_unavailable`、`connect_vpn`、`allow_local_network`、`port_unknown`、`sign_in`、`pair_in_settings`、`enter_code`、`wait`、`full_access`、`host_unsupported`、`failed`、`enable_plugin`、`verify`，各自的处理写在 `SKILL.md`。
- 端口不再手填。插件经本机隧道的设备地址 10.7.0.1 依次试连上次签装用的端口、`lan_services` 浏览并解析出的 `_remotepairing._tcp` 端口，只有本设备的端口能连通；都不通时扫描 49152–65535（跳过 62078），取第一个开放端口。10.7.0.1 本身连不上即判定 VPN 未连接。
- `status` 只检查当前状态。`start` 按需启动本机隧道，探测后执行 `install.sh --open <端口>` 并输出状态页链接，随后最多跟踪 25 秒，已有配对时可直接到登录页。签装目录不可写时得到 `full_access`：请用户在「设置 → 权限」为当前对话选择「完全权限」后重试，成功后改回。
- `--new-login` 等于在签装命令前加 `PALLAS_NEW_LOGIN=1`，用于换 Apple 账号。

出现 Apple 7460 表示账号的开发证书名额已满，签装页会让你选择。可以保留现有证书并退出；撤销旧证书会影响其他使用它签名的 App。

`install.sh` 仍可手动运行：`sh /root/workspace/siboot-runner-0.6.1/install.sh --open <端口>`，去掉 `--open` 时在前台等待退出码。

## 发布到插件市场（未执行，由用户决定）

App 的插件市场读 `https://api.dshfind.com/market/dsh-index.json`（dshfind.com 社区目录，每日生成）。按 dshfind 源码（`hikariming/dshfind` 的 `scripts/lib/dsh-index.mjs`、`scripts/lib/npm-discovery.mjs`），一个包进索引要同时满足：

- 有公开 GitHub 仓库，且被发现：仓库挂 topic `dsh-plugin`，或 npm 包 keywords 含 `dsh-plugin` / `dsh-bundle`（本包已加）。新仓库按批次「慢慢补」，可能要等几天。
- `package.json` 声明 `dsh.bundle`（已有），已发布到 npm，最新版是精确 semver。
- npm 包的 `repository` 指回该 GitHub 仓库（`npm_repo_backlink`）。仓库地址未知，**发布前要在 package.json 加上 `"repository": {"type": "git", "url": "git+https://github.com/<owner>/pallas-phone-control.git"}`**（子目录发布再加 `directory`）。
- 未被运营标为风险（`is_risky`，人工标记，标了沉底并挂警示）或蹭热度（隐藏）。名字不以 `@deepseek-ai/` 开头。

市场里显示的**标题就是 GitHub 仓库名**，简介是 GitHub 仓库的 description，作者和图标是仓库所有者。所以建议：

- npm 包名与仓库名：`pallas-phone-control`（npm 上目前没人用；不要含 theme、skin、client-ui、web-ui，App 会把这类当网页界面插件藏起来）。
- 仓库 description（即市场简介）：「手机操控 Phone Control：让 Pallas Agent 操作这台设备上的其他 App。安装后在对话里说『开通手机操控』。」App 的搜索按空格拆词逐个匹配名字、标题、简介，所以「手机操控」「phone control」都能搜到。
- 分类由 dshfind 自动判定，期望是 `tools`；可以联系运营手动定。

App 侧：`PluginPolicy` 只拒绝改界面的插件（`dshGo` 键、`dsh.client`、导出 `./client`），本包都没有。npm 安装（`PluginDownload`）核对 integrity，要求依赖要么打进包里要么引擎自带（本包无依赖），再交给与离线导入相同的 `local-plugins.cjs`；那里只拒绝符号链接、特殊文件和扩展名为 `.node/.dylib/.dll/.so` 的原生库。`siboot-runner-aarch64` 没有这些扩展名、IPA 是普通文件，都放行。包体积 npm 压缩约 6 MB、解包约 12 MB，低于 64 MB / 160 MB 上限。`package.json` 的 `files` 决定 npm 包内容（不含 `checks/`、`validation/` 截图和 WodeiPad 专用安装页），`checks/check-import.cjs` 会用 `npm pack` 的结果走一遍与市场安装相同的导入。

发布前的阻碍：

- **许可**：0.5.6 起签装器不再编入 SideInstaller 的代码，只含 siboot（MIT）、idevice 和 isideload（MIT）、apple-codesign-quick（LGPL-2.1-or-later）和本插件自写代码，二进制可以随包分发；LGPL 要求随附可重新链接的源码，`fork/` 已包含。
- GitHub 仓库需公开插件源码（目前在私有仓库里且被 .gitignore 忽略）。
- 签装器把组件连到运行插件的 Pallas。宿主需提供配对、端口转发和执行器所用的接口（0.3.4 起具备）。

## 自动续期

成功安装、核对执行器并读回连接密钥后，插件保存描述文件的实际到期时间，默认开启自动续期。在具备本机 Linux 的 Pallas 宿主运行时，启动即检查，之后每 15 分钟检查一次。在到期前 48 小时内会尝试续期。失败后至少隔一小时重试。iPadOS 挂起宿主时会暂停这个计时器，再次打开宿主可继续检查。此前真机续期验证在「Pallas 配对测试」中完成。

续期使用同一设备、Apple 团队、开发证书、执行器和 Pallas 连接密钥。配对失效、账号会话过期或证书不可用时，需要打开签装器处理。自动任务只使用已有证书。手动安装以及自动续期共用一把锁。

```sh
sh /root/workspace/siboot-runner-0.6.1/renew.sh status
```

子命令 `disable` 关闭自动续期，`enable` 重新启用，`now` 立即续签。续期时重新探测设备端口，并使用已授权启用的本机隧道访问设备。若系统配置已停用，打开 Pallas 并运行 `setup.sh start` 重新授权。续期还需能访问 Apple。正在使用其他个人 VPN 时，iOS 可能会切换连接。使用完毕可在原 VPN 中查看连接状态。

## 设置里找不到开发者模式时

不用电脑。在本机对话里，agent 发现设置里没有「开发者模式」时运行：

```sh
sh /root/workspace/siboot-runner-0.6.1/setup.sh reveal
```

插件在后台跑 `reveal.sh`（`reveal.py`）：

1. 下载固定版本的 cloudflared（2026.11.1 linux-arm64，校验 SHA-256，存在 `/root/.pallas-siboot/bin`），在本机 Linux 起一个只听回环的小网站，经 Cloudflare 临时隧道拿到公网 HTTPS 地址。路径里带随机令牌。
2. 输入框上方的卡片给出「在 Safari 打开」。用户下载「Pallas 识别本机」描述文件，在「设置」里安装。它是 Profile Service，只把 UDID、型号、系统版本回传到上面的地址，带随机 challenge 校验，不留下任何设置。回传地址必须是 HTTPS：用 http 时系统直接报「描述文件安装失败」，不回传。
3. 签装器 `siboot reveal` 用免费 Apple 账号登录（和正常安装同一个登录页、同一份会话），把这个 UDID 登记进个人团队，用正常安装将来要用的同一个 App ID 和证书给执行器签名，不连设备、不安装。
4. 卡片再给出安装页。用户在 Safari 点「安装」。装不装得上都可以：系统看到描述文件里登记了本机，就会在「设置 › 隐私与安全性」里显示开发者模式。
5. 任务以「请打开开发者模式」结束。用户打开开关、重启，再回到 Pallas 做正常的配对和安装。

用户离开 Pallas 去 Safari 和设置时，App 靠 `PairingKeepAlive`（任务在跑就申请后台续命）保持运行；否则 iOS 在 30 秒后冻结整个 App 连同 Linux，隧道随之断开。

2026-11-20 在同一台重置过的 iPad（iPadOS 27.2.1）上的对照：未签名的包、签名有效但没登记本机的包都装不上，开关也不出现；登记了本机 UDID 的免费团队签名包同样装不上，但开关出现了。Profile Service 回传 UDID 在 HTTPS 下约 12 秒完成。wode16 上 cloudflared 在本机 Linux 里能跑，前台每次请求 0.2–0.8 秒。完整的 `setup.sh reveal` 流程还要在一台开关被隐藏的设备上从头走一遍。

## 实现与状态

插件在 iOS 回环地址上发布状态页。Linux 签装器也只在回环地址监听，两端使用带随机口令的反向连接转发登录页面。登录和双重认证由上游 siboot 的设备内页面处理。签装器使用上游 Apple 登录代码以及 ani.iloader.app 的 anisette 服务。配对记录、Apple 开发者会话和签名私钥保存在本机 Linux 磁盘的 /root/.pallas-siboot，目录权限为 0700。脚本需要写入该磁盘。

签装器验证随包 IPA 的固定 SHA-256、Apple 描述文件的 Personal Team 标记、有效期、证书、设备和 App ID。安装完成后，从安装服务重新查找组件，并写入和读回 Pallas 的执行器连接密钥。遇到证书上限时，设备上的选择页允许保留原证书并退出。选择某张证书并再次确认撤销后，签装器才会向 Apple 撤销它。

源代码基于上游 [siboot 固定提交](https://github.com/FrizzleM/siboot/tree/4ae7ef873490ee6ca7b9111e5ad2cf4fc0cb664d/minis)。fork/ 目录含补丁、runner 源文件及构建脚本。runner.sha256 记录两个设备端文件的校验值。

## WodeiPad 真机结果（2026-11-14）

独立的 Pallas 0.3.3 (6) 测试包使用当前源码的通用局域网桥接。Mac 部署并启动测试包后，Pallas 的 Linux shell 在 iPadOS 27.2.1 内完成初次配对、重启后复用、隧道、RSD 和 lockdown 查询。签装命令经本机页面完成免费 Apple 账号登录。Apple 返回证书名额已满（7460）；设备端选择并确认后，签装器取得新证书、验证描述文件、签名、安装并读回宿主密钥。退出码为 0。

TestFlight Pallas 0.3.1 (4) 随后启动新执行器，实际在系统计算器按出 37 × 19，诊断页读回 703。Mac 负责部署独立测试包和观察画面。测试时使用前台等待的签装命令，由测试包直接展示设备内登录页面。配对、签名和安装均在 iPad 上完成。

0.3.1 的发布源码缺少本插件初次配对所需的 `lan_services` 和 `dsh_guest_forward`。该版本作为手机操控宿主已通过验收。0.3.4（7）源码具备初次配对的局域网接口和回环端口转发，0.4.1 已将其加入 TestFlight 宿主版本检查。已在 Mac 上用 0.3.4 的 Swift 解包代码、本地插件安装模块和随附 Cordis 运行时检查两个 ZIP，验证插件启动、签装页响应、局域网工具调用接口以及 Linux 文件校验。该检查为局域网工具提供了测试响应。0.3.4 从导入到签装并读回 703 的完整真机测试尚未执行。早期配对记录见 validation-2026-11-14.json。

0.5.0 的引导只做了本地检查（2026-11-14）：`checks/` 下 `check-setup.cjs` 用本机监听端口模拟设备，验证端口探测（Bonjour 记录、上次端口、IPv6 描述、扫描回退、VPN 未连接）和 `setup.py` 在无 VPN、等待配对、显示配对码、已知失败、已安装与待续期各状态给出的步骤；`check-import.cjs` 用 App 的解包代码、本地插件安装模块和 Cordis 运行时导入两个 ZIP，验证插件启动、技能注册与 Linux 文件校验；`check-skill.mjs` 用引擎的 SkillRegistry 列出并加载该技能；`check-plugin.cjs`、`check-mode.cjs` 是原有的状态页和开发者模式入口检查；`package.py` 打包两个 ZIP（WodeiPad 包沿用上一版的安装页地址，加 `--check-url` 才检查是否仍可访问）。真机上的对话引导、10.7.0.1 端口探测和完整签装尚未验证。

### 本次重复安装与自动续期

同一台 WodeiPad 跳过了已开启的开发者模式、Safari 安装页、配对码与交互登录。设备内重复签装返回 0。随后只在测试宿主把一次检查的续期窗口放宽到 8 天，正式插件保持 48 小时。调度器从启动时的检查进入无交互续期路径，仍使用设备与 Apple 的真实时间。iPad 系统列出的同一执行器最新描述文件到期时间依次为 2026-11-21 14:43:54、15:07:28、15:09:05（太平洋时间）。前两项分别为复测前和重复签装后，最后一项为自动续期后。TestFlight Pallas 再次操作系统计算器，并读回 703。本轮没有关闭开发者模式重做首次触发，也没有等待七个自然日。证据见 validation-2026-11-14.json。

## 第三方来源及许可

0.5.6 起签装器不含 SideInstaller 的代码：Apple 登录与会话复用（`fork/login.rs`）、错误文本（`fork/error_text.rs`）、续签时只用已有证书的检查（`fork/runner.rs`）由本插件自写；idevice、isideload、apple-codesign-quick 改用各自上游的原版（crates.io 与 isideload 固定提交），构建时不拉 SideInstaller 子模块。逐项清单与许可文本见 `licenses/THIRD-PARTY.md`。

- siboot 0.18.0 的 Rust 工程在 Cargo.toml 声明 MIT。[固定版本清单](https://github.com/FrizzleM/siboot/blob/4ae7ef873490ee6ca7b9111e5ad2cf4fc0cb664d/minis/Cargo.toml)。本插件对配对桥、页面、签装和续期的修改见 `fork/runner.patch`。
- idevice 0.1.68（MIT）、isideload 326e562（MIT）、apple-codesign-quick 0.1.0（LGPL-2.1-or-later，全文见 `licenses/LGPL-2.1.txt`）。
- 与 0.5.4 相比少了的能力：两步验证不再支持「打电话报码」（上游没有），保存的 Apple 会话换了新格式，升级后第一次签装需要重新登录一次。

设备通信使用 Bonjour 发布配对服务，经 RPPairing 验证建立 TLS-PSK 隧道，再通过 RSD 发现 AFC、installation_proxy 和 House Arrest 等系统服务。
