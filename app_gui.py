import glob
import json
import os
import queue
import subprocess
import sys
import tkinter as tk
import traceback
from typing import Optional
from tkinter import filedialog, messagebox, scrolledtext, ttk

import pytesseract

from sheets import sheet_link_to_id
from ui_worker import WorkerThread


DEFAULT_WORKSHEET = "Probate Information"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Probate PDF Extractor")
        self.root.geometry("1100x960")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.message_queue: "queue.Queue" = queue.Queue()
        self.worker: Optional[WorkerThread] = None

        self.settings_path = os.path.join(os.path.dirname(__file__), "ui_settings.json")

        # Form variables
        self.pdf_dir_var = tk.StringVar()
        self.sheet_link_var = tk.StringVar()
        self.worksheet_var = tk.StringVar(value=DEFAULT_WORKSHEET)
        self.out_csv_var = tk.StringVar(value="output.csv")
        self.append_var = tk.BooleanVar(value=True)
        self.mode_var = tk.StringVar(value="service")
        self.creds_var = tk.StringVar()
        self.creds_prev = ""
        self.service_email = ""

        self._load_settings()
        # Status variables
        self.google_status_var = tk.StringVar(value="Google write: CSV only")
        self.total_var = tk.StringVar(value="Total: 0")
        self.processed_var = tk.StringVar(value="Processed: 0")
        self.success_var = tk.StringVar(value="Success: 0")
        self.failed_var = tk.StringVar(value="Failed: 0")
        self.ocr_var = tk.StringVar(value="OCR: 0")

        self._build_ui()
        self._update_google_status()
        self.root.after(200, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # Input section
        frm = ttk.LabelFrame(self.root, text="Input")
        frm.pack(fill="x", padx=10, pady=6)

        self._add_labeled_entry(frm, "PDF Folder", self.pdf_dir_var, self._browse_pdf_dir)
        self._add_labeled_entry(frm, "Google Sheet Link", self.sheet_link_var)
        self._add_labeled_entry(frm, "Worksheet/Tab", self.worksheet_var)
        self._add_labeled_entry(frm, "Output CSV", self.out_csv_var, self._choose_csv_path)

        # Google write section
        gfrm = ttk.LabelFrame(self.root, text="Google Write Access")
        gfrm.pack(fill="x", padx=10, pady=6)

        chk = ttk.Checkbutton(gfrm, text="Append to Google Sheet", variable=self.append_var, command=self._update_google_status)
        chk.grid(row=0, column=0, sticky="w", **pad)

        ttk.Radiobutton(
            gfrm,
            text="Use Service Account JSON (recommended)",
            variable=self.mode_var,
            value="service",
            command=self._update_google_status,
        ).grid(row=1, column=0, sticky="w", **pad)
        ttk.Label(gfrm, text="Service Account JSON").grid(row=2, column=0, sticky="w", **pad)
        entry_creds = ttk.Entry(gfrm, textvariable=self.creds_var, width=50)
        entry_creds.grid(row=2, column=1, sticky="ew", **pad)
        gfrm.grid_columnconfigure(1, weight=1)
        ttk.Button(gfrm, text="Browse", command=self._browse_creds).grid(row=2, column=2, padx=4, pady=4, sticky="w")
        ttk.Button(gfrm, text="Use Previous", command=self._use_previous_creds).grid(row=2, column=3, padx=4, pady=4, sticky="w")

        ttk.Radiobutton(
            gfrm,
            text="No Google write (CSV only)",
            variable=self.mode_var,
            value="none",
            command=self._update_google_status,
        ).grid(row=2, column=0, sticky="w", **pad)

        self.google_status_lbl = ttk.Label(gfrm, textvariable=self.google_status_var, foreground="blue")
        self.google_status_lbl.grid(row=3, column=0, columnspan=2, sticky="w", **pad)

        # Controls
        cfrm = ttk.Frame(self.root)
        cfrm.pack(fill="x", padx=10, pady=6)
        self.start_btn = ttk.Button(cfrm, text="Start", command=self.start_run)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(cfrm, text="Stop", command=self.stop_run, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.open_btn = ttk.Button(cfrm, text="Open Output Folder", command=self._open_output_folder)
        self.open_btn.pack(side="left", padx=4)

        # Progress
        pfrm = ttk.LabelFrame(self.root, text="Progress")
        pfrm.pack(fill="x", padx=10, pady=6)
        self.progress = ttk.Progressbar(pfrm, length=400, mode="determinate")
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=4)
        ttk.Label(pfrm, textvariable=self.total_var).grid(row=1, column=0, sticky="w", padx=6)
        ttk.Label(pfrm, textvariable=self.processed_var).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(pfrm, textvariable=self.success_var).grid(row=2, column=0, sticky="w", padx=6)
        ttk.Label(pfrm, textvariable=self.failed_var).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(pfrm, textvariable=self.ocr_var).grid(row=2, column=2, sticky="w", padx=6)

        # Log box
        lfrm = ttk.LabelFrame(self.root, text="Log")
        lfrm.pack(fill="both", expand=True, padx=10, pady=6)
        self.log_box = scrolledtext.ScrolledText(lfrm, height=18, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

    def _add_labeled_entry(self, parent, label, var, browse_cmd=None, row=None, column=0):
        if row is None:
            row = parent.grid_size()[1]
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=8, pady=4)
        entry = ttk.Entry(parent, textvariable=var, width=50)
        entry.grid(row=row, column=column + 1, sticky="ew", padx=8, pady=4)
        parent.grid_columnconfigure(column + 1, weight=1)
        if browse_cmd:
            ttk.Button(parent, text="Browse", command=browse_cmd).grid(row=row, column=column + 2, padx=4, pady=4)
        return entry

    def _append_log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _load_settings(self):
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.pdf_dir_var.set(data.get("pdf_dir", ""))
            self.sheet_link_var.set(data.get("sheet_link", ""))
            self.worksheet_var.set(data.get("worksheet", DEFAULT_WORKSHEET))
            self.out_csv_var.set(data.get("out_csv", "output.csv"))
            self.append_var.set(data.get("append", True))
            self.mode_var.set(data.get("mode", "service"))
            self.creds_var.set(data.get("creds", ""))
            self.creds_prev = data.get("creds_prev", "")
            self.service_email = self._read_service_email(self.creds_var.get().strip())
        except FileNotFoundError:
            pass
        except Exception:
            # Ignore corrupt settings
            pass

    def _save_settings(self):
        data = {
            "pdf_dir": self.pdf_dir_var.get().strip(),
            "sheet_link": self.sheet_link_var.get().strip(),
            "worksheet": self.worksheet_var.get().strip(),
            "out_csv": self.out_csv_var.get().strip(),
            "append": self.append_var.get(),
            "mode": self.mode_var.get(),
            "creds": self.creds_var.get().strip(),
            "creds_prev": self.creds_prev,
        }
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def _read_service_email(path: str) -> str:
        if not path:
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("client_email", "")
        except Exception:
            return ""

    def _use_previous_creds(self):
        if self.creds_prev:
            self.creds_var.set(self.creds_prev)
            self.service_email = self._read_service_email(self.creds_prev)
            self.mode_var.set("service")
            self._save_settings()
            self._update_google_status()
            self._append_log(f"Switched to previous service account JSON: {self.creds_prev}")
        else:
            messagebox.showinfo("Previous JSON", "No previous service account JSON remembered.")

    def _browse_pdf_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.pdf_dir_var.set(path)

    def _choose_csv_path(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if path:
            self.out_csv_var.set(path)

    def _browse_creds(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All Files", "*.*")])
        if path:
            if self.creds_var.get().strip():
                self.creds_prev = self.creds_var.get().strip()
            self.creds_var.set(path)
            self.service_email = self._read_service_email(path)
            self.mode_var.set("service")
            self._save_settings()
            self._update_google_status()

    def _open_output_folder(self):
        out_path = self.out_csv_var.get().strip() or "output.csv"
        folder = os.path.abspath(os.path.dirname(out_path) or ".")
        if sys.platform.startswith("win"):
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def _update_google_status(self):
        append = self.append_var.get() and self.mode_var.get() == "service"
        if not append:
            self.google_status_var.set("Google write: CSV only")
            self.google_status_lbl.configure(foreground="gray")
            return
        if not self.creds_var.get().strip():
            self.google_status_var.set("Google write: Missing service account JSON (will fall back to CSV)")
            self.google_status_lbl.configure(foreground="orange")
        else:
            extra = f" ({self.service_email})" if self.service_email else ""
            self.google_status_var.set(f"Google write: Ready (service account{extra})")
            self.google_status_lbl.configure(foreground="green")

    def _validate_inputs(self) -> bool:
        pdf_dir = self.pdf_dir_var.get().strip()
        if not pdf_dir or not os.path.isdir(pdf_dir):
            messagebox.showerror("Validation", "Please select a valid PDF folder.")
            return False
        if not glob.glob(os.path.join(pdf_dir, "*.pdf")):
            messagebox.showerror("Validation", "No PDFs found in the selected folder.")
            return False
        out_csv = self.out_csv_var.get().strip()
        if not out_csv:
            messagebox.showerror("Validation", "Please provide an output CSV path.")
            return False
        append = self.append_var.get() and self.mode_var.get() == "service"
        if append and not self.creds_var.get().strip():
            messagebox.showwarning(
                "Google Write",
                "Service account JSON is required to append to Google Sheet. Falling back to CSV only.",
            )
            self.append_var.set(False)
            self._update_google_status()
        return True

    def start_run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Running", "Processing is already running.")
            return
        if not self._validate_inputs():
            return

        pdf_dir = self.pdf_dir_var.get().strip()
        out_csv = self.out_csv_var.get().strip() or "output.csv"
        sheet_link = self.sheet_link_var.get().strip()
        worksheet = self.worksheet_var.get().strip() or DEFAULT_WORKSHEET
        append = self.append_var.get() and self.mode_var.get() == "service" and bool(self.creds_var.get().strip())

        sheet_cfg = {
            "append": append,
            "sheet_link": sheet_link,
            "worksheet": worksheet,
            "creds": self.creds_var.get().strip(),
        }

        log_path = os.path.join(os.path.dirname(out_csv) or ".", "run_log.json")
        settings = {
            "min_text_length": 200,
            "ocr_dpi": 300,
            "log_path": log_path,
            "recursive": False,
        }

        self._append_log("Starting...")
        self._log_tesseract_status()
        if append and not sheet_link:
            self._append_log("Warning: No Google Sheet link provided; CSV will still be generated.")

        self._save_settings()
        sheet_id = sheet_link_to_id(sheet_link) if sheet_link else ""
        if append:
            self._append_log(
                f"Google append enabled -> Sheet ID: {sheet_id or 'N/A'}, Worksheet: {worksheet}, Service email: {self.service_email or 'unknown'}"
            )
        else:
            self._append_log("Google append disabled -> CSV only.")

        self.worker = WorkerThread(
            pdf_dir=pdf_dir,
            out_csv=out_csv,
            sheet_cfg=sheet_cfg,
            settings=settings,
            message_queue=self.message_queue,
        )
        self.worker.start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._reset_progress()

    def stop_run(self):
        if self.worker and self.worker.is_alive():
            self.worker.cancel()
            self._append_log("Stop requested. Finishing current file...")
            self.stop_btn.configure(state="disabled")

    def _reset_progress(self):
        self.progress["value"] = 0
        self.total_var.set("Total: 0")
        self.processed_var.set("Processed: 0")
        self.success_var.set("Success: 0")
        self.failed_var.set("Failed: 0")
        self.ocr_var.set("OCR: 0")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Exit", "A run is in progress. Stop and exit?"):
                return
            self.worker.cancel()
        self._save_settings()
        self.root.destroy()

    def _poll_queue(self):
        try:
            while True:
                msg = self.message_queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _handle_message(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "log":
            self._append_log(msg.get("message", ""))
        elif mtype == "progress":
            stats = msg.get("stats", {})
            total = stats.get("total", 0) or 0
            processed = stats.get("processed", 0) or 0
            self.total_var.set(f"Total: {total}")
            self.processed_var.set(f"Processed: {processed}")
            self.success_var.set(f"Success: {stats.get('success', 0)}")
            self.failed_var.set(f"Failed: {stats.get('failed', 0)}")
            self.ocr_var.set(f"OCR: {stats.get('ocr', 0)}")
            self.progress["maximum"] = max(total, 1)
            self.progress["value"] = processed
        elif mtype == "done":
            result = msg.get("result", {})
            stats = result.get("stats", {})
            self._append_log(
                f"Done. Processed {stats.get('processed', 0)} of {stats.get('total', 0)} "
                f"(success {stats.get('success', 0)}, failed {stats.get('failed', 0)}, OCR {stats.get('ocr', 0)})."
            )
            if result.get("sheet_error"):
                self._append_log(f"Sheet warning: {result['sheet_error']}")
            self._append_log(f"CSV: {result.get('out_csv')} | Log: {result.get('log_path')}")
            messagebox.showinfo("Finished", "Processing completed. Check log for details.")
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
        elif mtype == "error":
            self._append_log(f"Error: {msg.get('error')}")
            messagebox.showerror("Error", msg.get("error", "Unknown error"))
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")

    def _log_tesseract_status(self):
        try:
            version = pytesseract.get_tesseract_version()
            self._append_log(f"Tesseract detected: {version}")
        except Exception:
            self._append_log("Tesseract not detected on PATH; OCR will attempt default invocation.")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
