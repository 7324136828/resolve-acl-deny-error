"""Tk settings dialog shared by the source and packaged GUI."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from codex_config import (
    APPROVAL_POLICIES, APPROVAL_REVIEWERS, SANDBOX_MODES, PERMISSION_LEVELS,
    ConfigError, read_codex_config, update_codex_config,
)

PRESET_LABELS = {
    "Keep current permissions": None,
    "Read only; ask for approval": "read-only",
    "Workspace write; ask for approval": "workspace",
    "Approve for me; workspace write": "approve-for-me",
    "Workspace write; no approval prompts": "workspace-no-approvals",
    "Full access; no approval prompts": "full-access",
    "Custom settings": "custom",
}
KEEP = "Keep current value"


class SettingsDialog:
    def __init__(self, parent: tk.Misc, codex_home: Path, on_saved: Callable[[str], None]):
        self.codex_home = codex_home
        self.on_saved = on_saved
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("Codex permissions and model")
        self.window.transient(parent)
        self.window.resizable(True, True)
        self.window.minsize(600, 500)
        frame = ttk.Frame(self.window, padding=20)
        frame.grid(sticky="nsew")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        try:
            current = read_codex_config(codex_home)
        except (ConfigError, OSError) as exc:
            messagebox.showerror("Cannot read Codex settings", str(exc), parent=parent)
            self.window.destroy()
            return
        self.current = current.settings
        ttk.Label(frame, text="Codex permissions and model", font=("TkDefaultFont", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(frame, text=str(current.config_file), wraplength=560).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))
        current_text = "\n".join(f"{key}: {value}" for key, value in self.current.items())
        ttk.Label(frame, text="Current defaults:\n" + (current_text or "No permission or model defaults set."),
                  wraplength=560).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 16))

        self.preset = tk.StringVar(value="Keep current permissions")
        ttk.Label(frame, text="Permission level").grid(row=3, column=0, sticky="w", padx=(0, 15))
        preset_box = ttk.Combobox(frame, textvariable=self.preset, values=list(PRESET_LABELS), state="readonly", width=42)
        preset_box.grid(row=3, column=1, sticky="ew", pady=5)
        preset_box.bind("<<ComboboxSelected>>", self.select_preset)

        self.values = {}
        self.boxes = {}
        for row, (key, label, choices) in enumerate((
            ("approval_policy", "Approval policy", APPROVAL_POLICIES),
            ("approvals_reviewer", "Approval reviewer", APPROVAL_REVIEWERS),
            ("sandbox_mode", "Sandbox mode", SANDBOX_MODES),
        ), start=4):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            variable = tk.StringVar(value=KEEP)
            box = ttk.Combobox(frame, textvariable=variable, values=(KEEP,) + choices, state="disabled")
            box.grid(row=row, column=1, sticky="ew", pady=5)
            self.values[key] = variable
            self.boxes[key] = box

        ttk.Label(frame, text="Default model").grid(row=7, column=0, sticky="w")
        self.model = tk.StringVar(value=str(self.current.get("model", "")))
        ttk.Entry(frame, textvariable=self.model).grid(row=7, column=1, sticky="ew", pady=5)
        ttk.Label(frame, text="Enter a model ID such as gpt-6.1-sol. Leave blank to keep the current model.",
                  wraplength=560).grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 12))
        self.description = tk.StringVar()
        ttk.Label(frame, textvariable=self.description, wraplength=560).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(frame, text=(
            "Save creates a backup of an existing config. Restart Codex to load the defaults. "
            "Project settings, selected profiles, and organization policies may take precedence. "
            "Use a model available to your account."
        ), wraplength=560).grid(row=10, column=0, columnspan=2, sticky="w", pady=(0, 16))
        buttons = ttk.Frame(frame)
        buttons.grid(row=11, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.window.destroy).pack(side="left", padx=6)
        ttk.Button(buttons, text="Save settings", command=self.save).pack(side="left")
        self.select_preset()
        self.window.deiconify()
        self.window.grab_set()

    def select_preset(self, event=None):
        preset = PRESET_LABELS[self.preset.get()]
        custom = preset == "custom"
        values = PERMISSION_LEVELS.get(preset, (KEEP, KEEP, KEEP))
        for (key, variable), value in zip(self.values.items(), values):
            variable.set(value)
            self.boxes[key].configure(state="readonly" if custom else "disabled")
        self.description.set({
            None: "Permissions remain as configured. You can change only the model.",
            "read-only": "Filesystem writes require approval to run outside the read-only sandbox.",
            "workspace": "Codex can write in the workspace and ask you for approval when required.",
            "approve-for-me": "Uses the workspace sandbox and sends eligible approval requests to automatic review.",
            "workspace-no-approvals": "Workspace sandbox stays active. Actions requiring approval are rejected.",
            "full-access": "Removes sandbox restrictions and disables approval prompts. Commands can access your machine.",
            "custom": "Choose when approval is requested, who reviews it, and the sandbox access level.",
        }[preset])

    def save(self):
        options = {key: variable.get() for key, variable in self.values.items() if variable.get() != KEEP}
        model = self.model.get().strip()
        if model and model != str(self.current.get("model", "")):
            options["model"] = model
        if not options:
            messagebox.showinfo("Codex settings", "No settings changes selected.", parent=self.window)
            return
        try:
            result = update_codex_config(self.codex_home, **options)
        except (ConfigError, OSError) as exc:
            messagebox.showerror("Settings were not saved", str(exc), parent=self.window)
            return
        message = "Saved Codex defaults. Restart Codex to load them." if result.changed else "Settings already match."
        if result.backup_file:
            message += f"\nBackup: {result.backup_file}"
        self.on_saved(message)
        messagebox.showinfo("Codex settings", message, parent=self.window)
        self.window.destroy()
