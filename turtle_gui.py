"""Interactive Turtle-based GUI for repairing Codex deny-read ACL state corruption.

Provides visual status inspection, dry-run checking, one-click repair,
quick access to the Codex sandbox folder, and a TOML settings editor.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import turtle
from typing import Optional

from repair_acl import (
    CheckResult,
    RepairResult,
    StateStatus,
    check_codex_state,
    default_codex_home,
    get_paths,
    repair_codex_state,
)

# Color Palette (Modern Dark Theme)
BG_COLOR = "#181825"
CARD_BG = "#1e1e2e"
SURFACE_BG = "#313244"
TEXT_PRIMARY = "#cdd6f4"
TEXT_MUTED = "#a6adc8"
ACCENT_BLUE = "#89b4fa"
SUCCESS_GREEN = "#a6e3a1"
WARNING_YELLOW = "#f9e2af"
ERROR_RED = "#f38ba8"
BUTTON_BG = "#45475a"
BUTTON_HOVER = "#585b70"

# Button Definitions: (name, x, y, width, height, text, bg_color, text_color, action_id)
BUTTONS = [
    {"id": "check", "x": -340, "y": -40, "w": 130, "h": 40, "text": "Check Status", "bg": "#313244", "fg": "#89b4fa"},
    {"id": "fix", "x": -200, "y": -40, "w": 130, "h": 40, "text": "Fix / Repair", "bg": "#a6e3a1", "fg": "#11111b"},
    {"id": "settings", "x": -60, "y": -40, "w": 130, "h": 40, "text": "Settings", "bg": "#313244", "fg": "#89b4fa"},
    {"id": "open", "x": 80, "y": -40, "w": 130, "h": 40, "text": "Open Folder", "bg": "#313244", "fg": "#cdd6f4"},
    {"id": "exit", "x": 220, "y": -40, "w": 120, "h": 40, "text": "Exit", "bg": "#45475a", "fg": "#f38ba8"},
]


class CodexRepairUI:
    def __init__(self, codex_home: Optional[Path] = None):
        self.codex_home = codex_home or default_codex_home()
        self.home, self.sandbox, self.state_file = get_paths(self.codex_home)
        self.logs = [
            f"[{datetime.now().strftime('%H:%M:%S')}] Ready. Target: {self.state_file.name}",
            "Click 'Check Status' to inspect without modifying files.",
            "Make sure ChatGPT / Codex and VS Code sessions are closed before fixing.",
        ]
        self.last_check: Optional[CheckResult] = None
        self.last_repair: Optional[RepairResult] = None
        self.current_status = StateStatus.NOT_FOUND
        self.status_title = "Ready to Inspect"
        self.status_detail = "Click 'Check Status' to diagnose sandbox state."
        self.status_color = SURFACE_BG
        self.status_fg = TEXT_PRIMARY

        # Setup Turtle Screen
        turtle.setup(width=760, height=620)
        self.screen = turtle.Screen()
        self.screen.title("Codex Repair and Settings")
        self.screen.bgcolor(BG_COLOR)
        self.screen.tracer(0)

        # Drawing turtle
        self.t = turtle.Turtle()
        self.t.hideturtle()
        self.t.speed(0)

        # Initial check
        self.perform_check(log_start=False)

        # Register click handler
        self.screen.onscreenclick(self.on_click)

    def add_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")
        if len(self.logs) > 6:
            self.logs = self.logs[-6:]

    def draw_rect(self, x: float, y: float, w: float, h: float, fill: str, border: Optional[str] = None) -> None:
        self.t.penup()
        self.t.goto(x, y)
        self.t.setheading(0)
        self.t.pendown()
        if fill:
            self.t.fillcolor(fill)
            self.t.begin_fill()
        if border:
            self.t.pencolor(border)
            self.t.pensize(1)
        else:
            self.t.pencolor(fill)

        for _ in range(2):
            self.t.forward(w)
            self.t.left(90)
            self.t.forward(h)
            self.t.left(90)

        if fill:
            self.t.end_fill()
        self.t.penup()

    def draw_text(self, x: float, y: float, text: str, color: str = TEXT_PRIMARY,
                  font_size: int = 10, bold: bool = False, align: str = "left") -> None:
        self.t.penup()
        self.t.goto(x, y)
        self.t.pencolor(color)
        weight = "bold" if bold else "normal"
        self.t.write(text, align=align, font=("Segoe UI", font_size, weight))

    def render(self) -> None:
        self.t.clear()

        # 1. Header Card
        self.draw_rect(-360, 230, 720, 65, CARD_BG, border="#45475a")
        self.draw_text(-340, 268, "Codex Repair and Settings", TEXT_PRIMARY, font_size=15, bold=True)
        self.draw_text(
            -340, 245,
            "Repair Windows ACL state and choose your Codex permissions and default model",
            TEXT_MUTED, font_size=10
        )

        # 2. Path Information Card
        self.draw_rect(-360, 140, 720, 75, CARD_BG, border="#313244")
        self.draw_text(-340, 192, "Codex Home:", ACCENT_BLUE, font_size=10, bold=True)
        self.draw_text(-230, 192, str(self.home), TEXT_PRIMARY, font_size=9)
        self.draw_text(-340, 172, "Sandbox Dir:", ACCENT_BLUE, font_size=10, bold=True)
        self.draw_text(-230, 172, str(self.sandbox), TEXT_PRIMARY, font_size=9)
        self.draw_text(-340, 152, "Target State:", ACCENT_BLUE, font_size=10, bold=True)
        self.draw_text(-230, 152, str(self.state_file), TEXT_PRIMARY, font_size=9)

        # 3. Status Display Card
        self.draw_rect(-360, 20, 720, 105, CARD_BG, border=self.status_color)
        # Status Badge Pill
        self.draw_rect(-340, 80, 200, 32, self.status_color)
        self.draw_text(-240, 88, self.status_title, self.status_fg, font_size=11, bold=True, align="center")

        # Detail explanation
        self.draw_text(-340, 52, self.status_detail, TEXT_PRIMARY, font_size=10)
        advice = "Safe by design: Original bytes and permissions are preserved in a timestamped backup."
        self.draw_text(-340, 32, advice, TEXT_MUTED, font_size=9)

        # 4. Action Buttons
        for btn in BUTTONS:
            self.draw_rect(btn["x"], btn["y"], btn["w"], btn["h"], btn["bg"], border="#585b70")
            center_x = btn["x"] + btn["w"] / 2
            center_y = btn["y"] + (btn["h"] - 14) / 2
            self.draw_text(center_x, center_y, btn["text"], btn["fg"], font_size=10, bold=True, align="center")

        # 5. Activity Log Panel
        self.draw_rect(-360, -250, 720, 190, "#11111b", border="#313244")
        self.draw_text(-340, -75, "Activity & Diagnostic Log:", ACCENT_BLUE, font_size=10, bold=True)

        log_y = -100
        for line in self.logs:
            self.draw_text(-340, log_y, line, TEXT_MUTED, font_size=9)
            log_y -= 22

        # 6. Footer Note
        self.draw_text(0, -280, "Close Codex before repair or saving settings. ACL repair does not change permissions.",
                       TEXT_MUTED, font_size=9, align="center")

        self.screen.update()

    def perform_check(self, log_start: bool = True) -> None:
        if os.name != "nt":
            self.status_title = "Codex Settings"
            self.status_detail = "Use Settings to choose permissions and model. ACL repair is Windows-only."
            self.status_color = ACCENT_BLUE
            self.status_fg = "#11111b"
            self.render()
            return
        if log_start:
            self.add_log("Checking state file...")
        try:
            check = check_codex_state(self.codex_home)
            self.last_check = check
            self.current_status = check.status

            if check.status == StateStatus.HEALTHY:
                self.status_title = "✅ File Healthy"
                self.status_detail = check.message
                self.status_color = SUCCESS_GREEN
                self.status_fg = "#11111b"
                self.add_log(f"Scan complete: State file is valid JSON ({check.size_bytes} bytes).")
            elif check.status == StateStatus.CORRUPT:
                self.status_title = "⚠️ Corruption Detected"
                self.status_detail = f"Corruption: {check.reason} ({check.size_bytes} bytes)."
                self.status_color = ERROR_RED
                self.status_fg = "#11111b"
                self.add_log(f"ALERT: {check.message}")
                self.add_log("Click 'Fix / Repair' to quarantine corrupt file.")
            elif check.status == StateStatus.NOT_FOUND:
                self.status_title = "ℹ️ No State File"
                self.status_detail = check.message
                self.status_color = WARNING_YELLOW
                self.status_fg = "#11111b"
                self.add_log("Notice: No deny_read_acl_state.json exists.")
            else:
                self.status_title = "❌ State Error"
                self.status_detail = check.message
                self.status_color = ERROR_RED
                self.status_fg = "#11111b"
                self.add_log(f"Error: {check.message}")
        except Exception as exc:
            self.status_title = "❌ Error"
            self.status_detail = f"Failed to check state: {exc}"
            self.status_color = ERROR_RED
            self.status_fg = "#11111b"
            self.add_log(f"Exception: {exc}")

        self.render()

    def perform_repair(self) -> None:
        if os.name != "nt":
            self.add_log("ACL repair applies to Windows only. Use Settings on this platform.")
            self.render()
            return
        self.add_log("Initiating repair process...")
        self.render()

        try:
            repair = repair_codex_state(self.codex_home, check_only=False)
            self.last_repair = repair

            if repair.backup_file:
                self.status_title = "🎉 Repaired!"
                self.status_detail = f"Corrupt file quarantined to: {repair.backup_file.name}"
                self.status_color = ACCENT_BLUE
                self.status_fg = "#11111b"
                self.add_log("SUCCESS: Corrupt tracking file moved aside.")
                self.add_log(f"Backup: {repair.backup_file.name}")
                self.add_log("Codex will recreate state on next command.")
            else:
                if repair.status == StateStatus.HEALTHY:
                    self.status_title = "✅ Already Healthy"
                    self.status_detail = "State file is parseable JSON; untouched to prevent data loss."
                    self.status_color = SUCCESS_GREEN
                    self.status_fg = "#11111b"
                    self.add_log("Info: File is healthy JSON. No fix needed.")
                else:
                    self.status_title = "ℹ️ Nothing to Fix"
                    self.status_detail = repair.message
                    self.status_color = WARNING_YELLOW
                    self.status_fg = "#11111b"
                    self.add_log(repair.message)
        except Exception as exc:
            self.status_title = "❌ Repair Failed"
            self.status_detail = f"Could not repair: {exc}"
            self.status_color = ERROR_RED
            self.status_fg = "#11111b"
            self.add_log(f"Repair Error: {exc}")

        self.render()

    def open_settings(self) -> None:
        from settings_gui import SettingsDialog

        def saved(message: str) -> None:
            self.add_log(message.splitlines()[0])
            self.render()

        SettingsDialog(self.screen.getcanvas().winfo_toplevel(), self.codex_home, saved)

    def open_sandbox_folder(self) -> None:
        target_dir = self.sandbox if self.sandbox.exists() else self.home
        self.add_log(f"Opening folder: {target_dir}")
        try:
            if os.name == "nt":
                os.startfile(str(target_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target_dir)])
            else:
                subprocess.Popen(["xdg-open", str(target_dir)])
        except Exception as exc:
            self.add_log(f"Failed to open explorer: {exc}")
        self.render()

    def on_click(self, x: float, y: float) -> None:
        for btn in BUTTONS:
            if btn["x"] <= x <= btn["x"] + btn["w"] and btn["y"] <= y <= btn["y"] + btn["h"]:
                action_id = btn["id"]
                if action_id == "check":
                    self.perform_check()
                elif action_id == "fix":
                    self.perform_repair()
                elif action_id == "settings":
                    self.open_settings()
                elif action_id == "open":
                    self.open_sandbox_folder()
                elif action_id == "exit":
                    self.add_log("Exiting...")
                    self.screen.bye()
                break


def run_turtle_ui(codex_home: Optional[Path] = None) -> None:
    """Launch and run the Turtle graphical user interface."""
    ui = CodexRepairUI(codex_home)
    ui.render()
    turtle.mainloop()


if __name__ == "__main__":
    run_turtle_ui()
