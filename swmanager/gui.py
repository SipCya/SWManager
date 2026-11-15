"""Modern CustomTkinter GUI for SWManager."""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw
from tkinter import Menu, messagebox

from . import (__version__, cleanup, drivers, icons, leftovers, programs,
               utils)

ASSETS = Path(__file__).resolve().parent.parent / "assets"

ACCENT = "#5b7cfa"
ACCENT_HOVER = "#4a6af0"
OK_GREEN = "#2ea043"
WARN = "#d98a1f"
DANGER = "#e5534b"
MUTED = "#8b93a7"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_ICON_SIZE = (30, 30)
_placeholder_cache: ctk.CTkImage | None = None


def _load_image(path, size) -> ctk.CTkImage | None:
    try:
        img = Image.open(path).convert("RGBA")
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        return None


def _placeholder() -> ctk.CTkImage:
    global _placeholder_cache
    if _placeholder_cache is None:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([4, 4, 59, 59], radius=14, fill=(88, 96, 120, 255))
        d.ellipse([24, 24, 40, 40], fill=(200, 206, 222, 255))
        _placeholder_cache = ctk.CTkImage(light_image=img, dark_image=img,
                                          size=_ICON_SIZE)
    return _placeholder_cache


class SWManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.busy = False
        self.admin = utils.is_admin()
        self._row_images: list = []          # keep references (avoid GC)
        self._programs: list[programs.Program] = []
        self._prog_row_widgets: dict[str, ctk.CTkFrame] = {}
        self._clean_rows: list[tuple[cleanup.CleanTarget, ctk.CTkCheckBox]] = []
        self._leftover_rows: list[tuple[str, ctk.CTkCheckBox]] = []
        self._icon_map: dict[str, str] = {}
        self._prog_loaded = False
        self._left_loaded = False

        self.title(f"SWManager {__version__}")
        self.geometry("1060x720")
        self.minsize(900, 600)
        try:
            self.iconbitmap(str(ASSETS / "logo.ico"))
        except Exception:
            pass

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content()
        self._build_statusbar()

        self._show_page("programs")
        if not programs.winget_available():
            self.log("winget not found: install “App Installer” from the "
                     "Microsoft Store to manage programs.")

    # ----------------------------------------------------------- sidebar
    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, width=220, corner_radius=0)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_rowconfigure(7, weight=1)
        bar.grid_propagate(False)

        logo = _load_image(ASSETS / "logo_128.png", (44, 44))
        head = ctk.CTkFrame(bar, fg_color="transparent")
        head.grid(row=0, column=0, padx=18, pady=(22, 18), sticky="w")
        if logo:
            lab = ctk.CTkLabel(head, image=logo, text="")
            lab.image = logo
            lab.pack(side="left")
        ctk.CTkLabel(head, text="SWManager",
                     font=ctk.CTkFont(size=19, weight="bold")).pack(
            side="left", padx=10)

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        items = [
            ("programs", "  🧩   Programs"),
            ("cleanup", "  🧹   Cleanup"),
            ("leftovers", "  🧽   Leftovers"),
            ("drivers", "  🔧   Drivers"),
        ]
        for i, (key, label) in enumerate(items, start=1):
            btn = ctk.CTkButton(
                bar, text=label, anchor="w", height=44, corner_radius=10,
                fg_color="transparent", text_color=("gray10", "gray90"),
                hover_color=("gray80", "gray25"),
                font=ctk.CTkFont(size=15),
                command=lambda k=key: self._show_page(k))
            btn.grid(row=i, column=0, padx=12, pady=4, sticky="ew")
            self._nav_buttons[key] = btn

        foot = ctk.CTkFrame(bar, fg_color="transparent")
        foot.grid(row=8, column=0, padx=16, pady=16, sticky="ew")
        txt = "● Administrator" if self.admin else "● Standard user"
        ctk.CTkLabel(foot, text=txt,
                     text_color=OK_GREEN if self.admin else WARN,
                     font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 8))
        if not self.admin:
            ctk.CTkButton(foot, text="Restart as admin", height=32,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=self._elevate).pack(fill="x", pady=(0, 8))
        self.theme_switch = ctk.CTkSwitch(
            foot, text="Light theme", command=self._toggle_theme)
        self.theme_switch.pack(anchor="w")

    def _toggle_theme(self):
        ctk.set_appearance_mode(
            "light" if self.theme_switch.get() else "dark")

    def _elevate(self):
        if utils.relaunch_as_admin():
            self.destroy()
        else:
            messagebox.showerror("Elevation failed",
                                 "Could not obtain administrator rights.")

    # ----------------------------------------------------------- content
    def _build_content(self):
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {}
        for key, builder in (("programs", self._build_programs),
                             ("cleanup", self._build_cleanup),
                             ("leftovers", self._build_leftovers),
                             ("drivers", self._build_drivers)):
            frame = ctk.CTkFrame(self.content, fg_color="transparent")
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)
            builder(frame)
            self.pages[key] = frame

    def _show_page(self, key: str):
        self.pages[key].tkraise()
        for k, btn in self._nav_buttons.items():
            btn.configure(fg_color=ACCENT if k == key else "transparent",
                          text_color="white" if k == key
                          else ("gray10", "gray90"))
        if key == "programs" and not self._prog_loaded:
            self._prog_loaded = True
            self._reload_programs()
        if key == "leftovers" and not self._left_loaded:
            self._left_loaded = True
            self._scan_leftovers()

    @staticmethod
    def _title(frame, text, subtitle=""):
        box = ctk.CTkFrame(frame, fg_color="transparent")
        ctk.CTkLabel(box, text=text,
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(box, text=subtitle, text_color=MUTED,
                         font=ctk.CTkFont(size=13)).pack(anchor="w")
        return box

    # ------------------------------------------------------- Programs page
    def _build_programs(self, frame):
        frame.grid_rowconfigure(2, weight=1)
        self._title(frame, "Programs",
                    "Update or uninstall installed apps").grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        bar.grid_columnconfigure(3, weight=1)

        self.prog_mode = ctk.CTkSegmentedButton(
            bar, values=["Upgradable", "All"],
            command=lambda _=None: self._reload_programs())
        self.prog_mode.set("Upgradable")
        self.prog_mode.grid(row=0, column=0)

        self.prog_search = ctk.CTkEntry(bar, placeholder_text="Search…",
                                        width=200)
        self.prog_search.grid(row=0, column=1, padx=10)
        self.prog_search.bind("<KeyRelease>", lambda _e: self._render_programs())

        ctk.CTkButton(bar, text="⟳ Refresh list", width=120, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER,
                      command=self._reload_programs).grid(row=0, column=2)
        self.prog_upall = ctk.CTkButton(
            bar, text="Update all", width=110, fg_color=OK_GREEN,
            hover_color="#268c39", command=self._upgrade_all)
        self.prog_upall.grid(row=0, column=4, sticky="e")

        self.prog_list = ctk.CTkScrollableFrame(frame, fg_color=("gray92",
                                                                 "gray14"))
        self.prog_list.grid(row=2, column=0, sticky="nsew")
        self.prog_list.grid_columnconfigure(0, weight=1)
        self.prog_count = ctk.CTkLabel(frame, text="", text_color=MUTED)
        self.prog_count.grid(row=3, column=0, sticky="w", pady=(6, 0))

    def _reload_programs(self):
        mode = self.prog_mode.get()
        self.prog_upall.grid() if mode == "Upgradable" else \
            self.prog_upall.grid_remove()
        self._clear(self.prog_list)
        ctk.CTkLabel(self.prog_list, text="Loading…",
                     text_color=MUTED).grid(row=0, column=0, pady=30)

        fetch = (programs.list_upgradable if mode == "Upgradable"
                 else programs.list_installed)
        self.run_async(fetch, self._on_programs, "Loading programs…")

    def _on_programs(self, items):
        self._programs = items
        self._render_programs()
        self.log(f"{len(items)} programs"
                 + (" with updates." if self.prog_mode.get() == "Upgradable"
                    else " installed."))
        names = [p.name for p in items][:120]
        threading.Thread(target=self._load_icons, args=(names,),
                         daemon=True).start()

    def _load_icons(self, names):
        try:
            mapping = icons.extract_icons(names)
        except Exception:
            mapping = {}
        if mapping:
            self.after(0, lambda: self._apply_icons(mapping))

    def _apply_icons(self, mapping):
        self._icon_map.update(mapping)
        self._render_programs()

    def _render_programs(self):
        self._clear(self.prog_list)
        self._row_images.clear()
        self._prog_row_widgets = {}
        q = self.prog_search.get().lower().strip()
        shown = 0
        cap = 150
        for p in self._programs:
            if q and q not in p.name.lower() and q not in p.pkg_id.lower():
                continue
            if shown >= cap:
                break
            self._program_row(p, shown, self._icon_map.get(p.name))
            shown += 1
        total = len([p for p in self._programs
                     if not q or q in p.name.lower() or q in p.pkg_id.lower()])
        extra = f"  (showing {shown} of {total}, use search)" \
            if total > shown else ""
        self.prog_count.configure(text=f"{total} programs{extra}")
        if shown == 0:
            ctk.CTkLabel(self.prog_list, text="No programs.",
                         text_color=MUTED).grid(row=0, column=0, pady=30)

    def _program_row(self, p: programs.Program, row: int, icon_path):
        rf = ctk.CTkFrame(self.prog_list, corner_radius=10,
                          fg_color=("white", "gray18"))
        rf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        rf.grid_columnconfigure(1, weight=1)
        self._prog_row_widgets[p.pkg_id] = rf

        img = _load_image(icon_path, _ICON_SIZE) if icon_path else _placeholder()
        self._row_images.append(img)
        ctk.CTkLabel(rf, image=img, text="").grid(
            row=0, column=0, rowspan=2, padx=(12, 10), pady=10)

        ctk.CTkLabel(rf, text=p.name, anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(rf, text=p.pkg_id, anchor="w", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(
            row=1, column=1, sticky="w", pady=(0, 10))

        if p.available:
            ctk.CTkLabel(rf, text=f"{p.version}  →  {p.available}",
                         text_color=WARN,
                         font=ctk.CTkFont(size=12, weight="bold")).grid(
                row=0, column=2, rowspan=2, padx=10)
            ctk.CTkButton(rf, text="Update", width=90, height=30,
                          fg_color=OK_GREEN, hover_color="#268c39",
                          command=lambda: self._upgrade_one(p)).grid(
                row=0, column=3, rowspan=2, padx=(0, 6))
        else:
            ctk.CTkLabel(rf, text=p.version, text_color=MUTED,
                         font=ctk.CTkFont(size=12)).grid(
                row=0, column=2, rowspan=2, padx=10)

        ctk.CTkButton(rf, text="Uninstall", width=96, height=30,
                      fg_color="transparent", border_width=1,
                      border_color=DANGER, text_color=DANGER,
                      hover_color=("gray85", "gray25"),
                      command=lambda: self._uninstall_one(p)).grid(
            row=0, column=4, rowspan=2, padx=(0, 12))

        self._bind_menu(rf, p)

    def _bind_menu(self, widget, p):
        """Bind a right-click menu on the row and all of its children."""
        widget.bind("<Button-3>", lambda e, p=p: self._row_menu(e, p))
        for child in widget.winfo_children():
            self._bind_menu(child, p)

    def _row_menu(self, event, p):
        menu = Menu(self, tearoff=0)
        if p.available:
            menu.add_command(label="Update",
                             command=lambda: self._upgrade_one(p))
        menu.add_command(label="Uninstall",
                         command=lambda: self._uninstall_one(p))
        menu.add_separator()
        menu.add_command(label="Force remove leftover entry",
                         command=lambda: self._troubleshoot(p))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _remove_program_row(self, pkg_id: str):
        """Remove one row in place (keeps the scroll position intact)."""
        self._programs = [p for p in self._programs if p.pkg_id != pkg_id]
        w = self._prog_row_widgets.pop(pkg_id, None)
        if w is not None:
            w.destroy()
        self.prog_count.configure(text=f"{len(self._programs)} programs")

    def _upgrade_one(self, p):
        self.log(f"Updating {p.name}…")
        self.run_async(lambda: programs.upgrade(p.pkg_id),
                       lambda r: self._after_upgrade(r, p),
                       f"Updating {p.name}…")

    def _after_upgrade(self, res, p):
        if res.ok:
            self.log(f"✔ Updated {p.name}.")
            if self.prog_mode.get() == "Upgradable":
                self._remove_program_row(p.pkg_id)
        else:
            tail = (res.out or res.err or "").strip().splitlines()
            self.log(f"✖ Update {p.name} failed (code {res.code}). "
                     + (tail[-1] if tail else ""))

    def _upgrade_all(self):
        if not messagebox.askyesno("Confirm", "Update all programs?"):
            return
        self.log("Updating all programs…")
        self.run_async(programs.upgrade_all,
                       lambda r: self._after_cmd(r, "Update all", reload=True),
                       "Updating all programs…")

    def _uninstall_one(self, p):
        if not messagebox.askyesno(
                "Confirm", f"Uninstall “{p.name}”?\nThis cannot be undone."):
            return
        self.log(f"Uninstalling {p.name}…")
        self.run_async(lambda: programs.uninstall(p.pkg_id),
                       lambda r: self._after_uninstall(r, p),
                       f"Uninstalling {p.name}…")

    def _after_uninstall(self, res, p):
        kind = programs.classify_error(res)
        if kind == "ok":
            self.log(f"✔ Uninstalled {p.name}.")
            self._remove_program_row(p.pkg_id)
            return
        if kind == "multiple":
            if messagebox.askyesno(
                    "Multiple versions",
                    f"Multiple versions of “{p.name}” are installed.\n"
                    "Remove all of them?"):
                self.log(f"Removing all versions of {p.name}…")
                self.run_async(
                    lambda: programs.uninstall(p.pkg_id, all_versions=True),
                    lambda r: self._after_uninstall(r, p),
                    f"Removing all versions of {p.name}…")
            else:
                self.log("Uninstall cancelled.")
            return
        if kind == "notfound":
            self._troubleshoot(p)
            return
        tail = (res.out or res.err or "").strip().splitlines()
        self.log(f"✖ Uninstall {p.name} failed (code {res.code}). "
                 + (tail[-1] if tail else ""))

    # ---- Recovery for "ghost" entries (app already gone, still listed)
    def _troubleshoot(self, p):
        self.log(f"Searching for leftover entries for {p.name}…")
        kw = programs.keyword(p.name)
        self.run_async(lambda: (programs.find_appx(kw), programs.find_arp(kw)),
                       lambda r: self._show_troubleshoot(p, r[0], r[1]),
                       "Diagnosing…")

    def _show_troubleshoot(self, p, appx, arp):
        if appx:
            names = ", ".join(a.name for a in appx[:3])
            if messagebox.askyesno(
                    "Windows app found",
                    f"“{p.name}” looks like a Windows (MSIX) app:\n{names}\n\n"
                    "Remove it now? (no admin required)"):
                def work():
                    ok = err = 0
                    for a in appx:
                        if programs.remove_appx(a.full_name).ok:
                            ok += 1
                        else:
                            err += 1
                    return ok, err
                self.run_async(work, lambda r: self._after_force(p, *r),
                               "Removing app…")
            return
        if arp:
            e = arp[0]
            needs_admin = ("HKEY_LOCAL_MACHINE" in e.pspath) and not self.admin
            extra = ("\n\nThis needs administrator rights — if it fails, "
                     "click “Restart as admin” and try again."
                     if needs_admin else "")
            if messagebox.askyesno(
                    "Ghost entry found",
                    f"“{p.name}” is already gone, but a leftover registry "
                    f"entry keeps it in the list:\n\n{e.display}\n\n"
                    f"Remove this ghost entry?{extra}"):
                self.log(f"Removing ghost registry entry for {p.name}…")
                self.run_async(lambda: programs.remove_registry_key(e.pspath),
                               lambda r: self._after_ghost(p, r),
                               "Removing ghost entry…")
            return
        self.log(f"No removable leftover found for {p.name}. It may already be "
                 "gone — click “Refresh list”.")
        messagebox.showinfo(
            "Nothing found",
            f"Couldn't find a removable leftover for “{p.name}”.\n"
            "Try “Refresh list”.")

    def _after_force(self, p, ok, err):
        self.log(f"✔ Removed {ok} package(s)"
                 + (f", {err} failed." if err else "."))
        if ok:
            self._remove_program_row(p.pkg_id)

    def _after_ghost(self, p, res):
        if res.ok:
            self.log(f"✔ Removed ghost entry for {p.name}.")
            self._remove_program_row(p.pkg_id)
            return
        tail = (res.err or res.out or "").strip().splitlines()
        reason = tail[-1] if tail else ""
        if not self.admin:
            self.log(f"✖ Couldn't remove ghost entry (needs admin). {reason}")
            messagebox.showwarning(
                "Administrator required",
                "Removing this entry requires administrator rights.\n"
                "Click “Restart as admin” and try again.")
        else:
            self.log(f"✖ Couldn't remove ghost entry: {reason}")

    def _after_cmd(self, res: utils.CmdResult, label, reload=False):
        tail = (res.out or res.err or "").strip().splitlines()
        snippet = tail[-1] if tail else ""
        self.log((f"✔ {label} done. {snippet}" if res.ok
                  else f"✖ {label}: code {res.code}. {snippet}"))
        if reload:
            self._reload_programs()

    # --------------------------------------------------------- Cleanup page
    def _build_cleanup(self, frame):
        frame.grid_rowconfigure(2, weight=1)
        self._title(frame, "Cleanup",
                    "Free up space from temporary files and caches").grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        bar.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(bar, text="🔍  Analyze space", fg_color=ACCENT,
                      hover_color=ACCENT_HOVER,
                      command=self._scan_cleanup).grid(row=0, column=0)
        ctk.CTkButton(bar, text="🧹  Clean selected", fg_color=OK_GREEN,
                      hover_color="#268c39",
                      command=self._run_cleanup).grid(row=0, column=1, padx=10)
        self.clean_total = ctk.CTkLabel(
            bar, text="Total: —", font=ctk.CTkFont(size=16, weight="bold"))
        self.clean_total.grid(row=0, column=2, sticky="e")

        self.clean_list = ctk.CTkScrollableFrame(frame, fg_color=("gray92",
                                                                  "gray14"))
        self.clean_list.grid(row=2, column=0, sticky="nsew")
        self.clean_list.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.clean_list,
                     text="Press “Analyze space” to begin.",
                     text_color=MUTED).grid(row=0, column=0, pady=30)

    def _scan_cleanup(self):
        self._clear(self.clean_list)
        ctk.CTkLabel(self.clean_list, text="Analyzing…",
                     text_color=MUTED).grid(row=0, column=0, pady=30)
        self.run_async(cleanup.scan, self._show_cleanup, "Analyzing space…")

    def _show_cleanup(self, targets):
        self._clear(self.clean_list)
        self._clean_rows = []
        total = 0
        for i, t in enumerate(targets):
            total += t.size
            rf = ctk.CTkFrame(self.clean_list, corner_radius=10,
                              fg_color=("white", "gray18"))
            rf.grid(row=i, column=0, sticky="ew", padx=6, pady=4)
            rf.grid_columnconfigure(0, weight=1)
            label = t.label + ("   [admin]" if t.needs_admin and not self.admin
                               else "")
            cb = ctk.CTkCheckBox(rf, text=label, font=ctk.CTkFont(size=14))
            if t.size > 0:
                cb.select()
            cb.grid(row=0, column=0, sticky="w", padx=14, pady=12)
            ctk.CTkLabel(rf, text=utils.human_size(t.size), text_color=ACCENT,
                         font=ctk.CTkFont(size=14, weight="bold")).grid(
                row=0, column=1, sticky="e", padx=16)
            self._clean_rows.append((t, cb))
        self.clean_total.configure(text=f"Total: {utils.human_size(total)}")
        self.log(f"Analysis complete: {utils.human_size(total)} recoverable.")

    def _run_cleanup(self):
        chosen = [t for t, cb in self._clean_rows if cb.get()]
        if not chosen:
            messagebox.showinfo("Cleanup", "Select at least one category.")
            return
        need_admin = any(t.needs_admin for t in chosen) and not self.admin
        warn = ("\n\nSome categories need administrator rights and may be "
                "skipped." if need_admin else "")
        if not messagebox.askyesno(
                "Confirm", f"Clean {len(chosen)} categories?{warn}"):
            return

        def work():
            freed = errs = 0
            for t in chosen:
                f, e = cleanup.clean_target(t)
                freed += f
                errs += e
                self.after(0, lambda t=t, f=f: self.log(
                    f"  {t.label}: freed {utils.human_size(f)}"))
            return freed, errs

        def done(result):
            freed, errs = result
            self.log(f"✔ Cleanup complete: {utils.human_size(freed)} freed"
                     + (f", {errs} items in use skipped." if errs else "."))
            messagebox.showinfo("Cleanup complete",
                                f"Space freed: {utils.human_size(freed)}")
            self._scan_cleanup()

        self.log("Starting cleanup…")
        self.run_async(work, done, "Cleaning…")

    # --------------------------------------------------------- Leftovers page
    def _build_leftovers(self, frame):
        frame.grid_rowconfigure(3, weight=1)
        self._title(frame, "Leftovers",
                    "Broken shortcuts and folders left after uninstalls").grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        bar.grid_columnconfigure(3, weight=1)
        self.left_mode = ctk.CTkSegmentedButton(
            bar, values=["Shortcuts", "Empty folders", "Leftover folders"],
            command=lambda _=None: self._scan_leftovers())
        self.left_mode.set("Shortcuts")
        self.left_mode.grid(row=0, column=0)
        ctk.CTkButton(bar, text="🔍  Scan", fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, width=90,
                      command=self._scan_leftovers).grid(row=0, column=1,
                                                         padx=10)
        ctk.CTkButton(bar, text="🗑  Delete selected (Recycle Bin)",
                      fg_color=DANGER, hover_color="#c23b34",
                      command=self._delete_leftovers).grid(row=0, column=2)
        self.left_select_all = ctk.CTkCheckBox(
            bar, text="Select all", command=self._toggle_select_all)
        self.left_select_all.grid(row=0, column=4, sticky="e", padx=(10, 0))

        self.left_warn = ctk.CTkLabel(
            frame, text="", text_color=WARN, anchor="w",
            font=ctk.CTkFont(size=12), wraplength=760, justify="left")
        self.left_warn.grid(row=2, column=0, sticky="w", pady=(0, 6))

        self.left_list = ctk.CTkScrollableFrame(frame, fg_color=("gray92",
                                                                 "gray14"))
        self.left_list.grid(row=3, column=0, sticky="nsew")
        self.left_list.grid_columnconfigure(0, weight=1)
        self.left_count = ctk.CTkLabel(frame, text="", text_color=MUTED)
        self.left_count.grid(row=4, column=0, sticky="w", pady=(6, 0))

    def _scan_leftovers(self):
        mode = self.left_mode.get()
        self._clear(self.left_list)
        self._leftover_rows = []
        self._set_master_checkbox(False)
        ctk.CTkLabel(self.left_list, text="Scanning…",
                     text_color=MUTED).grid(row=0, column=0, pady=30)
        if mode == "Shortcuts":
            self.left_warn.configure(
                text="These shortcuts point to files that no longer exist. "
                     "Note: shortcuts to disconnected external drives can also "
                     "appear here.")
            self.run_async(leftovers.scan_broken_shortcuts,
                           self._show_shortcuts,
                           "Scanning broken shortcuts…")
        elif mode == "Empty folders":
            self.left_warn.configure(
                text="Completely empty folders (no files). Safe to remove: "
                     "they are moved to the Recycle Bin.")
            self.run_async(leftovers.scan_empty_folders,
                           lambda r: self._show_folders(r, preselect=True),
                           "Scanning empty folders…")
        else:
            self.left_warn.configure(
                text="⚠  Heuristic: folders not matched to any installed "
                     "program. May include caches or portable apps STILL in "
                     "use. Review manually before deleting. Everything goes to "
                     "the Recycle Bin (recoverable).")
            self.run_async(leftovers.scan_leftover_folders,
                           lambda r: self._show_folders(r, preselect=False),
                           "Scanning leftover folders…")

    def _show_shortcuts(self, items):
        self._clear(self.left_list)
        self._leftover_rows = []
        if not items:
            ctk.CTkLabel(self.left_list, text="✔ No broken shortcuts.",
                         text_color=MUTED).grid(row=0, column=0, pady=30)
            self.left_count.configure(text="")
            return
        for i, s in enumerate(items):
            self._left_row(i, s.name, f"→ {s.target}", s.path, preselect=True)
        self._set_master_checkbox(True)
        self.left_count.configure(text=f"{len(items)} broken shortcuts")
        self.log(f"{len(items)} broken shortcuts found.")

    def _show_folders(self, items, preselect):
        self._clear(self.left_list)
        self._leftover_rows = []
        if not items:
            ctk.CTkLabel(self.left_list, text="✔ Nothing to show.",
                         text_color=MUTED).grid(row=0, column=0, pady=30)
            self.left_count.configure(text="")
            return
        for i, f in enumerate(items):
            size = ("" if f.size == 0
                    else ("≈ " if f.approx else "") + utils.human_size(f.size))
            self._left_row(i, f.name, f"{f.category}  ·  {f.path}", f.path,
                           preselect=preselect, right=size)
        self._set_master_checkbox(preselect)
        total = sum(f.size for f in items)
        extra = f"  ·  {utils.human_size(total)}" if total else ""
        self.left_count.configure(text=f"{len(items)} folders{extra}")
        self.log(f"{len(items)} folders found.")

    def _left_row(self, row, title, subtitle, path, preselect, right=""):
        rf = ctk.CTkFrame(self.left_list, corner_radius=10,
                          fg_color=("white", "gray18"))
        rf.grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        rf.grid_columnconfigure(1, weight=1)
        cb = ctk.CTkCheckBox(rf, text="", width=24)
        if preselect:
            cb.select()
        cb.grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=10)
        ctk.CTkLabel(rf, text=title, anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(rf, text=subtitle, anchor="w", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(
            row=1, column=1, sticky="w", pady=(0, 10), padx=(0, 10))
        if right:
            ctk.CTkLabel(rf, text=right, text_color=ACCENT,
                         font=ctk.CTkFont(size=13, weight="bold")).grid(
                row=0, column=2, rowspan=2, padx=14)
        self._leftover_rows.append((path, cb))

    def _toggle_select_all(self):
        select = bool(self.left_select_all.get())
        for _p, cb in self._leftover_rows:
            cb.select() if select else cb.deselect()

    def _set_master_checkbox(self, checked: bool):
        self.left_select_all.select() if checked else \
            self.left_select_all.deselect()

    def _delete_leftovers(self):
        paths = [p for p, cb in self._leftover_rows if cb.get()]
        if not paths:
            messagebox.showinfo("Leftovers", "Select at least one item.")
            return
        if not messagebox.askyesno(
                "Confirm deletion",
                f"Move {len(paths)} items to the Recycle Bin?\n"
                "You can restore them from the Recycle Bin if needed."):
            return
        self.log(f"Deleting {len(paths)} leftovers (to Recycle Bin)…")
        self.run_async(lambda: leftovers.delete_to_recycle_bin(paths),
                       self._after_delete, "Moving to Recycle Bin…")

    def _after_delete(self, result):
        ok, err = result
        self.log(f"✔ {ok} items moved to the Recycle Bin"
                 + (f", {err} skipped (in use or protected)." if err else "."))
        messagebox.showinfo("Done",
                            f"{ok} items moved to the Recycle Bin."
                            + (f"\n{err} skipped (in use or protected)."
                               if err else ""))
        self._scan_leftovers()

    # ---------------------------------------------------------- Drivers page
    def _build_drivers(self, frame):
        frame.grid_rowconfigure(2, weight=1)
        self._title(frame, "Drivers",
                    "Check for updates and device status").grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        buttons = [
            ("⬇  Check for updates", self._search_drivers, ACCENT),
            ("⚠  Problem devices", self._problem_devices, None),
            ("📦  Installed drivers", self._installed_drivers, None),
            ("🔄  Scan hardware", self._scan_hw, None),
            ("⚙  Windows Update", drivers.open_windows_update, None),
        ]
        for i, (text, cmd, color) in enumerate(buttons):
            kwargs = dict(text=text, height=34, command=cmd)
            if color:
                kwargs.update(fg_color=color, hover_color=ACCENT_HOVER)
            else:
                kwargs.update(fg_color="transparent", border_width=1,
                              border_color=MUTED,
                              text_color=("gray10", "gray90"),
                              hover_color=("gray85", "gray25"))
            ctk.CTkButton(bar, **kwargs).grid(row=0, column=i, padx=4)

        self.drv_list = ctk.CTkScrollableFrame(frame, fg_color=("gray92",
                                                                "gray14"))
        self.drv_list.grid(row=2, column=0, sticky="nsew")
        self.drv_list.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.drv_list, text="Pick an action above.",
                     text_color=MUTED).grid(row=0, column=0, pady=30)

    def _drv_rows(self, rows, empty):
        self._clear(self.drv_list)
        if not rows:
            ctk.CTkLabel(self.drv_list, text=empty, text_color=MUTED).grid(
                row=0, column=0, pady=30)
            return
        for i, (title, sub) in enumerate(rows):
            rf = ctk.CTkFrame(self.drv_list, corner_radius=10,
                              fg_color=("white", "gray18"))
            rf.grid(row=i, column=0, sticky="ew", padx=6, pady=4)
            rf.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(rf, text=title, anchor="w",
                         font=ctk.CTkFont(size=14)).grid(
                row=0, column=0, sticky="w", padx=14,
                pady=(10, 0 if sub else 10))
            if sub:
                ctk.CTkLabel(rf, text=sub, anchor="w", text_color=MUTED,
                             font=ctk.CTkFont(size=11)).grid(
                    row=1, column=0, sticky="w", padx=14, pady=(0, 10))

    def _search_drivers(self):
        self.log("Checking for driver updates via Windows Update…")
        self.run_async(drivers.search_driver_updates, self._show_driver_updates,
                       "Checking for driver updates…")

    def _show_driver_updates(self, result):
        updates, error = result
        if error:
            self._drv_rows([], f"Error: {error}")
            self.log(f"Windows Update: {error}")
            return
        rows = [(u.title, "") for u in updates]
        self._drv_rows(rows, "✔ No driver updates available.")
        self.log(f"{len(updates)} driver updates found."
                 if updates else "No driver updates.")

    def _problem_devices(self):
        self.run_async(drivers.list_problem_devices,
                       lambda d: self._drv_rows(
                           [(x.name, f"{x.cls} · {x.problem}") for x in d],
                           "✔ All devices are working correctly."),
                       "Checking devices…")

    def _installed_drivers(self):
        self.run_async(drivers.list_third_party_drivers,
                       lambda p: self._drv_rows(
                           [(x.provider or x.published_name,
                             f"{x.cls} · v{x.version} · {x.date}") for x in p],
                           "No third-party drivers (or access denied)."),
                       "Listing drivers…")

    def _scan_hw(self):
        self.run_async(drivers.scan_hardware_changes,
                       lambda r: self._after_cmd(r, "Hardware scan"),
                       "Scanning for hardware changes…")

    # ----------------------------------------------------------- status bar
    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, height=116, corner_radius=0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        self.progress = ctk.CTkProgressBar(bar, width=160, mode="indeterminate")
        self.progress.grid(row=0, column=0, padx=16, pady=(10, 4), sticky="w")
        self.progress.set(0)
        self.status = ctk.CTkLabel(bar, text="Ready.", anchor="w",
                                   text_color=MUTED)
        self.status.grid(row=0, column=1, sticky="w", pady=(10, 4))

        self.log_box = ctk.CTkTextbox(bar, height=66, activate_scrollbars=True,
                                      font=ctk.CTkFont(family="Consolas",
                                                       size=11))
        self.log_box.grid(row=1, column=0, columnspan=2, sticky="ew",
                          padx=16, pady=(0, 12))
        self.log_box.configure(state="disabled")

    def log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _clear(frame):
        for w in frame.winfo_children():
            w.destroy()

    def run_async(self, fn, on_done=None, status="Working…"):
        if self.busy:
            messagebox.showinfo("Please wait",
                                "An operation is already running.")
            return
        self.busy = True
        self.status.configure(text=status)
        self.progress.start()

        def worker():
            try:
                result, err = fn(), None
            except Exception as exc:  # pragma: no cover
                result, err = None, exc
            self.after(0, lambda: self._finish(result, err, on_done))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, result, err, on_done):
        self.busy = False
        self.progress.stop()
        self.progress.set(0)
        self.status.configure(text="Ready.")
        if err is not None:
            self.log(f"ERROR: {err}")
            messagebox.showerror("Error", str(err))
            return
        if on_done:
            on_done(result)


def main():
    app = SWManagerApp()
    app.mainloop()
