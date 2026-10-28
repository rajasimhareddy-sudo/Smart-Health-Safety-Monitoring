"""
Sensor Station Dashboard
Reads lines like  $D,temp,hum,gas,lat,lon,sats,fix  from the HC-05 (COM / rfcomm port),
plots DHT11 + MQ-2 graphs, shows GPS coordinates in a box, and logs everything to Excel.

Install:  pip install pyserial matplotlib openpyxl
(Linux:   sudo apt install python3-tk)
"""

import os
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports
from openpyxl import Workbook, load_workbook
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ---------------- Settings ----------------
BAUD = 9600
EXCEL_FILE = "sensor_data.xlsx"
MAX_POINTS = 60          # points kept on each graph
SAVE_EVERY = 5           # save Excel every N samples
GAS_WARN = 300
GAS_HIGH = 600
HEADERS = ["Timestamp", "Temperature (C)", "Humidity (%)", "Gas (raw)",
           "Latitude", "Longitude", "Satellites"]


def nan_to_none(v):
    return None if v != v else v


def gas_status(g):
    if g >= GAS_SAFE:
        return "SAFE - gas/smoke!", "light-green"
    if g >= GAS_HIGH:
        return "HIGH - gas/smoke!", "red"
    if g >= GAS_WARN:
        return "Elevated", "orange"
    return "Normal", "green"


