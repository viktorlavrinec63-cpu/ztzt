import asyncio
import json
import threading
import subprocess
import sys
import os
import logging
import re
import time
import random
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import psutil

# ---------------- logging ----------------
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(os.path.join('logs', 'app.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("GUI")

# глобальный выключатель аварийного убийства дерева процессов (оставляем False по умолчанию)
KILL_BOT_ENABLED = False

# === импорт моста (как у тебя) ===
from app.bridge_ws.integ import (
    start_bridge_and_open,
    queue_command,
    request_number,
    request_sms_code,
    request_delete_account,
    reset_cycle,
    open_2no_and_login,
    set_last_code_for_next_sms,
    wait_ready,
)
from app.control_api.server import ControlServer


DEFAULTS = {
    "runs": 1,
    "headful": True,
    "config": "config.json",
    "proxies": "proxies.txt",
    "profiles": "profiles.json",
    "ws_port": 8765,
}

def load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bazos AutoReg — GUI")
        self.geometry("980x680")

        # base state
        self.runs = tk.IntVar(value=DEFAULTS["runs"])
        self.headful = tk.BooleanVar(value=DEFAULTS["headful"])
        self.config_path = tk.StringVar(value=DEFAULTS["config"])
        self.proxies_path = tk.StringVar(value=DEFAULTS["proxies"])
        self.profiles_path = tk.StringVar(value=DEFAULTS["profiles"])
        self.ws_port = tk.IntVar(value=DEFAULTS["ws_port"])
        self.ws_mode = tk.BooleanVar(value=True)
        self._ws_started = False
        self._bridge_server = None
        self._ws_queue = None
        self._queued_phone = None
        self._phone_sent = False
        self._numbers_page_ready = threading.Event()
        self._ws_rpc_pending = False
        self._sms_request_active = False
        self._sms_request_lock = threading.Lock()
        self._events_thread = None
        self._last_phone_sent = None
        self._last_code_sent = None
        self._awaiting_sms = False
        self._queued_code = None
        self._latest_external_code = None
        self._latest_external_code_ts = 0.0
        self._run_started_at = 0.0
        self._run_wd_timer = None
        self._run_finished = True
        self._last_cycle_code = None
        self._cycle_target_runs = 1
        self._cycle_done = 0
        self._sms_wait_timer = None
        self._sms_wait_deadline = 0.0
        self._did_start_number = False
        self._sms_wait_started_at = None
        self._cleanup_done_event = threading.Event()
        self._cleanup_result_ok = None
        self._cycle_active = False
        self._cycle_started_at = None
        self._bot_proc = None
        self._control_srv = None

        self.SMS_WAIT_LIMIT = 60
        self.CYCLE_HARD_LIMIT = 400

        # provider (загружаем для вкладки)
        cfg = load_json(self.config_path.get(), {})
        self.sms_provider = tk.StringVar(value=cfg.get("sms_provider", "manual"))

        # OnlineSim
        on = cfg.get("onlinesim", {})
        self.os_api_key  = tk.StringVar(value=on.get("api_key", ""))
        self.os_base_url = tk.StringVar(value=on.get("base_url", "https://onlinesim.io"))
        self.os_service  = tk.StringVar(value=on.get("service", "bazos"))
        self.os_poll     = tk.IntVar(value=int(on.get("poll_interval_sec", 5)))
        self.dom_country_mode = tk.StringVar(value=on.get("activation_country_mode", "manual"))
        self.dom_country = tk.StringVar(value=on.get("activation_country", "CZ"))
        self.sms_country_mode = tk.StringVar(value=on.get("sms_number_country_mode", "manual"))
        self.sms_country = tk.StringVar(value=on.get("sms_number_country", "PL"))

        # SMSHub
        sh = cfg.get("smshub", {})
        self.sh_api_key   = tk.StringVar(value=sh.get("api_key", ""))
        self.sh_base_url  = tk.StringVar(value=sh.get("base_url", "https://smshub.org/stubs/handler_api.php"))
        self.sh_service   = tk.StringVar(value=sh.get("service", "cb"))
        self.sh_operator  = tk.StringVar(value=sh.get("operator", "any"))
        self.sh_poll      = tk.IntVar(value=int(sh.get("poll_interval_sec", 5)))
        self.sh_max_price = tk.StringVar(value=str(sh.get("max_price", "")))
        self.sh_random    = tk.BooleanVar(value=bool(sh.get("random", False)))

        # SecondNo (пути отображаем для совместимости)
        sn = cfg.get("secondno", {})
        self.sn_chrome_dir     = tk.StringVar(value=sn.get("chrome_dir", "GoogleChromePortable"))
        self.sn_ext_dir        = tk.StringVar(value=sn.get("ext_dir", "extension_ws_bridge"))
        self.sn_port           = tk.IntVar(value=int(sn.get("port", 8765)))
        self.sn_start_timeout  = tk.IntVar(value=int(sn.get("start_timeout", 3)))

        self.build_ui()

        try:
            import os
            port = int(os.environ.get("CONTROL_API_PORT", "8767"))
        except Exception:
            port = 8767
        try:
            self._control_srv = ControlServer(self, port=port).start()
        except Exception as e:
            try:
                self.append_log(f"[API] control server failed: {e}")
            except Exception:
                pass

    def build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.notebook = nb

        tab_run = ttk.Frame(nb); nb.add(tab_run, text="Запуск")
        tab_provider = ttk.Frame(nb); nb.add(tab_provider, text="SMS провайдер")
        tab_proxies = ttk.Frame(nb); nb.add(tab_proxies, text="Прокси")
        tab_files = ttk.Frame(nb); nb.add(tab_files, text="Файлы")

        self.build_run_tab(tab_run)
        self.build_provider_tab(tab_provider)
        self.build_proxies_tab(tab_proxies)
        self.build_files_tab(tab_files)

    def build_run_tab(self, frm):
        pad = {"padx":6, "pady":6}
        row = 0
        ttk.Label(frm, text="Циклов (runs):").grid(row=row, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=1, to=9999, textvariable=self.runs, width=10).grid(row=row, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Показывать браузер (headful)", variable=self.headful).grid(row=row, column=2, sticky="w", **pad)
        ttk.Checkbutton(frm, text="WS режим (через расширение)", variable=self.ws_mode).grid(row=row, column=3, sticky="w", **pad)
        row += 1

        ttk.Label(frm, text="WS порт:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=1024, to=65535, textvariable=self.ws_port, width=10).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        ttk.Label(frm, text="config.json:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.config_path, width=56).grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(frm, text="...", command=self.pick_config, width=3).grid(row=row, column=3, **pad)
        row += 1

        ttk.Label(frm, text="proxies.txt:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.proxies_path, width=56).grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(frm, text="...", command=self.pick_proxies, width=3).grid(row=row, column=3, **pad)
        row += 1

        ttk.Label(frm, text="profiles.json:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.profiles_path, width=56).grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(frm, text="...", command=self.pick_profiles, width=3).grid(row=row, column=3, **pad)
        row += 1

        self.log = tk.Text(frm, height=18, wrap="word")
        self.log.grid(row=row, column=0, columnspan=4, sticky="nsew", padx=6, pady=(10,6))
        frm.rowconfigure(row, weight=1)
        frm.columnconfigure(1, weight=1)
        row += 1

        # статусная строка
        self.status = tk.StringVar(value="Готово")
        ttk.Label(frm, textvariable=self.status).grid(row=row, column=0, columnspan=4, sticky="we", padx=6)
        row += 1

        bar = ttk.Frame(frm)
        bar.grid(row=row, column=0, columnspan=4, sticky="we")
        ttk.Button(bar, text="Старт", command=self.run).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Открыть папку", command=self.open_folder).pack(side=tk.LEFT, padx=4)

    def build_provider_tab(self, frm):
        pad = {"padx":6, "pady":6}
        row = 0
        ttk.Label(frm, text="Провайдер:").grid(row=row, column=0, sticky="w", **pad)
        cb = ttk.Combobox(frm, textvariable=self.sms_provider,
                          values=["manual","onlinesim","smshub","secondno"],
                          state="readonly", width=20)
        cb.grid(row=row, column=1, sticky="w", **pad)
        cb.bind("<<ComboboxSelected>>", lambda e: self._switch_provider_ui())
        row += 1

        ttk.Separator(frm).grid(row=row, column=0, columnspan=4, sticky="we", pady=4)
        row += 1

        # OnlineSim
        self.os_frame = ttk.LabelFrame(frm, text="OnlineSim")
        self.os_frame.grid(row=row, column=0, columnspan=4, sticky="we", **pad)
        r = 0
        ttk.Label(self.os_frame, text="API key:").grid(row=r, column=0, sticky="w", **pad)
        ttk.Entry(self.os_frame, textvariable=self.os_api_key, width=48).grid(row=r, column=1, sticky="we", **pad)
        ttk.Button(self.os_frame, text="Вставить", command=self.paste_api_key).grid(row=r, column=2, **pad)
        r += 1

        ttk.Label(self.os_frame, text="Base URL:").grid(row=r, column=0, sticky="w", **pad)
        ttk.Entry(self.os_frame, textvariable=self.os_base_url, width=48).grid(row=r, column=1, sticky="we", **pad)
        r += 1

        ttk.Label(self.os_frame, text="Service:").grid(row=r, column=0, sticky="w", **pad)
        ttk.Entry(self.os_frame, textvariable=self.os_service, width=48).grid(row=r, column=1, sticky="we", **pad)
        r += 1

        ttk.Label(self.os_frame, text="Период опроса (сек):").grid(row=r, column=0, sticky="w", **pad)
        ttk.Spinbox(self.os_frame, from_=2, to=60, textvariable=self.os_poll, width=10).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ttk.Label(self.os_frame, text="Страна домена (bazos.*):").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(self.os_frame, textvariable=self.dom_country_mode,
                     values=["manual","same_as_sms"], state="readonly", width=20).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ttk.Label(self.os_frame, text="Если manual — CZ/SK:").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(self.os_frame, textvariable=self.dom_country,
                     values=["CZ","SK"], state="readonly", width=10).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ttk.Label(self.os_frame, text="Страна номера (SMS):").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(self.os_frame, textvariable=self.sms_country_mode,
                     values=["manual","same_as_domain"], state="readonly", width=20).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ttk.Label(self.os_frame, text="Если manual — PL/CZ/SK/DE:").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(self.os_frame, textvariable=self.sms_country,
                     values=["PL","CZ","SK","DE"], state="readonly", width=10).grid(row=r, column=1, sticky="w", **pad)

        # SMSHub
        self.sh_frame = ttk.LabelFrame(frm, text="SMSHub")
        self.sh_frame.grid(row=row+1, column=0, columnspan=4, sticky="we", **pad)
        r2 = 0
        ttk.Label(self.sh_frame, text="API key:").grid(row=r2, column=0, sticky="w", **pad)
        ttk.Entry(self.sh_frame, textvariable=self.sh_api_key, width=48).grid(row=r2, column=1, sticky="we", **pad); r2 += 1
        ttk.Label(self.sh_frame, text="Base URL:").grid(row=r2, column=0, sticky="w", **pad)
        ttk.Entry(self.sh_frame, textvariable=self.sh_base_url, width=48).grid(row=r2, column=1, sticky="we", **pad); r2 += 1
        ttk.Label(self.sh_frame, text="Service:").grid(row=r2, column=0, sticky="w", **pad)
        ttk.Entry(self.sh_frame, textvariable=self.sh_service, width=48).grid(row=r2, column=1, sticky="we", **pad); r2 += 1
        ttk.Label(self.sh_frame, text="Operator:").grid(row=r2, column=0, sticky="w", **pad)
        ttk.Entry(self.sh_frame, textvariable=self.sh_operator, width=48).grid(row=r2, column=1, sticky="we", **pad); r2 += 1
        ttk.Label(self.sh_frame, text="Период опроса (сек):").grid(row=r2, column=0, sticky="w", **pad)
        ttk.Spinbox(self.sh_frame, from_=2, to=60, textvariable=self.sh_poll, width=10).grid(row=r2, column=1, sticky="w", **pad); r2 += 1
        ttk.Label(self.sh_frame, text="Макс. цена (maxPrice):").grid(row=r2, column=0, sticky="w", **pad)
        ttk.Entry(self.sh_frame, textvariable=self.sh_max_price, width=10).grid(row=r2, column=1, sticky="w", **pad)
        ttk.Checkbutton(self.sh_frame, text="Случайная выдача (random)", variable=self.sh_random).grid(row=r2, column=0, columnspan=2, sticky="w", **pad)

        # SecondNo (отображение путей)
        self.sn_frame = ttk.LabelFrame(frm, text="SecondNo (через ChromePortable)")
        self.sn_frame.grid(row=row+2, column=0, columnspan=4, sticky="we", **pad)
        self.sn_frame.columnconfigure(1, weight=1)
        r3 = 0
        ttk.Label(self.sn_frame, text="ChromePortable папка:").grid(row=r3, column=0, sticky="w", **pad)
        ttk.Entry(self.sn_frame, textvariable=self.sn_chrome_dir, width=48).grid(row=r3, column=1, sticky="we", **pad)
        ttk.Button(self.sn_frame, text="...", command=self.pick_sn_chrome_dir, width=3).grid(row=r3, column=2, **pad); r3 += 1
        ttk.Label(self.sn_frame, text="Папка расширения:").grid(row=r3, column=0, sticky="w", **pad)
        ttk.Entry(self.sn_frame, textvariable=self.sn_ext_dir, width=48).grid(row=r3, column=1, sticky="we", **pad)
        ttk.Button(self.sn_frame, text="...", command=self.pick_sn_ext_dir, width=3).grid(row=r3, column=2, **pad); r3 += 1
        ttk.Label(self.sn_frame, text="Локальный порт моста:").grid(row=r3, column=0, sticky="w", **pad)
        ttk.Spinbox(self.sn_frame, from_=1024, to=65535, textvariable=self.sn_port, width=10).grid(row=r3, column=1, sticky="w", **pad); r3 += 1
        ttk.Label(self.sn_frame, text="Задержка старта (сек):").grid(row=r3, column=0, sticky="w", **pad)
        ttk.Spinbox(self.sn_frame, from_=1, to=60, textvariable=self.sn_start_timeout, width=10).grid(row=r3, column=1, sticky="w", **pad)

        ttk.Separator(frm).grid(row=row+3, column=0, columnspan=4, sticky="we", pady=6)
        ttk.Button(frm, text="Сохранить настройки", command=self.save_provider).grid(row=row+4, column=0, sticky="w", **pad)
        self._switch_provider_ui()

    def build_proxies_tab(self, frm):
        pad = {"padx":6, "pady":6}
        ttk.Label(frm, text="proxies.txt:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.proxies_path, width=60).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Открыть", command=self.open_proxies).grid(row=0, column=2, **pad)
        ttk.Button(frm, text="...", command=self.pick_proxies).grid(row=0, column=3, **pad)
        self.proxies_text = tk.Text(frm, height=22, wrap="none")
        self.proxies_text.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=6, pady=(4,6))
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(1, weight=1)
        ttk.Button(frm, text="Сохранить прокси", command=self.save_proxies).grid(row=2, column=0, sticky="w", **pad)
        try:
            with open(self.proxies_path.get(), "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = ""
        self.proxies_text.delete("1.0","end")
        self.proxies_text.insert("1.0", text)

    def build_files_tab(self, frm):
        pad = {"padx":6, "pady":6}
        ttk.Label(frm, text="config.json:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.config_path, width=60).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Открыть", command=self.open_config).grid(row=0, column=2, **pad)
        ttk.Button(frm, text="...", command=self.pick_config).grid(row=0, column=3, **pad)
        ttk.Label(frm, text="profiles.json:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.profiles_path, width=60).grid(row=1, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Открыть", command=self.open_profiles).grid(row=1, column=2, **pad)
        ttk.Button(frm, text="...", command=self.pick_profiles).grid(row=1, column=3, **pad)

    # helpers
    def set_status(self, text):
        if threading.current_thread() is threading.main_thread():
            try:
                self.status.set(text)
                self.update_idletasks()
            except Exception:
                logger.exception("set_status failed")
        else:
            try:
                self.after(0, lambda: self.set_status(text))
            except Exception:
                logger.exception("set_status cross-thread failed")

    def append_log(self, line: str):
        if threading.current_thread() is threading.main_thread():
            try:
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.update_idletasks()
                self._inspect_run_line(line)
            except Exception:
                logger.exception("append_log failed")
        else:
            try:
                self.after(0, lambda: self.append_log(line))
            except Exception:
                logger.exception("append_log cross-thread failed")

    def log_manual(self, text: str):
        """Log manual-mode messages without switching notebook tabs."""
        try:
            self.append_log(f"[manual] {text}")
        except Exception:
            try:
                print(f"[manual] {text}")
            except Exception:
                pass

    def on_manual_event(self, msg: str):
        self.log_manual(msg)

    def _switch_to_sms_tab_if_any(self):
        # GUI no longer switches tabs automatically for SMS provider.
        return

    def _inspect_run_line(self, line: str) -> None:
        if self._run_finished:
            return
        try:
            if not isinstance(line, str):
                return
            text = line.strip()
            if not text:
                return
            lowered = text.lower()
            sms_wait_match = re.search(r"\[sms wait\].*waiting up to\s*(\d+)s", text, flags=re.IGNORECASE)
            if sms_wait_match:
                seconds = int(sms_wait_match.group(1))
                wait_for = min(self.SMS_WAIT_LIMIT, max(1, seconds))
                self._sms_wait_started_at = datetime.utcnow()
                self._sms_wait_deadline = time.time() + wait_for
                timer = self._sms_wait_timer
                if not timer or not timer.is_alive():
                    self._sms_wait_timer = threading.Thread(target=self._sms_timeout_guard, daemon=True)
                    self._sms_wait_timer.start()
            if 'sms_timeout_closed' in lowered:
                if getattr(self, "_cycle_active", False) and not self._run_finished:
                    self._schedule_account_cleanup(
                        f"[GUI] SMS watchdog: {self.SMS_WAIT_LIMIT}s истекли (BOT SMS_TIMEOUT_CLOSED) — аварийная очистка аккаунта и переход к следующему циклу"
                    )
                return
            # Аварийное завершение, если main.py выдал RUN-LEVEL ошибку
            if '[run-level] unexpected error:' in lowered:
                if getattr(self, "_cycle_active", False) and not self._run_finished:
                    self._schedule_account_cleanup(
                        "[GUI] RUN-LEVEL unexpected error — аварийная очистка аккаунта и переход к следующему циклу"
                    )
                return
            if 'start_sms_wait' in lowered and ('country=sk' in lowered or 'second country' in lowered):
                if self._last_cycle_code:
                    try:
                        set_last_code_for_next_sms(self._bridge_server, self._last_cycle_code)
                        self.append_log('[GUI] notified content to ignore previous SMS code')
                    except Exception as exc:
                        try:
                            self.append_log(f"[GUI] set_last_code_for_next_sms error: {exc}")
                        except Exception:
                            logger.exception("set_last_code_for_next_sms error", exc_info=True)
            if 'finalize:' in lowered or re.search(r"\bresult:\s*(cz|sk)", text, re.IGNORECASE):
                if not getattr(self, "_cycle_active", False):
                    return
                self._schedule_account_cleanup("[GUI] finalize detected — удаляю аккаунт и закрываю вкладку")
        except Exception as exc:
            try:
                self.append_log(f"[GUI] cleanup parse error: {exc}")
            except Exception:
                logger.exception("cleanup parse error", exc_info=True)

    def _schedule_account_cleanup(self, message: str) -> None:
        self._run_finished = True
        self._sms_wait_deadline = 0
        self._sms_wait_started_at = None
        self._cycle_active = False
        self._cycle_started_at = None

        def _act() -> None:
            try:
                self.append_log(message)
            except Exception:
                logger.exception("cleanup message log failed")
            try:
                self._kill_bot_tree()
            except Exception:
                logger.exception("kill bot tree failed")
            try:
                try:
                    self._cleanup_done_event.clear()
                except Exception:
                    pass
                self._cleanup_result_ok = None
                try:
                    self.append_log("[GUI] запросил удаление аккаунта")
                except Exception:
                    logger.exception("cleanup wait log failed")
                res = request_delete_account(self._bridge_server)
                if not res.get("ok"):
                    self.append_log(f"[GUI] cleanup request error: {res.get('error')}")
            except Exception as exc:
                try:
                    self.append_log(f"[GUI] cleanup exception: {exc}")
                except Exception:
                    logger.exception("cleanup exception", exc_info=True)
                self._cleanup_result_ok = False
                try:
                    self._cleanup_done_event.set()
                except Exception:
                    pass
            try:
                self._after_cycle_and_maybe_next()
            except Exception:
                logger.exception("after cycle follow-up failed")

        if threading.current_thread() is threading.main_thread():
            _act()
        else:
            try:
                self.after(0, _act)
            except Exception:
                logger.exception("schedule cleanup action failed")
                # ВАЖНО: здесь больше НЕ вызываем request_delete_account — ждём нормальную ветку

    def _after_cycle_and_maybe_next(self) -> None:
        target = max(1, int(self._cycle_target_runs or 1))

        def _worker() -> None:
            self._cycle_done += 1
            done = self._cycle_done
            if done >= target:
                self._cycle_started_at = None
                self._run_finished = True
                self.append_log(f"[GUI] все циклы выполнены: {done}/{target}")
                return
            self.append_log(f"[GUI] старт следующего цикла: {done + 1}/{target}")
            try:
                reset_cycle(self._bridge_server)
            except Exception as exc:
                self.append_log(f"[GUI] reset_cycle error: {exc}")
            try:
                open_2no_and_login(self._bridge_server)
            except Exception as exc:
                self.append_log(f"[GUI] open_2no_and_login error: {exc}")
            self._last_cycle_code = None
            self._run_started_at = time.time()
            self._cycle_started_at = datetime.utcnow()
            self._run_finished = False
            self._sms_wait_deadline = 0
            self._sms_wait_timer = None
            self._awaiting_sms = False
            self._did_start_number = False
            self._sms_wait_started_at = None
            self._cycle_active = False
            self._arm_run_watchdog()

        threading.Thread(target=_worker, daemon=True).start()

    def _arm_run_watchdog(self) -> None:
        mark = datetime.utcnow()
        self._cycle_started_at = mark

        def _wd(current_mark: datetime) -> None:
            time.sleep(self.CYCLE_HARD_LIMIT)
            if self._cycle_started_at != current_mark or self._run_finished:
                return
            self._schedule_account_cleanup(
                f"[GUI] watchdog: {self.CYCLE_HARD_LIMIT}s истекли — аварийная очистка аккаунта"
            )

        t = threading.Thread(target=_wd, args=(mark,), daemon=True)
        t.start()
        self._run_wd_timer = t

    def _sms_timeout_guard(self) -> None:
        while self._sms_wait_deadline:
            if time.time() > self._sms_wait_deadline:
                if self._run_finished:
                    break
                self._schedule_account_cleanup(
                    f"[GUI] SMS timeout {self.SMS_WAIT_LIMIT}s — аварийная очистка аккаунта и переход к следующему циклу"
                )
                break
            time.sleep(0.3)

    def _kill_bot_tree(self) -> None:
        """Terminate bazos bot process and its children (Chrome)."""
        if not KILL_BOT_ENABLED:
            print("[GUI] kill_bot_tree skipped (disabled)")
            return

        proc = self._bot_proc or getattr(self, "_proc", None)
        if not proc:
            return
        try:
            proc.terminate()
        except Exception:
            pass

        try:
            parent = psutil.Process(proc.pid)
        except psutil.Error:
            self._bot_proc = None
            return

        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except Exception:
                pass

        _gone, alive = psutil.wait_procs([parent, *children], timeout=3)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
        try:
            parent.wait(timeout=1)
        except psutil.TimeoutExpired:
            try:
                parent.kill()
            except Exception:
                pass
        except psutil.Error:
            pass

        self._bot_proc = None
        if getattr(self, "_proc", None) is proc:
            self._proc = None

    def _ensure_events_thread(self):
        if self._events_thread and self._events_thread.is_alive():
            return
        self._events_thread = threading.Thread(target=self._events_pump, daemon=True)
        self._events_thread.start()

    def graceful_shutdown(self):
        import sys, time, psutil
        try:
            self.append_log("[SHUTDOWN] graceful shutdown…")
        except Exception:
            pass

        # 1) аккуратно закрыть браузерные контексты/драйверы (если у тебя используются)
        for attr in ("playwright_context", "playwright_browser", "playwright"):
            try:
                obj = getattr(self, attr, None)
                if obj and hasattr(obj, "close"):
                    obj.close()
                if obj and hasattr(obj, "stop"):
                    obj.stop()
            except Exception:
                pass

        # 2) завершить дочерние процессы, запущенные GUI
        try:
            me = psutil.Process()
            kids = me.children(recursive=True)
            for c in kids:
                try:
                    c.terminate()
                except Exception:
                    pass
            psutil.wait_procs(kids, timeout=2)
            for c in kids:
                if c.is_running():
                    try:
                        c.kill()
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            server = getattr(self, "_bridge_server", None)
            if server:
                server.stop_login_watch()
        except Exception:
            pass

        try:
            srv = getattr(self, "_control_srv", None)
            if srv:
                srv.stop()
        except Exception:
            pass

        # 3) закрыть окно Tk и выйти (CMD закроется, если батник с /C)
        try:
            self.destroy()
        except Exception:
            try:
                self.quit()
            except Exception:
                pass

        time.sleep(0.2)
        sys.exit(0)

    def _handle_external_code_callback(self, code: str) -> None:
        self._process_external_code(code, source="callback")

    def _process_external_code(self, code: str, source: str) -> None:
        code = (code or "").strip()
        if not code:
            return
        now = time.time()
        if self._latest_external_code == code and (now - self._latest_external_code_ts) < 30.0:
            self.append_log(f"[GUI] SMS код проигнорирован (дубликат, source={source})")
            return
        self._latest_external_code = code
        self._latest_external_code_ts = now
        self._queued_code = code
        self._last_cycle_code = code
        self.set_status(f"🔐 Получен SMS код ({len(code)} цифр)")
        self.append_log(f"[GUI] SMS код получен ({source}, len={len(code)})")
        self._switch_to_sms_tab_if_any()
        self._send_code_to_bot(code)

    def _send_code_to_bot(self, code: str) -> bool:
        code = (code or "").strip()
        if not code:
            return False

        self._queued_code = code

        proc = None
        for attr in ("_proc", "proc_main", "_proc_main", "bot_proc", "_bot_proc", "bazos_proc", "_bazos_proc"):
            candidate = getattr(self, attr, None)
            if candidate is not None:
                proc = candidate
                break

        if not proc:
            self.append_log("[GUI] нет активного процесса для SMS кода — оставлен в очереди")
            return False

        stream = getattr(proc, "stdin", None)
        if not stream:
            self.append_log("[GUI] у процесса нет stdin, код оставлен в очереди")
            return False

        line = code + "\n"
        try:
            try:
                stream.write(line)
            except TypeError:
                stream.write(line.encode("utf-8"))
            stream.flush()
        except Exception as exc:
            self.append_log(f"[GUI] не удалось отправить SMS код в stdin: {exc}")
            return False

        self._last_code_sent = code
        self._awaiting_sms = False
        self._queued_code = None
        self._sms_wait_deadline = 0
        self.append_log(f"[GUI] SMS код отправлен в stdin (len={len(code)})")
        return True

    def _events_pump(self):
        while True:
            server = getattr(self, "_bridge_server", None)
            if not server:
                time.sleep(0.2)
                continue
            loop = getattr(server, "loop", None)
            events = getattr(server, "events", None)
            if loop is None or events is None:
                time.sleep(0.2)
                continue
            try:
                loop_running = loop.is_running()
            except Exception:
                loop_running = False
            if not loop_running:
                time.sleep(0.2)
                continue
            try:
                fut = asyncio.run_coroutine_threadsafe(events.get(), loop)
                payload = fut.result()
            except Exception:
                time.sleep(0.2)
                continue
            try:
                self._handle_bridge_event(payload)
            except Exception:
                logger.exception("handle bridge event failed")

    def _handle_bridge_event(self, payload):
        if not isinstance(payload, dict):
            return
        event_type = (payload.get("event") or payload.get("type") or "").lower()
        if event_type == "page_ready_numbers":
            self._handle_bridge_page_ready(payload)
        elif event_type == "external_number":
            self._handle_bridge_number(payload)
        elif event_type == "external_code":
            self._handle_bridge_code(payload)
        elif event_type == "login_reached":
            try:
                self.append_log("[EXT] login page (or app) reached")
            except Exception:
                pass
            server = getattr(self, "_bridge_server", None)
            if server:
                try:
                    server.stop_login_watch()
                except Exception:
                    pass
            return
        elif event_type == "login_watch_limit":
            try:
                self.append_log("[EXT] login-watch reached limit (3 min). Stopping reloads.")
            except Exception:
                pass
            return
        elif event_type == "browser_closed":
            try:
                self.append_log("[EXT] browser window closed by extension")
            except Exception:
                pass
            try:
                self.graceful_shutdown()
            except Exception:
                pass
            return
        elif event_type == "result":
            of = payload.get("of")
            ok = payload.get("ok")
            try:
                self.append_log(f"[SW] result: of={of} ok={ok}")
            except Exception:
                pass
        elif event_type == "delete_done":
            self._handle_bridge_delete(payload)
        elif event_type == "cleanup_done_broadcast":
            self._handle_cleanup_done(payload)

    def _handle_bridge_page_ready(self, payload):
        server = getattr(self, "_bridge_server", None)
        if server:
            try:
                server.stop_login_watch()
            except Exception:
                pass
        self._numbers_page_ready.set()
        self._cycle_active = True
        if self._ws_rpc_pending:
            return

        self._ws_rpc_pending = True

        def _notify_ready():
            try:
                self.append_log("[bridge] страница My numbers готова (event)")
            except Exception:
                pass

        try:
            self.after(0, _notify_ready)
        except Exception:
            _notify_ready()

        def _trigger_rpc():
            try:
                self.append_log("[WS] page_ready_numbers → отправляю start_number_registration…")
                self.ws_request_number_and_proceed(timeout_sec=45.0)
            except Exception as exc:
                self.append_log(f"[WS] ошибка запроса номера (page_ready): {exc}")
            finally:
                self._ws_rpc_pending = False

        threading.Thread(target=_trigger_rpc, daemon=True).start()

    def _handle_bridge_number(self, payload):
        number = (
            payload.get("number")
            or payload.get("value")
            or payload.get("phone")
        )
        if not number:
            return
        number = str(number).strip()
        if not number:
            return

        self._queued_phone = number
        if number == self._last_phone_sent and self._phone_sent:
            return
        self._last_phone_sent = number

        def _apply():
            try:
                self.set_status(f"☎ Получен номер: {number}")
                self._switch_to_sms_tab_if_any()
                proc = getattr(self, "_proc", None)
                if proc and proc.stdin and not self._phone_sent:
                    try:
                        proc.stdin.write(number + "\n")
                        proc.stdin.flush()
                        self._phone_sent = True
                        self.append_log(f"[GUI] phone auto-sent (ws): {number}")
                    except Exception:
                        self.append_log(f"[GUI] номер получен (ws): {number}")
                else:
                    if not proc:
                        self.append_log(f"[GUI] номер получен (ws): {number}")
            except Exception:
                pass

        if threading.current_thread() is threading.main_thread():
            _apply()
        else:
            try:
                self.after(0, _apply)
            except Exception:
                _apply()

    def _handle_bridge_code(self, payload):
        code = payload.get("code") or payload.get("value")
        if code is None:
            return
        self._process_external_code(code, source="ws-event")

    def _handle_bridge_delete(self, payload):
        ok = bool(payload.get("ok", True))
        rid = payload.get("rid")
        if ok:
            msg = "Аккаунт удалён через расширение"
            try:
                server = getattr(self, "_bridge_server", None)
                if server:
                    server.request_close_browser_window()
            except Exception:
                pass
        else:
            err = payload.get("error") or "unknown"
            msg = f"Не удалось удалить аккаунт (rid={rid or 'n/a'}): {err}"
        self.log_manual(msg)

    def _handle_cleanup_done(self, payload):
        ok = bool(payload.get("ok", False))
        self._cleanup_result_ok = ok
        try:
            self._cleanup_done_event.set()
        except Exception:
            pass
        try:
            state = "успешно" if ok else "с ошибками"
            self.append_log(f"[GUI] cleanup_done_broadcast: завершено {state}")
        except Exception:
            pass

    def _handle_sms_wait_line(self, line: str) -> None:
        with self._sms_request_lock:
            if self._sms_request_active:
                return
            self._sms_request_active = True
            self._awaiting_sms = True
            self._last_code_sent = None

        timeout_sec = float(self.SMS_WAIT_LIMIT)
        try:
            match = re.search(r"up to\s+([0-9]+(?:\.[0-9]+)?)s", line, flags=re.IGNORECASE)
            if match:
                timeout_sec = min(float(match.group(1)), float(self.SMS_WAIT_LIMIT))
        except Exception:
            pass

        self.append_log(f"[GUI] обнаружен запрос SMS кода (ожидание ≈ {int(timeout_sec)}s)")
        self._switch_to_sms_tab_if_any()
        self._sms_wait_started_at = datetime.utcnow()
        self._sms_wait_deadline = time.time() + timeout_sec
        timer = self._sms_wait_timer
        if not timer or not timer.is_alive():
            self._sms_wait_timer = threading.Thread(target=self._sms_timeout_guard, daemon=True)
            self._sms_wait_timer.start()

        # если код уже пришёл ранее — отправляем немедленно и завершаем
        queued = self._queued_code
        if queued and self._send_code_to_bot(str(queued)):
            with self._sms_request_lock:
                self._sms_request_active = False
            return

        def _worker() -> None:
            try:
                server = getattr(self, "_bridge_server", None)
                if not server:
                    return
                if not wait_ready(server, timeout_sec=min(10.0, timeout_sec)):
                    self.append_log("[WS] расширение не готово для запроса SMS кода")
                    return
                try:
                    res = request_sms_code(server, timeout_sec=timeout_sec)
                except Exception as exc:
                    self.append_log(f"[GUI] ошибка ожидания SMS кода: {exc}")
                    return
                if not res or not (res.get("code") or res.get("value")):
                    self.append_log("[GUI] SMS код не получен (timeout/ws)")
                    self._awaiting_sms = False
            finally:
                with self._sms_request_lock:
                    self._sms_request_active = False

        threading.Thread(target=_worker, daemon=True).start()

    def open_folder(self):
        base_dir = Path(__file__).resolve().parent
        os.startfile(str(base_dir))

    # pickers
    def paste_api_key(self):
        try:
            txt = self.clipboard_get().strip()
            if not txt:
                return
            if self.sms_provider.get() == "smshub":
                self.sh_api_key.set(txt)
                self.append_log("Вставлен API key в SMSHub")
            else:
                self.os_api_key.set(txt)
                self.append_log("Вставлен API key в OnlineSim")
        except Exception:
            logger.exception("paste_api_key failed")

    def pick_config(self):
        p = filedialog.askopenfilename(title="Выбрать config.json", filetypes=[("JSON","*.json"),("Все файлы","*.*")])
        if p: self.config_path.set(p)

    def pick_proxies(self):
        p = filedialog.askopenfilename(title="Выбрать proxies.txt", filetypes=[("TXT","*.txt"),("Все файлы","*.*")])
        if p: self.proxies_path.set(p)

    def pick_profiles(self):
        p = filedialog.askopenfilename(title="Выбрать profiles.json", filetypes=[("JSON","*.json"),("Все файлы","*.*")])
        if p: self.profiles_path.set(p)

    def pick_sn_chrome_dir(self):
        d = filedialog.askdirectory(title="Выбрать папку GoogleChromePortable")
        if d:
            self.sn_chrome_dir.set(Path(d).name)

    def pick_sn_ext_dir(self):
        d = filedialog.askdirectory(title="Выбрать папку расширения (extension_ws_bridge)")
        if d:
            self.sn_ext_dir.set(Path(d).name)

    # config save / provider switch
    def save_provider(self, silent: bool=False):
        try:
            path = self.config_path.get() or "config.json"
            cfg = load_json(path, {})
            cfg["sms_provider"] = self.sms_provider.get()

            cfg.setdefault("onlinesim", {})
            cfg["onlinesim"]["api_key"] = self.os_api_key.get().strip()
            cfg["onlinesim"]["base_url"] = self.os_base_url.get().strip()
            cfg["onlinesim"]["service"] = self.os_service.get().strip() or "bazos"
            cfg["onlinesim"]["poll_interval_sec"] = int(self.os_poll.get() or 5)
            cfg["onlinesim"]["activation_country_mode"] = self.dom_country_mode.get()
            cfg["onlinesim"]["activation_country"] = self.dom_country.get()
            cfg["onlinesim"]["sms_number_country_mode"] = self.sms_country_mode.get()
            cfg["onlinesim"]["sms_number_country"] = self.sms_country.get()

            cfg.setdefault("smshub", {})
            cfg["smshub"]["api_key"] = self.sh_api_key.get().strip()
            cfg["smshub"]["base_url"] = self.sh_base_url.get().strip()
            cfg["smshub"]["service"] = self.sh_service.get().strip() or "cb"
            cfg["smshub"]["operator"] = self.sh_operator.get().strip() or "any"
            cfg["smshub"]["poll_interval_sec"] = int(self.sh_poll.get() or 5)
            if self.sh_max_price.get().strip():
                try:
                    cfg["smshub"]["max_price"] = float(self.sh_max_price.get().strip())
                except Exception:
                    pass
            cfg["smshub"]["random"] = bool(self.sh_random.get())

            cfg.setdefault("secondno", {})
            cfg["secondno"]["chrome_dir"] = self.sn_chrome_dir.get().strip()
            cfg["secondno"]["ext_dir"]    = self.sn_ext_dir.get().strip()
            cfg["secondno"]["port"]       = int(self.sn_port.get() or 8765)
            cfg["secondno"]["start_timeout"] = int(self.sn_start_timeout.get() or 3)

            save_json(path, cfg)
            if not silent:
                messagebox.showinfo("Сохранено", f"Настройки сохранены в:\n{path}")
        except Exception:
            logger.exception("save_provider failed")
            if not silent:
                messagebox.showerror("Ошибка", "Не удалось сохранить настройки. Подробности в logs/app.log")

    def _switch_provider_ui(self):
        # показать только выбранный фрейм
        for frm in ("os_frame", "sh_frame", "sn_frame"):
            try:
                getattr(self, frm).grid_remove()
            except Exception:
                pass
        p = self.sms_provider.get()
        try:
            if p == "onlinesim":
                self.os_frame.grid()
            elif p == "smshub":
                self.sh_frame.grid()
            elif p == "secondno":
                self.sn_frame.grid()
        except Exception:
            pass

    # proxies/files
    def open_proxies(self):
        p = Path(self.proxies_path.get() or "proxies.txt")
        if not p.exists():
            p.write_text("", encoding="utf-8")
        os.startfile(str(p))

    def save_proxies(self):
        try:
            p = Path(self.proxies_path.get() or "proxies.txt")
            if not p.exists():
                p.write_text("", encoding="utf-8")
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.proxies_text.get("1.0","end"))
            messagebox.showinfo("OK", f"Сохранено:\n{p}")
        except Exception:
            logger.exception("save_proxies failed")

    def open_config(self):
        p = Path(self.config_path.get() or "config.json")
        if not p.exists():
            p.write_text("{}", encoding="utf-8")
        os.startfile(str(p))

    def open_profiles(self):
        p = Path(self.profiles_path.get() or "profiles.json")
        if not p.exists():
            p.write_text("[]", encoding="utf-8")
        os.startfile(str(p))

    # ---------------- START ----------------
    def run(self):
        try:
            self._cycle_target_runs = max(1, int(self.runs.get() or 1))
        except Exception:
            self._cycle_target_runs = 1
        self._cycle_done = 0
        self._last_cycle_code = None
        self._run_started_at = time.time()
        self._cycle_started_at = datetime.utcnow()
        self._run_finished = False
        self._cycle_active = False
        self._arm_run_watchdog()
        # === Auto-login to 2nd-no via WS bridge ===
        try:
            print("[AUTOLOGIN] run pipeline to open 2nd-no and click Google")
            from app.bridge_ws.autologin import auto_login_google
            asyncio.run(auto_login_google())
        except Exception as _e:
            print("[AUTOLOGIN] skipped or failed:", _e)
        # === end autologin ===
        try:
            # сохраняем настройки провайдера перед запуском
            self.save_provider(silent=True)

            base_dir = Path(__file__).resolve().parent
            py = sys.executable or "python"

            # 1) WS мост + открытие 2nd-no — только при первом клике Start
            if self.ws_mode.get() and not self._ws_started:
                # визуальный статус для manual
                if self.sms_provider.get() == "manual":
                    self.set_status("⏳ Ожидаю польский номер (+48) от расширения…")
                try:
                    port = int(self.ws_port.get() or 8765)
                    self._numbers_page_ready.clear()
                    self._bridge_server = start_bridge_and_open(base_dir='.', ws_port=port, url='https://2nd-no.com/')
                    self._ws_started = True
                    if self._bridge_server:
                        self._bridge_server.on_external_code = self._handle_external_code_callback
                        self._bridge_server.append_log = self.append_log
                        self._ws_queue = lambda payload: queue_command(self._bridge_server, payload)
                        try:
                            self._bridge_server.start_login_watch()
                        except Exception:
                            pass
                    self.append_log(f"[bridge] WS запущен на порту {port}")

                    if self._bridge_server:
                        self._ensure_events_thread()

                    # Автоклик по кнопке "Login with Google"
                    try:
                        if self._ws_queue:
                            self._ws_queue({"type":"run_js","code":'(function autoClickGoogle(){\n  function byText(tag, text){\n    var els = Array.from(document.querySelectorAll(tag));\n    return els.find(e => (e.textContent||\'\').trim().toLowerCase() === text.toLowerCase());\n  }\n  var btn = byText(\'button\',\'Login with Google\');\n  if(!btn){\n    try{\n      var xp = document.evaluate("//button[contains(., \'Login with Google\')]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;\n      if(xp) btn = xp;\n    }catch(e){}\n  }\n  if(!btn){\n    var labels = Array.from(document.querySelectorAll(\'button, .button, .btn\')).filter(b=>/login with google/i.test(b.textContent||\'\'));\n    if(labels.length) btn = labels[0];\n  }\n  if(btn){ btn.click(); return \'clicked\'; }\n  setTimeout(autoClickGoogle, 600);\n  return \'waiting\';\n})();'})
                            self.append_log("[bridge] queued run_js: click Google")
                    except Exception as e:
                        try:
                            if self._ws_queue:
                                self._ws_queue({"type":"eval","code":'(function autoClickGoogle(){\n  function byText(tag, text){\n    var els = Array.from(document.querySelectorAll(tag));\n    return els.find(e => (e.textContent||\'\').trim().toLowerCase() === text.toLowerCase());\n  }\n  var btn = byText(\'button\',\'Login with Google\');\n  if(!btn){\n    try{\n      var xp = document.evaluate("//button[contains(., \'Login with Google\')]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;\n      if(xp) btn = xp;\n    }catch(e){}\n  }\n  if(!btn){\n    var labels = Array.from(document.querySelectorAll(\'button, .button, .btn\')).filter(b=>/login with google/i.test(b.textContent||\'\'));\n    if(labels.length) btn = labels[0];\n  }\n  if(btn){ btn.click(); return \'clicked\'; }\n  setTimeout(autoClickGoogle, 600);\n  return \'waiting\';\n})();'})
                                self.append_log("[bridge] queued eval: click Google")
                        except Exception as e2:
                            self.append_log(f"[bridge] cannot queue click: {e2}")

                except Exception as e:
                    self.append_log(f"[bridge error] {e}")

            if self.ws_mode.get() and self._bridge_server:
                try:
                    reset_cycle(self._bridge_server)
                except Exception as exc:
                    self.append_log(f"[bridge] reset_cycle error: {exc}")
                try:
                    open_2no_and_login(self._bridge_server)
                except Exception as exc:
                    self.append_log(f"[bridge] open_2no_and_login error: {exc}")
                else:
                    try:
                        self._bridge_server.start_login_watch()
                    except Exception:
                        pass

            # 2) Запускаем main.py, если он есть
            main_py = base_dir / "main.py"
            if main_py.exists():
                cmd = [py, str(main_py),
                       "--runs", str(self.runs.get() or 1),
                       "--proxies", self.proxies_path.get(),
                       "--profiles", self.profiles_path.get(),
                       "--config", self.config_path.get()]
                if self.headful.get():
                    cmd.append("--headful")
                if self.ws_mode.get():
                    cmd.append("--ws-mode")

                self.append_log(">>> " + " ".join(cmd))
                logger.info("RUN: %s", " ".join(cmd))
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    text=True,
                    cwd=str(base_dir)
                )
                # сохраним процесс для автоподстановки номера
                self._proc = proc
                self._bot_proc = proc
                self._phone_sent = False
                self._queued_phone = None
                self._last_phone_sent = None
                self._last_code_sent = None

                def reader():
                    try:
                        for raw in proc.stdout:
                            line = raw.rstrip()
                            self.append_log(line)

                            # если manual провайдер попросил номер — отправим, если уже есть
                            try:
                                if ('[manual]' in line and 'Введите номер телефона' in line) and self._queued_phone and not self._phone_sent:
                                    self._proc.stdin.write(self._queued_phone + "\\n")
                                    self._proc.stdin.flush()
                                    self._phone_sent = True
                                    self.append_log(f"[GUI] phone auto-sent on prompt: {self._queued_phone}")
                            except Exception:
                                pass

                            # ловим польский номер +48 и либо ставим в очередь, либо сразу отправляем
                            try:
                                m = re.search(r"(\\+?48[\\s\\-()]*\\d(?:[\\s\\-()]*\\d){8})", line)
                                if m:
                                    ph = re.sub(r"[^\\d]", "", m.group(1))
                                    if not ph.startswith('48'):
                                        # на случай, если пришло +... но не 48
                                        pass
                                    ph = '+' + ph if not ph.startswith('+') else '+' + ph.lstrip('+')
                                    self.set_status(f"☎ Получен польский номер: {ph}")
                                    self._queued_phone = ph
                                    self._switch_to_sms_tab_if_any()
                                    if not self._phone_sent:
                                        try:
                                            self._proc.stdin.write(ph + "\\n")
                                            self._proc.stdin.flush()
                                            self._phone_sent = True
                                            self.append_log(f"[GUI] phone auto-sent: {ph}")
                                        except Exception:
                                            pass
                            except Exception:
                                pass

                            if "[SMS WAIT]" in line or "waiting up to" in line.lower():
                                try:
                                    self._handle_sms_wait_line(line)
                                except Exception:
                                    logger.exception("handle sms wait failed")

                    except Exception:
                        logger.exception("reader failed")

                threading.Thread(target=reader, daemon=True).start()
            else:
                self.append_log("main.py не найден — открыт только браузер")
        except Exception:
            logger.exception("run failed")
            messagebox.showerror("Ошибка запуска", "Смотри logs/app.log")

    # === RPC helper: запросить номер через расширение и сразу пробросить в подпроцесс ===
    def ws_request_number_and_proceed(self, timeout_sec: float = 45.0) -> bool:
        if not self._bridge_server:
            self.append_log("[WS] мост не запущен")
            return False
        if not wait_ready(self._bridge_server, timeout_sec=min(10.0, timeout_sec)):
            self.append_log("[WS] расширение не подключено")
            return False
        if not self._numbers_page_ready.wait(timeout=15):
            self.append_log("[WS] страница My numbers не готова")
            return False
        try:
            self.set_status("⏳ Запрашиваю номер у 2nd-no…")
            res = request_number(self._bridge_server, timeout_sec=timeout_sec)
            if not res or not res.get("number"):
                self.append_log("[WS] номер не получен (timeout/none)")
                return False
            number = res["number"]
            self._queued_phone = number
            self._switch_to_sms_tab_if_any()
            self.set_status(f"☎ Получен номер: {number}")
            if getattr(self, "_proc", None):
                try:
                    self._proc.stdin.write(number + "\n")
                    self._proc.stdin.flush()
                    self._phone_sent = True
                    self.append_log(f"[GUI] phone sent (rpc): {number}")
                except Exception:
                    pass
            self._cycle_active = True
            return True
        except Exception as e:
            self.append_log(f"[WS] ошибка запроса номера: {e}")
            return False

    def on_click_ws_create_number(self):
        if not self._bridge_server:
            self.append_log("[WS] мост не запущен")
            return
        if not wait_ready(self._bridge_server, timeout_sec=10.0):
            self.append_log("[WS] расширение не подключено")
            return
        if self._ws_rpc_pending:
            self.append_log("[WS] запрос номера уже выполняется")
            return

        self._ws_rpc_pending = True
        self.append_log("[WS] ручной запуск → отправляю start_number_registration…")

        def _worker() -> None:
            try:
                ok = self.ws_request_number_and_proceed(timeout_sec=45.0)
                if not ok:
                    self.append_log("[WS] номер не получен (timeout/none) — смотри логи background.js и консоль страницы")
            except Exception as exc:  # pragma: no cover - GUI safety
                self.append_log(f"[WS] ошибка запроса номера (manual): {exc}")
            finally:
                self._ws_rpc_pending = False

        threading.Thread(target=_worker, daemon=True).start()

if __name__ == "__main__":
    logger.info("Starting GUI")
    App().mainloop()
