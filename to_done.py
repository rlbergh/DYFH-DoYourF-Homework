import json
import os
from tkinter import messagebox
from datetime import datetime, timezone
import datetime as _dt
import uuid
import customtkinter as ctk
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict
import sys
from pathlib import Path
import webbrowser
from urllib.parse import urlparse
import platform
import matplotlib
matplotlib.use("Agg")  # safe default backend
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from collections import defaultdict


def app_base_dir() -> Path:
    #packaging
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

def local_path(*parts) -> str:
    return str(app_base_dir().joinpath(*parts))

SAVE_FILE = local_path("tasks.json")
ZOOM_LINKS_FILE = local_path("zoom_links.json")
SETTINGS_FILE = local_path("settings.json")

# ctk theme
ctk.set_appearance_mode("dark")          # "light", "dark", or "system"
ctk.set_default_color_theme("green")        # "blue", "green", "dark-blue"

@dataclass
class Task:
    id: str
    text: str
    done: bool = False
    due: Optional[str] = None  # ISO date 'YYYY-MM-DD'
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    course: Optional[str] = None
    sessions: List[Dict] = field(default_factory=list)
    running_start: Optional[str] = None
    url: Optional[str] = None

class ToDoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # ---- settings-related attrs first ----
        # defaults (may be overwritten by _load_settings)
        self.safe_mode: bool = False
        self.hidden_courses: set[str] = set()
        self.show_archived = ctk.BooleanVar(value=False)  # UI toggle

        # zoom links + settings (may update safe_mode / hidden_courses)
        self.class_zoom_urls: Dict[str, str] = self._load_zoom_links()
        self._load_settings()

        # ---- fonts ----
        base_size = ctk.CTkFont().cget("size")  # keeps platform default
        self.font_normal = ctk.CTkFont(size=base_size)
        self.font_done = ctk.CTkFont(size=base_size, overstrike=True)

        # ---- window title based on safe mode ----
        title = "Do Your Homework" if self.safe_mode else "Do your fucking homework"
        self.title(title)

        self.geometry("900x520")
        self.minsize(900, 520)

        self.tasks: List[Task] = []
        self.filter_mode = ctk.StringVar(value="Active")
        self.editing_task_id: Optional[str] = None
        self.sort_asc = True  # <-- added toggle flag
        self.class_var = ctk.StringVar()
        self.group_by_class = ctk.BooleanVar(value=False)
        self.url_var = ctk.StringVar()

        # quick filter
        self.course_filter: Optional[str] = None

        # tooltip state
        self._tooltip_window = None

        self._build_ui()
        self._load_tasks()
        self._refresh_list()


        # ---------- UI ----------
    def _build_ui(self):
        # --- Top row: add task, due date, class, add button ---
        top = ctk.CTkFrame(self, corner_radius=12)
        top.pack(fill="x", padx=10, pady=10)

        # Task text
        self.entry = ctk.CTkEntry(top, placeholder_text="Add a task…")
        self.entry.pack(side="left", fill="x", expand=True, padx=(10, 8), pady=10)
        self.entry.focus()

        # Due date (YYYY-MM-DD)
        self.due_var = getattr(self, "due_var", ctk.StringVar())  # keep your existing var if present
        due = ctk.CTkEntry(top, width=120, textvariable=self.due_var, placeholder_text="YYYY-MM-DD")
        due.pack(side="left", pady=10)
        ctk.CTkLabel(top, text="(YYYY-MM-DD)").pack(side="left", padx=(10, 10))

        # Class selector
        ctk.CTkLabel(top, text="Class:").pack(side="left", padx=(10, 2))
        self.class_combo = ctk.CTkComboBox(top,
                                           width=100,
                                           variable=self.class_var,
                                           values=[""],
                                           state="normal")
        self.class_combo.pack(side="left", padx=(0, 6), pady=10)

        #url entry
        ctk.CTkLabel(top, text="Link: ").pack(side="left", padx=(10, 2))
        self.url_entry = ctk.CTkEntry(top, width=200, textvariable=self.url_var, placeholder_text="https://...")
        self.url_entry.pack(side="left", padx=(0, 6), pady=10)

        # Allow free typing
        self.add_btn = ctk.CTkButton(top, text="Add", command=self._add_or_update)
        self.add_btn.pack(side="left", padx=(4, 10), pady=10)

        # KPI Strip
        self.kpi = ctk.CTkFrame(self, corner_radius=12)
        self.kpi.pack(fill="x", padx=10, pady=(0,10))

        kpi_inner = ctk.CTkFrame(self.kpi, fg_color="transparent")
        kpi_inner.pack(fill="x", padx=10, pady=8)

        self._kpi_container = kpi_inner
        self._kpi_rows: list[ctk.CTkFrame] = []

        # --- Mid section container ---
        mid = ctk.CTkFrame(self, corner_radius=12)
        mid.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Controls row
        controls = ctk.CTkFrame(mid, fg_color="transparent")
        controls.pack(fill="x", padx=10, pady=(10, 6))

        self.entry.bind("<Return>", lambda e: self._add_or_update())

        # Sort button
        self.sort_btn = ctk.CTkButton(controls, text="Sort by Due ↑",
                                      command=self._sort_by_due)
        self.sort_btn.pack(side="left", padx=(8, 8))

        # Group by class button
        ctk.CTkCheckBox(controls, text="Group by class",
                        variable=self.group_by_class,
                        command=self._refresh_list).pack(side="left", padx=(8, 0))

        # Toggle to include archived classes in the view
        ctk.CTkCheckBox(
            controls,
            text="Show archived classes",
            variable=self.show_archived,
            command=self._refresh_list
        ).pack(side="left", padx=(8, 0))


        # Filter menu
        ctk.CTkOptionMenu(controls,
                          variable=self.filter_mode,
                          values=["All", "Active", "Completed"],
                          command=lambda _: self._refresh_list()) \
            .pack(side="right", padx=(0, 8))
        ctk.CTkLabel(controls, text="Filter: ").pack(side="right", padx=(0,4))

        # --- List (card-style) ---
        self.cards = ctk.CTkScrollableFrame(mid, corner_radius=12)
        self.cards.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._card_rows = []

        # --- Status bar at bottom with settings gear ---
        self.status = getattr(self, "status", ctk.StringVar(value="Ready"))

        status_bar = ctk.CTkFrame(self, fg_color="transparent")
        status_bar.pack(fill="x", side="bottom", padx=10, pady=(0, 8))

        status_label = ctk.CTkLabel(status_bar, textvariable=self.status, anchor="w")
        status_label.pack(side="left", fill="x", expand=True)

        icon_font = ctk.CTkFont(size=17)  # experiment: 14–18

        # Gear button to open settings
        self.settings_btn = ctk.CTkButton(
            status_bar,
            text="⚙",
            width=32,
            height=32,
            font=icon_font,
            command=self._open_settings_dialog
        )
        self.settings_btn.pack(side="right")

        self.settings_btn.bind(
            "<Enter>",
            lambda e: self._show_tooltip(self.settings_btn, "Open app settings")
        )
        self.settings_btn.bind(
            "<Leave>",
            lambda e: self._hide_tooltip()
        )


    # ---------- Persistence ----------
    def _load_tasks(self):
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.tasks = [Task(**t) for t in raw]
                self._set_status(f"Loaded {len(self.tasks)} task(s).")
            except Exception as e:
                messagebox.showwarning("Load error", f"Could not read {SAVE_FILE}.\n{e}")
                self.tasks = []

        else:
            self.tasks = []

        self._update_course_values()

    def _save_tasks(self):
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump([asdict(t) for t in self.tasks], f, indent=2)
        except Exception as e:
            messagebox.showerror("Save error", f"Could not save to {SAVE_FILE}.\n{e}")

    def _update_course_values(self):
        """Scan tasks for distinct non-empty course tags and load them into the combobox."""
        if not hasattr(self, "class_combo"):
            return  # UI not built yet

        courses = {
            (t.course or "").strip()
            for t in self.tasks
            if getattr(t, "course", None) and str(t.course).strip()
        }
        values = sorted(courses, key=lambda s: (not s.isdigit(), s))  # numbers first, then alpha

        if not values:
            values = [""]

        self.class_combo.configure(values= values)

    # ---------- Zoom link persistence ----------

    def _load_zoom_links(self) -> Dict[str, str]:
        """Load per-class Zoom URLs from zoom_links.json."""
        if not os.path.exists(ZOOM_LINKS_FILE):
            return {}
        try:
            with open(ZOOM_LINKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # ensure it's a simple str→str dict
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception as e:
            messagebox.showwarning("Zoom links",
                                   f"Could not read {ZOOM_LINKS_FILE}.\n{e}")
        return {}

    def _save_zoom_links(self):
        """Save per-class Zoom URLs to zoom_links.json."""
        try:
            with open(ZOOM_LINKS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.class_zoom_urls, f, indent=2)
        except Exception as e:
            messagebox.showerror("Zoom links",
                                 f"Could not save to {ZOOM_LINKS_FILE}.\n{e}")

    # ---------- App settings (archived classes) ----------

    def _load_settings(self):
        if not os.path.exists(SETTINGS_FILE):
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            hidden = data.get("hidden_courses", [])
            self.safe_mode = data.get("safe_mode", False)
            if isinstance(hidden, list):
                self.hidden_courses = {str(c) for c in hidden}
        except Exception as e:
            messagebox.showwarning("Settings",
                                   f"Could not read {SETTINGS_FILE}.\n{e}")

    def _save_settings(self):
        data = {
            "hidden_courses": sorted(self.hidden_courses),
            "safe_mode": self.safe_mode,
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Settings",
                                 f"Could not save to {SETTINGS_FILE}.\n{e}")

    # ---------- Helpers ----------

    def _iter_sessions(self, selected_courses: set[str], include_archived: bool = False):
        """
        Yield (task, course_key, start_datetime, seconds) for sessions
        matching selected courses and archive visibility.
        """
        for t in self.tasks:
            course = (t.course or "Unassigned").strip() or "Unassigned"

            # respect archive settings
            if not include_archived and course in self.hidden_courses:
                continue

            # respect selected course filter (analytics-level)
            if selected_courses and course not in selected_courses:
                continue

            for s in t.sessions:
                secs = s.get("seconds", 0)
                if secs <= 0:
                    continue
                try:
                    start = datetime.fromisoformat(s["start"])
                except Exception:
                    continue
                yield t, course, start, secs

    def _quick_filter_class(self, course: str):
        """
        Toggle a class filter based on KPI badge click.
        - Clicking a class applies that filter.
        - Clicking the same class again clears the filter.
        """
        # Normalize course key (we use bare codes like '550' or 'Unassigned')
        course = (course or "Unassigned").strip() or "Unassigned"

        if self.course_filter == course:
            # toggle off if already selected
            self.course_filter = None
            self._set_status("Cleared class filter.")
        else:
            self.course_filter = course
            # it’s handy to show grouped view when filtering by class
            self.group_by_class.set(True)
            self._set_status(f"Filtered to {course}.")

        self._refresh_list()



    def _toggle_btn_style(self, running: bool) -> dict:
        """Return CTkButton style kwargs based on running state."""
        if running:
            # 'Stop' state: red-ish danger styling
            return {
                "fg_color": ("#ffdddd", "#822222"),  # light / dark
                "hover_color": ("#ffcccc", "#9b2c2c"),
                "text_color": ("#000000", "#ffffff"),
                "border_width": 0
            }
        # 'Start' state: default CTk styling (let theme handle it)
        return {
            "fg_color": None,
            "hover_color": None,
            "text_color": None,
            "border_width": 0
        }

    def _filtered_tasks(self):
        mode = self.filter_mode.get()
        show_arch = self.show_archived.get()

        if mode == "Active":
            base = [t for t in self.tasks if not t.done]
        elif mode == "Completed":
            base = [t for t in self.tasks if t.done]
        else:
            base = list(self.tasks)

        # hide archived classes unless user explicitly shows them
        if not show_arch:
            base = [
                t for t in base
                if not t.course or str(t.course).strip() not in self.hidden_courses
            ]

        # NEW: filter by a specific class when set
        if self.course_filter:
            def course_key(t: Task) -> str:
                return (t.course or "Unassigned").strip() or "Unassigned"

            base = [t for t in base if course_key(t) == self.course_filter]

        return base



    def _refresh_list(self):
        self._refresh_cards()
        self._update_kpi()
        todo = sum(1 for t in self.tasks if not t.done)
        self._set_status(f"{len(self.tasks)} total — {todo} to do — "
                         f"Filter: {self.filter_mode.get()} — "
                         f"{'Grouped' if self.group_by_class.get() else 'Flat'}")

    def _refresh_cards(self):
        # blow away old rows
        for row in self._card_rows:
            row.destroy()
        self._card_rows.clear()
        current = self._filtered_tasks()

        if self.group_by_class.get():
            buckets: dict[str, list[Task]] = {}
            for t in current:
                key = (f"{t.course}" or "Unassigned").strip()
                buckets.setdefault(key, []).append(t)

            def bucket_key(k: str):  # Unassigned last
                return (k == "Unassigned", k)

            for cls in sorted(buckets.keys(), key=bucket_key):
                # Section header
                header = ctk.CTkLabel(self.cards, text=cls, anchor="w",
                                      font=("TkDefaultFont", 13, "bold"))
                header.pack(fill="x", padx=12, pady=(10, 0))
                self._card_rows.append(header)

                for t in buckets[cls]:
                    card = self._make_task_card(self.cards, t)
                    card.pack(fill="x", padx=10, pady=6)
                    self._card_rows.append(card)
        else:
            for t in current:
                card = self._make_task_card(self.cards, t)
                card.pack(fill="x", padx=10, pady=6)
                self._card_rows.append(card)

    def _now_iso(self) -> str:
        # use UTC to avoid DST weirdness in durations
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _task_total_seconds(self, t: Task) -> int:
        total = sum(s.get("seconds", 0) for s in t.sessions)
        # include running session if any
        if t.running_start:
            try:
                start = datetime.fromisoformat(t.running_start)
                now = datetime.now(timezone.utc)
                total += int((now - start).total_seconds())
            except Exception:
                pass
        return max(0, total)

    def _fmt_seconds(self, secs: int) -> str:
        h, r = divmod(secs, 3600)
        m, s = divmod(r, 60)
        if h: return f"{h}h {m}m"
        if m: return f"{m}m {s}s"
        return f"{s}s"

    def _course_totals(self, include_archived: bool = False) -> dict[str, int]:
        """Aggregate total seconds by course, including running sessions."""
        totals: dict[str, int] = {}
        for t in self.tasks:
            key = (t.course or "Unassigned").strip() or "Unassigned"
            # skip archived unless explicitly included
            if not include_archived and key in self.hidden_courses:
                continue
            secs = self._task_total_seconds(t)
            totals[key] = totals.get(key, 0) + secs
        return totals

    def _sort_course_keys(self, keys: list[str]) -> list[str]:
        """Numbers first (ascending), then alpha, 'Unassigned' last"""
        def key_fn(k: str):
            if k == "Unassigned":
                return (2, k)
            return (0, int(k)) if k.isdigit() else (1, k)
        return sorted(keys, key=key_fn)

    def _update_kpi(self):
        # clear old badges
        for w in self._kpi_rows:
            w.destroy()
        self._kpi_rows.clear()

        totals = self._course_totals(include_archived=self.show_archived.get())
        if not totals:
            lbl = ctk.CTkLabel(self._kpi_container, text="No time tracked yet")
            lbl.pack(side="left", padx=(0, 8))
            self._kpi_rows.append(lbl)
            return

        title = ctk.CTkLabel(self._kpi_container, text="Time by class",
                             font=("TkDefaultFont", 16, "bold"))
        title.pack(side="left", padx=(0, 8))
        self._kpi_rows.append(title)

        grand_total = 0
        for course in self._sort_course_keys(list(totals.keys())):
            secs = totals[course]
            grand_total += secs

            course_box = ctk.CTkFrame(self._kpi_container, fg_color="transparent")
            course_box.pack(side="left", padx=(6, 0))
            self._kpi_rows.append(course_box)

            badge = self._make_big_badge(
                course_box,
                f"{course}: {self._fmt_seconds(secs)}",
                tone="highlight"
            )
            badge.pack(side="top", pady=(0, 2))

            has_zoom = (course != "Unassigned" and course in self.class_zoom_urls)

            # click = Zoom if link exists, else filter
            badge.bind(
                "<Button-1>",
                lambda _e, c=course: self._on_kpi_badge_click(c)
            )

            # hover: hand cursor + tooltip
            def on_enter(e, lbl=badge, c=course, hz=has_zoom):
                lbl.configure(cursor="hand2")
                tip_text = "Join Zoom" if hz else "Filter tasks"
                self._show_tooltip(lbl, tip_text)

            def on_leave(e, lbl=badge):
                lbl.configure(cursor="")
                self._hide_tooltip()

            badge.bind("<Enter>", on_enter)
            badge.bind("<Leave>", on_leave)

        total_badge = self._make_big_badge(
            self._kpi_container,
            f"Σ {self._fmt_seconds(grand_total)}",
            tone="neutral"
        )
        total_badge.pack(side="right", padx=(10, 0))
        self._kpi_rows.append(total_badge)

    #zoom link logic
    def _open_zoom_links_dialog(self):
        """Small dialog to add/edit per-class Zoom links."""
        win = ctk.CTkToplevel(self)
        win.title("Zoom links")
        win.geometry("420x180")
        win.resizable(False, False)
        win.grab_set()  # modal-ish

        # Collect known class codes from tasks and from existing zoom links
        courses = set(k for k in self.class_zoom_urls.keys())
        for t in self.tasks:
            if t.course:
                courses.add(str(t.course).strip())
        if "Unassigned" in courses:
            courses.remove("Unassigned")
        course_values = sorted(courses, key=lambda s: (not s.isdigit(), s))

        class_var = ctk.StringVar()
        url_var = ctk.StringVar()

        def load_url_for_class(*_):
            c = class_var.get().strip()
            url_var.set(self.class_zoom_urls.get(c, ""))

        # Row 1: class code
        row1 = ctk.CTkFrame(win, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(16, 6))

        c_label = ctk.CTkLabel(row1, text="Class code (e.g., 550):")
        c_label.pack(side="left", padx=(0, 8))

        class_combo = ctk.CTkComboBox(row1,
                                      width=120,
                                      variable=class_var,
                                      values=course_values,
                                      command=lambda _v: load_url_for_class())
        class_combo.pack(side="left", fill="x", expand=True)

        # allow free typing
        class_combo.configure(state="normal")

        # Row 2: URL
        row2 = ctk.CTkFrame(win, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(6, 6))

        u_label = ctk.CTkLabel(row2, text="Zoom URL:")
        u_label.pack(side="left", padx=(0, 8))

        url_entry = ctk.CTkEntry(row2, textvariable=url_var)
        url_entry.pack(side="left", fill="x", expand=True)

        # Row 3: buttons
        row3 = ctk.CTkFrame(win, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=(10, 10))

        def save_and_close():
            c = class_var.get().strip()
            u = url_var.get().strip()
            if not c:
                messagebox.showinfo("Zoom links", "Enter a class code, e.g., 550.")
                return
            if not u:
                # allow clearing link entirely
                if c in self.class_zoom_urls:
                    del self.class_zoom_urls[c]
                self._save_zoom_links()
                self._update_kpi()
                win.destroy()
                return

            self.class_zoom_urls[c] = u
            self._save_zoom_links()
            self._update_kpi()
            win.destroy()

        def delete_link():
            c = class_var.get().strip()
            if not c or c not in self.class_zoom_urls:
                return
            if messagebox.askyesno("Zoom links",
                                   f"Remove Zoom link for {c}?"):
                del self.class_zoom_urls[c]
                self._save_zoom_links()
                self._update_kpi()
                url_var.set("")

        save_btn = ctk.CTkButton(row3, text="Save", command=save_and_close)
        save_btn.pack(side="right", padx=(8, 0))

        del_btn = ctk.CTkButton(row3, text="Delete link", fg_color="#a6171c",
                                hover_color="#6b1013", command=delete_link)
        del_btn.pack(side="left")

        # focus niceties
        class_combo.focus_set()

    def _open_class_archive_dialog(self):
        """Dialog to mark classes as active/archived (hidden)."""
        win = ctk.CTkToplevel(self)
        win.title("Manage classes")
        win.geometry("400x420")  # a bit taller so buttons don't get cut off
        win.resizable(False, True)
        win.grab_set()

        # ---- Main container ----
        main = ctk.CTkFrame(win, corner_radius=10)
        main.pack(fill="both", expand=True, padx=10, pady=12)

        info = ctk.CTkLabel(
            main,
            text="Uncheck a class to archive it.\n\n"
                 "Archived classes are hidden from the task list and KPIs\n"
                 "unless 'Show archived classes' is enabled.",
            justify="left"
        )
        info.pack(anchor="w", padx=16, pady=(10, 8))

        # ---- Class list ----
        list_frame = ctk.CTkScrollableFrame(main, corner_radius=8)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # collect all seen course codes from tasks
        courses = set()
        for t in self.tasks:
            if t.course:
                courses.add(str(t.course).strip())
        if "Unassigned" in courses:
            courses.remove("Unassigned")

        course_values = sorted(courses, key=lambda s: (not s.isdigit(), s))

        check_vars: Dict[str, ctk.BooleanVar] = {}

        for c in course_values:
            var = ctk.BooleanVar(value=(c not in self.hidden_courses))
            chk = ctk.CTkCheckBox(list_frame, text=f"{c}", variable=var)
            chk.pack(anchor="w", pady=2, padx=8)
            check_vars[c] = var

        # ---- Buttons ----
        btn_row = ctk.CTkFrame(main, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(10, 10))

        def save_and_close():
            # visible = checked; hidden = unchecked
            self.hidden_courses.clear()
            for c, var in check_vars.items():
                if not var.get():
                    self.hidden_courses.add(c)

            # persist + refresh UI
            self._save_settings()
            self._refresh_list()
            self._update_kpi()
            win.destroy()

        def cancel():
            win.destroy()

        cancel_btn = ctk.CTkButton(btn_row,
                                   text="Cancel",
                                   command=cancel,
                                   fg_color="#daf2ec",
                                   text_color="#171717",
                                   hover_color="#a5e8d7")
        cancel_btn.pack(side="right", padx=(8, 0))

        save_btn = ctk.CTkButton(btn_row, text="Save", command=save_and_close)
        save_btn.pack(side="left")

        win.focus_set()

    # open settings dialog
    def _open_settings_dialog(self):
        """Main app settings: zoom links, class archiving, delete completed."""
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("520x520")
        win.resizable(False, False)
        win.grab_set()

        # ----- Zoom section -----
        zoom_frame = ctk.CTkFrame(win, corner_radius=10)
        zoom_frame.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(
            zoom_frame,
            text="Zoom links",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            zoom_frame,
            text="Add or edit Zoom links for your classes.\n"
                 "KPI badges with links behave as “Join Zoom” buttons.",
            justify="left"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        ctk.CTkButton(
            zoom_frame,
            text="Edit class Zoom links…",
            command=self._open_zoom_links_dialog
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # ----- Class archiving section -----
        arch_frame = ctk.CTkFrame(win, corner_radius=10)
        arch_frame.pack(fill="x", padx=16, pady=(8, 8))

        ctk.CTkLabel(
            arch_frame,
            text="Classes & archiving",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            arch_frame,
            text="Archive old classes to hide them from the task list and KPIs.\n"
                 "Use the 'Show archived classes' checkbox in the main view to peek at them.",
            justify="left"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        ctk.CTkButton(
            arch_frame,
            text="Manage archived classes…",
            command=self._open_class_archive_dialog
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # ----- Safe language section -----
        safe_var = ctk.BooleanVar(value=self.safe_mode)

        settings_frame = ctk.CTkFrame(win, corner_radius=10, height=80)
        settings_frame.pack(fill="x", padx=16, pady=(8, 8))
        settings_frame.pack_propagate(False)  # keep the frame height, don't shrink

        ctk.CTkLabel(
            settings_frame,
            text="Language & tone",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 2))

        ctk.CTkCheckBox(
            settings_frame,
            text="Safe Language Mode",
            variable=safe_var,
            command=lambda: self._toggle_safe_mode(safe_var.get())
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # ----- Danger zone -----
        danger = ctk.CTkFrame(win, corner_radius=10)
        danger.pack(fill="x", padx=16, pady=(8, 16))

        ctk.CTkLabel(
            danger,
            text="Danger zone",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            danger,
            text="Delete all completed tasks. This cannot be undone.",
            justify="left"
        ).pack(anchor="w", padx=12, pady=(0, 8))

        ctk.CTkButton(
            danger,
            text="Delete completed tasks…",
            fg_color="#cf6523",
            hover_color="#bf1704",
            text_color="white",
            command=self._clear_completed
        ).pack(anchor="w", padx=12, pady=(0, 10))

    def _toggle_safe_mode(self, val: bool):
        self.safe_mode = val
        self._save_settings()
        new_title = "Do Your Homework" if val else "Do your fucking homework"
        self.title(new_title)

    def _open_course_zoom(self, course: str):
        """Open the Zoom link for a given course code (e.g., '550')."""
        url = self.class_zoom_urls.get(course)
        if not url:
            self._set_status(f"No Zoom link configured for {course}.")
            return

        target = self._normalize_url_or_path(url)
        if not target:
            self._set_status("Invalid Zoom link.")
            return

        try:
            if os.path.exists(target):
                if platform.system() == "Windows":
                    os.startfile(target)  # type: ignore[attr-defined]
                elif platform.system() == "Darwin":
                    os.system(f'open "{target}"')
                else:
                    os.system(f'xdg-open "{target}"')
            else:
                webbrowser.open(target)
            self._set_status(f"Opening Zoom for {course}")
        except Exception as e:
            messagebox.showerror("Open Zoom link",
                                 f"Could not open link:\n{target}\n\n{e}")

    # kpi badge click

    def _on_kpi_badge_click(self, course: str):
        """
        When a KPI badge is clicked:
        - If we have a Zoom URL for this course, open it.
        - Otherwise, fall back to quick-filtering that class.
        """
        if course != "Unassigned" and course in self.class_zoom_urls:
            self._open_course_zoom(course)
        else:
            # assumes you already have _quick_filter_class defined
            try:
                self._quick_filter_class(course)
            except AttributeError:
                # graceful fallback if that method doesn't exist
                self._set_status(f"Clicked: {course}")

    # Analytics aggregations
    def _analytics_time_by_day(self, selected_courses: set[str]) -> list[tuple[_dt.date, float]]:
        """Return list of (date, cumulative_hours) sorted by date."""
        per_day = defaultdict(int)  # date -> seconds

        for _t, _course, start, secs in self._iter_sessions(selected_courses, include_archived=True):
            d = start.date()
            per_day[d] += secs

        if not per_day:
            return []

        days = sorted(per_day.keys())
        data = []
        cum_secs = 0
        for d in days:
            cum_secs += per_day[d]
            data.append((d, cum_secs / 3600.0))  # hours

        return data

    def _analytics_top_tasks(self, selected_courses: set[str], limit: int = 10) -> list[tuple[str, float]]:
        """Return list of (task_title, minutes) for top tasks by time."""
        per_task = defaultdict(int)  # task_id -> seconds
        titles: dict[str, str] = {}

        for t in self.tasks:
            course = (t.course or "Unassigned").strip() or "Unassigned"
            if selected_courses and course not in selected_courses:
                continue
            secs = self._task_total_seconds(t)
            if secs <= 0:
                continue
            per_task[t.id] += secs
            titles[t.id] = t.text or "(no title)"

        top = sorted(per_task.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [(titles[tid], secs / 60.0) for tid, secs in top]  # minutes

    def _analytics_time_by_weekday(self, selected_courses: set[str]) -> list[tuple[str, float]]:
        """Return [('Mon', hours), ...] in order Mon..Sun."""
        per_wd = defaultdict(int)  # weekday_idx -> seconds

        for _t, _course, start, secs in self._iter_sessions(selected_courses, include_archived=True):
            wd = start.weekday()  # 0=Mon
            per_wd[wd] += secs

        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        result = []
        for i, lbl in enumerate(labels):
            result.append((lbl, per_wd[i] / 3600.0))
        return result

    def _open_analytics_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Analytics")
        win.geometry("900x600")
        win.grab_set()

        # --- layout: left = class filters, right = chart + controls ---
        container = ctk.CTkFrame(win)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        left = ctk.CTkFrame(container, corner_radius=10)
        left.pack(side="left", fill="y", padx=(0, 10))

        right = ctk.CTkFrame(container, corner_radius=10)
        right.pack(side="left", fill="both", expand=True)

        # ----- Left: class checkboxes -----
        ctk.CTkLabel(
            left,
            text="Classes",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 4))

        courses = set()
        for t in self.tasks:
            if t.course:
                courses.add((t.course or "").strip())
        if "Unassigned" in courses:
            courses.remove("Unassigned")

        course_values = sorted(courses, key=lambda s: (not s.isdigit(), s))
        self._analytics_course_vars: dict[str, ctk.BooleanVar] = {}

        course_list = ctk.CTkScrollableFrame(left, height=300)
        course_list.pack(fill="y", expand=True, padx=8, pady=(0, 10))

        for c in course_values:
            var = ctk.BooleanVar(value=True)  # default: show all
            chk = ctk.CTkCheckBox(course_list, text=f"{c}", variable=var,
                                  command=lambda: self._analytics_refresh_chart())
            chk.pack(anchor="w", pady=2)
            self._analytics_course_vars[c] = var

        # ----- Right: chart type toggle + matplotlib canvas -----
        header = ctk.CTkFrame(right, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 0))

        ctk.CTkLabel(
            header,
            text="Charts",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        self._analytics_chart_type = ctk.StringVar(value="Cumulative time")
        chart_toggle = ctk.CTkSegmentedButton(
            header,
            values=["Cumulative time", "Time by task", "By weekday"],
            variable=self._analytics_chart_type,
            command=lambda _v: self._analytics_refresh_chart()
        )
        chart_toggle.pack(side="right", padx=10)

        # Matplotlib Figure + Canvas
        self._analytics_fig = Figure(figsize=(5, 4), dpi=70)
        self._analytics_ax = self._analytics_fig.add_subplot(111)

        # 🔹 Dark background for figure + axes
        bg = "#1e1e1e"
        fg = "#f5f5f5"
        self._analytics_fig.patch.set_facecolor(bg)
        self._analytics_ax.set_facecolor(bg)
        self._analytics_ax.tick_params(colors=fg)
        self._analytics_ax.spines["bottom"].set_color(fg)
        self._analytics_ax.spines["top"].set_color(fg)
        self._analytics_ax.spines["left"].set_color(fg)
        self._analytics_ax.spines["right"].set_color(fg)
        self._analytics_ax.yaxis.label.set_color(fg)
        self._analytics_ax.xaxis.label.set_color(fg)
        self._analytics_ax.title.set_color(fg)

        self._analytics_canvas = FigureCanvasTkAgg(self._analytics_fig, master=right)
        self._analytics_canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

        # Kick off first render *after* window is laid out
        def _initial_draw():
            try: win.update_idletasks()
            except Exception:
                pass
            self._analytics_refresh_chart()

        win.after(50, _initial_draw)

    def _analytics_selected_courses(self) -> set[str]:
        """Return set of course codes selected in analytics (e.g., {'550', '585'})."""
        selected = set()
        if not hasattr(self, "_analytics_course_vars"):
            return selected
        for c, var in self._analytics_course_vars.items():
            if var.get():
                selected.add(c)
        return selected

    def _analytics_refresh_chart(self):
        if not hasattr(self, "_analytics_fig"):
            return

        # Ensure canvas/layout is up to date before sizing the figure
        try:
            widget = self._analytics_canvas.get_tk_widget()
            widget.update_idletasks()
            width = max(widget.winfo_width(), 100)
            height = max(widget.winfo_height(), 100)

            # Match figure size (in inches) to the current canvas size
            dpi = self._analytics_fig.dpi or 100
            self._analytics_fig.set_size_inches(width / dpi, height / dpi, forward=True)
        except Exception:
            pass

        selected_courses = self._analytics_selected_courses()
        chart_type = getattr(self, "_analytics_chart_type", None)
        chart_type = chart_type.get() if chart_type is not None else "Cumulative time"

        self._analytics_ax.clear()

        # Re-apply dark theme styling on each redraw
        bg = "#1e1e1e"
        fg = "#f5f5f5"
        self._analytics_fig.patch.set_facecolor(bg)
        self._analytics_ax.set_facecolor(bg)
        self._analytics_ax.tick_params(colors=fg)
        for spine in self._analytics_ax.spines.values():
            spine.set_color(fg)
        self._analytics_ax.yaxis.label.set_color(fg)
        self._analytics_ax.xaxis.label.set_color(fg)
        self._analytics_ax.title.set_color(fg)


        if chart_type == "Cumulative time":
            data = self._analytics_time_by_day(selected_courses)
            if not data:
                self._analytics_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            else:
                dates = [d for d, _h in data]
                hours = [h for _d, h in data]
                self._analytics_ax.plot(dates, hours)
                self._analytics_ax.set_title("Cumulative time by day")
                self._analytics_ax.set_ylabel("Hours")
                self._analytics_ax.set_xlabel("Date")
        elif chart_type == "Time by task":
            data = self._analytics_top_tasks(selected_courses)
            if not data:
                self._analytics_ax.text(0.5, 0.5, "No data", ha="center", va="center")
            else:
                labels = [t for t, _m in data]
                minutes = [m for _t, m in data]
                y_pos = range(len(labels))
                self._analytics_ax.barh(y_pos, minutes)
                self._analytics_ax.set_yticks(y_pos)
                self._analytics_ax.set_yticklabels(labels)
                self._analytics_ax.invert_yaxis()
                self._analytics_ax.set_title("Top tasks by time")
                self._analytics_ax.set_xlabel("Minutes")
        else:  # weekday
            data = self._analytics_time_by_weekday(selected_courses)
            labels = [lbl for lbl, _h in data]
            hours = [h for _lbl, h in data]
            x_pos = range(len(labels))
            self._analytics_ax.bar(x_pos, hours)
            self._analytics_ax.set_xticks(x_pos)
            self._analytics_ax.set_xticklabels(labels)
            self._analytics_ax.set_title("Time by weekday")
            self._analytics_ax.set_ylabel("Hours")

        self._analytics_fig.tight_layout()
        self._analytics_canvas.draw()


    # --- Card design ---
    def _make_task_card(self, parent, task: Task):
        card = ctk.CTkFrame(parent, corner_radius=12,
                            fg_color=("gray95", "gray15"), height=75)
        card.pack(fill="x", padx=10, pady=0)
        card.pack_propagate(False)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=0)

        inner.grid_columnconfigure(0, weight=1)
        inner.grid_columnconfigure(1, weight=1)

        # left  (checkbox, title, task badges)
        left = ctk.CTkFrame(inner, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        left.grid_columnconfigure(0, minsize=18, weight=0)
        left.grid_columnconfigure(1, weight=1)

        cb_holder = ctk.CTkFrame(left, fg_color="transparent", width=40)
        cb_holder.grid(row=0, column=0, sticky="nw", padx=(0,6), pady=(20,20))
        cb_holder.grid_propagate(False)

        var = ctk.BooleanVar(value=task.done)
        cb = ctk.CTkCheckBox(cb_holder, text="", variable=var,
                             command=lambda tid=task.id, v=var: self._toggle_done_by_id(tid, v.get()))
        cb.place(relx=0.0, rely=0.0, anchor="nw")

        #Task title
        textwrap = ctk.CTkFrame(left, fg_color="transparent")
        textwrap.grid(row=0, column=1, sticky="nw", pady=(6,0))

        text_lbl = ctk.CTkLabel(
            textwrap,
            text=task.text or "(no title)",
            anchor="w",
            justify="left",
            font=self.font_done if task.done else self.font_normal
        )
        text_lbl.pack(side="top", fill="x", pady=(0, 0))

        # meta row
        meta = ctk.CTkFrame(textwrap, fg_color="transparent")
        meta.pack(side="top", fill="x", pady=(0, 0))

        # due badge
        if task.due:
            due_badge = self._make_badge(meta, f"Due {task.due}")
            try:
                d = _dt.date.fromisoformat(task.due)
                if not task.done:
                    if d < _dt.date.today():
                        due_badge.configure(fg_color=("orange", "dark orange"))
                    elif d == _dt.date.today():
                        due_badge.configure(fg_color=("gold", "goldenrod"))
            except Exception:
                pass
            due_badge.pack(side="left", padx=(0, 6))
        else:
            self._make_badge(meta, "No due date").pack(side="left", padx=(0, 6))

        # class badge
        if task.course:
            self._make_badge(meta, f"{task.course}", tone="info").pack(side="left")

        # time badge (total including running)
        total_secs = self._task_total_seconds(task)
        time_badge = self._make_badge(meta, f"⏱ {self._fmt_seconds(total_secs)}", tone="neutral")
        time_badge.pack(side="left", padx=(6, 0))

        # right actions
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.grid(row=0, column=1, sticky="ne",padx=(8, 15), pady=(23, 20))

        edit_btn = (ctk.CTkButton(right, text="Edit", width=72,
                      command=lambda tid=task.id: self._start_edit_by_id(tid)))
        edit_btn.pack(side="left", padx=(0, 6))

        trash_btn = ctk.CTkButton(
            right,
            text="🗑",
            width=36,
            fg_color="#cf6523",  # same family as Delete Completed
            hover_color="#bf1704",
            text_color="white",
            command=lambda tid=task.id: self._delete_by_id(tid)
        )
        trash_btn.pack(side="left", padx=(0, 6))

        is_running = bool(task.running_start)
        style = self._toggle_btn_style(is_running)
        toggle_btn = ctk.CTkButton(
            right,
            text=("Stop" if is_running else "Start"),
            width=72,
            command=(lambda tid=task.id: self._check_in_by_id(tid)) if is_running
                else (lambda tid=task.id: self._check_out_by_id(tid)),
            **style
        )
        toggle_btn.pack(side="left", padx=(0, 6))

        reset_btn = (ctk.CTkButton(right,
                                   text="⟲",
                                   width=36,
                                   fg_color="#2e2929",
                                   hover_color="#781a1a",
                                   border_color="#e0c5c5",
                                   border_width=1,
                      command=lambda tid=task.id: self._reset_time_by_id(tid)))
        reset_btn.pack(side="left")

        def _maybe_open(e, tid=task.id):
            # Don’t trigger if you clicked on interactive controls
            interactive = (ctk.CTkButton, ctk.CTkCheckBox, ctk.CTkComboBox, ctk.CTkEntry)
            if isinstance(e.widget, interactive):
                return
            self._set_focus(tid)
            self._open_task_url_by_id(tid)

        def _on_hover_enter(e):
            # only show hand if the task actually has a URL
            if getattr(task, "url", None):
                e.widget.configure(cursor="hand2")

        def _on_hover_leave(e):
            if getattr(task, "url", None):
                e.widget.configure(cursor="")

        for w in (card, inner, left, textwrap, meta):
            w.bind("<Button-1>", _maybe_open, add="+")
            w.bind("<Enter>", _on_hover_enter, add="+")
            w.bind("<Leave>", _on_hover_leave, add="+")

        # reflect done state in label font live
        def _sync_font(*_):
            text_lbl.configure(font=self.font_done if var.get() else self.font_normal)

        var.trace_add("write", lambda *_: _sync_font())

        return card

    # --- badge styles ---
        # -- small --
    def _make_badge(self, parent, text, tone="neutral"):
        colors = {
            "neutral": ("#e7e7e7", "#2b2b2b"),
            "info": ("#d7e9ff", "#1f3b57"),
            "highlight": ("#4d20d4","#d9d3eb"),
            "transparent": ("transparent","#ffffff")
        }
        fg = colors.get(tone, colors["neutral"])
        return ctk.CTkLabel(parent, text=text, padx=8, pady=2, height=22,
                            corner_radius=999, fg_color=fg[0], text_color=fg[1])

        # -- big --
    def _make_big_badge(self, parent, text, tone="neutral"):
        colors = {
            "neutral": ("#e7e7e7", "#2b2b2b"),
            "info": ("#d7e9ff", "#1f3b57"),
            "highlight": ("#4d20d4","#d9d3eb"),
            "transparent": ("transparent","#ffffff")
        }
        fg = colors.get(tone, colors["neutral"])
        return ctk.CTkLabel(parent, text=text, padx=8, pady=2, height=35, font=ctk.CTkFont(size=16, weight="bold"),
                            corner_radius=30, fg_color=fg[0], text_color=fg[1])

    ''' Unused
    def _start_timer_tick(self):
        # call once in __init__
        self.after(1000, self._timer_tick)

    def _timer_tick(self):
        # just repaint cards; avoids rewriting file
        # (you could optimize to only update running tasks)
        if hasattr(self, "_refresh_cards"):
            self._refresh_cards()
        self.after(1000, self._timer_tick)
    '''

    def _set_focus(self, task_id: Optional[str]):
        self._focus_task_id = task_id
        t = self._task_by_id(task_id)
        if t:
            self._set_status(f"Selected: {t.text} — {self._fmt_seconds(self._task_total_seconds(t))}")

    def _task_by_id(self, task_id: Optional[str]) -> Optional[Task]:
        if not task_id:
            return None
        return next((t for t in self.tasks if t.id == task_id), None)

    def _validate_due(self, s: str) -> Optional[str]:
        s = s.strip()
        if not s:
            return None
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showwarning("Invalid date", "Use YYYY-MM-DD (e.g., 2025-10-15)")
            return "INVALID"

    def _set_status(self, text: str):
        self.status.set(text)

    # ---------- Tooltip helpers ----------

    def _show_tooltip(self, widget, text: str):
        """Show a small tooltip near the given widget."""
        # Clear any existing tooltip
        self._hide_tooltip()
        if not text:
            return

        # Create a borderless top-level window
        tw = ctk.CTkToplevel(self)
        tw.overrideredirect(True)   # no title bar
        tw.attributes("-topmost", True)

        # Position: just above the widget, slight offset
        try:
            x = widget.winfo_rootx() + widget.winfo_width() // 2
            y = widget.winfo_rooty() - 25
        except Exception:
            x, y = 0, 0

        tw.geometry(f"+{x}+{y}")

        label = ctk.CTkLabel(
            tw,
            text=text,
            corner_radius=6,
            fg_color=("gray90", "gray20"),
            text_color=("black", "white"),
            padx=8,
            pady=4,
        )
        label.pack()

        self._tooltip_window = tw

    def _hide_tooltip(self):
        """Hide any active tooltip."""
        if self._tooltip_window is not None:
            try:
                self._tooltip_window.destroy()
            except Exception:
                pass
            self._tooltip_window = None


    # ---------- Actions ----------
    def _add_or_update(self):
        text = self.entry.get().strip()
        if not text:
            messagebox.showinfo("Empty", "Type a task description first.")
            return
        due = self._validate_due(self.due_var.get())
        if due == "INVALID":
            return
        course = self.class_var.get().strip() or None
        url = (self.url_var.get().strip() or None)

        if self.editing_task_id:
            # Update existing
            t = next((x for x in self.tasks if x.id == self.editing_task_id), None)
            if t:
                t.text = text
                t.due = due
                t.course = course
                t.url = url
                self._save_tasks()
                self._refresh_list()
                self._set_status("Updated task.")
            self.editing_task_id = None
            self.add_btn.configure(text="Add")
        else:
            # Create new
            self.tasks.append(Task(id=str(uuid.uuid4()), text=text, due=due, course=course, url=url))
            self._save_tasks()
            self._refresh_list()
            self._set_status("Added task.")
        if course:
            current_vals = set(self.class_combo.cget("values") or [])
            if course not in current_vals:
                updated = sorted(current_vals | {course}, key=lambda s: (not s.isdigit(), s))
                self.class_combo["values"] = updated

        self.entry.delete(0, "end")
        self.due_var.set("")
        self.class_var.set("")
        self.url_var.set("")

    """ # unused
    def _start_edit(self, *_):
        # now acts on focused card
        self._start_edit_by_id(self._focus_task_id)

    def _toggle_done(self):
        self._toggle_done_by_id(self._focus_task_id)
        self._refresh_list()

    def _delete_selected(self):
        self._delete_by_id(self._focus_task_id)
        self._refresh_list()
    """ #

    def _check_out_by_id(self, task_id: Optional[str]):
        t = self._task_by_id(task_id)
        if not t: return
        if t.running_start:
            self._set_status("Already running; hit Stop to check in.")
            return
        t.running_start = self._now_iso()
        self._save_tasks()
        self._refresh_list()
        self._set_focus(t.id)
        self._set_status(f"Started timer for '{t.text}'")

    def _check_in_by_id(self, task_id: Optional[str]):
        t = self._task_by_id(task_id)
        if not t or not t.running_start:
            self._set_status("No running timer to stop.")
            return
        try:
            start = datetime.fromisoformat(t.running_start)
            end = datetime.now(timezone.utc)
            secs = int((end - start).total_seconds())
            t.sessions.append({
                "start": t.running_start, "end": end.isoformat(timespec="seconds"), "seconds": secs
            })
        except Exception:
            # if parsing fails, still push a session with zero seconds to keep data sane
            t.sessions.append({"start": t.running_start, "end": self._now_iso(), "seconds": 0})
        t.running_start = None
        self._save_tasks()
        self._refresh_cards()
        self._set_focus(t.id)
        self._set_status(f"Stopped timer for '{t.text}'")
        self._update_kpi()

    def _reset_time_by_id(self, task_id: Optional[str]):
        t = self._task_by_id(task_id)
        if not t: return
        if messagebox.askyesno("Reset time", f"Reset tracked time for '{t.text}'?"):
            t.sessions.clear()
            t.running_start = None
            self._save_tasks()
            self._refresh_cards()
            self._set_status("Time cleared.")
        self._update_kpi()

    def destroy(self):
        # check in any running tasks to "now"
        changed = False
        for t in self.tasks:
            if t.running_start:
                try:
                    start = datetime.fromisoformat(t.running_start)
                    end = datetime.now(timezone.utc)
                    secs = int((end - start).total_seconds())
                    t.sessions.append(
                        {"start": t.running_start, "end": end.isoformat(timespec="seconds"), "seconds": secs})
                except Exception:
                    pass
                t.running_start = None
                changed = True
        if changed:
            self._save_tasks()
        super().destroy()

    def _clear_completed(self):
        count = sum(1 for t in self.tasks if t.done)
        if count == 0:
            self._set_status("No completed tasks to clear.")
            return
        if messagebox.askyesno("Clear completed", f"Remove {count} completed task(s)?"):
            self.tasks = [t for t in self.tasks if not t.done]
            self._save_tasks()
            self._refresh_list()
            self._update_kpi()

    def _start_edit_by_id(self, task_id: Optional[str]):
        t = self._task_by_id(task_id)
        if not t: return
        self.entry.delete(0, "end")
        self.entry.insert(0, t.text)
        self.due_var.set(t.due or "")
        self.class_var.set(t.course or "")
        self.editing_task_id = t.id
        self.add_btn.configure(text="Update")
        self.entry.focus();
        self.entry.icursor("end")
        self._set_status("Editing… press Enter to save.")
        self._set_focus(t.id)
        self.url_var.set(t.url or "")

    def _toggle_done_by_id(self, task_id: Optional[str], new_val: Optional[bool] = None):
        t = self._task_by_id(task_id)
        if not t: return
        t.done = (not t.done) if new_val is None else bool(new_val)
        self._save_tasks()
        self._refresh_cards()
        self._set_focus(t.id)

    def _delete_by_id(self, task_id: Optional[str]):
        t = self._task_by_id(task_id)
        if not t: return
        if messagebox.askyesno("Delete", f"Delete '{t.text}'?"):
            self.tasks = [x for x in self.tasks if x.id != t.id]
            if self.editing_task_id == t.id:
                self.editing_task_id = None
                self.add_btn.configure(text="Add")
                self.entry.delete(0, "end");
                self.due_var.set("")
            self._save_tasks()
            self._refresh_cards()
            self._set_focus(None)
            self._update_kpi()

    def _clear_class(self):
        t = self._get_selected_task()
        if not t:
            return
        t.course = None
        self._save_tasks()
        self._refresh_list()

    def _normalize_url_or_path(self, s: str) -> Optional[str]:
        """Accept http(s) URLs or local file paths. Returns something openable."""
        if not s:
            return None
        s = s.strip()

        # If it's a plausible Windows path or existing file, treat as file
        if os.path.exists(s) or (":" in s and "\\" in s):
            return s

        # If it has a scheme, trust it
        parsed = urlparse(s)
        if parsed.scheme in {"http", "https"}:
            return s

        # If it looks like a bare domain, prefix https
        if parsed.scheme == "" and ("." in parsed.path or "." in s):
            return "https://" + s

        return s  # fallback (webbrowser can still try)

    def _open_task_url_by_id(self, task_id: Optional[str]):
        t = self._task_by_id(task_id)
        if not t or not t.url:
            self._set_status("No link on this task.")
            return

        target = self._normalize_url_or_path(t.url)
        if not target:
            self._set_status("Invalid link.")
            return

        try:
            # Local file?
            if os.path.exists(target):
                if platform.system() == "Windows":
                    os.startfile(target)  # type: ignore[attr-defined]
                elif platform.system() == "Darwin":
                    os.system(f'open "{target}"')
                else:
                    os.system(f'xdg-open "{target}"')
            else:
                webbrowser.open(target)
            self._set_status(f"Opening: {target}")
        except Exception as e:
            messagebox.showerror("Open link", f"Could not open link:\n{target}\n\n{e}")

    # ---------- Sorting ----------
    def _due_key(self, t: "Task"):
        # None goes last when ascending (first when descending by reversing)
        none_flag = (t.due is None)
        return (none_flag, t.due or "", t.created)

    def _sort_by_due(self):
        # Stable sort by: has_due -> due_date -> created
        self.tasks.sort(key=self._due_key)
        if not self.sort_asc:
            self.tasks.reverse()
        self._save_tasks()
        self._refresh_list()

        # Toggle for next click + update button label
        self.sort_asc = not self.sort_asc
        self.sort_btn.configure(text=f"Sort by Due {'↑' if self.sort_asc else '↓'}")
        self._set_status(f"Sorted by due date ({'ascending' if self.sort_asc else 'descending'} next).")

if __name__ == "__main__":
    # Nice default DPI scaling on Windows
    try:
        from ctypes import windll  # type: ignore
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = ToDoApp()
    app.mainloop()
