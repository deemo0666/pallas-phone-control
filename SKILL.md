# 开通手机操控

你带用户一步一步开通手机操控。插件已把脚本放在本机 Linux 的 `/root/workspace/{{DIR}}/`。用 bash 工具执行下面的命令，读最后一行 `next:` 决定下一步。用用户的语言回复。

```sh
sh /root/workspace/{{DIR}}/setup.sh status      # 检查每一步，已满足的自动跳过
sh /root/workspace/{{DIR}}/setup.sh start       # 自动找端口，后台开始配对和安装，输出 link
sh /root/workspace/{{DIR}}/setup.sh wait        # 跟踪进行中的任务，阶段变化或 45 秒后输出状态
sh /root/workspace/{{DIR}}/setup.sh reveal      # 设置里没有「开发者模式」时，让开关出现
sh /root/workspace/{{DIR}}/setup.sh trusted     # 用户已在设置里信任开发者之后执行，进入验证
sh /root/workspace/{{DIR}}/setup.sh reset       # 清除配对、Apple 登录和钥匙串里的备份，从头开通
```

## 规则

- 先跑 `status`，不要凭记忆判断进度。端口由脚本自己探测，不要让用户提供，也不要自己填固定数字。
- 能自己做的自己做：检查、启动、跟踪、最后验证。只有系统要求本人操作的才交给用户。
- 一次只让用户做一件事，说清在哪个 App、哪个页面、点什么。说完就结束这一轮，等用户回来说「好了」再跑 `status`。
- Apple 账号、密码、双重认证码只在本机签装页里填写。不要在聊天里索要、确认或复述它们；用户发了也不要使用，提醒对方只在页面里填。页面上的六位配对码也让用户直接看页面。
- 界面名称以中文界面为准，用户用英文界面时按意思说明。
- `status` 的 `page:` 与 `start` 的 `link:` 是本机状态页（`http://127.0.0.1:…`）。发给用户时做成可点击的链接，让用户在 Pallas 里打开并保持页面开着；这个页面会随进度变成登录页或显示配对码。

## 按 next 处理

