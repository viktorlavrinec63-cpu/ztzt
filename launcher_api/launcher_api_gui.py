# -*- coding: utf-8 -*-
import os, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import requests, psutil

DEFAULT_PORT=8767
DEFAULT_RUNS=10
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs', 'app.log'))
DONE_MARKERS = ('open_delete_account','connection closed')
WAIT_AFTER_MARKER_SEC = 10
PORTABLE_CHROME_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'GoogleChromePortable'))


def _cmdline_contains_path(proc: psutil.Process, base: str) -> bool:
    try:
        cmd = " ".join(proc.cmdline()).lower()
        return os.path.abspath(base).lower().replace("\\\\","\\").replace("\\","/") in cmd.replace("\\\\","\\").replace("\\","/")
    except Exception:
        return False

def kill_portable_chrome(base_dir: str):
    if not os.path.exists(base_dir):
        return
    for p in psutil.process_iter(["pid","name","cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            if name == "chrome.exe" and _cmdline_contains_path(psutil.Process(p.info["pid"]), base_dir):
                psutil.Process(p.info["pid"]).kill()
        except Exception:
            pass

def _kill_tree(root: psutil.Process):
    for ch in root.children(recursive=True):
        try: ch.kill()
        except Exception: pass
    try: root.kill()
    except Exception: pass

def kill_main_gui_tree():
    for p in psutil.process_iter(["pid","name","cmdline"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or [])
            if not cmd: continue
            if "main_gui.py" in cmd:
                _kill_tree(psutil.Process(p.info["pid"]))
        except Exception:
            pass

import threading

class _TailThread(threading.Thread):
    def __init__(self, logfile, markers, on_hit, stop_event):
        super().__init__(daemon=True)
        self.logfile = logfile
        self.markers = [m.lower() for m in markers]
        self.on_hit = on_hit
        self.stop_event = stop_event
    def run(self):
        # Wait for file
        t0 = time.time()
        while not os.path.exists(self.logfile) and not self.stop_event.is_set():
            time.sleep(0.2)
            if time.time()-t0>120: return
        try:
            with open(self.logfile, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, os.SEEK_END)
                while not self.stop_event.is_set():
                    line = f.readline()
                    if not line:
                        time.sleep(0.2); continue
                    low = line.strip().lower()
                    for m in self.markers:
                        if m and m in low:
                            self.on_hit()
                            return
        except Exception:
            return
class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BazosAutoReg — API Launcher"); self.geometry("680x420")
        self.var_runbat = tk.StringVar(value=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "run.bat")))
        self.var_port = tk.IntVar(value=DEFAULT_PORT)
        self.var_runs = tk.IntVar(value=DEFAULT_RUNS)
        self.var_temp = tk.BooleanVar(value=True)
        self.var_portable = tk.BooleanVar(value=True)
        self.mode_var = tk.StringVar(value="cz_sk")
        frm=ttk.Frame(self,padding=12); frm.pack(fill="both",expand=True)
        r=0
        ttk.Label(frm,text="Путь к run.bat:").grid(column=0,row=r,sticky="w")
        e=ttk.Entry(frm,textvariable=self.var_runbat,width=60); e.grid(column=1,row=r,sticky="we",padx=6)
        ttk.Button(frm,text="Обзор…",command=self._browse).grid(column=2,row=r,sticky="e")
        frm.columnconfigure(1,weight=1); r+=1
        ttk.Label(frm,text="Порт API:").grid(column=0,row=r,sticky="w"); ttk.Entry(frm,textvariable=self.var_port,width=10).grid(column=1,row=r,sticky="w"); r+=1
        ttk.Label(frm,text="Количество запусков:").grid(column=0,row=r,sticky="w"); ttk.Entry(frm,textvariable=self.var_runs,width=10).grid(column=1,row=r,sticky="w"); r+=1
        ttk.Checkbutton(frm,text="Показывать временный браузер (регистрация Bazos)",variable=self.var_temp).grid(column=0,row=r,columnspan=3,sticky="w",pady=(6,0)); r+=1
        ttk.Checkbutton(frm,text="Показывать портативный браузер 2nd-no",variable=self.var_portable).grid(column=0,row=r,columnspan=3,sticky="w"); r+=1
        mode_frame = ttk.Frame(frm)
        mode_frame.grid(column=0, row=r, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(mode_frame, text="Режим регистрации:").pack(pady=5)
        ttk.Radiobutton(mode_frame, text="Только Чехия", variable=self.mode_var, value="cz_only").pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="Только Словакия", variable=self.mode_var, value="sk_only").pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="Чехия → Словакия", variable=self.mode_var, value="cz_sk").pack(anchor="w")
        r+=1
        self.txt=tk.Text(frm,height=12); self.txt.grid(column=0,row=r,columnspan=3,sticky="nsew",pady=(10,0)); frm.rowconfigure(r,weight=1); r+=1
        btns=ttk.Frame(frm); btns.grid(column=0,row=r,columnspan=3,sticky="e",pady=(10,0))
        self.bstart=ttk.Button(btns,text="Старт",command=self.start_main); self.bstart.grid(column=0,row=0,padx=5)
        self.bstop=ttk.Button(btns,text="Стоп",command=self.stop,state="disabled"); self.bstop.grid(column=1,row=0,padx=5)
        self.proc=None; self.stop_flag=False

    def _browse(self):
        p=filedialog.askopenfilename(title="Выберите run.bat",filetypes=[("Batch","*.bat"),("All files","*.*")])
        if p: self.var_runbat.set(p)

    def log(self,s): self.txt.insert("end",f"[{time.strftime('%H:%M:%S')}] {s}\n"); self.txt.see("end"); self.update_idletasks()
    def stop(self): self.stop_flag=True; self.log("Запрошена остановка…")

    def _wait_port(self,port,timeout=45):
        import socket; t0=time.time()
        while time.time()-t0<timeout and not self.stop_flag:
            try:
                with socket.create_connection(("127.0.0.1",port),timeout=0.5): return True
            except Exception: time.sleep(0.3)
        return False

    def start(self):
        runbat=self.var_runbat.get().strip().strip('"')
        if not os.path.exists(runbat): return messagebox.showerror("Ошибка", f"Не найден run.bat:\n{runbat}")
        self.stop_flag=False; self.bstart.configure(state="disabled"); self.bstop.configure(state="normal")
        port=self.var_port.get(); runs=self.var_runs.get()
        for i in range(1,runs+1):
            if self.stop_flag: self.log(f"Остановлено на цикле {i}."); break
            self.log(f"=== Цикл {i}/{runs} ===")
            env=os.environ.copy()
            env["CONTROL_API_PORT"]=str(port)
            env["BAZOS_SHOW_TEMP_BROWSER"]="1" if self.var_temp.get() else "0"
            env["BAZOS_SHOW_PORTABLE_BROWSER"]="1" if self.var_portable.get() else "0"
            try:
                self.proc = subprocess.Popen([runbat], cwd=os.path.dirname(runbat), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1)
            except Exception as e:
                self.log(f"ERROR: запуск run.bat: {e}"); break
            if not self._wait_port(port,60): self.log("ERROR: API не поднялся."); self._kill_proc(); break
            try:
                cfg = {"headful": bool(self.var_temp.get())}
                r = requests.post(f"http://127.0.0.1:{port}/config", json=cfg, timeout=5)
                self.log(f"POST /config -> {r.status_code} {r.text}")
            except Exception as e:
                self.log(f"WARNING: /config failed: {e}")
            try:
                r=requests.post(f"http://127.0.0.1:{port}/start",timeout=10); self.log(f"POST /start -> {r.status_code} {r.text}")
                if r.status_code>=300: self.log("ERROR: /start вернул ошибку"); self._kill_proc(); break
            except Exception as e:
                self.log(f"ERROR: /start: {e}"); self._kill_proc(); break
            # tail app.log for markers while process runs
            hit = {'value': False}
            stop_evt = threading.Event()
            def _hit():
                hit['value']=True
                self.log("Маркер завершения найден в логе (open_delete_account/connection closed).")
            tail = _TailThread(LOG_FILE, DONE_MARKERS, _hit, stop_evt)
            tail.start()

            while self.proc and self.proc.poll() is None and not self.stop_flag and not hit['value']:
                # read a chunk of stdout quickly
                try:
                    line = self.proc.stdout.readline() if self.proc and self.proc.stdout else ''
                    if line:
                        low = line.strip().lower()
                        for m in DONE_MARKERS:
                            if m in low:
                                hit['value']=True
                                self.log('Маркер найден в stdout процесса.')
                                break
                    else:
                        time.sleep(0.1)
                except Exception:
                    time.sleep(0.2)

            # if marker seen while process alive -> wait and kill processes
            if hit['value'] and self.proc and self.proc.poll() is None:
                self.log(f"Ждём {WAIT_AFTER_MARKER_SEC} сек после финальных логов…")
                for _ in range(WAIT_AFTER_MARKER_SEC*10):
                    if self.stop_flag: break
                    time.sleep(0.1)
                try:
                    kill_portable_chrome(PORTABLE_CHROME_DIR)
                    self.log(f"Портативный Chrome в '{PORTABLE_CHROME_DIR}' закрыт.")
                except Exception as e:
                    self.log(f"WARNING: не удалось закрыть Chrome: {e}")
                # аккуратно убиваем только дерево процессов, запущенное этим лаунчером
                try:
                    if self.proc and self.proc.poll() is None:
                        root = psutil.Process(self.proc.pid)
                        _kill_tree(root)
                        self.log("main_gui.py и дочерние процессы (run.bat дерево) закрыты.")
                except Exception as e:
                    self.log(f"WARNING: не удалось закрыть main_gui.py: {e}")

            stop_evt.set()
            self.log("Основной софт завершился."); time.sleep(2)
        self.bstart.configure(state="normal"); self.bstop.configure(state="disabled"); self.log("Готово."); self.proc=None

    def start_main(self):
        mode = self.mode_var.get()
        main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        subprocess.Popen(["python", "main.py", "--mode", mode], cwd=main_path)

    def _kill_proc(self):
        try:
            if self.proc and self.proc.poll() is None:
                psutil.Process(self.proc.pid).terminate()
        except Exception: pass

if __name__=="__main__":
    Launcher().mainloop()
