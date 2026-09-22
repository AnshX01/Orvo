"""
History Dialog & Persistence Manager for Orvo.
Maintains a persistent record of recent dictations and provides an elegant,
searchable UI dialog for reviewing, searching, and copying past transcriptions.
"""

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Callable
import tkinter as tk
from tkinter import ttk, messagebox
import pyperclip

try:
    from src.config import get_config, CONFIG_FILE_PATH
except ImportError:
    from config import get_config, CONFIG_FILE_PATH


HISTORY_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(CONFIG_FILE_PATH), "history.json")
)


@dataclass
class HistoryEntry:
    id: str = field(default_factory=lambda: f"hist_{int(time.time() * 1000)}")
    timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    text: str = ""
    duration_s: float = 0.0
    backend: str = "local"
    model: str = "base.en"

    @property
    def char_count(self) -> int:
        return len(self.text)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HistoryEntry":
        return cls(
            id=data.get("id", f"hist_{int(time.time() * 1000)}"),
            timestamp=data.get("timestamp", ""),
            text=data.get("text", ""),
            duration_s=float(data.get("duration_s", 0.0)),
            backend=data.get("backend", "local"),
            model=data.get("model", ""),
        )


class HistoryManager:
    """Thread-safe persistent transcription history manager."""

    _instance: Optional["HistoryManager"] = None
    _lock = threading.Lock()

    def __new__(cls, file_path: Optional[str] = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(HistoryManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, file_path: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self.file_path = file_path or HISTORY_FILE_PATH
        self._entries: List[HistoryEntry] = []
        self._rw_lock = threading.RLock()
        self.load()
        self._initialized = True

    def load(self) -> List[HistoryEntry]:
        """Loads entries from JSON file."""
        with self._rw_lock:
            if os.path.exists(self.file_path):
                try:
                    with open(self.file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        self._entries = [HistoryEntry.from_dict(item) for item in data]
                except Exception as err:
                    print(f"[HistoryManager] Warning: Failed to parse history file: {err}")
                    self._entries = []
            else:
                self._entries = []
            return self._entries

    def save(self) -> None:
        """Saves entries to JSON file."""
        with self._rw_lock:
            try:
                os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump([e.to_dict() for e in self._entries], f, indent=2, ensure_ascii=False)
            except Exception as err:
                print(f"[HistoryManager] Error saving history file: {err}")

    def add_entry(
        self,
        text: str,
        duration_s: float = 0.0,
        backend: str = "local",
        model: str = "",
    ) -> Optional[HistoryEntry]:
        """Appends a new transcription to history, enforcing limit."""
        clean_text = text.strip()
        if not clean_text:
            return None

        with self._rw_lock:
            limit = 50
            try:
                limit = get_config().ui.history_limit
            except Exception:
                pass

            entry = HistoryEntry(
                text=clean_text,
                duration_s=round(duration_s, 2),
                backend=backend,
                model=model,
            )
            # Insert at the top (most recent first)
            self._entries.insert(0, entry)
            if len(self._entries) > limit:
                self._entries = self._entries[:limit]
            self.save()
            return entry

    def get_entries(self) -> List[HistoryEntry]:
        with self._rw_lock:
            return list(self._entries)

    def delete_entry(self, entry_id: str) -> bool:
        with self._rw_lock:
            orig_len = len(self._entries)
            self._entries = [e for e in self._entries if e.id != entry_id]
            if len(self._entries) != orig_len:
                self.save()
                return True
            return False

    def clear(self) -> None:
        with self._rw_lock:
            self._entries.clear()
            self.save()


def get_history_manager() -> HistoryManager:
    return HistoryManager()


def add_history_entry(
    text: str,
    duration_s: float = 0.0,
    backend: str = "local",
    model: str = "",
) -> Optional[HistoryEntry]:
    return get_history_manager().add_entry(
        text=text, duration_s=duration_s, backend=backend, model=model
    )


class HistoryDialog:
    """
    Modern Tkinter dialog to review, search, and copy past transcriptions.
    Can be run as a Toplevel attached to an existing Tk root or standalone.
    """

    _active_instance: Optional["HistoryDialog"] = None

    def __init__(
        self,
        parent: Optional[tk.Misc] = None,
        history_manager: Optional[HistoryManager] = None,
    ):
        self.history_mgr = history_manager or get_history_manager()
        self.parent = parent
        self._is_standalone = parent is None

        if self._is_standalone:
            self.root = tk.Tk()
        else:
            self.root = tk.Toplevel(parent)

        HistoryDialog._active_instance = self
        self.root.title("Orvo — Dictation History")
        self.root.geometry("740x520")
        self.root.minsize(580, 380)

        # Center dialog
        self._center_window(740, 520)

        # Apply dark theme styling
        self._setup_styles()

        # Build UI layout
        self._build_ui()

        # Load data
        self.refresh_list()

        # Bind events
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda e: self.close())
        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())

    def _center_window(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _setup_styles(self) -> None:
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Dark palette colors
        self.bg_dark = "#18181b"       # zinc 900
        self.bg_card = "#27272a"       # zinc 800
        self.bg_input = "#3f3f46"      # zinc 700
        self.fg_main = "#f4f4f5"       # zinc 100
        self.fg_muted = "#a1a1aa"      # zinc 400
        self.accent = "#6366f1"        # indigo 500
        self.accent_hover = "#4f46e5"  # indigo 600
        self.danger = "#ef4444"        # red 500

        self.root.configure(bg=self.bg_dark)

        self.style.configure(
            "Dark.TFrame",
            background=self.bg_dark,
        )
        self.style.configure(
            "Card.TFrame",
            background=self.bg_card,
        )
        self.style.configure(
            "Title.TLabel",
            background=self.bg_dark,
            foreground=self.fg_main,
            font=("Segoe UI", 13, "bold"),
        )
        self.style.configure(
            "Muted.TLabel",
            background=self.bg_dark,
            foreground=self.fg_muted,
            font=("Segoe UI", 9),
        )
        self.style.configure(
            "Status.TLabel",
            background=self.bg_dark,
            foreground=self.fg_muted,
            font=("Segoe UI", 9),
        )
        self.style.configure(
            "Treeview",
            background="#202024",
            foreground=self.fg_main,
            fieldbackground="#202024",
            rowheight=26,
            font=("Segoe UI", 9),
            borderwidth=0,
        )
        self.style.map(
            "Treeview",
            background=[("selected", "#3b4261")],
            foreground=[("selected", "#ffffff")],
        )
        self.style.configure(
            "Treeview.Heading",
            background=self.bg_card,
            foreground=self.fg_main,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
        )
        self.style.map(
            "Treeview.Heading",
            background=[("active", "#323238")],
        )

    def _build_ui(self) -> None:
        # Container
        main_frame = ttk.Frame(self.root, style="Dark.TFrame", padding=14)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header Row
        header_frame = ttk.Frame(main_frame, style="Dark.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 10))

        title_lbl = ttk.Label(
            header_frame,
            text="📜 Dictation History",
            style="Title.TLabel",
        )
        title_lbl.pack(side=tk.LEFT)

        self.count_lbl = ttk.Label(
            header_frame,
            text="",
            style="Muted.TLabel",
        )
        self.count_lbl.pack(side=tk.RIGHT, pady=(4, 0))

        # Search Bar
        search_frame = ttk.Frame(main_frame, style="Dark.TFrame")
        search_frame.pack(fill=tk.X, pady=(0, 10))

        search_icon = tk.Label(
            search_frame,
            text="🔍",
            bg=self.bg_dark,
            fg=self.fg_muted,
            font=("Segoe UI", 10),
        )
        search_icon.pack(side=tk.LEFT, padx=(0, 6))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_filter_changed())

        self.search_entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            bg=self.bg_card,
            fg=self.fg_main,
            insertbackground=self.fg_main,
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(0, 6))

        clear_search_btn = tk.Button(
            search_frame,
            text="✕",
            command=lambda: self.search_var.set(""),
            bg=self.bg_card,
            fg=self.fg_muted,
            activebackground=self.bg_input,
            activeforeground=self.fg_main,
            relief="flat",
            padx=8,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )
        clear_search_btn.pack(side=tk.RIGHT)

        # PanedWindow: Split Treeview list and Preview Area
        paned = tk.PanedWindow(
            main_frame,
            orient=tk.VERTICAL,
            bg=self.bg_dark,
            sashrelief="flat",
            sashwidth=6,
        )
        paned.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Top section: Treeview list
        tree_container = ttk.Frame(paned, style="Dark.TFrame")
        paned.add(tree_container, height=220, minsize=120)

        columns = ("time", "text", "engine", "chars")
        self.tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("time", text="Time", anchor=tk.W)
        self.tree.heading("text", text="Transcription Snippet", anchor=tk.W)
        self.tree.heading("engine", text="Engine", anchor=tk.W)
        self.tree.heading("chars", text="Length", anchor=tk.E)

        self.tree.column("time", width=140, minwidth=110, stretch=False)
        self.tree.column("text", width=380, minwidth=200, stretch=True)
        self.tree.column("engine", width=120, minwidth=90, stretch=False)
        self.tree.column("chars", width=60, minwidth=50, stretch=False, anchor=tk.E)

        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.copy_selected())
        self.tree.bind("<Return>", lambda e: self.copy_selected())
        self.tree.bind("<Delete>", lambda e: self._delete_selected())

        # Bottom section: Text Preview Box
        preview_container = ttk.Frame(paned, style="Dark.TFrame")
        paned.add(preview_container, height=140, minsize=80)

        preview_header = ttk.Label(
            preview_container,
            text="Preview / Full Text:",
            style="Muted.TLabel",
        )
        preview_header.pack(anchor=tk.W, pady=(4, 2))

        self.preview_text = tk.Text(
            preview_container,
            wrap=tk.WORD,
            bg="#202024",
            fg=self.fg_main,
            insertbackground=self.fg_main,
            selectbackground="#4f46e5",
            selectforeground="#ffffff",
            relief="flat",
            font=("Segoe UI", 10),
            padx=10,
            pady=8,
        )
        preview_scroll = ttk.Scrollbar(preview_container, orient=tk.VERTICAL, command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=preview_scroll.set)

        self.preview_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        preview_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Footer Action Bar
        footer_frame = ttk.Frame(main_frame, style="Dark.TFrame")
        footer_frame.pack(fill=tk.X, pady=(2, 0))

        self.status_lbl = ttk.Label(
            footer_frame,
            text="Ready",
            style="Status.TLabel",
        )
        self.status_lbl.pack(side=tk.LEFT, pady=4)

        # Action Buttons
        btn_close = tk.Button(
            footer_frame,
            text="Close",
            command=self.close,
            bg=self.bg_card,
            fg=self.fg_main,
            activebackground=self.bg_input,
            activeforeground=self.fg_main,
            relief="flat",
            padx=14,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9),
        )
        btn_close.pack(side=tk.RIGHT, padx=(6, 0))

        btn_clear = tk.Button(
            footer_frame,
            text="🗑️ Clear All",
            command=self.clear_all,
            bg=self.bg_card,
            fg=self.danger,
            activebackground=self.bg_input,
            activeforeground="#ff6b6b",
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9),
        )
        btn_clear.pack(side=tk.RIGHT, padx=(6, 0))

        btn_copy = tk.Button(
            footer_frame,
            text="📋 Copy Selected",
            command=self.copy_selected,
            bg=self.accent,
            fg="#ffffff",
            activebackground=self.accent_hover,
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )
        btn_copy.pack(side=tk.RIGHT, padx=(6, 0))

        # Store entries map (item_id -> HistoryEntry)
        self._displayed_entries: dict[str, HistoryEntry] = {}

    def refresh_list(self) -> None:
        """Reloads items from storage and populates the list based on filter."""
        all_entries = self.history_mgr.get_entries()
        query = self.search_var.get().strip().lower()

        # Clear existing tree items
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._displayed_entries.clear()

        matched_count = 0
        for entry in all_entries:
            if query:
                # Search in text, backend, model, timestamp
                matches = (
                    query in entry.text.lower()
                    or query in entry.backend.lower()
                    or query in entry.model.lower()
                    or query in entry.timestamp.lower()
                )
                if not matches:
                    continue

            # Engine label
            engine_str = entry.backend
            if entry.model:
                engine_str = f"{entry.backend}:{entry.model}"
            if entry.duration_s > 0:
                engine_str += f" ({entry.duration_s}s)"

            # One-line snippet
            snippet = entry.text.replace("\n", " ").strip()
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."

            chars_str = f"{entry.char_count} chars"
            tree_id = self.tree.insert(
                "",
                tk.END,
                values=(entry.timestamp, snippet, engine_str, chars_str),
            )
            self._displayed_entries[tree_id] = entry
            matched_count += 1

        total_count = len(all_entries)
        if query:
            self.count_lbl.config(text=f"Showing {matched_count} of {total_count}")
        else:
            self.count_lbl.config(text=f"Total: {total_count} items")

        # Auto-select first item if available
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
            self._on_select()
        else:
            self._clear_preview()

    def _on_filter_changed(self) -> None:
        self.refresh_list()

    def _on_select(self, event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            self._clear_preview()
            return
        tree_id = selected[0]
        entry = self._displayed_entries.get(tree_id)
        if not entry:
            self._clear_preview()
            return

        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert(tk.END, entry.text)
        self.status_lbl.config(
            text=f"Selected: {entry.timestamp} | {entry.char_count} characters"
        )

    def _clear_preview(self) -> None:
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.status_lbl.config(text="No selection")

    def copy_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            self._show_status_flash("⚠️ Select a transcription first!")
            return
        tree_id = selected[0]
        entry = self._displayed_entries.get(tree_id)
        if not entry:
            return

        text = entry.text
        try:
            pyperclip.copy(text)
        except Exception:
            # Fallback to tkinter clipboard
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

        self._show_status_flash("✓ Copied transcription to clipboard!")

    def _delete_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        tree_id = selected[0]
        entry = self._displayed_entries.get(tree_id)
        if not entry:
            return

        if self.history_mgr.delete_entry(entry.id):
            self._show_status_flash("Deleted item from history")
            self.refresh_list()

    def clear_all(self) -> None:
        if not self.history_mgr.get_entries():
            self._show_status_flash("History is already empty.")
            return

        confirmed = messagebox.askyesno(
            "Clear Transcription History",
            "Are you sure you want to delete all saved transcriptions?",
            parent=self.root,
        )
        if confirmed:
            self.history_mgr.clear()
            self.refresh_list()
            self._show_status_flash("History cleared.")

    def _show_status_flash(self, message: str) -> None:
        self.status_lbl.config(text=message, foreground=self.accent)
        self.root.after(
            2200,
            lambda: self.status_lbl.config(
                text=f"Total: {len(self.history_mgr.get_entries())} items",
                foreground=self.fg_muted,
            ),
        )

    def close(self) -> None:
        HistoryDialog._active_instance = None
        if self._is_standalone:
            self.root.destroy()
        else:
            self.root.withdraw()
            self.root.destroy()

    @classmethod
    def show(
        cls,
        parent: Optional[tk.Misc] = None,
        history_manager: Optional[HistoryManager] = None,
    ) -> "HistoryDialog":
        """Thread-safe dialog opener. Focuses existing instance or creates a new one."""
        if cls._active_instance is not None:
            try:
                if cls._active_instance.root.winfo_exists():
                    cls._active_instance.root.deiconify()
                    cls._active_instance.root.lift()
                    cls._active_instance.root.focus_force()
                    cls._active_instance.refresh_list()
                    return cls._active_instance
            except Exception:
                cls._active_instance = None

        dlg = cls(parent=parent, history_manager=history_manager)
        if dlg._is_standalone:
            dlg.root.mainloop()
        return dlg


def open_history_dialog(parent: Optional[tk.Misc] = None) -> HistoryDialog:
    """Convenience helper to open the history dialog."""
    return HistoryDialog.show(parent=parent)


if __name__ == "__main__":
    # Test script with dummy entries if run directly
    mgr = get_history_manager()
    if not mgr.get_entries():
        mgr.add_entry(
            "Hello, this is a test transcription from Orvo!",
            duration_s=1.2,
            backend="local",
            model="base.en",
        )
        mgr.add_entry(
            "System wide dictation that types anywhere you can type.",
            duration_s=0.85,
            backend="groq",
            model="whisper-large-v3-turbo",
        )
    print("Opening History Dialog standalone...")
    HistoryDialog.show()