- `start`、`renew`：直接执行 `setup.sh start`，再按新的 `next` 处理。`renew` 表示组件快到期或已过期，同样重新签装；已有配对和登录会自动复用，通常不需要用户操作。
- `tunnel_unavailable`：请用户在 Pallas 前台再试一次，首次启动时允许 iOS 添加 VPN 配置。
- `connect_vpn`（旧版 Pallas）：请用户打开 LocalDevVPN，点连接，看到 Connected 后回到 Pallas。
- `allow_local_network`：请用户到「设置 → 隐私与安全性 → 本地网络」打开 Pallas Agent，再回来。
- `port_unknown`：VPN 通了，但设备没有应答配对端口。最常见原因是开发者模式没开。请用户确认「设置 → 隐私与安全性 → 开发者模式」已打开（打开后系统会要求重启并确认）。如果已开，在 Pallas 前台重试 `setup.sh start`。如果设置里根本没有「开发者模式」，执行 `setup.sh reveal`，按它的 `next` 处理（不用电脑就能让开关出现）。
- `sign_in`：请用户打开状态页链接，用 Apple 账号登录；双重认证码也在页面里填。页面若提示开发证书名额已满（Apple 7460），说明撤销旧证书会让用它签名的其他 App 失效，建议保留现有证书并退出，除非用户确定要撤销。用户说好了以后跑 `wait`。
- `pair_in_settings`、`enter_code`：请用户打开「设置 → 隐私与安全性 → 开发者模式」，在「其他设备」点「Pair with PallasBoot」，输入锁屏密码，再输入状态页上显示的六位码，然后回到 Pallas。
- `identify_device`：开关被隐藏时的第一步。请用户点输入框上方卡片里的「在 Safari 打开」，在 Safari 下载「Pallas 识别本机」，再打开「设置」，点顶部的「已下载描述文件」安装（要输锁屏密码），然后回到 Pallas。这个描述文件只读取设备标识，不会留下任何设置。卡片不见了就把 `link:` 做成链接，请用户长按选「在 Safari 中打开」。用户回来后跑 `setup.sh wait`。
- `install_in_safari`：请用户点卡片里的「在 Safari 打开」，在页面上点「安装」，系统再问时点「安装」。系统提示「无法安装」是正常的，开关正是因此出现，不要重试；接着跑 `setup.sh wait`。
- `turn_on_developer_mode`：请用户打开「设置 → 隐私与安全性 → 开发者模式」，打开开关，按提示重启，重启后确认打开。告诉用户重启后回到 Pallas 说「继续开通手机操控」。用户回来后先跑 `status`，按新的 `next` 继续（通常是 `start`）。重启会结束正在跑的签装任务，这是正常的，重新 `start` 即可，已有配对和登录会复用。如果用户说开关还是没出现，请用户等一两分钟再看一次；仍没有就把 `last_result` 告诉用户。
- `wait`：任务在跑但还没到需要用户的步骤。执行 `setup.sh wait`，最多连续两次，然后按结果处理。
- `full_access`：本机签装目录不可写。请用户在 Pallas「设置 → 权限」把当前对话设为「完全权限」，回来后你再执行 `setup.sh start`。全部完成后提醒用户可以改回原来的权限。
- `host_unsupported`：当前 Pallas 版本缺少所需接口，或这版插件不支持当前 Pallas 版本（`last_result` 含 `Expected Pallas`）。告诉用户需要更新 Pallas 或换用匹配的插件包，不要反复重试。
- `paid_account`：`last_result` 含 `paid_team` 是付费开发者账号（个人或公司），含 `multiple_teams` 是这个账号属于不止一个开发团队。这两种情况签装器在动账号之前就停下了：没有登记设备、没建 App ID，也没申请或撤销证书，可以这样告诉用户。含 `paid_team_profile` 时是签名后才发现，设备已登记进那个团队，不要说账号没动过。手机操控只能用只有免费个人团队的 Apple 账号。告诉用户：可以另外注册一个免费 Apple 账号，专门用来签手机操控，不需要是平时登录 iCloud 的账号，也不用付费；准备好后说一声，你再执行 `setup.sh start --new-login`。不要把 `paid_team`、`multiple_teams` 这些代码念给用户。
- `failed`：用一两句话说明 `last_result` 的原因和对应做法，然后问用户是否重试；重试就执行 `setup.sh start`。常见原因：`won't let Pallas reach` 是 VPN 没连；网络错误是访问 Apple 失败，检查网络后重试；页面里取消或超时直接重试。要换 Apple 账号时执行 `setup.sh start --new-login`（开关被隐藏、正在跑 reveal 时是 `setup.sh reveal --new-login`）。
- 用户要求清除手机操控的数据、从头开通，或彻底换一个 Apple 账号时，先确认用户知道之后要重新配对和登录，再执行 `setup.sh reset`，然后按输出的 `next` 继续。它不会删掉已装的组件，也不会关闭开发者模式。
- 用户说「手机操控续期没成功」（点了续期失败的通知，或设置里有效期一行显示「续期没成功」「已过期」）：跑 `status`，用一两句话说明 `auto_renewal` 里的出错原因，然后执行 `setup.sh start` 重新签装；需要重新登录 Apple 账号时，`next` 会是 `sign_in`，照常处理。
- `ios_too_old`：这台设备的系统是 `ios:` 那个版本，低于 iOS 27。在设备上自己配对是 iOS / iPadOS 27 才有的，现在开通不了。告诉用户把系统升级到 iOS 27 或更新版本后，回到 Pallas 说「开通手机操控」。不要执行 `start` 或 `reveal`，也不要让用户去设置里找配对入口。
- `enable_plugin`：插件没有启用，请用户在插件列表里启用它。
- 用户明确要求用新版插件更新 ScreenRunner 时，运行一次 `setup.sh start` 安装随包执行器，即使首次 `status` 因旧组件签名仍有效而返回 `verify`。本轮安装完成后按正常流程验证。
- 验证或使用时若报 `runner_launch_refused`（「系统没有让手机操控启动」）：先跑 `status`。`installed_until` 显示已过期，或 `next` 是 `renew`，就是组件过期了：直接执行 `setup.sh start` 重新签装，不要挂运行环境，也不要让用户去信任。没过期时，先执行 `setup.sh ddi`（重启后要重新挂载组件需要的开发者运行环境，约半分钟），看到 `next: verify` 再验证一次。仍被拒，或用户说屏幕上弹出了「未受信任的开发者」，就是还没信任开发者：按 `trust_developer` 带用户去信任，再验证。不要让用户自己去设置里试手机操控。
- `trust_developer`：组件刚装好，iOS 要用户先信任它的开发者才让它启动，否则会弹「未受信任的开发者」。请用户打开「设置 → 通用 → VPN 与设备管理」，在「开发者 App」下点以「Apple Development」开头、后面是自己 Apple 账号的那一行，点「信任“Apple Development: …”」，弹窗里再点「信任」，然后回到 Pallas 点卡片上的「信任好了，验证」或说「好了」。说完就结束这一轮。用户说已经信任后，先执行 `setup.sh trusted`，再按 `verify` 验证。页面上只剩「删除 App」说明早就信任过，同样执行 `setup.sh trusted`。
- 状态里有 `runner: missing`，或验证时报 `runner_not_installed`（「手机操控还没有开通」），或用户说把手机操控组件删了：组件已不在这台设备上，直接执行 `setup.sh start` 重新签装，已有配对和登录会复用，装好后照常带用户信任开发者、再验证。
- `verify`：组件已安装并已信任。如果你有 `iphone_screen` 工具，自己验证：打开计算器（`{"bundleParts":["com","apple","calculator"],"action":"open"}`），按 3、7、×、1、9、=，观察结果是 703。如果没有 `iphone_screen` 工具，请用户打开「设置 → 手机操控」把开关打开（若已打开，切到别的 App 再回来），然后说「继续」，你再验证。用户也可以在「设置 → 手机操控」点「试一下手机操控」，看到「试过了，手机操控可以用。」即成功。验证时若报 `runner_group_unavailable`（「手机操控和这个版本的 Pallas Agent 对不上」），说明组件还没连上当前这个 Pallas：不要让用户更新 Pallas，直接执行 `setup.sh start` 重新签装，组件会加上当前这个 Pallas，原来连着的也保留，已有配对和登录会复用；装好后再验证一次。

## 完成后

验证通过后，再跑一次 `status`，用两三句话告诉用户：手机操控已可用，组件签名到期时间（`installed_until`），自动续期是否开启（`auto_renewal`，开启时会在到期前 48 小时内自动续期，Pallas 打开时检查，需要能访问 Apple。新版 Pallas 会在续期期间自动启动已授权的本机隧道。旧版需要连接 LocalDevVPN）。若有 `上次续期出错`，一并说明。
