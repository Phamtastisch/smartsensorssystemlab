"""
PPG-Viewer fuer das PPG-Board RK-003 (XIAO ESP32C3 + ADS131M02)
Smart Sensor Systems, Lab 2 -- HAW Hamburg

Liest Zeilen "rot_mV,ir_mV,dunkel_mV" vom COM-Port, zeigt sie live an
und speichert alles als CSV.

Aufruf:
    python ppg_viewer.py COM5                    # live messen + CSV speichern
    python ppg_viewer.py --replay messung.csv    # gespeicherte Messung anzeigen

Hinweis: Erstellt mit Unterstuetzung von KI (Claude, Anthropic).
"""

import argparse
import collections
import csv
import datetime
import threading

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from scipy.signal import butter, sosfiltfilt

# ---------------------------------------------------------------------------
# Parameter (muessen zur Firmware passen)
# ---------------------------------------------------------------------------
FS = 4000 / 30          # Abtastrate pro Kanal in Hz (4 kSPS, 3 Phasen x 10 Samples)
WINDOW_S = 10           # angezeigtes Zeitfenster in Sekunden (Live-Modus)
N_WINDOW = int(FS * WINDOW_S)

# Bandpass fuer den pulsierenden Anteil (AC): 0,5-5 Hz = 30-300 bpm.
# Entfernt den Gleichanteil und das 33-Hz-Alias des Lampenflackerns.
SOS_BP = butter(2, [0.5, 5.0], btype="bandpass", fs=FS, output="sos")


# ---------------------------------------------------------------------------
# Signalverarbeitung
# ---------------------------------------------------------------------------
def process(red, ir, amb):
    """Umgebungslicht abziehen und AC-Anteil per Bandpass bestimmen."""
    red_c = np.asarray(red) - np.asarray(amb)   # Lichtanteil Rot (ohne Offset/Umgebung)
    ir_c = np.asarray(ir) - np.asarray(amb)     # Lichtanteil IR
    if len(red_c) > 50:
        red_ac = sosfiltfilt(SOS_BP, red_c)
        ir_ac = sosfiltfilt(SOS_BP, ir_c)
    else:
        red_ac = np.zeros_like(red_c)
        ir_ac = np.zeros_like(ir_c)
    return red_c, ir_c, red_ac, ir_ac


