"""
STT Master Control GUI
- Server Start/Stop (configurable port)
- STT Audio Capture Start/Stop (with auto-reconnect)
- Subtitle Overlay Show/Hide
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
from queue import Queue

import numpy as np
import soundcard as sc
import websockets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLING_RATE = 16000
CHUNK_FRAMES = 3200  # 0.2 s
DEFAULT_PORT = 8000
RECONNECT_DELAY = 2.0  # seconds


# ===================================================================
# ServerManager -- uvicorn subprocess start / stop / is_alive
# ===================================================================
class ServerManager:
    def __init__(self, log_callback=None):
        self._proc: subprocess.Popen | None = None
        self._log = log_callback or (lambda msg: None)
        self._reader_thread: threading.Thread | None = None
        self.port: int = DEFAULT_PORT

    # -- public API --------------------------------------------------
    def start(self, port: int | None = None):
        if self.is_alive():
            self._log("[Server] Already running.")
            return
        if port is not None:
            self.port = port

        env = os.environ.copy()
        env["MODELSCOPE_CACHE"] = os.path.join(BASE_DIR, "models")

        uvicorn_exe = os.path.join(BASE_DIR, ".venv", "Scripts", "uvicorn.exe")
        cmd = [uvicorn_exe, "server.app.main:app",
               "--host", "0.0.0.0", "--port", str(self.port)]

        try:
            self._proc = subprocess.Popen(
                cmd, cwd=BASE_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._reader_thread = threading.Thread(
                target=self._read_stdout, daemon=True)
            self._reader_thread.start()
            self._log(f"[Server] Starting uvicorn on port {self.port}...")
        except Exception as exc:
            self._log(f"[Server] Failed to start: {exc}")

    def stop(self):
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        except Exception:
            pass
        self._proc = None
        self._log("[Server] Stopped.")

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- internal ----------------------------------------------------
    def _read_stdout(self):
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self._log(f"[Server] {line.rstrip()}")
        except Exception:
            pass


# ===================================================================
# AudioStreamer -- WASAPI loopback capture + WebSocket streaming
# ===================================================================
class AudioStreamer:
    def __init__(self, log_callback=None, subtitle_callback=None):
        self._log = log_callback or (lambda msg: None)
        self._on_subtitle = subtitle_callback or (lambda text: None)
        self._running = False
        self._thread: threading.Thread | None = None
        self._ws_uri: str = ""
        # client-side dedup
        self._last_text: str = ""

    # -- public API --------------------------------------------------
    def start(self, port: int = DEFAULT_PORT):
        if self._running:
            self._log("[STT] Already running.")
            return
        self._ws_uri = f"ws://localhost:{port}/ws/stt"
        self._running = True
        self._last_text = ""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._log("[STT] Audio capture started.")

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._log("[STT] Audio capture stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    # -- internal ----------------------------------------------------
    def _run_loop(self):
        """Outer loop: keeps reconnecting while self._running is True."""
        while self._running:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._stream())
            except Exception as exc:
                if self._running:
                    self._log(f"[STT] Connection lost: {exc}")
                    self._log(f"[STT] Reconnecting in {RECONNECT_DELAY}s...")
                    time.sleep(RECONNECT_DELAY)
            finally:
                loop.close()

    async def _stream(self):
        audio_q: Queue = Queue()

        # start recorder thread
        rec_thread = threading.Thread(
            target=self._record_worker, args=(audio_q,), daemon=True)
        rec_thread.start()

        async with websockets.connect(self._ws_uri) as ws:
            self._log("[STT] Connected to server.")
            while self._running:
                # send queued audio
                while not audio_q.empty():
                    data = audio_q.get_nowait()
                    chunk_int16 = (data[:, 0] * 32767).astype(np.int16)
                    await ws.send(chunk_int16.tobytes())

                # receive subtitles (non-blocking)
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=0.05)
                    msg = json.loads(resp)
                    subs = msg.get("subtitles", [])
                    if subs:
                        text = " ".join(s["text"] for s in subs)
                        # client-side dedup: skip if identical to last
                        if text and text != self._last_text:
                            self._last_text = text
                            self._on_subtitle(text)
                            self._log(f"[STT] {text}")
                except asyncio.TimeoutError:
                    pass

                await asyncio.sleep(0.01)

    def _record_worker(self, audio_q: Queue):
        try:
            mics = sc.all_microphones(include_loopback=True)
            loopback = next(
                (m for m in mics
                 if "loopback" in m.name.lower() or "\ub8e8\ud504\ubc31" in m.name),
                mics[0] if mics else None,
            )
            if loopback is None:
                self._log("[STT] No audio device found.")
                self._running = False
                return
            self._log(f"[STT] Recording from: {loopback.name}")
            with loopback.recorder(samplerate=SAMPLING_RATE, channels=1) as rec:
                while self._running:
                    data = rec.record(numframes=CHUNK_FRAMES)
                    audio_q.put(data)
        except Exception as exc:
            self._log(f"[STT] Record error: {exc}")
            self._running = False


# ===================================================================
# SubtitleOverlay -- transparent Toplevel window
# ===================================================================
class SubtitleOverlay:
    FADE_TIMEOUT = 3.0  # seconds before clearing text

    def __init__(self, master: tk.Tk):
        self._win = tk.Toplevel(master)
        self._win.overrideredirect(True)
        self._win.attributes("-alpha", 0.85)
        self._win.attributes("-topmost", True)
        self._win.configure(bg="black")

        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        w, h = 1400, 150
        x = (sw - w) // 2
        y = sh - 220
        self._win.geometry(f"{w}x{h}+{x}+{y}")

        self._label = tk.Label(
            self._win, text="", font=("Malgun Gothic", 36, "bold"),
            fg="#FFFF00", bg="black", wraplength=1300,
        )
        self._label.pack(expand=True)

        self._last_update: float = 0.0
        self._visible = True

    # -- public API --------------------------------------------------
    def set_text(self, text: str):
        self._label.config(text=text)
        self._last_update = time.time()

    def tick(self):
        """Call from main-thread polling loop to auto-clear stale text."""
        if self._last_update and time.time() - self._last_update > self.FADE_TIMEOUT:
            self._label.config(text="")
            self._last_update = 0.0

    def toggle(self):
        if self._visible:
            self._win.withdraw()
        else:
            self._win.deiconify()
        self._visible = not self._visible

    @property
    def visible(self) -> bool:
        return self._visible

    def destroy(self):
        self._win.destroy()


# ===================================================================
# MasterControlGUI -- main Tk application
# ===================================================================
class MasterControlGUI:
    POLL_MS = 50       # GUI queue polling interval
    STATUS_MS = 1000   # status check interval

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("STT Master Control")
        self.root.geometry("620x520")
        self.root.attributes("-topmost", True)

        # thread-safe queues for GUI updates
        self._log_q: Queue = Queue()
        self._sub_q: Queue = Queue()

        # managers
        self.server = ServerManager(log_callback=self._enqueue_log)
        self.streamer = AudioStreamer(
            log_callback=self._enqueue_log,
            subtitle_callback=self._enqueue_subtitle,
        )

        self._build_ui()
        self.overlay = SubtitleOverlay(self.root)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # start polling loops
        self._poll_queues()
        self._poll_status()

        self._enqueue_log("System initialized.")

    # -- UI construction ---------------------------------------------
    def _build_ui(self):
        pad = dict(padx=10, pady=(5, 0), fill=tk.X)

        # --- Server Control ---
        frm_srv = ttk.LabelFrame(self.root, text="Server Control")
        frm_srv.pack(**pad)
        inner_srv = tk.Frame(frm_srv)
        inner_srv.pack(fill=tk.X, padx=5, pady=5)

        self.btn_srv_start = ttk.Button(
            inner_srv, text="Start Server", command=self._cmd_server_start)
        self.btn_srv_start.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_srv_stop = ttk.Button(
            inner_srv, text="Stop Server", command=self._cmd_server_stop)
        self.btn_srv_stop.pack(side=tk.LEFT, padx=(0, 5))

        # port entry
        tk.Label(inner_srv, text="Port:", font=("Consolas", 9)).pack(
            side=tk.LEFT, padx=(10, 2))
        self._port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self._port_entry = ttk.Entry(inner_srv, textvariable=self._port_var,
                                     width=6, font=("Consolas", 10))
        self._port_entry.pack(side=tk.LEFT)

        self.lbl_srv = tk.Label(
            inner_srv, text="OFFLINE", fg="red",
            font=("Consolas", 10, "bold"))
        self.lbl_srv.pack(side=tk.RIGHT, padx=5)

        # --- STT Audio Capture ---
        frm_stt = ttk.LabelFrame(self.root, text="STT Audio Capture")
        frm_stt.pack(**pad)
        inner_stt = tk.Frame(frm_stt)
        inner_stt.pack(fill=tk.X, padx=5, pady=5)

        self.btn_stt_start = ttk.Button(
            inner_stt, text="Start STT", command=self._cmd_stt_start)
        self.btn_stt_start.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_stt_stop = ttk.Button(
            inner_stt, text="Stop STT", command=self._cmd_stt_stop)
        self.btn_stt_stop.pack(side=tk.LEFT, padx=(0, 5))

        self.lbl_stt = tk.Label(
            inner_stt, text="IDLE", fg="gray",
            font=("Consolas", 10, "bold"))
        self.lbl_stt.pack(side=tk.RIGHT, padx=5)

        # --- Subtitle Overlay ---
        frm_sub = ttk.LabelFrame(self.root, text="Subtitle Overlay")
        frm_sub.pack(**pad)
        inner_sub = tk.Frame(frm_sub)
        inner_sub.pack(fill=tk.X, padx=5, pady=5)

        self.btn_sub_toggle = ttk.Button(
            inner_sub, text="Hide Subtitle", command=self._cmd_sub_toggle)
        self.btn_sub_toggle.pack(side=tk.LEFT, padx=(0, 5))

        self.lbl_sub = tk.Label(
            inner_sub, text="VISIBLE", fg="green",
            font=("Consolas", 10, "bold"))
        self.lbl_sub.pack(side=tk.RIGHT, padx=5)

        # --- System Logs ---
        frm_log = ttk.LabelFrame(self.root, text="System Logs")
        frm_log.pack(padx=10, pady=(5, 0), fill=tk.BOTH, expand=True)

        self.log_area = scrolledtext.ScrolledText(
            frm_log, height=10, font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", state=tk.DISABLED,
        )
        self.log_area.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)

        # --- Status Bar ---
        self.status_bar = tk.Label(
            self.root, text="Ready", anchor=tk.W,
            font=("Consolas", 9), relief=tk.SUNKEN)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # -- helpers -----------------------------------------------------
    def _get_port(self) -> int:
        """Read port from entry field, fallback to default."""
        try:
            port = int(self._port_var.get().strip())
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
        self._enqueue_log(f"[System] Invalid port, using default {DEFAULT_PORT}.")
        self._port_var.set(str(DEFAULT_PORT))
        return DEFAULT_PORT

    # -- command handlers --------------------------------------------
    def _cmd_server_start(self):
        port = self._get_port()
        self._port_entry.config(state=tk.DISABLED)
        self.server.start(port=port)

    def _cmd_server_stop(self):
        # stop STT first to avoid orphan connections
        if self.streamer.is_running:
            self.streamer.stop()
            self._enqueue_log("[System] STT stopped (server shutting down).")
        self.server.stop()

    def _cmd_stt_start(self):
        if not self.server.is_alive():
            self._enqueue_log("[System] Cannot start STT -- server is not running.")
            return
        self.streamer.start(port=self.server.port)

    def _cmd_stt_stop(self):
        self.streamer.stop()

    def _cmd_sub_toggle(self):
        self.overlay.toggle()
        if self.overlay.visible:
            self.btn_sub_toggle.config(text="Hide Subtitle")
            self.lbl_sub.config(text="VISIBLE", fg="green")
        else:
            self.btn_sub_toggle.config(text="Show Subtitle")
            self.lbl_sub.config(text="HIDDEN", fg="gray")

    # -- thread-safe helpers -----------------------------------------
    def _enqueue_log(self, msg: str):
        self._log_q.put(msg)

    def _enqueue_subtitle(self, text: str):
        self._sub_q.put(text)

    # -- polling loops (main thread) ---------------------------------
    def _poll_queues(self):
        # drain log queue
        while not self._log_q.empty():
            msg = self._log_q.get_nowait()
            self.log_area.config(state=tk.NORMAL)
            self.log_area.insert(
                tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            self.log_area.see(tk.END)
            self.log_area.config(state=tk.DISABLED)

        # drain subtitle queue (take latest only)
        latest_sub = None
        while not self._sub_q.empty():
            latest_sub = self._sub_q.get_nowait()
        if latest_sub is not None:
            self.overlay.set_text(latest_sub)

        # auto-clear stale subtitle
        self.overlay.tick()

        self.root.after(self.POLL_MS, self._poll_queues)

    def _poll_status(self):
        # --- server status ---
        srv_alive = self.server.is_alive()
        if srv_alive:
            self.lbl_srv.config(text="ONLINE", fg="green")
            self.btn_srv_start.config(state=tk.DISABLED)
            self.btn_srv_stop.config(state=tk.NORMAL)
            self._port_entry.config(state=tk.DISABLED)
        else:
            self.lbl_srv.config(text="OFFLINE", fg="red")
            self.btn_srv_start.config(state=tk.NORMAL)
            self.btn_srv_stop.config(state=tk.DISABLED)
            self._port_entry.config(state=tk.NORMAL)

        # --- stt status ---
        stt_alive = self.streamer.is_running
        if stt_alive:
            self.lbl_stt.config(text="RUNNING", fg="green")
            self.btn_stt_start.config(state=tk.DISABLED)
            self.btn_stt_stop.config(state=tk.NORMAL)
        else:
            self.lbl_stt.config(text="IDLE", fg="gray")
            self.btn_stt_start.config(state=tk.NORMAL)
            self.btn_stt_stop.config(state=tk.DISABLED)

        # if server died while STT running, stop STT
        if not srv_alive and stt_alive:
            self.streamer.stop()
            self._enqueue_log("[System] Server exited -- STT auto-stopped.")

        self.root.after(self.STATUS_MS, self._poll_status)

    # -- cleanup -----------------------------------------------------
    def _on_close(self):
        self.streamer.stop()
        self.server.stop()
        self.overlay.destroy()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ===================================================================
if __name__ == "__main__":
    app = MasterControlGUI()
    app.run()
