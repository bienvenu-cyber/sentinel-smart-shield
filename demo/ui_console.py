#!/usr/bin/env python3
"""
================================================================
 ui_console.py — UI terminal moderne style Claude Code / Shannon
================================================================
Helpers d'affichage pour rendre le CLI beau :
  - couleurs ANSI (256 + truecolor)
  - box Unicode (╭─╮│╰─╯)
  - timestamps discrets [HH:MM:SS]
  - statuts ● colorés (success / error / info / warn / running)
  - spinner animé (thread non-bloquant)
  - header ASCII art
  - séparateurs élégants

Aucune dépendance externe — 100% stdlib.
================================================================
"""
from __future__ import annotations

import os
import sys
import time
import threading
import shutil
from datetime import datetime

# ---------------- Détection couleur ----------------
_NO_COLOR = os.getenv("NO_COLOR") is not None or not sys.stdout.isatty()

def _c(code: str) -> str:
    return "" if _NO_COLOR else code

# Palette inspirée Claude Code / Shannon (tons doux + accents vifs)
RESET   = _c("\x1b[0m")
DIM     = _c("\x1b[2m")
BOLD    = _c("\x1b[1m")
ITAL    = _c("\x1b[3m")

# Truecolor (24-bit) — fallback ANSI 16 si terminal limité
def _rgb(r: int, g: int, b: int) -> str:
    return _c(f"\x1b[38;2;{r};{g};{b}m")

def _bg(r: int, g: int, b: int) -> str:
    return _c(f"\x1b[48;2;{r};{g};{b}m")

# Tons principaux
FG_MUTED   = _rgb(120, 120, 130)   # gris doux pour timestamps
FG_DIM     = _rgb(160, 160, 170)   # gris clair pour secondaires
FG_TEXT    = _rgb(220, 220, 230)   # blanc cassé (texte normal)
FG_TITLE   = _rgb(255, 255, 255)   # blanc pur (titres)

# Accents
FG_CYAN    = _rgb( 88, 200, 220)   # cyan principal (Claude)
FG_GREEN   = _rgb(120, 220, 140)   # succès
FG_RED     = _rgb(240, 100, 110)   # erreur
FG_YELLOW  = _rgb(240, 200, 100)   # warn
FG_BLUE    = _rgb(130, 170, 240)   # info
FG_PURPLE  = _rgb(190, 140, 240)   # IA / spécial
FG_ORANGE  = _rgb(240, 160,  90)   # action / capture
FG_PINK    = _rgb(240, 120, 180)   # vidéo / média

# ---------------- Largeur terminal ----------------
def _term_width(default: int = 70) -> int:
    try:
        return min(shutil.get_terminal_size((default, 20)).columns, 90)
    except Exception:
        return default

# ---------------- Timestamps ----------------
def _ts() -> str:
    return f"{FG_MUTED}{datetime.now().strftime('%H:%M:%S')}{RESET}"

# ---------------- Statuts (puce ● + label) ----------------
_GLYPHS = {
    "ok":      ("●", FG_GREEN),
    "fail":    ("●", FG_RED),
    "warn":    ("●", FG_YELLOW),
    "info":    ("●", FG_BLUE),
    "run":     ("◆", FG_CYAN),
    "ai":      ("✦", FG_PURPLE),
    "cam":     ("◉", FG_ORANGE),
    "video":   ("▶", FG_PINK),
    "send":    ("▲", FG_CYAN),
    "save":    ("■", FG_DIM),
    "step":    ("›", FG_CYAN),
}

def _line(kind: str, text: str, indent: int = 0) -> None:
    glyph, color = _GLYPHS.get(kind, ("·", FG_DIM))
    pad = "  " * indent
    sys.stdout.write(f"{pad}{_ts()}  {color}{glyph}{RESET}  {FG_TEXT}{text}{RESET}\n")
    sys.stdout.flush()

