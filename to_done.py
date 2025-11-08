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

def app_base_dir() -> Path:
    #packaging
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

def local_path(*parts) -> str:
    return str(app_base_dir().joinpath(*parts))

SAVE_FILE = local_path("tasks.json")

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

        # Use CTkFont, not tkinter.font.Font
        base_size = ctk.CTkFont().cget("size")  # keeps platform default
        self.font_normal = ctk.CTkFont(size=base_size)
        self.font_done = ctk.CTkFont(size=base_size, overstrike=True)

        self.title("Do your fucking homework")
        self.geometry("900x520")
        self.minsize(900, 520)

        self.tasks: List[Task] = []
        self.filter_mode = ctk.StringVar(value="Active")
        self.editing_task_id: Optional[str] = None
        self.sort_asc = True  # <-- added toggle flag
        self.class_var = ctk.StringVar()
        self.group_by_class = ctk.BooleanVar(value=False)
        self.url_var = ctk.StringVar()

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
                                           values=("585", "550")) #replace with your class numbers
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

        clear_btn = ctk.CTkButton(controls, text="Delete Completed",
                      fg_color="#cf6523",
                      hover_color="#bf1704",
                      text_color="white",
                      command=self._clear_completed)
        clear_btn.pack(side="left", padx=(8, 0))
        self.entry.bind("<Return>", lambda e: self._add_or_update())

        # Group by class button
        ctk.CTkCheckBox(controls, text="Group by class",
                        variable=self.group_by_class,
                        command=self._refresh_list).pack(side="left", padx=(8, 0))

        # Sort button
        self.sort_btn = ctk.CTkButton(controls, text="Sort by Due ↑",
                                      command=self._sort_by_due)
        self.sort_btn.pack(side="left", padx=(8, 8))

        # Filter menu
        ctk.CTkOptionMenu(controls,
                          variable=self.filter_mode,
                          values=["All", "Active", "Completed"],
                          command=lambda _: self._refresh_list()) \
            .pack(side="right", padx=(0, 8))
        ctk.CTkLabel(controls, text="Filter: ").pack(side="right", padx=(0,4))

        # --- List (card-style) ---
        self.cards = ctk.CTkScrollableFrame(mid, corner_radius=12, height=420)
        self.cards.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._card_rows = []

        # --- Status bar at bottom ---
        self.status = getattr(self, "status", ctk.StringVar(value="Ready"))
        ctk.CTkLabel(self, textvariable=self.status, anchor="w") \
            .pack(fill="x", side="bottom", padx=10, pady=(0, 8))

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
                self._update_course_values()
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
        self.class_combo["values"] = values

    # ---------- Helpers ----------

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
        if mode == "Active":
            return [t for t in self.tasks if not t.done]
        elif mode == "Completed":
            return [t for t in self.tasks if t.done]
        return list(self.tasks)

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
                key = (f"IMT {t.course}" or "Unassigned").strip()
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

    def _course_totals(self) -> dict[str, int]:
        """Aggregate total seconds by course, including running sessions"""
        totals: dict[str, int] = {}
        for t in self.tasks:
            secs = self._task_total_seconds(t)
            key = (t.course or "Unassigned").strip() or "Unassigned"
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

        totals = self._course_totals()
        if not totals:
            lbl = ctk.CTkLabel(self._kpi_container, text="No time tracked yet")
            lbl.pack(side ="left", padx=(0,8))
            self._kpi_rows.append(lbl)
            return

        title = ctk.CTkLabel(self._kpi_container, text="Time by class",
                             font=("TkDefaultFont", 16, "bold"))
        title.pack(side ="left", padx=(0,8))
        self._kpi_rows.append(title)

        # sum all times together
        grand_total = 0
        for course in self._sort_course_keys(list(totals.keys())):
            secs = totals[course]
            grand_total += secs
            badge = self._make_big_badge(
                self._kpi_container,
                f"{course}: {self._fmt_seconds(secs)}",
                tone="highlight"
            )

            badge.bind("<Button-1>", lambda _e, c=course: self._quick_filter_class(c))
            badge.pack(side="left", padx=(6, 0))
            self._kpi_rows.append(badge)

        total_badge = self._make_big_badge(
            self._kpi_container, f"Σ {self._fmt_seconds(grand_total)}", tone="neutral"
        )
        total_badge.pack(side="right", padx=(10, 0))
        self._kpi_rows.append(total_badge)

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
            self._make_badge(meta, f"IMT {task.course}", tone="info").pack(side="left")

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

        trash_btn = (ctk.CTkButton(right, text="🗑", width=36,
                      command=lambda tid=task.id: self._delete_by_id(tid)))
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

        reset_btn = (ctk.CTkButton(right, text="⟲", width=36, fg_color="#a6171c", hover_color="#6b1013",
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
            self.add_btn.config(text="Add")
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
        self.add_btn.config(text="Update")
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
                self.add_btn.config(text="Add")
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
        self.sort_btn.config(text=f"Sort by Due {'↑' if self.sort_asc else '↓'}")
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
