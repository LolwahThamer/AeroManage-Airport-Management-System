import tkinter as tk
import customtkinter as ctk
import sqlite3
import random
import string
import threading
import os
import json
from datetime import datetime


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg":       "#0d1117",
    "card":     "#161b22",
    "border":   "#30363d",
    "accent":   "#00d4aa",
    "accent2":  "#1f6feb",
    "danger":   "#f85149",
    "warning":  "#f0883e",
    "text":     "#e6edf3",
    "muted":    "#7d8590",
    "green":    "#3fb950",
}


class Database:
    def __init__(self, path="aero.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS staff (
            civil_id TEXT PRIMARY KEY,
            name TEXT, role TEXT, password TEXT
        );
        CREATE TABLE IF NOT EXISTS flights (
            flight_number TEXT PRIMARY KEY,
            origin TEXT, destination TEXT,
            total_seats INTEGER, available_seats INTEGER, fare REAL
        );
        CREATE TABLE IF NOT EXISTS bookings (
            pnr TEXT PRIMARY KEY,
            flight_number TEXT, origin TEXT, destination TEXT,
            civil_id TEXT, passenger_name TEXT,
            passenger_age INTEGER, passenger_address TEXT,
            booked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS blocked (
            civil_id TEXT PRIMARY KEY
        );
        """)

        base = os.path.dirname(os.path.abspath(__file__))

        # Load STAFF from data.txt
        if not c.execute("SELECT 1 FROM staff LIMIT 1").fetchone():
            data_path = os.path.join(base, "data.txt")
            with open(data_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = [p.strip() for p in line.strip().split(",")]
                    if len(parts) >= 6:
                        civil_id, name, role, age, address, password = parts[:6]
                        role_norm = "Security" if "security" in role.lower() else "FlightStaff"
                        c.execute("INSERT OR IGNORE INTO staff VALUES (?,?,?,?)",
                                  (civil_id, name, role_norm, password))

        # Load FLIGHTS from flight.txt
        if not c.execute("SELECT 1 FROM flights LIMIT 1").fetchone():
            flight_path = os.path.join(base, "flight.txt")
            with open(flight_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = [p.strip() for p in line.strip().split(",")]
                    if len(parts) >= 6:
                        fnum, origin, dest, total, avail, fare = parts[:6]
                        c.execute("INSERT OR IGNORE INTO flights VALUES (?,?,?,?,?,?)",
                                  (fnum, origin, dest, int(total), int(avail), float(fare)))

        # Load BOOKINGS from booking.txt
        if not c.execute("SELECT 1 FROM bookings LIMIT 1").fetchone():
            booking_path = os.path.join(base, "booking.txt")
            with open(booking_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = [p.strip() for p in line.strip().split(",")]
                    if len(parts) >= 8:
                        pnr, fnum, origin, dest, civil_id, name, age, address = parts[:8]
                        c.execute("INSERT OR IGNORE INTO bookings VALUES (?,?,?,?,?,?,?,?,?)",
                                  (pnr, fnum, origin, dest, civil_id, name,
                                   int(age), address,
                                   datetime.now().strftime("%Y-%m-%d %H:%M")))

        self.conn.commit()

    def q(self, sql, params=()):
        return self.conn.execute(sql, params)

    def run(self, sql, params=()):
        self.conn.execute(sql, params)
        self.conn.commit()


class Passenger:
    def __init__(self, civil_id, name, age, address):
        self.civil_id = civil_id
        self.name     = name
        self.age      = age
        self.address  = address

    def is_blocked(self, db):
        return db.q("SELECT 1 FROM blocked WHERE civil_id=?", (self.civil_id,)).fetchone() is not None

    def book_flight(self, db, flight_number, origin, destination):
        if self.is_blocked(db):
            raise PermissionError("Passenger is blocked.")
        row = db.q("SELECT available_seats FROM flights WHERE flight_number=?", (flight_number,)).fetchone()
        if not row:
            raise ValueError("Flight not found.")
        if row["available_seats"] < 1:
            raise ValueError("No seats available.")
        pnr = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        db.run("""INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?,?)""",
               (pnr, flight_number, origin, destination,
                self.civil_id, self.name, self.age, self.address,
                datetime.now().strftime("%Y-%m-%d %H:%M")))
        db.run("UPDATE flights SET available_seats = available_seats - 1 WHERE flight_number=?", (flight_number,))
        return pnr

    def cancel_booking(self, db, pnr):
        row = db.q("SELECT flight_number FROM bookings WHERE pnr=? AND civil_id=?",
                   (pnr, self.civil_id)).fetchone()
        if not row:
            raise ValueError("Booking not found or not yours.")
        db.run("DELETE FROM bookings WHERE pnr=?", (pnr,))
        db.run("UPDATE flights SET available_seats = available_seats + 1 WHERE flight_number=?",
               (row["flight_number"],))


class Flight:
    @staticmethod
    def search(db, origin, destination):
        return db.q("""SELECT * FROM flights
                       WHERE LOWER(origin)=LOWER(?) AND LOWER(destination)=LOWER(?)
                       AND available_seats > 0""", (origin, destination)).fetchall()

    @staticmethod
    def all_flights(db):
        return db.q("SELECT * FROM flights ORDER BY flight_number").fetchall()

    @staticmethod
    def get(db, flight_number):
        return db.q("SELECT * FROM flights WHERE flight_number=?", (flight_number,)).fetchone()

    @staticmethod
    def passengers(db, flight_number):
        return db.q("SELECT * FROM bookings WHERE flight_number=?", (flight_number,)).fetchall()

    @staticmethod
    def cancel(db, flight_number):
        db.run("DELETE FROM bookings WHERE flight_number=?", (flight_number,))
        db.run("DELETE FROM flights WHERE flight_number=?", (flight_number,))

    @staticmethod
    def load_report(db):
        rows = db.q("SELECT * FROM flights").fetchall()
        return [r for r in rows if r["total_seats"] > 0 and
                ((r["total_seats"] - r["available_seats"]) / r["total_seats"]) > 0.5]


class Staff:
    def __init__(self, row):
        self.civil_id = row["civil_id"]
        self.name     = row["name"]
        self.role     = row["role"]

    @staticmethod
    def authenticate(db, civil_id, password):
        row = db.q("SELECT * FROM staff WHERE civil_id=? AND password=?",
                   (civil_id, password)).fetchone()
        if row:
            return Staff(row)
        return None


class Security(Staff):
    def block_passenger(self, db, civil_id):
        db.run("INSERT OR IGNORE INTO blocked VALUES (?)", (civil_id,))
        db.run("DELETE FROM bookings WHERE civil_id=?", (civil_id,))

    def unblock_passenger(self, db, civil_id):
        db.run("DELETE FROM blocked WHERE civil_id=?", (civil_id,))


def label(parent, text, size=13, weight="normal", color=None, **kw):
    return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=size, weight=weight),
                        text_color=color or COLORS["text"], **kw)

def entry(parent, placeholder="", width=300, **kw):
    return ctk.CTkEntry(parent, placeholder_text=placeholder, width=width,
                        fg_color=COLORS["card"], border_color=COLORS["border"],
                        text_color=COLORS["text"], **kw)

def btn(parent, text, cmd, color=None, width=140, **kw):
    return ctk.CTkButton(parent, text=text, command=cmd, width=width,
                         fg_color=color or COLORS["accent2"],
                         hover_color="#2d7dd2",
                         text_color="#ffffff",
                         font=ctk.CTkFont(size=13, weight="bold"), **kw)

def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=COLORS["card"],
                        border_color=COLORS["border"], border_width=1,
                        corner_radius=10, **kw)

def section_title(parent, text):
    f = ctk.CTkFrame(parent, fg_color="transparent")
    label(f, text, size=18, weight="bold").pack(side="left")
    return f

def show_toast(root, msg, ok=True):
    t = ctk.CTkToplevel(root)
    t.overrideredirect(True)
    t.attributes("-topmost", True)
    color = COLORS["green"] if ok else COLORS["danger"]
    ctk.CTkFrame(t, fg_color=color, corner_radius=8,
                 width=320, height=50).pack()
    ctk.CTkLabel(t, text=msg, font=ctk.CTkFont(size=13, weight="bold"),
                 text_color="#fff").place(relx=0.5, rely=0.5, anchor="center")
    # centre on screen
    t.update_idletasks()
    sw, sh = t.winfo_screenwidth(), t.winfo_screenheight()
    t.geometry(f"320x50+{sw//2-160}+{sh-100}")
    t.after(2500, t.destroy)


class PassengerPortal(ctk.CTkFrame):
    def __init__(self, parent, db):
        super().__init__(parent, fg_color="transparent")
        self.db = db
        self.tabs = ctk.CTkTabview(self, fg_color=COLORS["card"],
                                   segmented_button_fg_color=COLORS["bg"],
                                   segmented_button_selected_color=COLORS["accent2"])
        self.tabs.pack(fill="both", expand=True, padx=20, pady=20)
        self._search_tab()
        self._bookings_tab()
        self._profile_tab()

    # ── Search & Book ──────────────────────────────────────────
    def _search_tab(self):
        tab = self.tabs.add("✈  Search & Book")
        tab.grid_columnconfigure(0, weight=1)

        info = card(tab)
        info.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 16))
        label(info, "Find & Book Your Flight", size=16, weight="bold").pack(anchor="w", padx=16, pady=(12,4))
        label(info, "Search available routes and book instantly with auto-generated PNR.",
              color=COLORS["muted"]).pack(anchor="w", padx=16, pady=(0,12))

        form = card(tab)
        form.grid(row=1, column=0, sticky="ew", padx=0, pady=(0,16))
        form.grid_columnconfigure((0,1,2,3), weight=1)

        label(form, "Origin City").grid(row=0, column=0, sticky="w", padx=16, pady=(14,4))
        label(form, "Destination City").grid(row=0, column=1, sticky="w", padx=8, pady=(14,4))
        label(form, "Your Civil ID").grid(row=0, column=2, sticky="w", padx=8, pady=(14,4))
        self.s_origin = entry(form, "e.g. Kuwait", width=160)
        self.s_dest   = entry(form, "e.g. Dubai",  width=160)
        self.s_civil  = entry(form, "12-digit ID",  width=140)
        self.s_origin.grid(row=1, column=0, padx=16, pady=(0,14))
        self.s_dest.grid(row=1, column=1, padx=8, pady=(0,14))
        self.s_civil.grid(row=1, column=2, padx=8, pady=(0,14))
        btn(form, "🔍  Search", self._do_search, width=120).grid(row=1, column=3, padx=16, pady=(0,14))

        # Results
        res = card(tab)
        res.grid(row=2, column=0, sticky="nsew", padx=0)
        tab.grid_rowconfigure(2, weight=1)
        label(res, "Available Flights", size=14, weight="bold").pack(anchor="w", padx=16, pady=(12,8))
        cols = ("Flight","From","To","Seats Left","Fare (KWD)")
        self.flight_tree = self._make_tree(res, cols)
        self.flight_tree.pack(fill="both", expand=True, padx=16, pady=(0,8))
        btn(res, "📋  Book Selected", self._open_book_dialog,
            color=COLORS["accent"], width=180).pack(pady=(0,14))

    def _make_tree(self, parent, cols):
        import tkinter.ttk as ttk
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("AMS.Treeview",
            background=COLORS["card"], foreground=COLORS["text"],
            fieldbackground=COLORS["card"], rowheight=32,
            borderwidth=0, relief="flat",
            font=("Courier New", 12))
        style.configure("AMS.Treeview.Heading",
            background=COLORS["bg"], foreground=COLORS["muted"],
            relief="flat", font=("Courier New", 11, "bold"))
        style.map("AMS.Treeview", background=[("selected", COLORS["accent2"])])

        tv = ttk.Treeview(parent, columns=cols, show="headings",
                          style="AMS.Treeview", selectmode="browse")
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=140, anchor="center")
        return tv

    def _do_search(self):
        for i in self.flight_tree.get_children():
            self.flight_tree.delete(i)
        origin = self.s_origin.get().strip()
        dest   = self.s_dest.get().strip()
        if not origin or not dest:
            show_toast(self.winfo_toplevel(), "Enter origin and destination", ok=False)
            return
        rows = Flight.search(self.db, origin, dest)
        if not rows:
            show_toast(self.winfo_toplevel(), "No flights found for that route", ok=False)
            return
        for r in rows:
            self.flight_tree.insert("", "end", iid=r["flight_number"],
                values=(r["flight_number"], r["origin"], r["destination"],
                        r["available_seats"], f"{r['fare']:.2f}"))
        show_toast(self.winfo_toplevel(), f"{len(rows)} flight(s) found")

    def _open_book_dialog(self):
        sel = self.flight_tree.selection()
        if not sel:
            show_toast(self.winfo_toplevel(), "Select a flight first", ok=False)
            return
        fnum = sel[0]
        row  = Flight.get(self.db, fnum)

        dlg = ctk.CTkToplevel(self.winfo_toplevel())
        dlg.title("Complete Booking")
        dlg.geometry("460x520")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(fg_color=COLORS["bg"])

        label(dlg, f"Book Flight {fnum}", size=18, weight="bold").pack(pady=(20,4))
        label(dlg, f"{row['origin']} → {row['destination']}  ·  KWD {row['fare']:.2f}",
              color=COLORS["muted"]).pack()

        frm = card(dlg)
        frm.pack(fill="x", padx=24, pady=16)

        fields = {}
        for lbl, ph, key in [
            ("Full Name",       "Passenger full name",  "name"),
            ("Civil ID",        "Civil ID",             "civil"),
            ("Age",             "Age",                  "age"),
            ("Address",         "Home address",         "addr"),
        ]:
            label(frm, lbl, color=COLORS["muted"], size=12).pack(anchor="w", padx=16, pady=(10,2))
            e = entry(frm, ph, width=400)
            e.pack(padx=16, pady=(0,2))
            # pre-fill civil id
            if key == "civil":
                e.insert(0, self.s_civil.get())
            fields[key] = e

        def confirm():
            try:
                name  = fields["name"].get().strip()
                civil = fields["civil"].get().strip()
                age   = int(fields["age"].get().strip())
                addr  = fields["addr"].get().strip()
                if not all([name, civil, addr]):
                    raise ValueError("All fields required")
                p = Passenger(civil, name, age, addr)
                pnr = p.book_flight(self.db, fnum, row["origin"], row["destination"])
                dlg.destroy()
                show_toast(self.winfo_toplevel(), f"✅  Booked! PNR: {pnr}")
            except Exception as ex:
                show_toast(self.winfo_toplevel(), str(ex), ok=False)

        btn(dlg, "✅  Confirm Booking", confirm,
            color=COLORS["accent"], width=400).pack(pady=12)
        btn(dlg, "Cancel", dlg.destroy, color=COLORS["danger"], width=400).pack()

    # ── My Bookings ────────────────────────────────────────────
    def _bookings_tab(self):
        tab = self.tabs.add("📋  My Bookings")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        srch = card(tab)
        srch.grid(row=0, column=0, sticky="ew", padx=0, pady=(0,12))
        srch.grid_columnconfigure(1, weight=1)
        label(srch, "Civil ID").grid(row=0, column=0, padx=16, pady=12, sticky="w")
        self.b_civil = entry(srch, "Enter your Civil ID", width=300)
        self.b_civil.grid(row=0, column=1, padx=8, pady=12, sticky="w")
        btn(srch, "🔍  Load Bookings", self._load_bookings, width=160).grid(row=0, column=2, padx=16, pady=12)

        res = card(tab)
        res.grid(row=1, column=0, sticky="nsew", padx=0)
        cols = ("PNR","Flight","From","To","Date Booked")
        self.book_tree = self._make_tree(res, cols)
        self.book_tree.pack(fill="both", expand=True, padx=16, pady=16)
        btn(res, "❌  Cancel Selected Booking", self._cancel_booking,
            color=COLORS["danger"], width=220).pack(pady=(0,14))

    def _load_bookings(self):
        for i in self.book_tree.get_children():
            self.book_tree.delete(i)
        civil = self.b_civil.get().strip()
        if not civil:
            return
        rows = self.db.q("SELECT * FROM bookings WHERE civil_id=?", (civil,)).fetchall()
        for r in rows:
            self.book_tree.insert("", "end", iid=r["pnr"],
                values=(r["pnr"], r["flight_number"], r["origin"],
                        r["destination"], r["booked_at"]))
        if not rows:
            show_toast(self.winfo_toplevel(), "No bookings found", ok=False)

    def _cancel_booking(self):
        sel = self.book_tree.selection()
        if not sel:
            show_toast(self.winfo_toplevel(), "Select a booking to cancel", ok=False)
            return
        pnr   = sel[0]
        civil = self.b_civil.get().strip()
        try:
            p = Passenger(civil, "", 0, "")
            p.cancel_booking(self.db, pnr)
            self._load_bookings()
            show_toast(self.winfo_toplevel(), f"Booking {pnr} cancelled")
        except Exception as e:
            show_toast(self.winfo_toplevel(), str(e), ok=False)

    # ── Profile / Check PNR ────────────────────────────────────
    def _profile_tab(self):
        tab = self.tabs.add("🔎  Check PNR")
        tab.grid_columnconfigure(0, weight=1)

        frm = card(tab)
        frm.grid(row=0, column=0, sticky="ew", padx=0, pady=(0,16))
        frm.grid_columnconfigure(1, weight=1)
        label(frm, "Booking Reference (PNR)").grid(row=0, column=0, padx=16, pady=12)
        self.pnr_entry = entry(frm, "6-char PNR e.g. AB1C2D", width=200)
        self.pnr_entry.grid(row=0, column=1, padx=8, pady=12, sticky="w")
        btn(frm, "🔍  Lookup", self._check_pnr, width=120).grid(row=0, column=2, padx=16, pady=12)

        self.pnr_result = card(tab)
        self.pnr_result.grid(row=1, column=0, sticky="ew", padx=0)

    def _check_pnr(self):
        for w in self.pnr_result.winfo_children():
            w.destroy()
        pnr = self.pnr_entry.get().strip().upper()
        row = self.db.q("SELECT * FROM bookings WHERE pnr=?", (pnr,)).fetchone()
        if not row:
            label(self.pnr_result, "❌  Booking not found", color=COLORS["danger"]).pack(pady=20)
            return
        data = [
            ("PNR",         row["pnr"]),
            ("Flight",      row["flight_number"]),
            ("Route",       f"{row['origin']} → {row['destination']}"),
            ("Passenger",   row["passenger_name"]),
            ("Civil ID",    row["civil_id"]),
            ("Age",         str(row["passenger_age"])),
            ("Address",     row["passenger_address"]),
            ("Booked",      row["booked_at"]),
        ]
        for k, v in data:
            r = ctk.CTkFrame(self.pnr_result, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=3)
            label(r, k, color=COLORS["muted"], size=12).pack(side="left", padx=(0,12))
            label(r, v, weight="bold").pack(side="left")


class SecurityPortal(ctk.CTkFrame):
    def __init__(self, parent, db):
        super().__init__(parent, fg_color="transparent")
        self.db       = db
        self.security = None
        self._login_screen()

    def _login_screen(self):
        for w in self.winfo_children():
            w.destroy()
        f = card(self, width=380, height=320)
        f.place(relx=0.5, rely=0.5, anchor="center")
        f.pack_propagate(False)
        label(f, "🔒  Security Login", size=20, weight="bold").pack(pady=(28,4))
        label(f, "Authorised personnel only", color=COLORS["muted"]).pack(pady=(0,20))
        label(f, "Civil ID", color=COLORS["muted"], size=12).pack(anchor="w", padx=30)
        self._lid = entry(f, "Enter Civil ID", width=320)
        self._lid.pack(padx=30, pady=(2,12))
        label(f, "Password", color=COLORS["muted"], size=12).pack(anchor="w", padx=30)
        self._lpw = entry(f, "Password", width=320, show="●")
        self._lpw.pack(padx=30, pady=(2,20))
        btn(f, "Authenticate →", self._login, color=COLORS["danger"], width=320).pack()

    def _login(self):
        staff = Staff.authenticate(self.db, self._lid.get(), self._lpw.get())
        if not staff or staff.role != "Security":
            show_toast(self.winfo_toplevel(), "Invalid credentials", ok=False)
            return
        self.security = Security(self.db.q(
            "SELECT * FROM staff WHERE civil_id=?", (staff.civil_id,)).fetchone())
        self._dashboard()

    def _dashboard(self):
        for w in self.winfo_children():
            w.destroy()
        tabs = ctk.CTkTabview(self, fg_color=COLORS["card"],
                              segmented_button_fg_color=COLORS["bg"],
                              segmented_button_selected_color=COLORS["danger"])
        tabs.pack(fill="both", expand=True, padx=20, pady=20)

        # Block tab
        bt = tabs.add("🚫  Block Passenger")
        bt.grid_columnconfigure(0, weight=1)
        frm = card(bt)
        frm.grid(row=0, column=0, sticky="ew", pady=(0,16))
        label(frm, "Block a Passenger by Civil ID", size=15, weight="bold").pack(anchor="w", padx=16, pady=(12,4))
        label(frm, "Removes all their bookings and prevents future reservations.",
              color=COLORS["muted"]).pack(anchor="w", padx=16, pady=(0,12))
        label(frm, "Civil ID to Block", color=COLORS["muted"], size=12).pack(anchor="w", padx=16)
        self._block_id = entry(frm, "Passenger Civil ID", width=360)
        self._block_id.pack(padx=16, pady=(4,0))
        row2 = ctk.CTkFrame(frm, fg_color="transparent")
        row2.pack(pady=14, padx=16, anchor="w")
        btn(row2, "🚫  Block", self._block, color=COLORS["danger"], width=140).pack(side="left", padx=(0,8))
        btn(row2, "✅  Unblock", self._unblock, color=COLORS["green"], width=140).pack(side="left")

        blocked_card = card(bt)
        blocked_card.grid(row=1, column=0, sticky="nsew")
        bt.grid_rowconfigure(1, weight=1)
        label(blocked_card, "Currently Blocked", size=14, weight="bold").pack(anchor="w", padx=16, pady=(12,8))
        import tkinter.ttk as ttk
        style = ttk.Style()
        style.configure("Sec.Treeview",
            background=COLORS["card"], foreground=COLORS["text"],
            fieldbackground=COLORS["card"], rowheight=30, borderwidth=0,
            font=("Courier New", 12))
        style.configure("Sec.Treeview.Heading",
            background=COLORS["bg"], foreground=COLORS["muted"], relief="flat",
            font=("Courier New", 11, "bold"))
        self.blocked_tree = ttk.Treeview(blocked_card, columns=("Civil ID",),
                                         show="headings", style="Sec.Treeview")
        self.blocked_tree.heading("Civil ID", text="Civil ID")
        self.blocked_tree.pack(fill="both", expand=True, padx=16, pady=(0,12))
        self._refresh_blocked()

        tabs.add("📋  All Bookings")
        at = tabs.tab("📋  All Bookings")
        import tkinter.ttk as ttk2
        self.all_tree = ttk2.Treeview(at,
            columns=("PNR","Flight","Name","Civil ID","Date"),
            show="headings", style="Sec.Treeview")
        for c in ("PNR","Flight","Name","Civil ID","Date"):
            self.all_tree.heading(c, text=c)
            self.all_tree.column(c, width=130, anchor="center")
        self.all_tree.pack(fill="both", expand=True, padx=10, pady=10)
        self._refresh_all_bookings()

    def _block(self):
        cid = self._block_id.get().strip()
        if not cid:
            return
        self.security.block_passenger(self.db, cid)
        self._block_id.delete(0, "end")
        self._refresh_blocked()
        self._refresh_all_bookings()
        show_toast(self.winfo_toplevel(), f"Passenger {cid} blocked")

    def _unblock(self):
        cid = self._block_id.get().strip()
        if not cid:
            return
        self.security.unblock_passenger(self.db, cid)
        self._refresh_blocked()
        show_toast(self.winfo_toplevel(), f"Passenger {cid} unblocked")

    def _refresh_blocked(self):
        for i in self.blocked_tree.get_children():
            self.blocked_tree.delete(i)
        for r in self.db.q("SELECT * FROM blocked").fetchall():
            self.blocked_tree.insert("", "end", values=(r["civil_id"],))

    def _refresh_all_bookings(self):
        for i in self.all_tree.get_children():
            self.all_tree.delete(i)
        for r in self.db.q("SELECT * FROM bookings ORDER BY booked_at DESC").fetchall():
            self.all_tree.insert("", "end",
                values=(r["pnr"], r["flight_number"], r["passenger_name"],
                        r["civil_id"], r["booked_at"]))


class FlightStaffPortal(ctk.CTkFrame):
    def __init__(self, parent, db):
        super().__init__(parent, fg_color="transparent")
        self.db    = db
        self.staff = None
        self._login_screen()

    def _login_screen(self):
        for w in self.winfo_children():
            w.destroy()
        f = card(self, width=380, height=320)
        f.place(relx=0.5, rely=0.5, anchor="center")
        f.pack_propagate(False)
        label(f, "👨‍✈️  Flight Staff Login", size=20, weight="bold").pack(pady=(28,4))
        label(f, "Authorised personnel only", color=COLORS["muted"]).pack(pady=(0,20))
        label(f, "Civil ID", color=COLORS["muted"], size=12).pack(anchor="w", padx=30)
        self._lid = entry(f, "Enter Civil ID", width=320)
        self._lid.pack(padx=30, pady=(2,12))
        label(f, "Password", color=COLORS["muted"], size=12).pack(anchor="w", padx=30)
        self._lpw = entry(f, "Password", width=320, show="●")
        self._lpw.pack(padx=30, pady=(2,20))
        btn(f, "Authenticate →", self._login, color=COLORS["accent2"], width=320).pack()

    def _login(self):
        staff = Staff.authenticate(self.db, self._lid.get(), self._lpw.get())
        if not staff or staff.role != "FlightStaff":
            show_toast(self.winfo_toplevel(), "Invalid credentials", ok=False)
            return
        self.staff = staff
        self._dashboard()

    def _dashboard(self):
        for w in self.winfo_children():
            w.destroy()
        tabs = ctk.CTkTabview(self, fg_color=COLORS["card"],
                              segmented_button_fg_color=COLORS["bg"],
                              segmented_button_selected_color=COLORS["accent2"])
        tabs.pack(fill="both", expand=True, padx=20, pady=20)
        self._flights_tab(tabs)
        self._report_tab(tabs)
        self._cancel_tab(tabs)

    def _flights_tab(self, tabs):
        import tkinter.ttk as ttk
        tab = tabs.add("✈  All Flights")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        hdr = card(tab)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0,12))
        label(hdr, "Live Flight Board", size=15, weight="bold").pack(side="left", padx=16, pady=12)
        btn(hdr, "🔄 Refresh", self._refresh_flights, width=110).pack(side="right", padx=16, pady=12)

        cols = ("Flight","From","To","Total","Available","Load %","Fare")
        self.all_flights = ttk.Treeview(tab, columns=cols, show="headings",
                                         style="AMS.Treeview", selectmode="browse")
        for c in cols:
            self.all_flights.heading(c, text=c)
            self.all_flights.column(c, width=110, anchor="center")
        self.all_flights.grid(row=1, column=0, sticky="nsew")
        self.all_flights.bind("<<TreeviewSelect>>", self._show_passengers)
        self._refresh_flights()

        pax = card(tab)
        pax.grid(row=2, column=0, sticky="ew", pady=(12,0))
        label(pax, "Passengers on Selected Flight", size=13, weight="bold").pack(anchor="w", padx=16, pady=(10,4))
        self.pax_tree = ttk.Treeview(pax, columns=("PNR","Name","Age","Address","Booked"),
                                     show="headings", style="AMS.Treeview", height=4)
        for c in ("PNR","Name","Age","Address","Booked"):
            self.pax_tree.heading(c, text=c)
            self.pax_tree.column(c, width=130, anchor="center")
        self.pax_tree.pack(fill="x", padx=16, pady=(0,12))

    def _refresh_flights(self):
        for i in self.all_flights.get_children():
            self.all_flights.delete(i)
        for r in Flight.all_flights(self.db):
            booked = r["total_seats"] - r["available_seats"]
            load   = (booked / r["total_seats"] * 100) if r["total_seats"] else 0
            self.all_flights.insert("", "end", iid=r["flight_number"],
                values=(r["flight_number"], r["origin"], r["destination"],
                        r["total_seats"], r["available_seats"],
                        f"{load:.0f}%", f"{r['fare']:.2f}"))

    def _show_passengers(self, _=None):
        for i in self.pax_tree.get_children():
            self.pax_tree.delete(i)
        sel = self.all_flights.selection()
        if not sel:
            return
        for r in Flight.passengers(self.db, sel[0]):
            self.pax_tree.insert("", "end",
                values=(r["pnr"], r["passenger_name"], r["passenger_age"],
                        r["passenger_address"], r["booked_at"]))

    def _report_tab(self, tabs):
        tab = tabs.add("📊  Load Report")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        info = card(tab)
        info.grid(row=0, column=0, sticky="ew", pady=(0,12))
        label(info, "High-Load Flights (>50% full)", size=15, weight="bold").pack(side="left", padx=16, pady=12)
        btn(info, "🔄 Run Report", self._run_report, width=130).pack(side="right", padx=16, pady=12)

        import tkinter.ttk as ttk
        self.report_tree = ttk.Treeview(tab,
            columns=("Flight","From","To","Total","Booked","Load %","Fare"),
            show="headings", style="AMS.Treeview")
        for c in ("Flight","From","To","Total","Booked","Load %","Fare"):
            self.report_tree.heading(c, text=c)
            self.report_tree.column(c, width=110, anchor="center")
        self.report_tree.grid(row=1, column=0, sticky="nsew")
        self._run_report()

    def _run_report(self):
        for i in self.report_tree.get_children():
            self.report_tree.delete(i)
        for r in Flight.load_report(self.db):
            booked = r["total_seats"] - r["available_seats"]
            load   = booked / r["total_seats"] * 100
            self.report_tree.insert("", "end",
                values=(r["flight_number"], r["origin"], r["destination"],
                        r["total_seats"], booked, f"{load:.0f}%", f"{r['fare']:.2f}"))

    def _cancel_tab(self, tabs):
        tab = tabs.add("❌  Cancel Flight")
        tab.grid_columnconfigure(0, weight=1)

        warn = card(tab)
        warn.grid(row=0, column=0, sticky="ew", pady=(0,20))
        label(warn, "⚠️  Cancel a Flight", size=16, weight="bold",
              color=COLORS["warning"]).pack(anchor="w", padx=16, pady=(12,4))
        label(warn, "This permanently removes the flight and all its bookings. This cannot be undone.",
              color=COLORS["muted"]).pack(anchor="w", padx=16, pady=(0,12))

        frm = card(tab)
        frm.grid(row=1, column=0, sticky="ew")
        label(frm, "Flight Number", color=COLORS["muted"], size=12).pack(anchor="w", padx=16, pady=(14,4))
        self._cf_num = entry(frm, "e.g. KU101", width=360)
        self._cf_num.pack(padx=16, pady=(0,14))
        btn(frm, "❌  Cancel Flight", self._cancel_flight,
            color=COLORS["danger"], width=200).pack(pady=(0,16))

    def _cancel_flight(self):
        fnum = self._cf_num.get().strip().upper()
        if not fnum:
            return
        Flight.cancel(self.db, fnum)
        self._cf_num.delete(0, "end")
        show_toast(self.winfo_toplevel(), f"Flight {fnum} cancelled and removed")
        self._refresh_flights()

class AeroManageApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AeroManage — Airport Management System")
        self.geometry("1200x780")
        self.minsize(1000, 680)
        self.configure(fg_color=COLORS["bg"])

        self.db = Database()
        self._build()

    def _build(self):
        # ── Sidebar ────────────────────────────────────────────
        sidebar = ctk.CTkFrame(self, fg_color=COLORS["card"],
                               border_color=COLORS["border"], border_width=1,
                               width=200, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Logo
        logo = ctk.CTkFrame(sidebar, fg_color="transparent", height=70)
        logo.pack(fill="x")
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="✈ AeroManage",
                     font=ctk.CTkFont(family="Courier New", size=16, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=20)

        ctk.CTkFrame(sidebar, fg_color=COLORS["border"], height=1).pack(fill="x", padx=16)

        # Nav buttons
        self.nav_buttons = {}
        nav_items = [
            ("🧳  Passenger", "passenger"),
            ("🔒  Security", "security"),
            ("👨‍✈️  Flight Staff", "staff"),
        ]
        nav_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", pady=16)
        for label_text, key in nav_items:
            b = ctk.CTkButton(nav_frame, text=label_text, anchor="w",
                              fg_color="transparent", hover_color=COLORS["bg"],
                              text_color=COLORS["muted"],
                              font=ctk.CTkFont(size=13),
                              height=42, corner_radius=8,
                              command=lambda k=key: self._switch(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = b

        ctk.CTkFrame(sidebar, fg_color=COLORS["border"], height=1).pack(fill="x", padx=16, side="bottom", pady=16)
        ctk.CTkLabel(sidebar, text="Lolwah Thamer\nAirport Management System",
                     font=ctk.CTkFont(size=10), text_color=COLORS["muted"],
                     justify="center").pack(side="bottom", pady=12)

        # ── Content area ───────────────────────────────────────
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(side="left", fill="both", expand=True)

        # Page header
        self.header = ctk.CTkFrame(self.content, fg_color=COLORS["card"],
                                   border_color=COLORS["border"], border_width=1,
                                   height=60, corner_radius=0)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        self.page_title = ctk.CTkLabel(self.header, text="Passenger Portal",
                                       font=ctk.CTkFont(size=18, weight="bold"),
                                       text_color=COLORS["text"])
        self.page_title.pack(side="left", padx=24, pady=12)
        self.page_sub = ctk.CTkLabel(self.header, text="Search, book and manage your flights",
                                     font=ctk.CTkFont(size=12),
                                     text_color=COLORS["muted"])
        self.page_sub.pack(side="left", padx=0, pady=12)

        # Pages
        self.pages = {
            "passenger": PassengerPortal(self.content, self.db),
            "security": SecurityPortal(self.content, self.db),
            "staff": FlightStaffPortal(self.content, self.db),
        }
        for p in self.pages.values():
            p.place(relx=0, rely=0, relwidth=1, relheight=1)
            p.lower()

        self._switch("passenger")

    def _switch(self, key):
        titles = {
            "passenger": ("Passenger Portal", "Search, book and manage your flights"),
            "security": ("Security Portal", "Monitor passengers and manage access"),
            "staff": ("Flight Staff Portal", "Manage flights, reports and operations"),
        }
        t, s = titles[key]
        self.page_title.configure(text=t)
        self.page_sub.configure(text=s)

        for k, b in self.nav_buttons.items():
            if k == key:
                b.configure(fg_color=COLORS["bg"], text_color=COLORS["text"])
            else:
                b.configure(fg_color="transparent", text_color=COLORS["muted"])

        for k, p in self.pages.items():
            if k == key:
                p.lift()
            else:
                p.lower()


if __name__ == "__main__":
    app = AeroManageApp()
    app.mainloop()