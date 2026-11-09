"""
PPG-Auswerte-GUI fuer das PPG-Board RK-003 (XIAO ESP32C3 + ADS131M02)
Smart Sensor Systems, Lab 2 -- HAW Hamburg

Oeffnet gespeicherte Messungen und zeigt sie an:
  - CSV aus ppg_viewer.py  (t_s, rot_mV, ir_mV, dunkel_mV)
  - CSV direkt aus dem Serial Monitor (rot, ir, dunkel)
  - CSV aus deutschem Excel (Trennzeichen ';' und Dezimalkomma)
  - Excel-Dateien (.xlsx, benoetigt: pip install openpyxl)

Muss im selben Ordner wie ppg_viewer.py liegen (gleiche Abtastrate/Filter).

Aufruf:
    python ppg_gui.py

Hinweis: Erstellt mit Unterstuetzung von KI (Claude, Anthropic).
"""

import os
import glob
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import Counter

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from ppg_viewer import FS, process   # gleiche Abtastrate und Filter wie live

FILE_PATTERNS = ("*.csv", "*.xlsx", "*.txt")


# ---------------------------------------------------------------------------
# Datei einlesen
# ---------------------------------------------------------------------------
def _to_float(v):
    if isinstance(v, str):
        v = v.strip().replace(",", ".")
    return float(v)


