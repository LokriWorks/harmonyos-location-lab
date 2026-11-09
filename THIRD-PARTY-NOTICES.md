# 第三方组件

Windows EXE 内置 CPython 3.12、Tcl/Tk 8.6 和 PyInstaller 引导程序，无需用户安装 Python。

| 组件 | 来源 | 许可 |
| --- | --- | --- |
| CPython | https://www.python.org/ | Python 软件基金会许可及随附第三方声明，见 PYTHON-LICENSE.txt |
| Tcl/Tk | https://www.tcl.tk/ | Tcl/Tk 许可，见 TCL-LICENSE.txt / TK-LICENSE.txt |
| PyInstaller | https://pyinstaller.org/ | GPL 2.0 或更新版本，附引导程序分发例外，见 PYINSTALLER-COPYING.txt |

打包脚本保留这些许可；Releases 另提供同版本 licenses.zip 方便查看。PyInstaller 的引导程序例外允许分发由其生成的应用，不改变本项目代码的 MIT 许可。

本项目不打包 HDC、华为 SDK 或 libusb。实际设备操作需用户从官方开发工具获取 HDC，并保留其附带文件及许可。
