# 鸿蒙位置模拟与 GPX 轨迹测试工具

[![Tests](https://github.com/zoe2026test/harmonyos-location-lab/actions/workflows/test.yml/badge.svg)](https://github.com/zoe2026test/harmonyos-location-lab/actions/workflows/test.yml)
[![MIT](https://img.shields.io/badge/license-MIT-147d75)](LICENSE)

使用电脑上的 HDC，调用 HarmonyOS 的 `testhelper` 调试功能，提交固定位置或分批 GPX 轨迹。适合了解系统位置模拟接口、验证应用位置读取行为。

项目由 [zoe2026test](https://github.com/zoe2026test) 开发和维护。

**当前为 v0.1 草稿版命令行工具，不含 EXE、图形界面或 HDC 安装包。** 基于早期实验脚本整理，新 CLI 已做无设备单元测试，尚未重新做真机回归。没有连接手机时可先使用 dry-run 生成 GPX。

## 实测结论：请分清两层

| 对象 | 早期原型的观察结果 |
| --- | --- |
| 华为 nova 15，用户提供系统版本 7.0.0 | 曾通过 HDC 连接并提交模拟位置；具体系统构建号未记录 |
| 微信“发送位置”地图预览 | 用户多次测试均能显示模拟位置 |
| 校园跑小程序 | 测试失败，不作为本项目支持功能 |
| 应用连续跟随 GPX 移动 | 未完成稳定验证 |
| 其他机型和系统版本 | 未验证 |

这些是原型阶段的用户观察，不是所有鸿蒙设备或微信版本的兼容性保证。微信具体版本没有完整记录。

**“系统接受了位置提交”与“应用采用了位置”是两个不同结果。** 工具只报告调试命令的结果，应用效果需要在手机上独立确认。项目不提供隐藏模拟标记或修改第三方应用的功能。

## 功能

- 检查 HDC 连接和授权；多设备时要求指定目标。
- 固定坐标维持，带时长限制。
- 导入 GPX 的轨迹点、路线点或航点，按统一间隔提交。
- 小批量补发，尽量避免一次性位置数组耗尽；可选择循环。
- Ctrl+C 和普通异常后尝试关闭模拟，并清理本次临时文件。
- 不连接设备的 GPX 生成预览；仅 Python 标准库。

## 准备

1. 安装 Python 3.10 或更新版。
2. 从华为官方开发工具获取 HDC，将其加入 PATH，或通过 `--hdc` 指定完整路径。仓库不重新分发 SDK 二进制。
3. 在自己的手机上开启开发者选项和 USB 调试，连接数据线；解锁并允许电脑调试。
4. 设备需要提供并允许使用 `testhelper` 的位置模拟功能，普通 USB 连接并不代表该能力可用。

官方参考：[testhelper 工具指导](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/testhelper-guidelines/)。不同版本的工具行为以官方文档和设备实际结果为准。

## 快速开始

从 GitHub **Code → Download ZIP** 下载并解压，在项目目录打开终端。

先离线生成公开地标示例，不会修改手机：

```sh
python location_lab.py hold --lat 48.8582599 --lon 2.2945006 --dry-run preview.gpx
```

列出设备：

```sh
python location_lab.py devices
```

如果 HDC 没有加入 PATH，可以把全局参数放在子命令前：

```powershell
python location_lab.py --hdc "C:\Tools\HDC\hdc.exe" devices
```

连接成功后，固定在巴黎埃菲尔铁塔示例位置 60 秒：

```sh
python location_lab.py hold --lat 48.8582599 --lon 2.2945006 --duration 60
```

仅在微信“发送位置”预览页观察即可，无需向任何联系人发送位置。结束后重新打开预览页，确认恢复正常定位。

导入公开示例轨迹，按 1 秒间隔播放：

```sh
python location_lab.py play examples/eiffel.gpx --interval 1 --duration 60
```

默认到轨迹末尾即结束。希望循环时显式增加 `--loop`。间隔决定每个点的播放节奏，当前不按 GPX 原始时间戳或速度自动重采样；多个轨迹段按文件顺序读取，段间可能跳跃。

手动恢复：

```sh
python location_lab.py stop
```

多设备使用 `python location_lab.py --device YOUR_DEVICE_ID stop` 等形式。`YOUR_DEVICE_ID` 是占位符，不是预置设备号。也可用环境变量 `HDC_PATH` 指定工具。

## 已知限制与恢复

- 分批 GPX 提交仍属实验功能，USB 延迟、缓存和系统差异可能造成间断，不保证连续移动。
- 固定位置默认每批 30 点、1 秒间隔，提前补发；单次最长 3600 秒。该设置是保守的实验参数，不表示所有版本的固定上限。
- GPX 超过 2 MB、坐标无效或点数超过 10000 时拒绝处理。生成文件会重建时间戳和海拔，不保留输入的全部可选字段。
- 同一设备请只运行一个位置模拟会话；新会话会先关闭此前的模拟模式。
- 断线、电脑休眠、强行结束进程或系统崩溃时，无法保证自动恢复。恢复连接后执行 stop，并在应用中检查；必要时在手机端关闭调试并重启定位。
- 当前不修改手机系统文件、不安装 APK/HAP，也不采集屏幕截图或聊天内容。

## 测试与项目结构

```sh
python -m unittest discover -s tests -v
```

测试使用模拟 HDC 和模拟时钟，覆盖输入校验、设备选择、补发、正常结束、提交失败、中断、清理失败和离线预览。**CI 不连接真机，不证明第三方应用兼容。**

```text
location_lab.py          HDC 连接、GPX 生成与有界测试会话
examples/eiffel.gpx     公开地标示例，不包含私人地点
tests/                  无设备单元测试
docs/TESTING.md          真机回归记录方法
```

## 反馈与路线图

[报告问题或建议](https://github.com/zoe2026test/harmonyos-location-lab/issues/new/choose)。请写机型、系统版本、微信版本、命令结果与实际应用表现；设备序列号、学校、家庭坐标、聊天截图和个人路径应先遮住。不要把原始调试日志直接公开上传。

后续计划：补齐新 CLI 的真机回归、完善状态与停止控制，再评估图形界面、地图选点和与“随处”路线引擎复用。当前没有承诺这些功能已经实现。

代码采用 [MIT 许可证](LICENSE)。本项目与华为、微信没有隶属或背书关系。
