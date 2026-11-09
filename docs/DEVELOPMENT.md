# Development / 源码与打包

## 从源码运行（开发者）

使用 EXE 的用户无需安装 Python。以下步骤仅用于源码运行：

1. 安装含 tkinter 的 Python 3.10 或更新版。
2. 从华为官方开发工具获取 HDC，将其加入 PATH，或通过 `--hdc` 指定完整路径。仓库不重新分发 SDK 二进制。
3. 在自己的手机上开启开发者选项和 USB 调试，连接数据线；解锁并允许电脑调试。
4. 设备需要提供并允许使用 `testhelper` 的位置模拟功能，普通 USB 连接并不代表该能力可用。

官方参考：[testhelper 工具指导](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/testhelper-guidelines/)。不同版本的工具行为以官方文档和设备实际结果为准。

### 源码快速开始

从 GitHub **Code → Download ZIP** 下载并解压，在项目目录打开终端。

运行图形界面：

```sh
python gui.py
```

或者继续使用命令行。

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

测试使用模拟 HDC 和模拟时钟，覆盖表单与输入校验、设备选择、补发、正常结束、提交失败、中断、取消、清理失败和离线预览。发布流程还在移除 Python PATH 后启动真实 EXE，用模拟 HDC 验证界面线程、停止和清理。**CI 不连接真机，不证明第三方应用兼容。**

```text
location_lab.py          HDC 连接、GPX 生成与有界测试会话
gui.py                  tkinter 图形界面、后台执行与停止控制
app_version.py          发布版本
examples/eiffel.gpx     公开地标示例，不包含私人地点
tests/                  无设备单元测试
docs/TESTING.md          真机回归记录方法
scripts/                Windows 构建与 EXE 离线验证
.github/workflows/      自动测试、打包与发布
```

### 自行打包 EXE

在 Windows x64 和 Python 3.12 环境中：

```powershell
python -m pip install -r requirements-build.txt
./scripts/build-windows.ps1
./scripts/smoke-windows.ps1
```

产物位于 `dist/`。依赖许可见 [第三方组件说明](../THIRD-PARTY-NOTICES.md)，发布页另附许可证压缩包。

