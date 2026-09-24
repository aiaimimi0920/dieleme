from __future__ import annotations
import tkinter as tk


def main():
    from src.data_fixer import DataFixerApp

    root = tk.Tk()
    app = DataFixerApp(root)
    root.mainloop()

__all__ = ('main',)
