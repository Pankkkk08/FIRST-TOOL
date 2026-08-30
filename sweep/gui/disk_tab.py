"""Disk usage analyzer tab: folder scan + treemap + drill-down list."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from shared.format import human_size
from sweep.core.diskscan import Node, scan_directory, squarified_treemap
from shared.workers import CancellableTask
from shared import theme


class DiskUsageTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self._root_node: Node | None = None
        self._current_node: Node | None = None
        self._path_stack: list[Node] = []
        self._task: CancellableTask | None = None
        self._rect_by_id: dict[int, Node] = {}

        self._build_widgets()

    # -- layout -----------------------------------------------------------
    def _build_widgets(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        self.path_var = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(top, textvariable=self.path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Browse…", command=self._browse).pack(side="left", padx=4)
        self.scan_btn = ttk.Button(top, text="Scan", command=self._start_scan)
        self.scan_btn.pack(side="left")

        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=8)
        ttk.Button(nav, text="⬆ Up", command=self._go_up).pack(side="left")
        self.breadcrumb_var = tk.StringVar(value="")
        ttk.Label(nav, textvariable=self.breadcrumb_var).pack(side="left", padx=8)

        self.status_var = tk.StringVar(value="Pick a folder and click Scan.")
        ttk.Label(self, textvariable=self.status_var, foreground=theme.MUTED_FG).pack(
            anchor="w", padx=8
        )

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=6)

        self.canvas = tk.Canvas(body, background=theme.PANEL_BG, highlightthickness=0)
        self.canvas.bind("<Configure>", lambda e: self._render_treemap())
        self.canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        body.add(self.canvas, weight=3)

        list_frame = ttk.Frame(body)
        columns = ("name", "size")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Name")
        self.tree.heading("size", text="Size")
        self.tree.column("name", width=220)
        self.tree.column("size", width=90, anchor="e")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_row_double_click)
        body.add(list_frame, weight=2)

        # Parented to the canvas itself so event.x/event.y (canvas-relative)
        # can be used directly for placement without translating coordinates.
        self._tooltip = tk.Label(
            self.canvas, text="", background="#000000", foreground="#ffffff", font=theme.FONT
        )

    # -- actions ------------------------------------------------------------
    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.path_var.get() or os.path.expanduser("~"))
        if chosen:
            self.path_var.set(chosen)

    def _start_scan(self) -> None:
        path = self.path_var.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showerror("Sweep", f"Not a valid folder:\n{path}")
            return

        if self._task is not None:
            self._task.cancel()

        self.scan_btn.config(state="disabled")
        self.status_var.set(f"Scanning {path} …")
        self._task = CancellableTask()

        def do_scan():
            return scan_directory(path, should_stop=self._task.should_stop)

        def on_done(result, error):
            self.scan_btn.config(state="normal")
            if error is not None:
                self.status_var.set(f"Scan failed: {error}")
                messagebox.showerror("Sweep", f"Scan failed:\n{error}")
                return
            self._root_node = result
            self._path_stack = []
            self._set_current(result)
            self.status_var.set(f"{path} — total {human_size(result.size)}")

        self._task.run(self, do_scan, on_done)

    def _set_current(self, node: Node) -> None:
        self._current_node = node
        self._refresh_breadcrumb()
        self._refresh_list()
        self._render_treemap()

    def _refresh_breadcrumb(self) -> None:
        if self._current_node is None:
            self.breadcrumb_var.set("")
            return
        parts = [n.name for n in self._path_stack] + [self._current_node.name]
        self.breadcrumb_var.set(" / ".join(parts))

    def _go_up(self) -> None:
        if not self._path_stack:
            return
        parent = self._path_stack.pop()
        self._set_current(parent)

    def _refresh_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        if self._current_node is None:
            return
        for child in self._current_node.sorted_children():
            label = f"📁 {child.name}" if child.is_dir else child.name
            self.tree.insert("", "end", iid=child.path, values=(label, human_size(child.size)))

    def _descend(self, node: Node) -> None:
        if not node.is_dir:
            return
        if self._current_node is not None:
            self._path_stack.append(self._current_node)
        self._set_current(node)

    def _on_row_double_click(self, _event) -> None:
        selection = self.tree.selection()
        if not selection or self._current_node is None:
            return
        path = selection[0]
        for child in self._current_node.children:
            if child.path == path and child.is_dir:
                self._descend(child)
                return

    def _on_canvas_double_click(self, event) -> None:
        node = self._node_at(event.x, event.y)
        if node is not None and node.is_dir:
            self._descend(node)

    def _on_canvas_motion(self, event) -> None:
        node = self._node_at(event.x, event.y)
        if node is None:
            self._tooltip.place_forget()
            return
        self._tooltip.config(text=f"{node.name} — {human_size(node.size)}")
        self._tooltip.place(x=event.x + 12, y=event.y + 12)

    def _node_at(self, x: float, y: float) -> Node | None:
        overlapping = self.canvas.find_overlapping(x, y, x, y)
        for item_id in reversed(overlapping):
            if item_id in self._rect_by_id:
                return self._rect_by_id[item_id]
        return None

    def _render_treemap(self) -> None:
        self.canvas.delete("all")
        self._rect_by_id.clear()
        if self._current_node is None:
            return
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 2 or h <= 2:
            return
        children = self._current_node.sorted_children()
        if not children:
            self.canvas.create_text(
                w / 2, h / 2, text="(empty)", fill=theme.MUTED_FG, font=theme.FONT
            )
            return
        rects = squarified_treemap(children, 2, 2, w - 4, h - 4)
        for i, r in enumerate(rects):
            color = theme.TREEMAP_PALETTE[i % len(theme.TREEMAP_PALETTE)]
            rect_id = self.canvas.create_rectangle(
                r.x, r.y, r.x + r.w, r.y + r.h, fill=color, outline=theme.PANEL_BG, width=1
            )
            self._rect_by_id[rect_id] = r.node
            if r.w > 40 and r.h > 16:
                label = r.node.name if r.w > 70 else r.node.name[:8]
                text_id = self.canvas.create_text(
                    r.x + 4, r.y + 4, anchor="nw", text=label, fill="#111111", font=theme.FONT
                )
                self._rect_by_id[text_id] = r.node