def parse_line(line):
    """'rot,ir,dunkel' -> (r, i, a) oder None bei Kommentar/Fehler."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split(",")
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None          # z. B. Kopfzeile
    if len(vals) == 3:
        return tuple(vals)
    if len(vals) == 4:       # eigene CSV mit Zeitspalte
        return tuple(vals[1:])
    return None


# ---------------------------------------------------------------------------
# Darstellung
# ---------------------------------------------------------------------------
def make_figure():
    fig, (ax_dc, ax_ac) = plt.subplots(2, 1, sharex=True, figsize=(11, 7))
    l_red_dc, = ax_dc.plot([], [], color="tab:red", label="Rot - Dunkel")
    l_ir_dc, = ax_dc.plot([], [], color="tab:purple", label="IR - Dunkel")
    ax_dc.set_ylabel("Lichtanteil (mV)")
    ax_dc.legend(loc="upper left")
    ax_dc.grid(True, alpha=0.3)

    # AC invertiert: mehr Blut -> mehr Absorption -> Peak nach oben (Pulswelle)
    l_red_ac, = ax_ac.plot([], [], color="tab:red", label="Rot AC (invertiert)")
    l_ir_ac, = ax_ac.plot([], [], color="tab:purple", label="IR AC (invertiert)")
    ax_ac.set_ylabel("Puls (mV)")
    ax_ac.set_xlabel("Zeit (s)")
    ax_ac.legend(loc="upper left")
    ax_ac.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig, (ax_dc, ax_ac), (l_red_dc, l_ir_dc, l_red_ac, l_ir_ac)


def draw(axes, lines, t, red, ir, amb):
    red_c, ir_c, red_ac, ir_ac = process(red, ir, amb)
    l_red_dc, l_ir_dc, l_red_ac, l_ir_ac = lines
    l_red_dc.set_data(t, red_c)
    l_ir_dc.set_data(t, ir_c)
    l_red_ac.set_data(t, -red_ac)
    l_ir_ac.set_data(t, -ir_ac)
    for ax in axes:
        ax.relim()
        ax.autoscale_view()
    if len(t) > 1:
        axes[0].set_xlim(t[0], max(t[-1], t[0] + 1))


# ---------------------------------------------------------------------------
# Live-Modus: serieller Empfang in eigenem Thread
# ---------------------------------------------------------------------------
class SerialReader(threading.Thread):
    def __init__(self, port, csv_path):
        super().__init__(daemon=True)
        self.port = port
        self.csv_path = csv_path
        self.buf = collections.deque(maxlen=N_WINDOW)   # (t, rot, ir, dunkel)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.n = 0
        self.error = None

    def run(self):
        import serial   # pyserial
        try:
            with serial.serial_for_url(self.port, 115200, timeout=0.5) as ser, \
                    open(self.csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["t_s", "rot_mV", "ir_mV", "dunkel_mV"])
                while not self.stop_event.is_set():
                    raw = ser.readline().decode(errors="ignore")
                    vals = parse_line(raw)
                    if vals is None:
                        continue
                    t = self.n / FS            # Zeit aus Sample-Index (genauer als PC-Uhr)
                    self.n += 1
                    writer.writerow([f"{t:.4f}", *vals])
                    with self.lock:
                        self.buf.append((t, *vals))
        except Exception as exc:              # z. B. Port belegt
            self.error = exc

    def snapshot(self):
        with self.lock:
            data = list(self.buf)
        if not data:
            return None
        return np.array(data).T                # t, rot, ir, dunkel


def run_live(port):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"ppg_{stamp}.csv"
    reader = SerialReader(port, csv_path)
    reader.start()
    print(f"Lese von {port}, speichere nach {csv_path}  (Fenster schliessen = Ende)")

    fig, axes, lines = make_figure()

    def update(_frame):
        if reader.error:
            print(f"Fehler am Port: {reader.error}")
            plt.close(fig)
            return lines
        snap = reader.snapshot()
        if snap is not None:
            t, red, ir, amb = snap
            draw(axes, lines, t, red, ir, amb)
            fig.suptitle(f"{port}  |  {reader.n} Samples  |  {csv_path}")
        return lines

    anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    plt.show()
    reader.stop_event.set()
    reader.join(timeout=2)
    print(f"Gespeichert: {csv_path} ({reader.n} Samples)")
    return anim


# ---------------------------------------------------------------------------
# Replay-Modus: gespeicherte Datei komplett anzeigen
# ---------------------------------------------------------------------------
def load_file(path):
    rows = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            vals = parse_line(line)
            if vals is not None:
                rows.append(vals)
    data = np.array(rows)
    t = np.arange(len(data)) / FS
    return t, data[:, 0], data[:, 1], data[:, 2]


def run_replay(path, save_png=None):
    t, red, ir, amb = load_file(path)
    fig, axes, lines = make_figure()
    draw(axes, lines, t, red, ir, amb)
    fig.suptitle(f"{path}  |  {len(t)} Samples  |  {t[-1]:.1f} s")
    if save_png:
        fig.savefig(save_png, dpi=120)
    else:
        plt.show()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="PPG-Viewer")
    ap.add_argument("port", nargs="?", default="COM5", help="COM-Port, z. B. COM5")
    ap.add_argument("--replay", metavar="CSV", help="gespeicherte Messung anzeigen")
    ap.add_argument("--png", metavar="DATEI", help="(nur Replay) Bild speichern statt anzeigen")
    args = ap.parse_args()

    if args.replay:
        run_replay(args.replay, args.png)
    else:
        run_live(args.port)