def ok(text: str, indent: int = 0):    _line("ok", text, indent)
def fail(text: str, indent: int = 0):  _line("fail", text, indent)
def warn(text: str, indent: int = 0):  _line("warn", text, indent)
def info(text: str, indent: int = 0):  _line("info", text, indent)
def step(text: str, indent: int = 0):  _line("step", text, indent)
def ai(text: str, indent: int = 0):    _line("ai", text, indent)
def cam(text: str, indent: int = 0):   _line("cam", text, indent)
def video(text: str, indent: int = 0): _line("video", text, indent)
def send(text: str, indent: int = 0):  _line("send", text, indent)
def save(text: str, indent: int = 0):  _line("save", text, indent)

# ---------------- Box / panneaux ----------------
def _box_line(left: str, right: str, width: int, color: str) -> str:
    inner = width - 2
    body = f" {left}".ljust(inner - len(_strip_ansi(right)) - 1) + f"{right} "
    return f"{color}│{RESET}{body}{color}│{RESET}"

def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

def _visible_len(s: str) -> int:
    return len(_strip_ansi(s))

def header(title: str, subtitle: str = "", color: str = FG_CYAN) -> None:
    """Affiche un header en boîte arrondie."""
    width = _term_width()
    inner = width - 2
    top    = f"{color}╭{'─' * inner}╮{RESET}"
    bot    = f"{color}╰{'─' * inner}╯{RESET}"
    sys.stdout.write("\n" + top + "\n")

    title_str = f"{BOLD}{FG_TITLE}{title}{RESET}"
    pad = (inner - _visible_len(title_str)) // 2
    sys.stdout.write(
        f"{color}│{RESET}{' ' * pad}{title_str}"
        f"{' ' * (inner - pad - _visible_len(title_str))}{color}│{RESET}\n"
    )
    if subtitle:
        sub = f"{FG_DIM}{subtitle}{RESET}"
        pad2 = (inner - _visible_len(sub)) // 2
        sys.stdout.write(
            f"{color}│{RESET}{' ' * pad2}{sub}"
            f"{' ' * (inner - pad2 - _visible_len(sub))}{color}│{RESET}\n"
        )
    sys.stdout.write(bot + "\n")
    sys.stdout.flush()

def panel(rows: list[tuple[str, str]], color: str = FG_CYAN) -> None:
    """Panneau clé/valeur encadré."""
    width = _term_width()
    inner = width - 4
    key_w = max((len(k) for k, _ in rows), default=0)
    sys.stdout.write(f"{color}╭{'─' * (width - 2)}╮{RESET}\n")
    for k, v in rows:
        line = (
            f" {FG_DIM}{k.ljust(key_w)}{RESET}  "
            f"{FG_TEXT}{v}{RESET}"
        )
        pad = inner - _visible_len(line)
        sys.stdout.write(f"{color}│{RESET} {line}{' ' * pad} {color}│{RESET}\n")
    sys.stdout.write(f"{color}╰{'─' * (width - 2)}╯{RESET}\n")
    sys.stdout.flush()

def divider(char: str = "─", color: str = FG_DIM) -> None:
    sys.stdout.write(f"{color}{char * _term_width()}{RESET}\n")
    sys.stdout.flush()

def blank() -> None:
    sys.stdout.write("\n")

def hint(text: str) -> None:
    """Petit texte gris en italique."""
    sys.stdout.write(f"  {FG_MUTED}{ITAL}{text}{RESET}\n")
    sys.stdout.flush()

# ---------------- Spinner ----------------
_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

class Spinner:
    """Spinner animé non-bloquant. Usage : with Spinner('texte'): ..."""
    def __init__(self, text: str, color: str = FG_CYAN, indent: int = 0):
        self.text = text
        self.color = color
        self.indent = indent
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self):
        i = 0
        pad = "  " * self.indent
        while not self._stop.is_set():
            f = _FRAMES[i % len(_FRAMES)]
            sys.stdout.write(
                f"\r{pad}{_ts()}  {self.color}{f}{RESET}  "
                f"{FG_TEXT}{self.text}{RESET}   "
            )
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)
        # Efface la ligne du spinner
        sys.stdout.write("\r" + " " * (_term_width()) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        if _NO_COLOR:
            # Sans couleur (pipe/fichier) : juste un log statique
            info(self.text + "...", self.indent)
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def update(self, text: str):
        self.text = text

    def __exit__(self, *a):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)