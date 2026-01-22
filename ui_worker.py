import queue
import threading
from typing import Dict, Optional

from main import run_batch


class WorkerThread(threading.Thread):
    """Background worker that runs the batch extraction and streams updates."""

    def __init__(
        self,
        pdf_dir: str,
        out_csv: str,
        sheet_cfg: Optional[Dict],
        settings: Optional[Dict],
        message_queue: "queue.Queue",
    ):
        super().__init__(daemon=True)
        self.pdf_dir = pdf_dir
        self.out_csv = out_csv
        self.sheet_cfg = sheet_cfg or {}
        self.settings = settings or {}
        self.message_queue = message_queue
        self.cancel_event = threading.Event()
        self.result = None

    def cancel(self):
        self.cancel_event.set()

    def _on_log(self, msg: str):
        self.message_queue.put({"type": "log", "message": msg})

    def _on_progress(self, stats: Dict):
        self.message_queue.put({"type": "progress", "stats": stats})

    def run(self):
        try:
            summary = run_batch(
                pdf_dir=self.pdf_dir,
                out_csv=self.out_csv,
                sheet_cfg=self.sheet_cfg,
                settings=self.settings,
                on_progress=self._on_progress,
                on_log=self._on_log,
                cancel_event=self.cancel_event,
            )
            self.result = summary
            self.message_queue.put({"type": "done", "result": summary})
        except Exception as exc:  # noqa: BLE001
            self.message_queue.put({"type": "error", "error": str(exc)})