class Dashboard:
    def __init__(self, root):
        self.root = root
        root.title("Sensor Station Dashboard")
        root.geometry("1150x720")

        self.ser = None
        self.buffer = ""
        self.t0 = time.time()
        self.unsaved = 0
        self.last_lat = None
        self.last_lon = None

        self.xs = deque(maxlen=MAX_POINTS)
        self.temps = deque(maxlen=MAX_POINTS)
        self.hums = deque(maxlen=MAX_POINTS)
        self.gases = deque(maxlen=MAX_POINTS)

        self.init_excel()
        self.build_ui()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- Excel ----------------
    def init_excel(self):
        if os.path.exists(EXCEL_FILE):
            self.wb = load_workbook(EXCEL_FILE)
            self.ws = self.wb.active
        else:
            self.wb = Workbook()
            self.ws = self.wb.active
            self.ws.title = "Sensor Data"
            self.ws.append(HEADERS)

    def save_excel(self):
        try:
            self.wb.save(EXCEL_FILE)
            self.unsaved = 0
        except PermissionError:
            self.status_var.set("Close the Excel file so data can be saved!")

    # ---------------- UI ----------------
    def build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="Port:").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(top, textvariable=self.port_var, width=18,
                                     values=self.list_ports())
        self.port_box.pack(side="left", padx=5)
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left")
        self.btn = ttk.Button(top, text="Connect", command=self.toggle_connection)
        self.btn.pack(side="left", padx=10)
        self.status_var = tk.StringVar(value="Not connected")
        ttk.Label(top, textvariable=self.status_var).pack(side="left", padx=10)

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=10, pady=5)

        # Graphs (left)
        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.ax_t = self.fig.add_subplot(3, 1, 1)
        self.ax_h = self.fig.add_subplot(3, 1, 2)
        self.ax_g = self.fig.add_subplot(3, 1, 3)
        self.canvas = FigureCanvasTkAgg(self.fig, master=main)
        self.canvas.get_tk_widget().pack(side="left", fill="both", expand=True)
        self.redraw()

        # Right panel
        right = ttk.Frame(main)
        right.pack(side="right", fill="y", padx=(10, 0))

        gps_box = ttk.LabelFrame(right, text="GPS Coordinates", padding=12)
        gps_box.pack(fill="x", pady=(0, 12))
        self.lat_var = tk.StringVar(value="--")
        self.lon_var = tk.StringVar(value="--")
        self.sat_var = tk.StringVar(value="0")
        self.fix_var = tk.StringVar(value="Waiting for GPS fix...")
        big = ("Helvetica", 15, "bold")
        ttk.Label(gps_box, text="Latitude").pack(anchor="w")
        ttk.Label(gps_box, textvariable=self.lat_var, font=big).pack(anchor="w")
        ttk.Label(gps_box, text="Longitude").pack(anchor="w", pady=(8, 0))
        ttk.Label(gps_box, textvariable=self.lon_var, font=big).pack(anchor="w")
        ttk.Label(gps_box, text="Satellites").pack(anchor="w", pady=(8, 0))
        ttk.Label(gps_box, textvariable=self.sat_var, font=big).pack(anchor="w")
        ttk.Label(gps_box, textvariable=self.fix_var).pack(anchor="w", pady=(8, 0))
        ttk.Button(gps_box, text="Open in Google Maps", command=self.open_map).pack(
            fill="x", pady=(10, 0))

        live = ttk.LabelFrame(right, text="Live Readings", padding=12)
        live.pack(fill="x")
        self.temp_var = tk.StringVar(value="-- C")
        self.hum_var = tk.StringVar(value="-- %")
        self.gas_var = tk.StringVar(value="--")
        ttk.Label(live, text="Temperature").pack(anchor="w")
        ttk.Label(live, textvariable=self.temp_var, font=big).pack(anchor="w")
        ttk.Label(live, text="Humidity").pack(anchor="w", pady=(8, 0))
        ttk.Label(live, textvariable=self.hum_var, font=big).pack(anchor="w")
        ttk.Label(live, text="Gas (MQ-2 raw)").pack(anchor="w", pady=(8, 0))
        self.gas_label = tk.Label(live, textvariable=self.gas_var, font=big)
        self.gas_label.pack(anchor="w")

    # ---------------- Serial ----------------
    def list_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def refresh_ports(self):
        self.port_box["values"] = self.list_ports()

    def toggle_connection(self):
        if self.ser:
            self.disconnect()
            return
        port = self.port_var.get()
        if not port:
            messagebox.showwarning("No port", "Select the HC-05 COM port first.")
            return
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0)
        except serial.SerialException as e:
            messagebox.showerror("Connection failed", str(e))
            self.ser = None
            return
        self.t0 = time.time()
        self.buffer = ""
        self.btn.config(text="Disconnect")
        self.status_var.set(f"Connected to {port}")
        self.poll()

    def disconnect(self, msg="Disconnected"):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.btn.config(text="Connect")
        self.status_var.set(msg)
        self.save_excel()

    def poll(self):
        if not self.ser:
            return
        try:
            n = self.ser.in_waiting
            if n:
                self.buffer += self.ser.read(n).decode(errors="ignore")
                while "\n" in self.buffer:
                    line, self.buffer = self.buffer.split("\n", 1)
                    self.handle_line(line)
        except (serial.SerialException, OSError):
            self.disconnect("Connection lost")
            return
        self.root.after(200, self.poll)

    # ---------------- Data handling ----------------
    def handle_line(self, line):
        line = line.strip()
        if not line.startswith("$D,"):
            return
        p = line[3:].split(",")
        if len(p) != 7:
            return
        try:
            temp, hum, gas, lat, lon = map(float, p[:5])
            sats = int(p[5])
            fix = int(p[6])
        except ValueError:
            return

        # Graph data
        self.xs.append(round(time.time() - self.t0, 1))
        self.temps.append(temp)
        self.hums.append(hum)
        self.gases.append(gas)

        # Labels
        self.temp_var.set("--" if temp != temp else f"{temp:.1f} C")
        self.hum_var.set("--" if hum != hum else f"{hum:.0f} %")
        self.gas_var.set(f"{int(gas)}  ({gas_status(gas)[0]})")
        self.gas_label.config(fg=gas_status(gas)[1])
        self.sat_var.set(str(sats))
        if fix:
            self.lat_var.set(f"{lat:.6f}")
            self.lon_var.set(f"{lon:.6f}")
            self.fix_var.set("GPS fix acquired")
            self.last_lat, self.last_lon = lat, lon
        else:
            self.fix_var.set("Waiting for GPS fix...")

        self.redraw()

        # Excel log
        self.ws.append([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            nan_to_none(temp), nan_to_none(hum), int(gas),
            lat if fix else None, lon if fix else None, sats,
        ])
        self.unsaved += 1
        if self.unsaved >= SAVE_EVERY:
            self.save_excel()

    def redraw(self):
        panels = (
            (self.ax_t, self.temps, "Temperature (DHT11)", "deg C", "tab:red"),
            (self.ax_h, self.hums, "Humidity (DHT11)", "%", "tab:blue"),
            (self.ax_g, self.gases, "Gas level (MQ-2)", "raw ADC", "tab:green"),
        )
        for ax, data, title, ylabel, color in panels:
            ax.clear()
            ax.plot(list(self.xs), list(data), color=color, marker="o", markersize=3)
            ax.set_title(title, fontsize=10)
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.3)
        self.ax_g.axhline(GAS_WARN, color="orange", linestyle="--", linewidth=0.8)
        self.ax_g.axhline(GAS_HIGH, color="red", linestyle="--", linewidth=0.8)
        self.ax_g.set_xlabel("Time (s)")
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def open_map(self):
        if self.last_lat is None:
            messagebox.showinfo("No fix", "No GPS position received yet.")
            return
        webbrowser.open(f"https://www.google.com/maps?q={self.last_lat},{self.last_lon}")

    def on_close(self):
        self.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()
