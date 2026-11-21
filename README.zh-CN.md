# Pallas 手机操控

[English](README.md) | 简体中文

手机操控是 [Pallas Agent](https://github.com/deemo0666/pallas-agent) 的可选插件，让 AI 操作 iPhone 或 iPad 上的其他 App。开通全程在设备上完成，不需要电脑。

## 需要

- iOS / iPadOS 27 或更新版本（在设备上自己配对是 iOS 27 才有的）。
- 带本机引擎和本机 Linux shell 的 Pallas Agent。
- 一个免费 Apple 账号（用于给设备上的执行器签名，只在签装页填写，不在聊天里输入）。
- 开通和续期时能访问 Apple。

## 安装插件

Pallas 切到本机引擎，任选一种：

- **插件市场：**「设置 → 能力 → 插件 → 插件市场」搜「手机操控」，点安装。
- **离线包：**把 `pallasboot-runner.zip` 存到「文件」，打开「设置 → 能力 → 插件」，点「添加插件 → 选择文件或文件夹」，选中 ZIP 后点「导入并启用」。

装过旧版（包括旧包名 `pallas-siboot-probe`）的，先在插件详情里卸载。签装状态和续期计划存在插件目录之外，卸载不会丢。

## 开通

在本机对话里说**「开通手机操控」**。agent 会检查哪些已经完成并跳过，其余的每次带你做一步。第一次需要：

1. 允许 iOS 添加「PallasBoot」VPN 配置（连到设备自身的本机隧道，流量不出手机）。
2. 允许「本地网络」。
3. 在设备内的签装页登录 Apple 账号。
4. 打开「设置 → 隐私与安全性 → 开发者模式 → 其他设备」，点「Pair with PallasBoot」，输入锁屏密码和状态页上的六位码。
5. 打开 Pallas「设置 → 手机操控」的开关。

完成后 agent 打开计算器按 37 × 19，读到 703 即开通成功，并告诉你组件到期时间和自动续期状态。之后也可以在「设置 → 手机操控」点「试一下手机操控」。

### 设置里找不到开发者模式

告诉 agent，它会运行 `setup.sh reveal`。按提示在 Safari 打开链接，安装「Pallas 识别本机」描述文件（只回传 UDID、型号和系统版本，不留下任何设置），再在签装页点「安装」。之后「设置 → 隐私与安全性」里就会出现「开发者模式」。打开、重启，回到 Pallas 继续开通。

### 证书名额已满（Apple 7460）

Apple 账号的开发证书数量到了上限。签装页可以选择保留现有证书并退出，或撤销其中一张。撤销会影响用这张证书签名的其他 App。

## 自动续期

免费 Apple 账号签的 App 7 天到期。安装成功后默认开启自动续期：Pallas 启动时检查，之后每 15 分钟检查一次，到期前 48 小时内续期，失败后至少隔一小时重试。系统挂起 Pallas 时检查暂停，再次打开后继续。

续期沿用同一份配对、Apple 会话和证书。配对失效、会话过期或证书不可用时，再说一次「开通手机操控」即可。

## 命令

这些命令通常由 agent 执行。路径里的版本号按实际版本替换。

```sh
sh /root/workspace/pallasboot-runner-0.7.3/setup.sh status        # 当前状态和下一步
sh /root/workspace/pallasboot-runner-0.7.3/setup.sh start [--new-login]   # 开始签装；--new-login 换 Apple 账号
sh /root/workspace/pallasboot-runner-0.7.3/setup.sh wait [秒]
sh /root/workspace/pallasboot-runner-0.7.3/setup.sh reveal        # 让开发者模式出现
sh /root/workspace/pallasboot-runner-0.7.3/renew.sh status        # 另有 enable | disable | now
```

`start` 报 `full_access` 时，在「设置 → 权限」为当前对话选「完全权限」后重试，完成后改回。

## 隐私与安全

- 状态页和签装器只监听设备上的回环地址。
- 配对记录、Apple 会话和签名私钥存在本机 Linux 磁盘的 `/root/.pallasboot`（权限 0700）。
- 签装器安装前核对随包执行器的固定 SHA-256 和描述文件；只有你选中并确认后才会撤销证书。

## 源码与许可

签装器基于 [siboot](https://github.com/FrizzleM/siboot/tree/4ae7ef873490ee6ca7b9111e5ad2cf4fc0cb664d/minis)（MIT），并使用 idevice、isideload（MIT）和 apple-codesign-quick（LGPL-2.1-or-later）。补丁、执行器源码和构建脚本在 `fork/`，`runner.sha256` 记录设备端文件的校验值。详见 [LICENSE.zh-CN.md](LICENSE.zh-CN.md) 和 [licenses/THIRD-PARTY.md](licenses/THIRD-PARTY.md)。
