from __future__ import annotations
from src.data_fixer_context import *  # noqa: F401,F403


def main():
    root = tk.Tk()
    app = DataFixerApp(root)
    root.mainloop()

__all__ = ('main',)
