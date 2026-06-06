from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from rpa_bot.browser_bot import CpcbWasteTyreBot
from rpa_bot.config import BotConfig
from rpa_bot.excel_reader import ExcelDataReader
from rpa_bot.logging_setup import configure_logging
from rpa_bot.state import BotState

BASE_DIR = Path(__file__).resolve().parent


class RpaBotApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CPCB Waste Tyre RPA Bot")
        self.geometry("760x520")
        self.minsize(720, 480)

        self.log_file = configure_logging(BASE_DIR / "logs")
        self.config = BotConfig.load(BASE_DIR / "config.json")
        self.state = BotState(BASE_DIR / "state" / "bot_state.json")
        self.reader = ExcelDataReader(self.config.column_aliases)
        self.event_queue: queue.Queue[str] = queue.Queue()
        self.bot: CpcbWasteTyreBot | None = None

        self.login_id = tk.StringVar()
        self.password = tk.StringVar()
        self.procurement_file = tk.StringVar()
        self.recycling_file = tk.StringVar()
        self.sales_file = tk.StringVar()
        self.purchase_invoice_folder = tk.StringVar()
        self.sales_invoice_folder = tk.StringVar()
        self.status_text = tk.StringVar(value="Ready")

        self._build_ui()
        self.after(200, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)

        ttk.Label(root, text="Login ID").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.login_id).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(root, text="Password").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.password).grid(row=1, column=1, sticky="ew", pady=4)

        self._file_row(root, 2, "Procurement Excel", self.procurement_file)
        self._file_row(root, 3, "Recycling Excel", self.recycling_file)
        self._file_row(root, 4, "Sales Excel", self.sales_file)
        self._folder_row(root, 5, "Purchase Invoice Folder", self.purchase_invoice_folder)
        self._folder_row(root, 6, "Sales Invoice Folder", self.sales_invoice_folder)

        actions = ttk.Frame(root)
        actions.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(18, 8))
        actions.columnconfigure((0, 1, 2, 3), weight=1)


        ttk.Button(actions, text="Open Browser", command=self._run_open_browser).grid(row=0, column=0, padx=4, sticky="ew")
        ttk.Button(actions, text="Continue Data Entry", command=self._run_continue).grid(row=0, column=1, padx=4, sticky="ew")
        ttk.Button(actions, text="Show Errors", command=self._show_errors).grid(row=0, column=2, padx=4, sticky="ew")
        ttk.Button(actions, text="Logout", command=self._run_logout).grid(row=0, column=3, padx=4, sticky="ew")

        ttk.Label(root, textvariable=self.status_text).grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 4))

        log_box = ttk.LabelFrame(root, text="Activity")
        log_box.grid(row=9, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        root.rowconfigure(9, weight=1)
        log_box.rowconfigure(0, weight=1)
        log_box.columnconfigure(0, weight=1)

        self.activity = tk.Text(log_box, height=10, wrap="word", state="disabled")
        self.activity.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_box, orient="vertical", command=self.activity.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.activity.configure(yscrollcommand=scrollbar.set)

    def _file_row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse", command=lambda: self._pick_file(variable)).grid(row=row, column=2, padx=(8, 0))

    def _folder_row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse", command=lambda: self._pick_folder(variable)).grid(row=row, column=2, padx=(8, 0))

    def _pick_file(self, variable: tk.StringVar) -> None:
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")])
        if path:
            variable.set(path)

    def _pick_folder(self, variable: tk.StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            variable.set(path)

    def _run_open_browser(self) -> None:
        self._run_worker(self._open_browser)

    def _run_continue(self) -> None:
        self._run_worker(self._continue_data_entry)

    def _run_logout(self) -> None:
        self._run_worker(self._logout)

    def _run_worker(self, target) -> None:
        threading.Thread(target=target, daemon=True).start()

    def _open_browser(self) -> None:
        try:
            # self._ensure_bot().open_browser()
            bot = self._ensure_bot()
            bot.open_browser()
            if self.login_id.get() and self.password.get():
                bot.login(self.login_id.get(), self.password.get())
        except Exception as exc:
            logging.exception("Open browser failed: %s", exc)
            self._post(f"Open browser failed: {exc}")

    def _logout(self) -> None:
        try:
            self._ensure_bot().logout()
        except Exception as exc:
            logging.exception("Logout failed: %s", exc)
            self._post(f"Logout failed: {exc}")

    def _continue_data_entry(self) -> None:
        try:
            bot = self._ensure_bot()
            # if self.login_id.get() and self.password.get():
            #     bot.login(self.login_id.get(), self.password.get())

            datasets = [
                ("procurement", self.procurement_file.get()),
                ("recycling", self.recycling_file.get()),
                ("sales", self.sales_file.get()),
            ]
            for dataset, file_path in datasets:
                if not file_path:
                    self._post(f"Skipping {dataset}: no Excel file selected")
                    continue
                rows = self.reader.read_rows(Path(file_path))
                self._post(f"Processing {dataset}: {len(rows)} rows")
                bot.process_dataset(dataset, rows)
            self._post("Data entry run completed")
        except Exception as exc:
            logging.exception("Data entry failed: %s", exc)
            self._post(f"Data entry failed: {exc}")

    def _ensure_bot(self) -> CpcbWasteTyreBot:
        purchase_invoice_folder = Path(self.purchase_invoice_folder.get() or BASE_DIR)
        sales_invoice_folder = Path(self.sales_invoice_folder.get() or BASE_DIR)
        if self.bot is None:
            self.bot = CpcbWasteTyreBot(
                self.config,
                self.state,
                purchase_invoice_folder,
                sales_invoice_folder,
                self._prompt,
                self._post,
            )
        else:
            self.bot.purchase_invoice_folder = purchase_invoice_folder
            self.bot.sales_invoice_folder = sales_invoice_folder
        return self.bot

    def _prompt(self, title: str, message: str) -> str | None:
        result: queue.Queue[str | None] = queue.Queue(maxsize=1)

        def ask() -> None:
            result.put(simpledialog.askstring(title, message, parent=self))

        self.after(0, ask)
        return result.get()

    def _post(self, message: str) -> None:
        self.event_queue.put(message)

    def _drain_events(self) -> None:
        while True:
            try:
                message = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self.status_text.set(message)
            self.activity.configure(state="normal")
            self.activity.insert("end", message + "\n")
            self.activity.see("end")
            self.activity.configure(state="disabled")
        self.after(200, self._drain_events)

    def _show_errors(self) -> None:
        if not self.log_file.exists():
            messagebox.showinfo("Errors", "No log file found yet.")
            return
        lines = self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        errors = [line for line in lines if " | ERROR | " in line][-100:]
        if not errors:
            messagebox.showinfo("Errors", "No errors logged yet.")
            return
        window = tk.Toplevel(self)
        window.title("Recent Errors")
        window.geometry("900x420")
        text = tk.Text(window, wrap="word")
        text.pack(fill="both", expand=True)
        text.insert("1.0", "\n".join(errors))
        text.configure(state="disabled")

    def _on_close(self) -> None:
        if self.bot is not None:
            self.bot.close()
        self.destroy()


if __name__ == "__main__":
    RpaBotApp().mainloop()
