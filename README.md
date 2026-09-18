# Edge Copilot 修复工具

**简体中文** | [English](./README_EN.md)

用于诊断和修复 Microsoft Edge 中与 Copilot 入口显示有关的本地配置。提供中文交互菜单，也支持完整命令行参数，适合手动使用或自动化执行。

**单文件运行：只需下载 [patch_edge_copilot.py](./patch_edge_copilot.py)。** 种子文件处理逻辑已经内置，不需要其他本地 Python 模块。

脚本支持旧版 JSON 配置，以及新版 `VariationsSeedV2` 中的国家元数据。曾在 Windows、Edge **153.0.4234.32** 环境下实际修复 Copilot 入口；这不代表所有版本、账户和网络环境都能得到相同结果。

## 目录

- [功能](#功能)
- [环境与安装](#环境与安装)
- [快速开始](#快速开始)
- [交互菜单](#交互菜单)
- [命令行用法](#命令行用法)
- [参数参考](#参数参考)
- [自动化执行](#自动化执行)
- [配置目录与修改范围](#配置目录与修改范围)
- [关闭与重新打开浏览器](#关闭与重新打开浏览器)
- [备份与恢复](#备份与恢复)
- [工作原理与限制](#工作原理与限制)
- [常见问题](#常见问题)
- [测试](#测试)
- [问题反馈](#问题反馈)
- [参考资料](#参考资料)

## 功能

- **中文菜单**：无参数启动，输入数字选择修复、预览、诊断等操作。
- **命令行模式**：带参数时直接执行，不弹出菜单或交互问题。
- **新版种子修复**：可同步 `VariationsSeedV2` 中已有的国家字段，保留实验内容、签名及其他字段。
- **多通道与多配置**：支持指定 Stable、Beta、Dev、Canary，或自定义用户数据目录。
- **进程检查**：修改前确认 Edge 退出，提供 PID 和进程类型诊断。
- **自动备份**：修改前备份原始字节，随后原子替换并读回校验。
- **可选重开**：修复成功后可自动打开目标配置的 Edge 窗口。
- **重复执行**：已符合目标的配置不重复写入，也不重复生成备份。

## 环境与安装

| 项目 | 要求与说明 |
| --- | --- |
| Python | 3.8 或以上；已在 Python 3.8 环境运行验证 |
| Microsoft Edge | 已安装，并至少启动过一次，以生成用户配置 |
| Windows | 已实际验证；包含 Windows 进程退出检查和注册表只读诊断 |
| macOS / Linux | 包含路径发现和基础处理逻辑，尚未进行同等程度的实际验证 |
| `psutil` | 用于检查和关闭浏览器进程 |
| Zstandard 支持 | 推荐安装 `zstandard`；也可使用脚本能找到的现有 Zstandard 动态库 |

下载脚本和 [requirements.txt](./requirements.txt) 后，在文件所在目录打开 PowerShell 或终端，安装依赖：

```powershell
python --version
python -m pip install -r requirements.txt
```

如果只下载了单个脚本，也可以直接安装：

```powershell
python -m pip install "psutil>=5.8.0" "zstandard>=0.23.0"
```

如果系统使用 `python3` 或 `py` 启动 Python，请相应替换文中的 `python`，并用同一个解释器安装依赖、运行脚本。

“单文件”指不依赖其他项目内的 `.py` 文件，仍需要 Python 和上述运行环境。脚本不会自动安装依赖。

请以日常使用 Edge 的同一系统用户运行。通常不需要管理员权限；以另一个账户运行可能访问到错误的配置目录。

## 快速开始

```powershell
python patch_edge_copilot.py
```

1. 先保存 Edge 网页中尚未提交的内容。
2. 菜单默认目标是 **正式版 / Default**。如果使用其他通道或配置，先选择 `5` 更换目标。
3. 可先选择 `2`，查看计划修改的内容。
4. 选择 `1` 修复 Copilot。
5. 在“修复成功后重新打开 Edge 窗口？”处，按回车或输入 `y` 表示打开，输入 `n` 表示不打开。
6. 完成后在 Edge 中检查 Copilot 入口；未选择自动打开时，请手动启动浏览器。

只进入菜单不会修改配置。只有选择修复，或使用命令行 `--apply`，才会尝试写入。

## 交互菜单

```text
========== Edge Copilot 修复工具 ==========
当前配置：正式版 / Default
1. 修复 Copilot（自动关闭 Edge）
2. 预览修复内容
3. 只读诊断
4. 查看 Edge 进程
5. 更换浏览器通道 / 配置目录
0. 退出
请选择操作 [0-5]：
```

| 选项 | 行为 |
| --- | --- |
| `1` | 应用 JSON 补丁及新版种子国家修复，必要时关闭 Edge，并询问是否在成功后重开 |
| `2` | 预览包括种子修复在内的计划变更，不关闭浏览器、不写文件 |
| `3` | 只读检查当前配置，Windows 下还会检查相关注册表策略和代理设置状态 |
| `4` | 列出当前用户的活动 Edge 进程，帮助定位后台残留 |
| `5` | 选择通道或自定义 User Data 目录，再指定配置目录名 |
| `0` | 退出程序 |

操作结束后按回车返回菜单。目标选择仅保留到本次程序退出，不写入额外的设置文件。

选择配置目录时：

- 直接回车：使用 `Default`。
- 输入 `Profile 1` 等目录名：只处理该配置的 `Preferences`。
- 输入 `*`：处理该用户数据目录下全部已有的常规配置。

这里填写的是**磁盘目录名**，不是 Edge 界面中的账户昵称。菜单不会默认使用 `--force-close`。

## 命令行用法

以下示例以正式版的 `Default` 配置为例。**一旦提供参数，就不会进入菜单。** 仅提供路径、通道等参数而不指定操作时，默认执行只读诊断。

### 查看帮助或诊断

```powershell
python patch_edge_copilot.py --help
python patch_edge_copilot.py --diagnose --profile Default
python patch_edge_copilot.py --list-processes
```

### 预览完整修复

```powershell
python patch_edge_copilot.py --dry-run --patch-seed --profile Default
```

`--dry-run` 不修改文件、不关闭浏览器。预览时加上 `--patch-seed`，才能把新版独立种子元数据纳入修复计划。

### 修复，但不自动打开 Edge

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default --close-edge
```

命令行默认不重开浏览器。也可以显式添加 `--no-restart-edge`。

如果已经手动退出所有 Edge 窗口及后台进程，可以省略 `--close-edge`：

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default
```

### 修复成功后重新打开 Edge

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default --close-edge --restart-edge
```

### 选择其他通道或多个配置

修复 Beta 通道中的 `Profile 1`：

```powershell
python patch_edge_copilot.py --apply --patch-seed --channel beta --profile "Profile 1" --close-edge --restart-edge
```

处理同一通道的两个配置：

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default --profile "Profile 1" --close-edge
```

不指定 `--profile` 时，处理目标目录中已有的 `Default` 和 `Profile *` 常规配置。菜单的初始目标则明确限定为 `Default`。

预览所有已发现通道：

```powershell
python patch_edge_copilot.py --dry-run --patch-seed --channel all
```

### 自定义用户数据目录

```powershell
python patch_edge_copilot.py --apply --patch-seed --user-data-dir "D:\EdgeData\User Data" --profile Default --close-edge
```

该目录应包含 `Local State`，而不是直接指向 `Default` 或 `Profile 1`。

如果还要自动打开非标准位置的浏览器，可指定程序路径：

```powershell
python patch_edge_copilot.py --apply --patch-seed --user-data-dir "D:\EdgeData\User Data" --profile Default --close-edge --restart-edge --edge-exe "D:\Apps\Edge\Application\msedge.exe"
```

### 仅修复旧版 JSON 配置

```powershell
python patch_edge_copilot.py --apply --profile Default --close-edge
```

不加 `--patch-seed` 就不会修改独立种子文件。对于已经从 `VariationsSeedV2` 读取地区的版本，仅修改 JSON 可能不足以恢复入口。

## 参数参考

| 参数 | 含义 | 默认值 / 说明 |
| --- | --- | --- |
| `-h`, `--help` | 显示帮助并退出 | 不执行修复 |
| `--diagnose` | 只读诊断 | 仅提供其他非操作参数时的默认模式 |
| `--dry-run` | 预览计划修改 | 不写文件、不关闭浏览器 |
| `--apply` | 备份后应用补丁 | 显式启用写入 |
| `--list-processes` | 查看当前用户的活动 Edge 进程 | 不修改文件；不按通道或配置筛选 |
| `--channel` | 选择通道 | `stable`；可选 `beta`、`dev`、`canary`、`all` |
| `--user-data-dir` | 指定用户数据根目录 | 设置后优先使用此目录 |
| `--profile` | 指定配置目录名 | 可重复；命令行未指定时处理全部常规配置 |
| `--country` | 本地国家缓存目标 | `US`；接受两个英文字母并转为大写 |
| `--patch-seed` | 同步独立种子的国家元数据 | 命令行默认关闭；菜单修复和预览默认开启 |
| `--close-edge` | 写入前关闭 Edge | 仅与 `--apply` 配合 |
| `--force-close` | 正常关闭失败后强制结束进程 | 必须同时指定 `--apply --close-edge` |
| `--restart-edge` | 成功后打开目标 Edge 窗口 | 仅与 `--apply` 配合 |
| `--no-restart-edge` | 不自动打开 Edge | 命令行默认行为 |
| `--edge-exe` | 指定重开时的可执行文件 | 默认自动寻找对应通道 |

组合规则：

- `--diagnose`、`--dry-run`、`--apply`、`--list-processes` 互斥。
- `--restart-edge` 和 `--no-restart-edge` 互斥。
- `--close-edge`、`--force-close`、`--restart-edge` 不能用于只读操作。
- 未指定自定义 User Data 时，`--edge-exe` 不能与 `--channel all` 同用。
- `--country` 只改变本地缓存，不改变实际网络出口或账户地区。

## 自动化执行

批处理、PowerShell 脚本和计划任务应显式使用命令行参数，不要通过向菜单输入数字来自动化。

### PowerShell 调用示例

将以下路径替换为实际位置：

```powershell
$pythonExe = "C:\Python\python.exe"
$scriptPath = "D:\Tools\patch_edge_copilot.py"

& $pythonExe $scriptPath --apply --patch-seed --profile Default --close-edge --no-restart-edge
$resultCode = $LASTEXITCODE

if ($resultCode -ne 0) {
    Write-Error "Edge Copilot 配置处理失败，退出码：$resultCode"
}
exit $resultCode
```

需要完成后打开窗口时，将 `--no-restart-edge` 改为 `--restart-edge`。

### Windows 任务计划程序

可填写如下“操作”，路径按实际安装位置调整：

| 字段 | 示例 |
| --- | --- |
| 程序或脚本 | `C:\Python\python.exe` |
| 添加参数 | `"D:\Tools\patch_edge_copilot.py" --apply --patch-seed --profile Default --close-edge --no-restart-edge` |
| 起始于 | `D:\Tools` |

使用日常运行 Edge 的账户，并在该用户的交互登录会话中执行。关闭窗口和可见窗口检查依赖会话；不要把跨会话后台执行当作已验证的用法。计划中包含 `--close-edge` 时，也应确保触发时没有未保存的网页工作。

### 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 本次操作完成，或没有需要修改的配置 |
| `1` | 配置读取、进程处理、写入或重新启动等步骤失败 |
| `2` | 命令行参数无效 |
| `130` | 交互菜单中按 Ctrl+C 取消 |

`0` 表示脚本完成，不表示 Copilot 服务一定可用。菜单退出时返回的是菜单退出状态，不能用它代替每次修复的结果；自动化请使用参数模式。

## 配置目录与修改范围

### 如何找到自己的配置

在 Edge 地址栏打开 `edge://version`，查看“个人资料路径 / Profile path”。例如：

```text
C:\Users\<用户名>\AppData\Local\Microsoft\Edge\User Data\Profile 1
```

对应设置为：

- 用户数据根目录：上一级 `User Data`，传给 `--user-data-dir`。
- 配置目录名：`Profile 1`，传给 `--profile`。

Windows 默认数据目录如下：

| 通道 | 用户数据目录 |
| --- | --- |
| Stable | `%LOCALAPPDATA%\Microsoft\Edge\User Data` |
| Beta | `%LOCALAPPDATA%\Microsoft\Edge Beta\User Data` |
| Dev | `%LOCALAPPDATA%\Microsoft\Edge Dev\User Data` |
| Canary | `%LOCALAPPDATA%\Microsoft\Edge SxS\User Data` |

macOS 和 Linux 会按各自平台路径发现配置，也可以直接使用 `--user-data-dir`。

### 会修改什么

| 文件 | 目标字段 / 行为 |
| --- | --- |
| `Local State` | 设置 `variations_country`；同步已有且格式有效的 `variations_permanent_consistency_country` 国家项，保留版本值 |
| 指定配置的 `Preferences` | 设置 `browser.chat_ip_eligibility_status=true` 和 `browser.show_discover_toolbar_button=true` |
| `VariationsSeedV2` | 仅在启用 `--patch-seed` 时，同步已有且格式可识别的国家字段 6、7 |

**`--profile` 只限制 `Preferences` 的选择。** `Local State` 和 `VariationsSeedV2` 属于整个用户数据目录，地区修改会影响该目录下的其他配置。

脚本保留其他配置字段，不修改组织策略、页面读取授权、`VariationsSafeSeedV2` 或 `Local State` 中的 safe seed 元数据。不会为缺失或未知格式的国家字段编造数据，也不会创建新的 Edge 用户配置。

## 关闭与重新打开浏览器

### 关闭流程

使用 `--close-edge` 时，先请求关闭当前用户的 Edge 窗口，再持续检查进程退出状态。

Windows 下，如果只剩明确以 `--no-startup-window` 启动的后台实例，且连续检查确认没有可见窗口、没有页面渲染进程，脚本会结束这组后台实例，再重新读取磁盘配置。WebView2 和 Edge 更新器不属于要关闭的浏览器进程。

如果仍有网页、扩展页面、无头自动化或未知类型进程，脚本不会自动强制结束，而是列出 PID 和进程类型。可以在任务管理器的“详细信息”页核对。

**关闭操作针对当前用户的全部 Edge 浏览器进程，包括其他通道，不受 `--profile` 限制。** 如果只想处理配置而不让脚本关闭浏览器，请先手动完全退出 Edge，再省略 `--close-edge`。

确认已保存工作、确实需要强制关闭时：

```powershell
python patch_edge_copilot.py --apply --patch-seed --profile Default --close-edge --force-close
```

强制关闭可能丢失未保存的网页内容，不能保证正常的退出写回。

### 重开流程

- 菜单修复会询问是否重开，默认选“是”；命令行默认不重开。
- 重开使用目标通道、用户数据目录和指定配置。重复指定不同 `--profile` 时，会分别发送打开窗口请求。
- 配置已满足、无需修改时，如果指定 `--restart-edge`，仍会请求打开窗口。
- 修复步骤失败时不自动重开。若仅启动浏览器失败，配置修改可能已经完成，终端会明确提示。
- 打开窗口不等于恢复之前的所有标签页；会话恢复行为由 Edge 自身设置决定。
- 程序报告的是启动请求已发送，不对窗口最终显示或 Copilot 响应作自动判断。

## 备份与恢复

每个需要修改的文件，都会在原文件旁生成独立备份，文件名类似：

```text
Local State.copilot-backup-<日期时间>-<纳秒值>.bak
Preferences.copilot-backup-<日期时间>-<纳秒值>.bak
VariationsSeedV2.copilot-backup-<日期时间>-<纳秒值>.bak
```

备份保存原始字节，不覆盖以前的备份；无变更时不生成备份。终端会打印每个备份的完整位置。

恢复步骤：

1. 完全退出 Edge，包括后台进程。
2. 找到要恢复的那一次运行生成的备份。
3. 将备份复制覆盖回同目录的原文件，恢复原文件名。
4. 同一轮修改涉及多个文件时，恢复对应一轮的备份，再重新启动 Edge。

PowerShell 示例，执行前替换为实际备份路径：

```powershell
$backupPath = "D:\EdgeData\User Data\Local State.copilot-backup-<日期时间>-<纳秒值>.bak"
$targetPath = "D:\EdgeData\User Data\Local State"
Copy-Item -LiteralPath $backupPath -Destination $targetPath -Force
```

恢复旧的完整配置也会覆盖该文件在备份之后产生的设置变化。脚本目前没有专门的恢复菜单。

文件写入使用同目录临时文件、并发修改检查、原子替换和读回校验；但多个文件不是一个整体事务。如果中途失败，已完成的文件及其备份会保留，应根据输出决定重试还是恢复。浏览器配置和备份应留在本机，不要作为反馈附件公开上传。

## 工作原理与限制

旧版修复通常只调整 `Local State` 的地区缓存及 `Preferences` 的按钮相关开关。新版 Chromium 的独立种子存储还会在 `VariationsSeedV2` 中保存国家元数据；启用该存储方式时，修改 JSON 不会直接改掉文件中的国家值。[Chromium 种子读写实现](https://github.com/chromium/chromium/blob/2bc48d1e3a591d641005e9bc640adfd6c77c517f/components/variations/seed_reader_writer.cc)

`VariationsSeedV2` 是 Zstandard 压缩的 protobuf。启用 `--patch-seed` 后，脚本只替换已有且有效的两字母国家值，其余 protobuf 字节保持原样，包括实验数据和签名；不会重新生成或伪造签名。[StoredSeedInfo 定义](https://github.com/chromium/chromium/blob/2bc48d1e3a591d641005e9bc640adfd6c77c517f/components/variations/proto/stored_seed_info.proto)

本工具处理本地配置，不是微软提供的正式恢复接口。它不能保证解除服务端地区、账户或组织限制，也不能保证配置永久不被浏览器重新写回。若入口恢复但服务仍不可用，需要继续检查实际网络、账户及浏览器策略。

## 常见问题

### 运行后显示菜单，自动化却没有执行修复

无参数运行就是菜单模式。自动化时明确添加 `--apply` 等参数，完整示例见[自动化执行](#自动化执行)。

### 提示缺少 `psutil` 或 Zstandard

用运行脚本的同一个解释器安装：

```powershell
python -m pip install -r requirements.txt
```

如果装过仍然报错，检查是否在不同的 Python、虚拟环境或 Conda 环境间混用了安装与运行命令。

### 提示找不到用户数据目录或 Preferences

先启动一次对应通道的 Edge，再用 `edge://version` 确认真实配置路径。`--user-data-dir` 必须指向包含 `Local State` 的根目录；`--profile` 填写其下的目录名。

### Edge 窗口已经关了，为什么仍然提示有进程

窗口退出后，启动增强或后台服务可能继续运行。先执行：

```powershell
python patch_edge_copilot.py --list-processes
```

按照输出 PID 检查任务管理器的“详细信息”，必要时关闭 Edge 设置中的启动增强和后台运行。符合条件的无页面后台实例会由 `--close-edge` 自动清理；其余进程需要手动处理，或在保存工作后显式使用 `--force-close`。

### 提示无法确认进程归属或访问被拒绝

确认脚本与 Edge 由同一系统账户运行，并避免一边使用不同权限启动浏览器、一边用普通权限运行脚本。不要直接删除或重建用户数据目录。

### 提示未发现 `VariationsSeedV2`

脚本会跳过独立种子修复，继续检查已有 JSON。不同版本和运行历史可能使用不同的存储方式，不需要手动创建一个空种子文件。

### 提示种子格式未知或文件损坏

不要手工截断、清空种子文件。开启 `--patch-seed` 时，种子读取失败会阻止本次写入。记录 Edge 版本和错误文本后反馈；如果只打算处理 JSON，可不加 `--patch-seed`，但这可能无法解决新版地区缓存的问题。

### 显示配置已满足，但 Copilot 仍不出现

检查当前使用的是否是被修复的配置，并查看 `edge://settings/ai`；部分版本使用 `edge://settings/appearance/copilotAndSidebar`。还应查看 `edge://policy`，以及同一配置中 `https://copilot.microsoft.com/` 是否可用。本地开关满足并不能证明服务端资格满足。[微软排障说明](https://learn.microsoft.com/en-us/troubleshoot/microsoft-edge/experience/copilot-icon-missing-sidebar)

### 重启后地区又变回去了

浏览器或服务器后续更新可能重新写入地区缓存。可重新诊断确认，但不能把反复执行补丁当作永久解决方案。脚本不锁定配置文件、不禁用浏览器更新。

### 自动重开时提示找不到 Edge 程序

使用 `--edge-exe` 指定实际程序路径。对于自定义 Beta/Dev 数据目录，重开时还应选择对应通道，或明确提供该通道的程序路径。

## 测试

如果同时下载了仓库中的测试文件，可以运行：

```powershell
python -m unittest -v test_patch_edge_copilot.py test_edge_copilot_seed.py test_edge_shutdown.py test_edge_menu.py
```

当前已通过 **80 项自动化测试**，覆盖配置保留、坏文件保护、备份、并发写入检查、种子结构、进程退出、菜单和重开逻辑。自动化测试使用临时配置和模拟进程，不会操作真实 Edge 窗口。

另已验证：只把主脚本复制到独立临时目录，仍能运行菜单、预览及模拟配置修复。测试文件不是运行工具所需的依赖。

## 问题反馈

提交 Issue 时，建议提供以下信息：

- 操作系统、Python 版本、Edge 完整版本及通道。
- 使用菜单还是命令行，具体选择或命令参数。
- 现象是入口消失、无法打开会话，还是脚本执行报错。
- 脱敏后的诊断输出；进程关闭问题附 `--list-processes` 输出。
- 问题是否发生在 Edge 更新后，以及重启后地区缓存是否变化。

不要上传完整 `Local State`、`Preferences`、浏览器用户数据目录或备份文件。粘贴日志前可将用户名和个人目录路径替换为占位符。

## 参考资料

- [原始 patch-edge-copilot 项目](https://github.com/jiarandiana0307/patch-edge-copilot)
- [Chromium 种子读写实现](https://github.com/chromium/chromium/blob/2bc48d1e3a591d641005e9bc640adfd6c77c517f/components/variations/seed_reader_writer.cc)
- [StoredSeedInfo protobuf 结构](https://github.com/chromium/chromium/blob/2bc48d1e3a591d641005e9bc640adfd6c77c517f/components/variations/proto/stored_seed_info.proto)
- [Microsoft：Copilot 图标缺失排障](https://learn.microsoft.com/en-us/troubleshoot/microsoft-edge/experience/copilot-icon-missing-sidebar)
- [Microsoft：Copilot 支持的地区和语言](https://support.microsoft.com/en-us/microsoft-copilot/supported-regions-and-languages-in-microsoft-copilot)
