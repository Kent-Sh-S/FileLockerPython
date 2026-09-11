#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件加密打包器
==============

把任意文件打包成一个独立的 .exe 分享给他人。接收者打开 exe 后,
点击「解锁文件」按钮, 根据打包时的设置:
    · 方式一: 自动用默认浏览器打开你指定的网页链接, 然后获得文件
    · 方式二: 弹出你设置的题目, 答对后才能获得文件

用法:
    python file_locker.py
    选择文件 -> 选择解锁方式 -> 填写链接或题目答案 -> 生成 EXE

环境要求:
    Python 3.8+ (Windows)。生成 exe 依赖 PyInstaller,
    首次生成时程序会自动检测并提示安装。
"""

import hashlib
import json
import lzma
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

MAGIC = b"LOCKPAYLOADv1"
PAYLOAD_NAME = "__lockpayload__.bin"
INTERNAL_NAME = "locked_output"

LOCKED_TEMPLATE = r'''# -*- coding: utf-8 -*-
import hashlib
import json
import lzma
import os
import sys
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog

PAYLOAD_NAME = r"__PAYLOAD_NAME__"
MAGIC = b"LOCKPAYLOADv1"

BG = "#1e1e2e"
FG = "#cdd6f4"
SUB = "#a6adc8"
ACCENT = "#89b4fa"


def payload_path():
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, PAYLOAD_NAME)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), PAYLOAD_NAME)


def load_payload():
    with open(payload_path(), "rb") as f:
        raw = f.read()
    first = raw.find(b"\n")
    if first < 0 or raw[:first] != MAGIC:
        raise ValueError("无效的数据包")
    rest = raw[first + 1:]
    second = rest.find(b"\n")
    if second < 0:
        raise ValueError("无效的数据包")
    meta = json.loads(rest[:second].decode("utf-8"))
    return meta, rest[second + 1:]


class LockedApp:
    def __init__(self, root, meta, data):
        self.meta = meta
        self.data = data
        self.root = root
        root.title("加密文件")
        root.configure(bg=BG)
        root.resizable(False, False)
        w, h = 440, 280
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 3))

        tk.Label(root, text="该文件已被加密锁定", font=("Microsoft YaHei UI", 14, "bold"),
                 bg=BG, fg=FG).pack(pady=(40, 4))
        tk.Label(root, text="解锁后可获得: " + meta["filename"],
                 font=("Microsoft YaHei UI", 10), bg=BG, fg=SUB).pack()
        if meta["unlock_type"] == "url":
            hint = "点击「解锁文件」后, 将在默认浏览器中打开指定链接"
        else:
            hint = "点击「解锁文件」后, 需正确回答问题才能获得文件"
        tk.Label(root, text=hint, font=("Microsoft YaHei UI", 9), bg=BG, fg=SUB).pack(pady=(2, 24))

        tk.Button(root, text="解 锁 文 件", font=("Microsoft YaHei UI", 12, "bold"),
                  bg=ACCENT, fg="#11111b", activebackground="#74c7ec", activeforeground="#11111b",
                  relief="flat", cursor="hand2", width=20, height=2,
                  command=self.unlock).pack()

    def unlock(self):
        if self.meta["unlock_type"] == "url":
            try:
                webbrowser.open(self.meta["url"])
            except Exception:
                pass
            self.release()
            return
        answer = simpledialog.askstring(
            "解锁文件", self.meta["question"] + "\n\n请输入答案:", parent=self.root)
        if answer is None:
            return
        digest = hashlib.sha256(answer.strip().encode("utf-8")).hexdigest()
        if digest == self.meta["answer_sha256"]:
            self.release()
        else:
            messagebox.showerror("解锁失败", "答案不正确, 无法获得文件!")

    def release(self):
        try:
            raw = lzma.decompress(self.data)
        except Exception:
            messagebox.showerror("错误", "内置数据损坏, 无法释放文件。")
            return
        if hashlib.sha256(raw).hexdigest() != self.meta["file_sha256"]:
            messagebox.showerror("错误", "文件校验失败, 可能已损坏。")
            return
        ext = os.path.splitext(self.meta["filename"])[1]
        kwargs = {"title": "选择文件保存位置", "initialfile": self.meta["filename"]}
        if ext:
            kwargs["defaultextension"] = ext
        target = filedialog.asksaveasfilename(**kwargs)
        if not target:
            return
        with open(target, "wb") as f:
            f.write(raw)
        messagebox.showinfo("解锁成功", "文件已保存到:\n" + target)
        try:
            os.startfile(os.path.dirname(os.path.abspath(target)))
        except Exception:
            pass
        self.root.destroy()


def main():
    try:
        meta, data = load_payload()
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("错误", "读取内置数据失败: %s" % e)
        return
    root = tk.Tk()
    LockedApp(root, meta, data)
    root.mainloop()


if __name__ == "__main__":
    main()
'''


class BuildError(Exception):
    pass


def check_pyinstaller():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and (r.stdout or "").strip():
            return (r.stdout or "").strip()
    except Exception:
        pass
    return None


def default_ensure_pyinstaller(log):
    version = check_pyinstaller()
    if version:
        log("检测到 PyInstaller %s" % version)
        return True
    log("未检测到 PyInstaller, 正在自动安装 (pip install pyinstaller)...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        log("安装失败:\n" + (r.stderr or "")[-1500:])
        raise BuildError("PyInstaller 安装失败, 请手动执行: pip install pyinstaller")
    log("PyInstaller 安装成功。")
    return True


def build_exe(src, mode, url, question, answer, out_path,
              log=None, ensure_pyinstaller=None):
    log = log or (lambda msg: None)
    if mode not in ("url", "question"):
        raise BuildError("未知解锁方式: %s" % mode)
    if not src or not os.path.isfile(src):
        raise BuildError("文件不存在: %s" % src)
    if mode == "url":
        if not url:
            raise BuildError("未填写解锁链接")
        if "://" not in url:
            url = "https://" + url
    else:
        if not question or not answer.strip():
            raise BuildError("未填写问题或答案")
    if os.path.getsize(src) > 1024 ** 3:
        raise BuildError("文件超过 1GB, 不支持。")

    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if ensure_pyinstaller is None:
        ensure_pyinstaller = lambda: default_ensure_pyinstaller(log)

    log("读取文件: %s" % src)
    with open(src, "rb") as f:
        raw = f.read()
    log("原文件大小: %.2f MB" % (len(raw) / 1048576))

    log("正在 LZMA 压缩...")
    comp = lzma.compress(raw, preset=9)
    log("压缩完成: %.2f MB (压缩率 %.1f%%)"
        % (len(comp) / 1048576, len(comp) * 100.0 / max(len(raw), 1)))

    meta = {
        "filename": os.path.basename(src),
        "unlock_type": mode,
        "url": url if mode == "url" else "",
        "question": question if mode == "question" else "",
        "answer_sha256": (hashlib.sha256(answer.strip().encode("utf-8")).hexdigest()
                          if mode == "question" else ""),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
    }
    payload = (MAGIC + b"\n"
               + json.dumps(meta, ensure_ascii=False).encode("utf-8") + b"\n"
               + comp)

    workdir = tempfile.mkdtemp(prefix="locker_build_")
    try:
        payload_path = os.path.join(workdir, PAYLOAD_NAME)
        with open(payload_path, "wb") as f:
            f.write(payload)
        script_path = os.path.join(workdir, "locked_app.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(LOCKED_TEMPLATE.replace("__PAYLOAD_NAME__", PAYLOAD_NAME))

        if not ensure_pyinstaller():
            raise BuildError("缺少 PyInstaller, 无法生成 EXE。")

        log("正在编译 EXE, 大约需要 1~3 分钟, 请耐心等待...")
        dist_dir = os.path.join(workdir, "dist")
        build_dir = os.path.join(workdir, "build")
        sep = ";" if os.name == "nt" else ":"
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile", "--noconsole", "--clean",
            "--name", INTERNAL_NAME,
            "--distpath", dist_dir,
            "--workpath", build_dir,
            "--specpath", workdir,
            "--add-data", payload_path + sep + ".",
            script_path,
        ]
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-3000:]
            log("编译失败:\n" + tail)
            raise BuildError("EXE 编译失败, 详情见日志。")

        produced = os.path.join(dist_dir, INTERNAL_NAME + ".exe")
        if not os.path.isfile(produced):
            raise BuildError("未找到编译产物, 编译失败。")

        shutil.copy2(produced, out_path)
        log("生成成功: %s" % out_path)
        return out_path
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


class BuilderApp:
    def __init__(self, root):
        self.root = root
        self.mode_var = tk.StringVar(value="url")
        self.file_var = tk.StringVar()
        self.url_var = tk.StringVar()
        self.question_var = tk.StringVar()
        self.answer_var = tk.StringVar()
        self._building = False
        self._ask_event = threading.Event()

        root.title("文件加密打包器")
        root.geometry("580x660")
        root.minsize(520, 560)
        root.configure(bg="#f5f5f7")

        tk.Label(root, text="文件加密打包器", font=("Microsoft YaHei UI", 15, "bold"),
                 bg="#f5f5f7", fg="#333333").pack(pady=(14, 2))
        tk.Label(root, text="把文件打包成带解锁机制的 EXE 分享给他人",
                 font=("Microsoft YaHei UI", 9), bg="#f5f5f7", fg="#777777").pack()

        file_frame = tk.Frame(root, bg="#f5f5f7")
        file_frame.pack(fill="x", padx=14, pady=(14, 4))
        tk.Label(file_frame, text="要保护的文件:", font=("Microsoft YaHei UI", 10),
                 bg="#f5f5f7").pack(anchor="w")
        row = tk.Frame(file_frame, bg="#f5f5f7")
        row.pack(fill="x")
        tk.Entry(row, textvariable=self.file_var, font=("Microsoft YaHei UI", 10)).pack(
            side="left", fill="x", expand=True, ipady=3)
        tk.Button(row, text=" 浏览... ", font=("Microsoft YaHei UI", 10),
                  command=self.pick_file).pack(side="left", padx=(8, 0), ipady=2)

        tk.Label(root, text="解锁方式:", font=("Microsoft YaHei UI", 10),
                 bg="#f5f5f7").pack(anchor="w", padx=14, pady=(10, 0))
        mode_row = tk.Frame(root, bg="#f5f5f7")
        mode_row.pack(anchor="w", padx=14)
        tk.Radiobutton(mode_row, text="打开网页链接", variable=self.mode_var, value="url",
                       command=self.on_mode_change, bg="#f5f5f7",
                       font=("Microsoft YaHei UI", 10)).pack(side="left")
        tk.Radiobutton(mode_row, text="回答问题", variable=self.mode_var, value="question",
                       command=self.on_mode_change, bg="#f5f5f7",
                       font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(16, 0))

        self.mode_container = tk.Frame(root, bg="#f5f5f7")
        self.mode_container.pack(fill="x")

        self.url_frame = tk.Frame(self.mode_container, bg="#f5f5f7")
        tk.Label(self.url_frame, text="解锁时打开的链接:", font=("Microsoft YaHei UI", 9),
                 bg="#f5f5f7", fg="#777777").pack(anchor="w", padx=14, pady=(6, 0))
        tk.Entry(self.url_frame, textvariable=self.url_var,
                 font=("Microsoft YaHei UI", 10)).pack(fill="x", padx=14, ipady=3)

        self.question_frame = tk.Frame(self.mode_container, bg="#f5f5f7")
        tk.Label(self.question_frame, text="解锁问题:", font=("Microsoft YaHei UI", 9),
                 bg="#f5f5f7", fg="#777777").pack(anchor="w", padx=14, pady=(6, 0))
        tk.Entry(self.question_frame, textvariable=self.question_var,
                 font=("Microsoft YaHei UI", 10)).pack(fill="x", padx=14, ipady=3)
        tk.Label(self.question_frame, text="正确答案 (区分大小写, 首尾空格会被忽略):",
                 font=("Microsoft YaHei UI", 9), bg="#f5f5f7",
                 fg="#777777").pack(anchor="w", padx=14, pady=(6, 0))
        tk.Entry(self.question_frame, textvariable=self.answer_var,
                 font=("Microsoft YaHei UI", 10)).pack(fill="x", padx=14, ipady=3)

        self.url_frame.pack(fill="x")

        self.build_btn = tk.Button(root, text="生成 EXE", font=("Microsoft YaHei UI", 12, "bold"),
                                   bg="#3b82f6", fg="white", activebackground="#2563eb",
                                   activeforeground="white", relief="flat", cursor="hand2",
                                   command=self.start_build)
        self.build_btn.pack(fill="x", padx=14, pady=14, ipady=6)

        tk.Label(root, text="生成日志:", font=("Microsoft YaHei UI", 9),
                 bg="#f5f5f7", fg="#777777").pack(anchor="w", padx=14)
        self.log_text = tk.Text(root, height=10, font=("Consolas", 9), bg="#1e1e2e",
                                fg="#cdd6f4", state="disabled", relief="flat")
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(2, 4))

        tk.Label(root, text="提示: 生成的 EXE 可能被杀毒软件误报, 属正常现象; "
                            "打包依赖 PyInstaller, 首次生成时会自动检测安装。",
                 font=("Microsoft YaHei UI", 8), bg="#f5f5f7", fg="#999999").pack(pady=(0, 8))

    def pick_file(self):
        path = filedialog.askopenfilename(title="选择需要保护的文件")
        if path:
            self.file_var.set(path)

    def on_mode_change(self):
        self.url_frame.pack_forget()
        self.question_frame.pack_forget()
        if self.mode_var.get() == "url":
            self.url_frame.pack(fill="x")
        else:
            self.question_frame.pack(fill="x")

    def log(self, msg):
        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.ui(_append)

    def ui(self, fn):
        try:
            self.root.after(0, fn)
        except RuntimeError:
            pass

    def start_build(self):
        if self._building:
            return
        src = self.file_var.get().strip().strip('"')
        if not src:
            messagebox.showwarning("提示", "请先选择需要保护的文件。")
            return
        if not os.path.isfile(src):
            messagebox.showerror("错误", "文件不存在: " + src)
            return

        mode = self.mode_var.get()
        url = self.url_var.get().strip()
        question = self.question_var.get().strip()
        answer = self.answer_var.get()

        if mode == "url" and not url:
            messagebox.showwarning("提示", "请填写解锁时打开的链接。")
            return
        if mode == "question" and (not question or not answer.strip()):
            messagebox.showwarning("提示", "请填写问题和答案。")
            return

        default_name = os.path.splitext(os.path.basename(src))[0] + ".exe"
        out = filedialog.asksaveasfilename(
            title="保存 EXE", defaultextension=".exe", initialfile=default_name,
            filetypes=[("可执行文件", "*.exe")])
        if not out:
            return

        self._building = True
        self.build_btn.configure(state="disabled", text="正在生成...")
        threading.Thread(target=self._worker,
                         args=(src, mode, url, question, answer, os.path.abspath(out)),
                         daemon=True).start()

    def _worker(self, src, mode, url, question, answer, out_path):
        try:
            out = build_exe(src, mode, url, question, answer, out_path,
                            log=self.log, ensure_pyinstaller=self._ensure_pyinstaller)
            self.ui(lambda: messagebox.showinfo("完成", "EXE 已生成:\n" + out))
            try:
                os.startfile(os.path.dirname(out))
            except Exception:
                pass
        except BuildError as e:
            self.log("失败: %s" % e)
            self.ui(lambda: messagebox.showerror("错误", str(e)))
        except Exception as e:
            self.log("发生错误: %r" % e)
            self.ui(lambda: messagebox.showerror("错误", "发生错误: %s" % e))
        finally:
            def _reset():
                self._building = False
                self.build_btn.configure(state="normal", text="生成 EXE")
            self.ui(_reset)

    def _ensure_pyinstaller(self):
        version = check_pyinstaller()
        if version:
            self.log("检测到 PyInstaller %s" % version)
            return True
        self.log("未检测到 PyInstaller。")
        result = {"yes": False}
        self._ask_event.clear()

        def _ask():
            result["yes"] = messagebox.askyesno(
                "缺少依赖",
                "未检测到 PyInstaller, 无法生成 EXE。\n是否现在自动安装? (pip install pyinstaller)")
            self._ask_event.set()
        self.ui(_ask)
        self._ask_event.wait(600)
        if not result["yes"]:
            return False
        self.log("正在安装 PyInstaller, 请稍候...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            self.log("PyInstaller 安装成功。")
            return True
        self.log("安装失败:\n" + (r.stderr or "")[-1500:])
        self.ui(lambda: messagebox.showerror(
            "错误", "PyInstaller 安装失败, 请手动执行:\npip install pyinstaller"))
        return False


def main():
    root = tk.Tk()
    BuilderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
