"""Windows desktop interface. HDC calls run on one worker, Tk stays on the main thread."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import xml.etree.ElementTree as ET

from app_version import VERSION
from location_lab import Hdc, LabError, gpx_bytes, load_gpx, parse_devices, run_session, validate_point


def resource(name):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / name


def settings_path():
    return Path(os.getenv('LOCALAPPDATA', Path.home())) / 'HarmonyOSLocationLab' / 'settings.json'


def discover_hdc():
    # Store only the tool path, never coordinates, routes or device IDs.
    try:
        saved = json.loads(settings_path().read_text(encoding='utf-8')).get('hdc', '')
    except (OSError, ValueError, AttributeError):
        saved = ''
    adjacent = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    for candidate in (saved, os.getenv('HDC_PATH', ''), adjacent / 'hdc' / 'hdc.exe', shutil.which('hdc')):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return ''


def session_options(mode, latitude, longitude, gpx, duration, interval, loop):
    try:
        duration, interval = int(duration), int(interval)
        if not 1 <= duration <= 3600 or not 1 <= interval <= 60:
            raise ValueError()
    except (ValueError, TypeError):
        raise LabError('时长请输入 1–3600 秒，间隔请输入 1–60 秒的整数。') from None
    if mode == 'hold':
        try:
            points = [validate_point(float(latitude), float(longitude))]
        except (ValueError, TypeError):
            raise LabError('请填写有效的 WGS84 经纬度数字。') from None
    else:
        if not gpx:
            raise LabError('请先选择 GPX 文件。')
        points = load_gpx(gpx)
    return dict(points=points, duration=duration, interval=interval, loop=mode == 'hold' or bool(loop))


class App:
    def __init__(self, root, hdc_factory=Hdc, persist=True, dialogs=True):
        self.root, self.factory, self.persist, self.dialogs = root, hdc_factory, persist, dialogs
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.worker = None
        self.closing, self.busy = False, False
        self.devices = {}
        self.session_target = None
        self.last_error = None
        root.title(f'鸿蒙位置实验室 · {VERSION}')
        root.geometry('800x740')
        root.minsize(720, 680)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background='#f3f5f8')
        style.configure('TLabel', background='#f3f5f8', font=('Microsoft YaHei UI', 10))
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 21, 'bold'), foreground='#18324b')
        style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(10, 7))
        style.configure('TEntry', padding=5)
        base = ttk.Frame(root, padding=24)
        base.pack(fill='both', expand=True)
        base.columnconfigure(0, weight=1)
        ttk.Label(base, text='鸿蒙位置实验室', style='Title.TLabel').grid(sticky='w')
        ttk.Label(base, text='固定位置 / GPX 轨迹 · 通过 USB 调试连接手机').grid(sticky='w', pady=(3, 15))
        self.hdc = tk.StringVar(value=discover_hdc())
        self.device = tk.StringVar()
        connection = ttk.LabelFrame(base, text=' 1  连接工具与设备 ', padding=12)
        connection.grid(sticky='ew')
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text='HDC 路径').grid(row=0, column=0, padx=(0, 10))
        self.hdc_entry = ttk.Entry(connection, textvariable=self.hdc)
        self.hdc_entry.grid(row=0, column=1, sticky='ew')
        self.browse_hdc = ttk.Button(connection, text='选择 HDC', command=self.choose_hdc)
        self.browse_hdc.grid(row=0, column=2, padx=(8, 0))
        ttk.Label(connection, text='手机设备').grid(row=1, column=0, pady=(10, 0))
        self.device_box = ttk.Combobox(connection, textvariable=self.device, state='readonly')
        self.device_box.grid(row=1, column=1, sticky='ew', pady=(10, 0))
        self.scan_button = ttk.Button(connection, text='检测设备', command=self.scan)
        self.scan_button.grid(row=1, column=2, padx=(8, 0), pady=(10, 0))
        ttk.Label(connection, text='HDC 不随本程序分发。请从官方开发工具获取，并保留同目录的 DLL。', wraplength=670).grid(row=2, column=0, columnspan=3, sticky='w', pady=(10, 0))

        settings = ttk.LabelFrame(base, text=' 2  选择测试内容 ', padding=12)
        settings.grid(sticky='ew', pady=(14, 0))
        settings.columnconfigure(0, weight=1)
        self.tabs = ttk.Notebook(settings)
        self.tabs.grid(sticky='ew')
        fixed, route = ttk.Frame(self.tabs, padding=12), ttk.Frame(self.tabs, padding=12)
        self.tabs.add(fixed, text='固定位置')
        self.tabs.add(route, text='GPX 轨迹')
        self.latitude = tk.StringVar(value='48.8582599')
        self.longitude = tk.StringVar(value='2.2945006')
        ttk.Label(fixed, text='纬度').grid(row=0, column=0)
        self.lat_entry = ttk.Entry(fixed, textvariable=self.latitude, width=22)
        self.lat_entry.grid(row=0, column=1, padx=(8, 20))
        ttk.Label(fixed, text='经度').grid(row=0, column=2)
        self.lon_entry = ttk.Entry(fixed, textvariable=self.longitude, width=22)
        self.lon_entry.grid(row=0, column=3, padx=(8, 0))
        ttk.Label(fixed, text='WGS84 坐标；默认是巴黎埃菲尔铁塔公开地标。').grid(row=1, column=0, columnspan=4, sticky='w', pady=(10, 0))
        self.gpx = tk.StringVar(value=str(resource('examples/eiffel.gpx')))
        route.columnconfigure(0, weight=1)
        self.gpx_entry = ttk.Entry(route, textvariable=self.gpx)
        self.gpx_entry.grid(row=0, column=0, sticky='ew')
        self.gpx_button = ttk.Button(route, text='导入 GPX', command=self.choose_gpx)
        self.gpx_button.grid(row=0, column=1, padx=(8, 0))
        self.loop = tk.BooleanVar(value=False)
        self.loop_box = ttk.Checkbutton(route, text='到末尾后循环（仍受总时长限制）', variable=self.loop)
        self.loop_box.grid(row=1, column=0, columnspan=2, sticky='w', pady=(8, 0))
        timing = ttk.Frame(settings)
        timing.grid(sticky='ew', pady=(12, 0))
        self.duration, self.interval = tk.StringVar(value='60'), tk.StringVar(value='1')
        ttk.Label(timing, text='总时长（秒）').pack(side='left')
        self.duration_entry = ttk.Entry(timing, textvariable=self.duration, width=9)
        self.duration_entry.pack(side='left', padx=(8, 18))
        ttk.Label(timing, text='点间隔（秒）').pack(side='left')
        self.interval_entry = ttk.Entry(timing, textvariable=self.interval, width=9)
        self.interval_entry.pack(side='left', padx=8)
        ttk.Label(settings, text='轨迹按点间隔播放，不按原始时间戳或速度重采样；应用连续跟随尚未稳定验证。', wraplength=670).grid(sticky='w', pady=(10, 0))

        buttons = ttk.Frame(base)
        buttons.grid(sticky='ew', pady=14)
        self.start_button = ttk.Button(buttons, text='开始测试', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='停止并恢复定位', command=self.stop)
        self.stop_button.pack(side='left', padx=10)
        self.preview_button = ttk.Button(buttons, text='仅导出 GPX', command=self.preview)
        self.preview_button.pack(side='right')
        self.status = tk.StringVar(value='就绪 · 先选择 HDC 并检测设备；导出 GPX 无需连接手机。')
        ttk.Label(base, textvariable=self.status, foreground='#175c76', wraplength=730).grid(sticky='ew')
        base.rowconfigure(6, weight=1)
        self.log = tk.Text(base, height=7, wrap='word', state='disabled', font=('Microsoft YaHei UI', 9), bg='white', relief='flat', padx=10, pady=8)
        self.log.grid(sticky='nsew', pady=(10, 8))
        ttk.Label(base, text='实验版：系统接受提交，不代表应用采用。结束后请在手机上确认定位恢复。', wraplength=730).grid(sticky='ew')
        self.edit_controls = [self.hdc_entry, self.browse_hdc, self.scan_button, self.lat_entry, self.lon_entry,
                              self.gpx_entry, self.gpx_button, self.loop_box, self.duration_entry, self.interval_entry,
                              self.start_button, self.preview_button]
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def write(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S ') + text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def error(self, error):
        self.last_error = str(error)
        self.status.set(str(error))
        self.write(str(error))
        if self.dialogs:
            messagebox.showerror('操作未完成', str(error), parent=self.root)

    def choose_hdc(self):
        path = filedialog.askopenfilename(title='选择官方工具中的 hdc.exe', filetypes=[('HDC', 'hdc.exe')])
        if path:
            self.hdc.set(path)

    def choose_gpx(self):
        path = filedialog.askopenfilename(title='导入 GPX', filetypes=[('GPX', '*.gpx')])
        if path:
            self.gpx.set(path)

    def options(self):
        return session_options('hold' if self.tabs.index('current') == 0 else 'play', self.latitude.get(),
                               self.longitude.get(), self.gpx.get(), self.duration.get(), self.interval.get(), self.loop.get())

    def connection(self):
        path = self.hdc.get().strip()
        if not path:
            raise LabError('请先选择官方 HDC 工具中的 hdc.exe。')
        device = self.devices.get(self.device.get())
        return path, device

    def launch(self, kind, action):
        if self.busy:
            return
        self.last_error = None
        self.busy = True
        self.cancel.clear()
        for control in self.edit_controls:
            control.configure(state='disabled')
        self.device_box.configure(state='disabled')
        self.stop_button.configure(state='normal' if kind == 'session' else 'disabled')
        self.status.set({'scan': '正在检测设备…', 'session': '正在连接并提交…', 'restore': '正在关闭模拟…'}[kind])
        def work():
            try:
                result = action()
                self.events.put(('done', (kind, result)))
            except Exception as exc:
                self.events.put(('failed', str(exc)))
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def make_hdc(self, path, device):
        hdc = self.factory(path, device)
        hdc.select()
        return hdc

    def scan(self):
        try:
            path, _ = self.connection()
        except LabError as exc:
            self.error(exc)
            return
        self.launch('scan', lambda: parse_devices(self.factory(path, None).run('list', 'targets', '-v')))

    def start(self):
        if self.busy:
            return
        try:
            options = self.options()
            path, device = self.connection()
        except (LabError, OSError, ValueError, ET.ParseError) as exc:
            self.error(exc)
            return
        self.session_target = None
        if self.persist:
            try:
                file = settings_path()
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(json.dumps({'hdc': path}, ensure_ascii=False), encoding='utf-8')
            except OSError:
                self.write('HDC 路径未能保存；不影响本次测试。')
        def action():
            hdc = self.make_hdc(path, device)
            # Pin recovery to the device actually used, even when selection was automatic.
            self.session_target = (path, hdc.device)
            return run_session(hdc, **options, cancel=self.cancel, report=lambda s: self.events.put(('log', s)))
        self.launch('session', action)

    def stop(self):
        if self.busy:
            self.cancel.set()
            self.status.set('正在停止并恢复；等待当前 HDC 命令返回，断线时可能需要较长时间…')
            self.stop_button.configure(state='disabled')
            return
        try:
            path, device = self.session_target or self.connection()
        except LabError as exc:
            self.error(exc)
            return
        def action():
            self.make_hdc(path, device).run('shell', 'testhelper', 'disable-location-mock')
        self.launch('restore', action)

    def preview(self):
        try:
            options = self.options()
            path = filedialog.asksaveasfilename(title='导出 GPX（不连接手机）', defaultextension='.gpx', filetypes=[('GPX', '*.gpx')])
            if path:
                Path(path).write_bytes(gpx_bytes(options['points'], options['interval']))
                self.status.set('GPX 已导出；没有连接手机或修改定位。')
                self.write('已导出 GPX。')
        except (LabError, OSError, ValueError, ET.ParseError) as exc:
            self.error(exc)

    def poll(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.write(value)
                self.status.set(value)
                continue
            self.busy = False
            for control in self.edit_controls:
                control.configure(state='normal')
            self.device_box.configure(state='readonly')
            self.stop_button.configure(state='normal')
            if kind == 'failed':
                self.closing = False
                self.error(value + ' 请检查连接，必要时点“停止并恢复定位”重试，并在手机上确认。')
            else:
                operation, result = value
                if operation == 'scan':
                    self.devices = {f"{d['id']} · {d['status']}": d['id'] for d in result}
                    self.device_box.configure(values=list(self.devices))
                    self.device.set(next(iter(self.devices)) if len(self.devices) == 1 else '')
                    self.status.set(f'发现 {len(self.devices)} 台设备；多设备时请手动选择。' if result else '未发现设备。请检查 USB 调试、数据线和手机授权。')
                else:
                    self.status.set('已提交关闭模拟请求，请在手机上确认正常定位。')
                if self.closing:
                    self.root.destroy()
                    return
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            self.closing = True
            self.cancel.set()
            self.status.set('正在结束操作并尝试恢复定位，请稍候…')
            return
        self.root.destroy()


def self_test(root, app, output, calls):
    """Offline packaged-app smoke test: real Tk, fake HDC, worker cancellation and cleanup."""
    app.hdc.set('OFFLINE-FAKE-HDC')
    app.duration.set('60')
    app.start()
    deadline = time.monotonic() + 15
    stopped = False
    def check():
        nonlocal stopped
        if not stopped and any('set-mocked-locations' in c for c in calls):
            app.stop()
            stopped = True
        if stopped and not app.busy:
            chinese_ok = root.title().startswith('\u9e3f\u8499\u4f4d\u7f6e\u5b9e\u9a8c\u5ba4')
            ok = chinese_ok and app.last_error is None and any('disable-location-mock' in c for c in calls[-2:]) and calls[-1][1] == 'rm'
            Path(output).write_text(json.dumps({'ok': ok, 'version': VERSION, 'tk': str(tk.TkVersion),
                                               'frozen': bool(getattr(sys, 'frozen', False)), 'offline': True,
                                               'cancelled': stopped, 'chinese_ok': chinese_ok,
                                               'sample_points': len(load_gpx(resource('examples/eiffel.gpx')))}, indent=2), encoding='utf-8')
            root.destroy()
        elif time.monotonic() > deadline:
            app.cancel.set()
            Path(output).write_text(json.dumps({'ok': False, 'error': app.last_error or 'timeout'}), encoding='utf-8')
            root.destroy()
        else:
            root.after(50, check)
    root.after(50, check)


def main():
    parser = argparse.ArgumentParser(description='鸿蒙位置实验室图形界面')
    parser.add_argument('--self-test', metavar='RESULT_JSON', help='离线打包验证，不连接真实设备')
    args = parser.parse_args()
    root = tk.Tk()
    calls = []
    if args.self_test:
        class OfflineHdc:
            def __init__(self, path, device): self.device = 'OFFLINE-TEST'
            def select(self): pass
            def run(self, *command):
                calls.append(command)
                return 'Set mocked locations successfully.' if 'set-mocked-locations' in command else 'ok'
        app = App(root, hdc_factory=OfflineHdc, persist=False, dialogs=False)
        root.after(100, lambda: self_test(root, app, args.self_test, calls))
    else:
        App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