def _rows_from_text(path):
    rows = []
    with open(path, encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ";" in line:                       # deutsches Excel: ; und Dezimalkomma
                parts = line.split(";")
            else:
                parts = line.split(",")
            parts = [p for p in parts if p.strip() != ""]
            try:
                rows.append([_to_float(p) for p in parts])
            except ValueError:
                continue                          # Kopfzeile o. ae.
    return rows


def _rows_from_xlsx(path):
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise RuntimeError("Fuer .xlsx-Dateien bitte 'pip install openpyxl' ausfuehren.")
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for r in ws.iter_rows(values_only=True):
        vals = [v for v in r if v is not None and str(v).strip() != ""]
        try:
            vals = [_to_float(v) for v in vals]
        except (TypeError, ValueError):
            continue
        if vals:
            rows.append(vals)
    wb.close()
    return rows


def load_measurement(path):
    """Gibt t, rot, ir, dunkel (numpy-Arrays, mV) zurueck."""
    ext = os.path.splitext(path)[1].lower()
    rows = _rows_from_xlsx(path) if ext in (".xlsx", ".xlsm") else _rows_from_text(path)
    rows = [r for r in rows if len(r) in (3, 4)]
    if not rows:
        raise ValueError("Keine Messdaten gefunden (erwartet 3 oder 4 Spalten).")

    ncol = Counter(len(r) for r in rows).most_common(1)[0][0]
    data = np.array([r for r in rows if len(r) == ncol])
    if ncol == 4:
        t, red, ir, amb = data.T
    else:
        red, ir, amb = data.T
        t = np.arange(len(red)) / FS
    return t, red, ir, amb


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class PPGApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PPG-Auswertung")
        self.geometry("1300x800")

        self.folder = os.getcwd()
        self.data = None          # (t, rot, ir, dunkel)
        self.current_file = None

        self.var_red = tk.BooleanVar(value=True)
        self.var_ir = tk.BooleanVar(value=True)
        self.var_amb = tk.BooleanVar(value=False)
        self.var_mode = tk.StringVar(value="korrigiert")
        self.var_ac = tk.BooleanVar(value=True)

        self._build_sidebar()
        self._build_plot()
        self.refresh_file_list()

    # ---------- Aufbau ----------
    def _build_sidebar(self):
        side = ttk.Frame(self, padding=8)
        side.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(side, text="Messungen", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.lbl_folder = ttk.Label(side, text=self.folder, wraplength=260, foreground="gray")
        self.lbl_folder.pack(anchor="w", pady=(0, 4))

        btns = ttk.Frame(side)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Ordner...", command=self.choose_folder).pack(side=tk.LEFT)
        ttk.Button(btns, text="Aktualisieren", command=self.refresh_file_list).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Datei oeffnen...", command=self.open_file_dialog).pack(side=tk.LEFT)

        lst_frame = ttk.Frame(side)
        lst_frame.pack(fill=tk.BOTH, expand=False, pady=6)
        self.lst = tk.Listbox(lst_frame, width=40, height=12, exportselection=False)
        sb = ttk.Scrollbar(lst_frame, orient=tk.VERTICAL, command=self.lst.yview)
        self.lst.configure(yscrollcommand=sb.set)
        self.lst.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lst.bind("<<ListboxSelect>>", self.on_select)

        ttk.Separator(side).pack(fill=tk.X, pady=6)
        ttk.Label(side, text="Anzeige", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Checkbutton(side, text="Rot", variable=self.var_red, command=self.redraw).pack(anchor="w")
        ttk.Checkbutton(side, text="IR", variable=self.var_ir, command=self.redraw).pack(anchor="w")
        ttk.Checkbutton(side, text="Dunkel (nur Rohdaten)", variable=self.var_amb,
                        command=self.redraw).pack(anchor="w")
        ttk.Radiobutton(side, text="Rohdaten (mV)", value="roh", variable=self.var_mode,
                        command=self.redraw).pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(side, text="Lichtanteil (LED - Dunkel)", value="korrigiert",
                        variable=self.var_mode, command=self.redraw).pack(anchor="w")
        ttk.Checkbutton(side, text="Puls anzeigen (Bandpass 0,5-5 Hz)", variable=self.var_ac,
                        command=self.redraw).pack(anchor="w", pady=(6, 0))

        ttk.Separator(side).pack(fill=tk.X, pady=6)
        ttk.Label(side, text="Info", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.txt_info = tk.Text(side, width=40, height=14, font=("Consolas", 9), state=tk.DISABLED)
        self.txt_info.pack(fill=tk.X)

    def _build_plot(self):
        frame = ttk.Frame(self)
        frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self.fig = Figure(figsize=(9, 7), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        toolbar = NavigationToolbar2Tk(self.canvas, frame)   # Zoom, Verschieben, PNG speichern
        toolbar.update()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._empty_plot()

    # ---------- Dateien ----------
    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder)
        if folder:
            self.folder = folder
            self.lbl_folder.config(text=folder)
            self.refresh_file_list()

    def refresh_file_list(self):
        files = []
        for pat in FILE_PATTERNS:
            files += glob.glob(os.path.join(self.folder, pat))
        files.sort(key=os.path.getmtime, reverse=True)       # neueste oben
        self.files = files
        self.lst.delete(0, tk.END)
        for f in files:
            self.lst.insert(tk.END, os.path.basename(f))

    def open_file_dialog(self):
        path = filedialog.askopenfilename(
            initialdir=self.folder,
            filetypes=[("Messdaten", "*.csv *.xlsx *.txt"), ("Alle Dateien", "*.*")])
        if path:
            self.load(path)

    def on_select(self, _event):
        sel = self.lst.curselection()
        if sel:
            self.load(self.files[sel[0]])

    def load(self, path):
        try:
            self.data = load_measurement(path)
        except Exception as exc:
            messagebox.showerror("Fehler beim Laden", f"{os.path.basename(path)}\n\n{exc}")
            return
        self.current_file = path
        self.update_info()
        self.redraw()

    # ---------- Anzeige ----------
    def _empty_plot(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.text(0.5, 0.5, "Links eine Messung auswaehlen", ha="center", va="center",
                transform=ax.transAxes, color="gray")
        ax.set_axis_off()
        self.canvas.draw()

    def update_info(self):
        t, red, ir, amb = self.data
        dur = t[-1] - t[0] if len(t) > 1 else 0
        lines = [
            f"Datei:    {os.path.basename(self.current_file)}",
            f"Samples:  {len(t)}",
            f"Dauer:    {dur:.1f} s",
            f"fs:       {FS:.2f} Hz",
            "",
            "Mittelwerte (mV):",
            f"  Rot     {np.mean(red):9.2f}",
            f"  IR      {np.mean(ir):9.2f}",
            f"  Dunkel  {np.mean(amb):9.2f}",
            "",
            "Lichtanteil (LED - Dunkel):",
            f"  Rot     {np.mean(red - amb):9.2f}",
            f"  IR      {np.mean(ir - amb):9.2f}",
        ]
        self.txt_info.config(state=tk.NORMAL)
        self.txt_info.delete("1.0", tk.END)
        self.txt_info.insert(tk.END, "\n".join(lines))
        self.txt_info.config(state=tk.DISABLED)

    def redraw(self):
        if self.data is None:
            return
        t, red, ir, amb = self.data
        red_c, ir_c, red_ac, ir_ac = process(red, ir, amb)

        self.fig.clear()
        if self.var_ac.get():
            ax1 = self.fig.add_subplot(211)
            ax2 = self.fig.add_subplot(212, sharex=ax1)
        else:
            ax1 = self.fig.add_subplot(111)
            ax2 = None

        if self.var_mode.get() == "roh":
            if self.var_red.get():
                ax1.plot(t, red, color="tab:red", label="Rot")
            if self.var_ir.get():
                ax1.plot(t, ir, color="tab:purple", label="IR")
            if self.var_amb.get():
                ax1.plot(t, amb, color="gray", label="Dunkel")
            ax1.set_ylabel("Spannung (mV)")
        else:
            if self.var_red.get():
                ax1.plot(t, red_c, color="tab:red", label="Rot - Dunkel")
            if self.var_ir.get():
                ax1.plot(t, ir_c, color="tab:purple", label="IR - Dunkel")
            ax1.set_ylabel("Lichtanteil (mV)")
        ax1.grid(True, alpha=0.3)
        if ax1.get_legend_handles_labels()[0]:
            ax1.legend(loc="upper right")
        ax1.set_title(os.path.basename(self.current_file))

        if ax2 is not None:
            # invertiert: Herzschlag zeigt als Spitze nach oben
            if self.var_red.get():
                ax2.plot(t, -red_ac, color="tab:red", label="Rot AC (invertiert)")
            if self.var_ir.get():
                ax2.plot(t, -ir_ac, color="tab:purple", label="IR AC (invertiert)")
            ax2.set_ylabel("Puls (mV)")
            ax2.set_xlabel("Zeit (s)")
            ax2.grid(True, alpha=0.3)
            if ax2.get_legend_handles_labels()[0]:
                ax2.legend(loc="upper right")
        else:
            ax1.set_xlabel("Zeit (s)")

        self.fig.tight_layout()
        self.canvas.draw()


if __name__ == "__main__":
    PPGApp().mainloop()