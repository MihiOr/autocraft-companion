"""Personal AutoCraft companion. Run with pythonw app.py (or Start Companion.vbs)."""
import copy
from datetime import datetime
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

from patcher import patch_zip, install_zip, validate_settings
from site_client import Client, SiteError, garage_download, needs_submission
from storage import ROOT, load_settings, save_settings
from creator_watchdog import CreatorWatchdog, creator_running
from dashboard_bridge import DashboardBridge, DUMMY, ports


class Companion(tk.Tk):
    def __init__(self):
        from windows_identity import process_identity, configure_window
        process_identity()
        super().__init__()
        self.title('AutoCraft · Companion — Lua motor control')
        configure_window(self)
        self.settings = load_settings()
        self.settings.setdefault('dashboard_port', DUMMY)
        self.settings.setdefault('dashboard_baud', '921600')
        self.dashboard_bridge = DashboardBridge()
        self.settings['ev_ecu_mode'] = 'Custom Lua'
        self.settings['ev_regen'] = '0'
        self.settings.setdefault('restart_creator', True)
        self.settings.setdefault('latch_patch_enabled', True)
        self.settings.setdefault('spawn_heading_enabled', True)
        self.settings.setdefault('steering_response_enabled', True)
        self.settings.setdefault('steering_hydro_rate', '20')
        for key,value in {'ev_ratio_enabled':True,'ev_original_ratio':'5.4','ev_ratio':'4.3','ev_reference_speed':'130'}.items():
            self.settings.setdefault(key,value)
        self.settings.setdefault('suspension_enabled', True)
        self.settings['suspension_absolute'] = True
        self.settings.setdefault('front_length', '')
        self.settings.setdefault('rear_length', '')
        for axle in ('front', 'rear'):
            for field in ('length', 'rate', 'damping'):
                self.settings.setdefault(axle + '_' + field + '_multiplier', '1')
        self.settings.setdefault('export_version_label', True)
        self.settings.pop('orientation_enabled', None)
        self.settings.pop('steering_stops_enabled', None)
        self.settings.pop('steering_stop_angle', None)
        for key in ('ball_joints_enabled', 'ball_joint_front_angle', 'ball_joint_rear_angle'):
            self.settings.pop(key, None)
        self.settings.setdefault('kingpin_stops_enabled', True)
        self.settings.setdefault('kingpin_front_angle', '45')
        self.settings.setdefault('kingpin_rear_angle', '45')
        for key, value in {'electric_enabled': True, 'ev_csv': str(ROOT / 'one_wheel_realistic_overdrive_dyno.csv'),
                           'ev_curve_mode': 'Wheel output (direct drive)', 'ev_capacity': '100',
                           'ev_battery_mass': '500', 'ev_motor_mass': '35', 'ev_inertia': '0.1', 'ev_regen': '15',
                           'ev_weight_enabled': True, 'ev_base_mass': '450', 'ev_passenger_left': '80', 'ev_passenger_right': '80',
                           'ev_tire_enabled': True, 'ev_tire_grip': '1.4', 'ev_ecu_mode': 'Launch + traction control',
                           'ev_tc_slip': '8', 'ev_launch_slip': '8', 'ev_launch_ramp': '0.4',
                           'ev_sound_enabled': True, 'ev_sound_gain': '-9', 'ev_sound_pitch': '6.7'}.items():
            self.settings.setdefault(key, value)
        self.creator_watchdog = CreatorWatchdog()
        self.geometry(self.settings.get('geometry', '780x940'))
        self.minsize(740, 900)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.closing = False
        self.save_timer = None
        self.vars = {}
        self.buttons = []
        self.status = tk.StringVar(value='Ready — choose a VCL or resume the saved order.')
        self.saved = tk.StringVar(value='Settings saved locally')
        self.beamng_status = tk.StringVar(value=self.dashboard_bridge.beamng_status)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton', padding=7)
        style.configure('TNotebook.Tab', padding=(16, 9))
        style.configure('Title.TLabel', font=('Segoe UI', 20, 'bold'))
        style.configure('TLabel', font=('Segoe UI', 10))
        style.configure('BeamNG.TLabel', font=('Segoe UI', 10, 'bold'), foreground='#666666')
        style.configure('TCheckbutton', font=('Segoe UI', 10))
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='AutoCraft Companion', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Your export, with your settings.').pack(anchor='w', pady=(3, 15))
        ttk.Label(outer, textvariable=self.beamng_status, style='BeamNG.TLabel').pack(anchor='w', pady=(0, 12))
        tabs = ttk.Notebook(outer)
        tabs.pack(fill='both', expand=True)
        export = ttk.Frame(tabs, padding=16)
        overrides = ttk.Frame(tabs, padding=16)
        settings = ttk.Frame(tabs, padding=16)
        orders_tab = ttk.Frame(tabs, padding=16)
        dashboard = ttk.Frame(tabs, padding=16)
        tabs.add(export, text='Export & install')
        tabs.add(overrides, text='Overrides')
        tabs.add(dashboard, text='Dashboard')
        tabs.add(orders_tab, text='Orders')
        tabs.add(settings, text='Settings')
        self.build_dashboard(dashboard)
        override_tabs = ttk.Notebook(overrides)
        override_tabs.pack(fill='both', expand=True)
        suspension = self.override_page(override_tabs, 'Suspension')
        electric = self.override_page(override_tabs, 'Electric/Mass')
        ecu = self.override_page(override_tabs, 'ECU')
        misc = self.override_page(override_tabs, 'Misc')
        sounds = self.override_page(override_tabs, 'Sounds')
        electric.columnconfigure(1, weight=1)
        ttk.Checkbutton(electric, text='Replace combustion drivetrain with four electric motors', variable=self.var('electric_enabled', True)).grid(row=0, column=0, columnspan=3, sticky='w', pady=8)
        self.path_row(electric, 1, 'Motor dyno CSV', 'ev_csv', self.pick_ev_csv)
        self.note(electric, 2, 'One motor per wheel. CSV wheel RPM and torque are used directly at 1:1; no gearbox or differential. Shaft lengths are calculated from suspension geometry. Motor RPM is informational for this build.')
        for row, label, key in [(3, 'Battery capacity (kWh)', 'ev_capacity'), (4, 'Battery mass (kg)', 'ev_battery_mass'),
                                (5, 'Mass per motor (kg)', 'ev_motor_mass'), (6, 'Motor inertia (kg·m²)', 'ev_inertia'),
                                ]:
            ttk.Label(electric, text=label).grid(row=row, column=0, sticky='w', pady=6)
            ttk.Entry(electric, textvariable=self.var(key), width=16).grid(row=row, column=1, sticky='w', padx=8)
        ttk.Checkbutton(electric, text='Apply vehicle and passenger weight patch', variable=self.var('ev_weight_enabled', True)).grid(row=8, column=0, columnspan=3, sticky='w', pady=8)
        for row, label, key in [(9, 'Base vehicle mass, including motors (kg)', 'ev_base_mass'),
                                (10, 'Left passenger (kg; 0 = absent)', 'ev_passenger_left'),
                                (11, 'Right passenger (kg; 0 = absent)', 'ev_passenger_right')]:
            ttk.Label(electric, text=label).grid(row=row, column=0, sticky='w', pady=6)
            ttk.Entry(electric, textvariable=self.var(key), width=16).grid(row=row, column=1, sticky='w', padx=8)
        self.weight_estimate = tk.StringVar(value=self.settings.get('last_weight_estimate', 'Total weight estimate will appear after patching.'))
        ttk.Label(electric, textvariable=self.weight_estimate, wraplength=600, font=('Segoe UI', 10, 'bold')).grid(row=12, column=0, columnspan=3, sticky='w', pady=10)
        self.note(electric, 13, 'Base mass combines sprung and unsprung mass, excluding battery and passengers. Motor mass is included, not added twice. When reducing mass, stiffness and damping also decrease for solver stability. Brakes stay unchanged. Test handling in-game. Passengers add mass without a visible character model.')
        ttk.Checkbutton(electric,text='Gearbox ratio override (simulated in motor curve)',variable=self.var('ev_ratio_enabled',True)).grid(row=14,column=0,columnspan=3,sticky='w',pady=10)
        for row,label,key in [(15,'Original CSV ratio (:1)','ev_original_ratio'),(16,'New ratio (:1)','ev_ratio'),(17,'Original top speed reference (km/h)','ev_reference_speed')]:
            ttk.Label(electric,text=label).grid(row=row,column=0,sticky='w',pady=6)
            ttk.Entry(electric,textvariable=self.var(key),width=16).grid(row=row,column=1,sticky='w',padx=8)
        self.ratio_preview=tk.StringVar()
        ttk.Label(electric,textvariable=self.ratio_preview,wraplength=600).grid(row=18,column=0,columnspan=3,sticky='w',pady=8)
        for key in ('ev_ratio_enabled','ev_original_ratio','ev_ratio','ev_reference_speed'):
            self.vars[key].trace_add('write',self.update_ratio_preview)
        self.update_ratio_preview()
        self.note(electric,19,'Scales torque and RPM inversely from the original CSV on every patch. Power values are preserved, but their RPM positions move. Speed is a gearing-only estimate, not a guaranteed road speed or a speed limiter. No physical gearbox is added. Comma decimals are accepted.')
        ttk.Checkbutton(misc, text='Performance tire grip patch', variable=self.var('ev_tire_enabled', True)).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(misc, text='Tire grip multiplier (not guaranteed g)').grid(row=1, column=0, sticky='w', pady=6)
        ttk.Entry(misc, textvariable=self.var('ev_tire_grip'), width=16).grid(row=1, column=1, sticky='w', padx=8)
        ttk.Label(ecu, text='Motor control: custom_motor_control.lua').grid(row=0, column=0, columnspan=3, sticky='w', pady=6)
        ttk.Button(ecu,text='Edit custom Lua',command=self.edit_custom_lua).grid(row=4,column=0,sticky='w',pady=8)
        ttk.Button(ecu,text='Check Lua code',command=self.check_custom_lua).grid(row=4,column=1,sticky='w',pady=8)
        self.note(ecu,5,'Your Lua is the only motor-control policy on every EV export/reapply/install. Edit custom_motor_control.lua, save, then check code. Return FL/FR/RL/RR from -1 to +1 (0 = coast). No separate traction control, launch ramp or automatic regen. Motor curves, battery and damage still apply. Runtime errors disable all motor commands until reset.')
        ttk.Checkbutton(sounds, text='EV motor whine (legacy engine sound disabled)', variable=self.var('ev_sound_enabled', True)).grid(row=0,column=0,columnspan=3,sticky='w',pady=10)
        for row,label,key in [(1,'EV volume per motor (dB)','ev_sound_gain'),(2,'EV audio RPM multiplier','ev_sound_pitch')]:
            ttk.Label(sounds,text=label).grid(row=row,column=0,sticky='w',pady=6)
            ttk.Entry(sounds,textvariable=self.var(key),width=16).grid(row=row,column=1,sticky='w',padx=8)
        self.note(sounds,3,'Built-in ElectricMotor_02 with a sharper whine. Volume starts at -9 dB per motor; lower is quieter. Pitch scaling changes audio only. Uncheck for silent motors, with no combustion fallback.')
        self.order_rows = {}
        self.orders_loaded = False
        orders_toolbar = ttk.Frame(orders_tab)
        orders_toolbar.pack(fill='x', pady=(0, 10))
        self.job_button(orders_toolbar, 'Refresh orders', lambda: self.start('orders')).pack(side='left')
        self.job_button(orders_toolbar, 'Delete selected order…', self.delete_selected_order).pack(side='right')
        ttk.Label(orders_tab, text='Select an order to delete it from Delta Cross. Local downloads, backups and installed mods are kept.',
                  wraplength=620).pack(anchor='w', pady=(0, 12))
        order_list = ttk.Frame(orders_tab)
        order_list.pack(fill='both', expand=True)
        self.order_tree = ttk.Treeview(order_list, columns=('id', 'name', 'status', 'action'), show='headings', selectmode='browse')
        for col, label, width in [('id', 'Order', 70), ('name', 'File name', 230), ('status', 'Status', 110), ('action', 'Website action', 140)]:
            self.order_tree.heading(col, text=label)
            self.order_tree.column(col, width=width, minwidth=60, stretch=col == 'name')
        order_scroll = ttk.Scrollbar(order_list, orient='vertical', command=self.order_tree.yview)
        self.order_tree.configure(yscrollcommand=order_scroll.set)
        order_scroll.pack(side='right', fill='y')
        self.order_tree.pack(side='left', fill='both', expand=True)
        self.order_count = tk.StringVar(value='Open this tab to load your orders.')
        ttk.Label(orders_tab, textvariable=self.order_count).pack(anchor='w', pady=10)
        tabs.bind('<<NotebookTabChanged>>', lambda event: self.load_orders_tab(tabs, orders_tab))
        for frame in (export, settings):
            frame.columnconfigure(1, weight=1)
        suspension.columnconfigure(1, weight=1, uniform='axles')
        suspension.columnconfigure(2, weight=1, uniform='axles')
        self.path_row(export, 0, 'Vehicle project (.vcl)', 'vcl', self.pick_vcl)
        self.note(export, 1, 'One click uploads your saved project, submits the conversion, follows its order, downloads the ZIP, applies overrides and installs it in BeamNG.')
        actions = ttk.Frame(export)
        actions.grid(row=2, column=0, columnspan=3, sticky='ew', pady=12)
        self.job_button(actions, 'Convert & install', lambda: self.start('new')).pack(side='left', padx=(0, 8))
        self.job_button(actions, 'Resume saved order', lambda: self.start('resume')).pack(side='left')
        order_row = ttk.Frame(export)
        order_row.grid(row=3, column=0, columnspan=3, sticky='ew', pady=6)
        order_row.columnconfigure(0, weight=1)
        self.pending_label = ttk.Label(order_row, text=self.pending_text(), wraplength=400)
        self.pending_label.grid(row=0, column=0, sticky='w')
        self.job_button(order_row, 'Remove saved order', self.remove_order).grid(row=0, column=1, padx=(10, 0))
        ttk.Separator(export).grid(row=4, column=0, columnspan=3, sticky='ew', pady=15)
        self.job_button(export, 'Reapply settings to last download', lambda: self.start('reapply')).grid(row=5, column=0, columnspan=3, sticky='ew')
        self.job_button(export, 'Patch & install an existing ZIP…', self.pick_zip).grid(row=6, column=0, columnspan=3, sticky='ew', pady=8)
        self.note(export, 7, 'Existing mods are kept. Repeat installs use _01, _02, etc. on the ZIP and car name, continuing above existing numbers. Each copy keeps a separate random vehicle ID.')
        links = ttk.Frame(export)
        links.grid(row=8, column=0, columnspan=3, sticky='w', pady=8)
        ttk.Button(links, text='Open AutoCraft', command=self.open_creator).pack(side='left')
        ttk.Button(links, text='Open mods', command=lambda: self.open_folder(self.vars['mods'].get())).pack(side='left', padx=8)
        ttk.Button(links, text='Open backups', command=lambda: self.open_folder(ROOT / 'backups')).pack(side='left')
        ttk.Checkbutton(suspension, text='Springs and Shocks override', variable=self.var('suspension_enabled', True)).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(suspension, text='Front').grid(row=1, column=1, sticky='w')
        ttk.Label(suspension, text='Rear').grid(row=1, column=2, sticky='w')
        for row, label, suffix in [(2, 'Spring rest length (mm)', 'length'),
                                   (3, 'Spring stiffness (N/m)', 'rate'),
                                   (4, 'Bump damping (Ns/m)', 'damping')]:
            ttk.Label(suspension, text=label).grid(row=row, column=0, sticky='w', pady=8)
            for col, axle in [(1, 'front'), (2, 'rear')]:
                cell = ttk.Frame(suspension)
                cell.grid(row=row, column=col, sticky='ew', padx=7)
                cell.columnconfigure(0, weight=1)
                ttk.Entry(cell, textvariable=self.var(axle + '_' + suffix), width=10).grid(row=0, column=0, sticky='ew')
                ttk.Label(cell, text='×').grid(row=0, column=1, padx=3)
                ttk.Entry(cell, textvariable=self.var(axle + '_' + suffix + '_multiplier'), width=5).grid(row=0, column=2)
        self.note(suspension, 5, 'Value × multiplier is applied after the mass patch. ×1 keeps the value, ×1.1 adds 10%, ×0.9 reduces it 10%. Copying replaces values and keeps your multipliers. Blank keeps the resulting value. Length is spring rest length, not ride height; bump leaves rebound unchanged.')
        ttk.Separator(suspension).grid(row=6, column=0, columnspan=3, sticky='ew', pady=10)
        ttk.Button(suspension, text='Read suspension from a vehicle ZIP...', command=self.read_suspension_zip).grid(row=7, column=0, columnspan=3, sticky='ew')
        self.suspension_source = tk.StringVar(value='Choose a ZIP from your mods folder. Reading does not change overrides.')
        ttk.Label(suspension, textvariable=self.suspension_source, wraplength=580).grid(row=8, column=0, columnspan=3, sticky='w', pady=8)
        self.suspension_readings = {}
        self.suspension_read_values = None
        for col, label in ((1, 'Front average'), (2, 'Rear average')):
            ttk.Label(suspension, text=label).grid(row=9,column=col)
        for row,label,key in ((10,'Spring rest length (mm)','length'),(11,'Spring stiffness (N/m)','rate'),(12,'Bump damping (Ns/m)','damping')):
            ttk.Label(suspension,text=label).grid(row=row,column=0,sticky='w',pady=5)
            for col,axle in ((1,'front'),(2,'rear')):
                variable=tk.StringVar(value='')
                self.suspension_readings[axle+'_'+key]=variable
                ttk.Entry(suspension,textvariable=variable,state='readonly',width=16).grid(row=row,column=col,sticky='ew',padx=7)
        self.copy_suspension_button = ttk.Button(suspension,text='Copy all values',command=self.copy_suspension_values,state='disabled')
        self.copy_suspension_button.grid(row=13,column=0,columnspan=3,sticky='ew',pady=8)
        self.note(suspension,14,'Readouts use the actual ZIP contents and default configuration variables, including previous mass scaling. Each average combines the two springs or dampers on that axle. Select text and Ctrl+C to copy one value. Supported layout: AutoCraft coils and dampers; unsupported ZIPs show an error instead of guessed values.')
        ttk.Separator(suspension).grid(row=15, column=0, columnspan=3, sticky='ew', pady=10)
        ttk.Checkbutton(suspension, text='Kingpin rotation stops (front + rear)', variable=self.var('kingpin_stops_enabled', True)).grid(row=16, column=0, columnspan=3, sticky='w', pady=10)
        ttk.Label(suspension, text='Kingpin rotation each way (5-45 degrees)').grid(row=17, column=0, sticky='w')
        for col, axle in ((1, 'front'), (2, 'rear')):
            ttk.Entry(suspension, textvariable=self.var('kingpin_'+axle+'_angle'), width=14).grid(row=17, column=col, sticky='ew', padx=7)
        self.note(suspension, 18, 'Front / rear fields follow the columns above. Default +/-45 degrees about the line between the upper and lower ball joints. No collisions added. Passive stops are calibrated at the exported pose; suspension travel and beam flex affect actual engagement. Test full lock and bumps.')
        ttk.Checkbutton(suspension,text='Faster steering response',variable=self.var('steering_response_enabled',True)).grid(row=19,column=0,columnspan=3,sticky='w',pady=10)
        ttk.Label(suspension,text='Steering hydro rate (1–200)').grid(row=20,column=0,sticky='w')
        ttk.Entry(suspension,textvariable=self.var('steering_hydro_rate'),width=16).grid(row=20,column=1,sticky='w',padx=8)
        self.note(suspension,21,'Sets steering contraction, extension and centering rates. Exported default is 2; 20 moves the actuator target ten times faster. Direct mouse input does not bypass this limit. Angles and stiffness stay unchanged; actual tire movement also depends on suspension physics.')
        ttk.Checkbutton(misc, text='Clear glass · reduce tint and reflections', variable=self.var('clear_glass', True)).grid(row=3, column=0, columnspan=3, sticky='w')
        ttk.Label(misc, text='Glass opacity (0.01–0.40)').grid(row=4, column=0, sticky='w', pady=8)
        ttk.Entry(misc, textvariable=self.var('glass_opacity'), width=14).grid(row=4, column=1, sticky='w', padx=7)
        self.note(misc, 5, 'Clear glass removes metallic/cubemap reflections and uses the opacity above. Its final appearance still needs an in-game check.')
        self.path_row(settings, 0, 'BeamNG mods folder', 'mods', self.pick_mods)
        ttk.Checkbutton(misc, text='Latch stability patch', variable=self.var('latch_patch_enabled', True)).grid(row=6, column=0, columnspan=3, sticky='w', pady=10)
        self.note(misc, 7, 'Keeps latch/unlatch interaction but removes force assist when the latch and catch overlap. Fixes the latch sound node. Panels may need gravity or the node grabber to swing open.')
        ttk.Checkbutton(misc,text='Spawn 90° right (placement only)',variable=self.var('spawn_heading_enabled',True)).grid(row=8,column=0,columnspan=3,sticky='w',pady=10)
        self.note(misc,9,'Changes spawn placement only, without rotating nodes or meshes. Installs the CompanionSpawnHeading helper mod; restart BeamNG after its first installation. Does not correct internal vehicle axes or rotate the currently loaded car.')
        ttk.Label(settings, text='Delta Cross email').grid(row=1, column=0, sticky='w', pady=10)
        ttk.Entry(settings, textvariable=self.var('email')).grid(row=1, column=1, columnspan=2, sticky='ew')
        ttk.Label(settings, text='Password').grid(row=2, column=0, sticky='w', pady=10)
        ttk.Entry(settings, textvariable=self.var('password'), show='•').grid(row=2, column=1, columnspan=2, sticky='ew')
        self.note(settings, 3, 'Account and overrides are saved locally in settings.json. Credentials are sent only to Delta Cross over HTTPS and are not written to the activity log.')
        self.job_button(settings, 'Test login', lambda: self.start('login')).grid(row=4, column=0, sticky='w', pady=10)
        ttk.Checkbutton(settings, text='Keep this window on top', variable=self.var('topmost', True), command=self.pin).grid(row=5, column=0, columnspan=3, sticky='w', pady=8)
        ttk.Checkbutton(settings, text='Open AutoCraft through Steam when companion starts', variable=self.var('launch_creator', True)).grid(row=6, column=0, columnspan=3, sticky='w', pady=8)
        ttk.Checkbutton(settings, text='Restart AutoCraft if it closes while Companion is open', variable=self.var('restart_creator', True)).grid(row=7, column=0, columnspan=3, sticky='w', pady=8)
        self.note(settings, 8, 'Restart monitoring also treats a normal AutoCraft close as a crash. Close Companion first or turn this option off to keep AutoCraft closed. Settings save automatically.')
        ttk.Label(outer, textvariable=self.status, wraplength=660).pack(anchor='w', pady=(12, 5))
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x')
        self.log = tk.Text(outer, height=6, wrap='word', font=('Consolas', 9), state='disabled')
        self.log.pack(fill='x', pady=8)
        foot = ttk.Frame(outer)
        foot.pack(fill='x')
        ttk.Label(foot, textvariable=self.saved).pack(side='left')
        ttk.Button(foot, text='Stop waiting', command=self.cancel.set).pack(side='right')
        self.pin()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.pump)
        self.after(2000, self.watch_creator)
        if self.settings.get('launch_creator'):
            self.after(500, self.open_creator)

    def read_suspension_zip(self):
        path = filedialog.askopenfilename(title='Read suspension from ZIP', initialdir=self.vars['mods'].get(), filetypes=[('BeamNG ZIP','*.zip')])
        if not path:
            return
        self.suspension_read_values = None
        self.copy_suspension_button.configure(state='disabled')
        for variable in self.suspension_readings.values():
            variable.set('')
        try:
            from suspension_values import read_zip
            readings, details = read_zip(path)
            self.suspension_read_values = readings
            for key,value in readings.items():
                self.suspension_readings[key].set(f'{value:.10g}')
            self.suspension_source.set(Path(path).name + ' | default configuration | averages of two per axle')
            self.copy_suspension_button.configure(state='normal')
        except Exception as error:
            self.suspension_source.set('Could not read ' + Path(path).name)
            messagebox.showerror('Read suspension',str(error),parent=self)

    def copy_suspension_values(self):
        if self.suspension_read_values is None:
            return
        for key,value in self.suspension_read_values.items():
            self.vars[key].set(f'{value:.10g}')
        self.status.set('Copied all six suspension values. Use the checkbox to enable or disable them.')

    def override_page(self, notebook, title):
        page = ttk.Frame(notebook)
        notebook.add(page, text=title)
        canvas = tk.Canvas(page, highlightthickness=0)
        scrollbar = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas, padding=12)
        window = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        content.columnconfigure(1, weight=1)
        return content

    def var(self, name, boolean=False):
        if name not in self.vars:
            cls = tk.BooleanVar if boolean else tk.StringVar
            self.vars[name] = cls(value=self.settings.get(name, False if boolean else ''))
            self.vars[name].trace_add('write', self.schedule_save)
        return self.vars[name]

    def note(self, frame, row, text):
        ttk.Label(frame, text=text, wraplength=610, foreground='#4c5666').grid(row=row, column=0, columnspan=3, sticky='ew', pady=8)

    def path_row(self, frame, row, label, key, command):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=10)
        ttk.Entry(frame, textvariable=self.var(key)).grid(row=row, column=1, sticky='ew')
        ttk.Button(frame, text='Browse…', command=command).grid(row=row, column=2, padx=(8, 0))

    def job_button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.buttons.append(button)
        return button

    def pick_vcl(self):
        path = filedialog.askopenfilename(filetypes=[('AutoCraft project', '*.vcl')], initialdir=str(Path(self.vars['vcl'].get()).parent))
        if path:
            self.vars['vcl'].set(path)

    def pick_mods(self):
        path = filedialog.askdirectory(initialdir=self.vars['mods'].get())
        if path:
            self.vars['mods'].set(path)

    def pick_zip(self):
        path = filedialog.askopenfilename(filetypes=[('BeamNG ZIP', '*.zip')])
        if path:
            self.start('zip', path)

    def pick_ev_csv(self):
        path = filedialog.askopenfilename(filetypes=[('Dyno CSV', '*.csv')])
        if path:
            self.vars['ev_csv'].set(path)

    def pin(self):
        self.attributes('-topmost', bool(self.vars['topmost'].get()))

    def open_creator(self):
        if self.closing:
            return
        try:
            if creator_running():
                return
        except Exception:
            self.emit('Could not check whether AutoCraft is running. Try Open AutoCraft again.')
            return
        webbrowser.open('steam://rungameid/3800400')
        self.creator_watchdog.launched(time.monotonic())

    def watch_creator(self):
        if self.closing:
            return
        try:
            if self.creator_watchdog.poll(creator_running(), self.vars['restart_creator'].get(), time.monotonic()):
                self.emit('AutoCraft closed. Restarting it through Steam…')
                self.open_creator()
        except Exception:
            # A failed process query is not evidence that AutoCraft exited.
            self.creator_watchdog.missing = 0
        finally:
            if not self.closing:
                self.after(2000, self.watch_creator)

    def open_folder(self, path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def schedule_save(self, *_):
        if self.save_timer:
            self.after_cancel(self.save_timer)
        self.saved.set('Saving…')
        self.save_timer = self.after(350, self.save)

    def save(self):
        self.save_timer = None
        self.settings.update({k: v.get() for k, v in self.vars.items()})
        self.settings['geometry'] = self.geometry()
        try:
            save_settings(self.settings)
            self.saved.set('Settings saved locally')
        except OSError as exc:
            self.saved.set('Could not save settings: ' + str(exc))
            raise

    def pending_text(self):
        p = self.settings.get('pending')
        return f"Saved order #{p['id']} · {p['name']} · {p['state']}" if p else 'No saved order.'

    def load_orders_tab(self, tabs, orders_tab):
        if tabs.select() == str(orders_tab) and not self.orders_loaded:
            self.start('orders')

    def show_orders(self, rows):
        selected = self.order_tree.selection()
        self.order_rows = rows
        children = self.order_tree.get_children()
        if children:
            self.order_tree.delete(*children)
        for order_id, row in rows.items():
            self.order_tree.insert('', 'end', iid=order_id,
                                   values=(order_id, row['name'], row['status'], row['delete_label']))
        if selected and selected[0] in rows:
            self.order_tree.selection_set(selected[0])
        self.orders_loaded = True
        self.order_count.set(f'{len(rows)} website order(s) · refreshed {datetime.now():%H:%M:%S}')

    def delete_selected_order(self):
        if self.worker and self.worker.is_alive():
            return
        selected = self.order_tree.selection()
        row = self.order_rows.get(selected[0]) if selected else None
        if not row:
            messagebox.showinfo('Select an order', 'Select a row in Orders first.', parent=self)
            return
        if not row.get('delete_url'):
            messagebox.showinfo('Deletion unavailable', 'The website does not offer deletion for this order right now. Refresh to check again.', parent=self)
            return
        if messagebox.askyesno('Delete website order?',
                f"Delete order #{row['id']} — {row['name']} from Delta Cross?\n\n"
                'This can remove its downloadable mod from your online Garage. Download a copy first if needed. '
                'Your local files and installed mod will be kept.', parent=self):
            self.start('delete_order', dict(row))

    def remove_order(self):
        if self.worker and self.worker.is_alive():
            self.status.set('Stop waiting first, then remove the saved order.')
            return
        old = self.settings.pop('pending', None)
        try:
            self.save()
        except OSError as exc:
            if old is not None:
                self.settings['pending'] = old
            messagebox.showerror('Could not remove saved order', str(exc), parent=self)
            return
        self.pending_label.configure(text=self.pending_text())
        self.status.set('Saved order removed. You can start a new conversion. Downloads and overrides are kept.')

    def emit(self, text):
        self.events.put(('log', text))

    def persist(self, values):
        ack = threading.Event()
        self.events.put(('persist', (values, ack)))
        if not ack.wait(10):
            raise RuntimeError('Could not save job progress. Resume the saved order on reopening.')

    def update_ratio_preview(self, *_):
        from electric_patch import ratio_settings
        try:
            options=ratio_settings({key:self.vars[key].get() for key in ('ev_ratio_enabled','ev_original_ratio','ev_ratio','ev_reference_speed')})
            self.ratio_preview.set(f"Torque ×{options['torque_scale']:.4f} · RPM/speed ×{options['rpm_scale']:.4f}\nEstimated top speed: {options['estimated_speed_kmh']:.1f} km/h · peak power unchanged" if options['enabled'] else 'Original CSV curve; ratio override disabled.')
        except (ValueError,tk.TclError):
            self.ratio_preview.set('Enter positive ratios (0.1–30) and a reference speed (1–1000 km/h).')

    def edit_custom_lua(self):
        import subprocess
        from custom_control import USER_FILE
        subprocess.Popen(['notepad.exe', str(USER_FILE)])

    def check_custom_lua(self):
        from custom_control import check_code
        try:
            result = check_code()
            messagebox.showinfo('Custom Lua check', result, parent=self)
        except Exception as exc:
            messagebox.showerror('Custom Lua check failed', str(exc), parent=self)

    def start(self, mode, path=None):
        if self.worker and self.worker.is_alive():
            return
        try:
            self.save()
            config = copy.deepcopy(self.settings)
            if mode not in ('login', 'orders', 'delete_order'):
                validate_settings(config)
                if config.get('electric_enabled'):
                    from electric_patch import electric_settings
                    electric_settings(config)
                if not config.get('mods', '').strip():
                    raise ValueError('Choose a BeamNG mods folder.')
            pending = config.get('pending')
            if mode == 'new' and pending and pending['state'] != 'installed':
                raise ValueError('An order is already saved. Resume it, or click Remove saved order if you no longer need it.')
            if mode == 'resume' and not pending:
                raise ValueError('There is no saved order to resume.')
            if mode == 'reapply' and not config.get('last_download'):
                raise ValueError('Download a conversion or choose an existing ZIP first.')
        except Exception as exc:
            messagebox.showerror('Check settings', str(exc), parent=self)
            return
        self.cancel.clear()
        for button in self.buttons:
            button.configure(state='disabled')
        self.progress.start(12)
        self.worker = threading.Thread(target=self.run_job, args=(mode, config, path), daemon=True)
        self.worker.start()

    def run_job(self, mode, config, path):
        try:
            if mode in ('new', 'resume', 'login', 'orders', 'delete_order'):
                c = Client()
                self.emit('Logging in to Delta Cross…')
                c.login(config['email'], config['password'])
                if mode == 'login':
                    self.emit('Login successful.')
                    return
                if mode == 'orders':
                    self.emit('Loading website orders…')
                    rows = c.orders()
                    self.events.put(('orders', rows))
                    self.emit(f'{len(rows)} website order(s) loaded.')
                    return
                if mode == 'delete_order':
                    if self.cancel.is_set():
                        raise SiteError('Stopped before deleting the order.')
                    self.emit('Deleting website order #' + path['id'] + '…')
                    rows = c.delete_order(path['id'], path['name'])
                    if (config.get('pending') or {}).get('id') == path['id']:
                        self.persist({'pending': None})
                    self.events.put(('orders', rows))
                    self.emit('Website order #' + path['id'] + ' removed. Local files are kept.')
                    return
                pending = config.get('pending')
                if mode == 'new':
                    self.emit('Uploading ' + Path(config['vcl']).name + '…')
                    pending = c.upload(config['vcl'])
                    self.persist({'pending': pending})
                orders = c.orders()
                observed = orders.get(pending['id'])
                if needs_submission(pending, observed):
                    if self.cancel.is_set():
                        raise SiteError('Stopped before submission. Resume this order later.')
                    pending = dict(pending, state='submitting')
                    self.persist({'pending': pending})
                    self.emit('Submitting uploaded order #' + pending['id'] + '…')
                    c.submit(pending)
                    pending = dict(pending, state='submitted')
                    self.persist({'pending': pending})
                self.emit('Following order #' + pending['id'] + '…')
                deadline = time.monotonic() + 1800
                previous = None
                failures = 0
                while time.monotonic() < deadline:
                    if self.cancel.is_set():
                        raise SiteError('Stopped waiting. The website order is saved; use Resume saved order.')
                    try:
                        order = c.orders().get(pending['id'])
                        failures = 0
                    except Exception:
                        failures += 1
                        if failures >= 3:
                            raise
                        self.emit('Connection interrupted; retrying order status…')
                        self.cancel.wait(5)
                        continue
                    if not order:
                        raise SiteError('Saved order is not listed yet. Resume later; no duplicate submission was made.')
                    if order['name'] != pending['name']:
                        raise SiteError('Order filename mismatch. Stopped to avoid downloading another vehicle.')
                    status = order['status']
                    if status != previous:
                        self.emit('Order #' + pending['id'] + ': ' + status)
                        previous = status
                    if status == 'processed':
                        break
                    if status not in ('submitted', 'processing', 'queued', 'pending'):
                        raise SiteError('Website order status: ' + status + '. Check Orders in your browser.')
                    self.cancel.wait(5)
                else:
                    raise SiteError('Conversion is taking longer than 30 minutes. Resume this order later.')
                pending = dict(pending, state='processed')
                self.persist({'pending': pending})
                link = garage_download(c.garage_html(), pending)
                download = ROOT / 'downloads' / (pending['id'] + '_' + Path(pending['name']).name + '.zip')
                self.emit('Downloading the ZIP for order #' + pending['id'] + '…')
                c.download(link, download, self.cancel)
                path = download
                self.persist({'last_download': str(download)})
            elif mode == 'reapply':
                path = config['last_download']
                pending = None
            else:
                # Keep a stable copy outside mods before any replacement.
                import shutil
                source = Path(path)
                download = ROOT / 'downloads' / (datetime.now().strftime('local_%Y%m%d_%H%M%S_') + source.name)
                download.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, download)
                path, pending = download, None
                self.persist({'last_download': str(download)})
            if self.cancel.is_set():
                raise SiteError('Stopped before patch/install. Original download is preserved.')
            output = ROOT / 'patched' / (Path(path).stem + '_patched.zip')
            self.emit('Applying suspension, glass and four-motor electric conversion…' if config.get('electric_enabled') else 'Applying suspension, starter and glass settings…')
            root = patch_zip(path, output, config)
            if self.cancel.is_set():
                raise SiteError('Stopped before installation. Patched ZIP is preserved.')
            target, backup = install_zip(output, config['mods'], ROOT / 'backups')
            values = {'last_installed': str(target)}
            if config.get('electric_enabled') and config.get('ev_weight_enabled'):
                import json, zipfile
                with zipfile.ZipFile(output) as z:
                    mass = json.loads(z.read(f'vehicles/{root}/companion_ev_report.json'))['weight']
                values['last_weight_estimate'] = (f"Last patched estimate: {mass['total_kg']:.1f} kg total\n"
                    f"Base {mass['base_kg']:g} (includes motors) + battery {mass['battery_kg']:g} + "
                    f"left {mass['left_passenger_kg']:g} + right {mass['right_passenger_kg']:g} kg\n{target.name}")
            if pending:
                values['pending'] = dict(pending, state='installed')
            self.persist(values)
            if backup:
                self.emit('Previous copies backed up to ' + str(backup))
            self.emit('Installed ' + target.name + '. Refresh the vehicle selector in BeamNG.')
        except Exception as exc:
            # Never include request bodies, passwords or cookie values in logs.
            self.events.put(('error', str(exc)))
        finally:
            self.events.put(('done', None))

    def build_dashboard(self, frame):
        ttk.Label(frame,text='BeamNG → STM32 → Android',font=('Segoe UI',14,'bold')).pack(anchor='w',pady=10)
        ttk.Label(frame,text='Keep Companion open while driving. Sends all 35 telemetry values at 24 Hz.\nDefault: 921600 baud, 8N1, no flow control. Settings are saved.',wraplength=610).pack(anchor='w',pady=10)
        form=ttk.Frame(frame);form.pack(fill='x',pady=12)
        ttk.Label(form,text='COM port').grid(row=0,column=0,sticky='w')
        self.dashboard_ports=ttk.Combobox(form,textvariable=self.var('dashboard_port'),values=ports(),width=36)
        self.dashboard_ports.grid(row=0,column=1,padx=10,pady=8)
        ttk.Button(form,text='Refresh',command=lambda:self.dashboard_ports.configure(values=ports())).grid(row=0,column=2)
        ttk.Label(form,text='Baud rate').grid(row=1,column=0,sticky='w')
        ttk.Combobox(form,textvariable=self.var('dashboard_baud'),values=('38400','57600','115200','230400','460800','921600','1000000','2000000'),width=16).grid(row=1,column=1,sticky='w',padx=10,pady=8)
        actions=ttk.Frame(frame);actions.pack(fill='x',pady=12)
        ttk.Button(actions,text='Connect',command=self.connect_dashboard).pack(side='left')
        ttk.Button(actions,text='Disconnect',command=self.dashboard_bridge.stop).pack(side='left',padx=10)
        ttk.Button(frame,text='Install/update telemetry mod',command=self.install_dashboard).pack(anchor='w',pady=10)
        ttk.Label(frame, textvariable=self.beamng_status, style='BeamNG.TLabel', wraplength=610).pack(anchor='w', pady=(12, 0))
        self.dashboard_status=tk.StringVar(value='Disconnected')
        self.dashboard_preview=tk.StringVar()
        ttk.Label(frame,textvariable=self.dashboard_status,wraplength=610).pack(anchor='w',pady=12)
        ttk.Label(frame,textvariable=self.dashboard_preview,wraplength=610).pack(anchor='w',pady=8)
        ttk.Label(frame,text='Dummy receiver uses a virtual serial loopback. Select it and Connect to see decoded game data without hardware.\n\nThe mod works with the current player vehicle. No car export is needed. Restart BeamNG after installing the mod. Missing values use the protocol minimum.',wraplength=610).pack(anchor='w',pady=15)

    def connect_dashboard(self):
        try:
            self.dashboard_bridge.start(self.vars['dashboard_port'].get().strip(),self.vars['dashboard_baud'].get())
        except Exception as exc:
            messagebox.showerror('Dashboard connection',str(exc),parent=self)

    def install_dashboard(self):
        try:
            from dashboard_install import install
            target=install(self.vars['mods'].get())
            messagebox.showinfo('Dashboard mod',f'Installed {target.name}. Restart BeamNG to load it.',parent=self)
        except Exception as exc:
            messagebox.showerror('Dashboard mod',str(exc),parent=self)

    def pump(self):
        beamng_status = self.dashboard_bridge.beamng_status
        if self.beamng_status.get() != beamng_status:
            self.beamng_status.set(beamng_status)
            ttk.Style(self).configure('BeamNG.TLabel', foreground='#217a39' if self.dashboard_bridge.beamng_connected else '#666666')
        self.dashboard_status.set(self.dashboard_bridge.status)
        decoded=self.dashboard_bridge.receiver.latest
        self.dashboard_preview.set(('Dummy decoded: %.1f km/h · longitudinal %.3f G · lateral %.3f G\nSequence %d · %d complete packets' % (decoded['speedKmh'],decoded['longitudinalG'],decoded['lateralG'],decoded['seq'],self.dashboard_bridge.receiver.packets)) if decoded else '')
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'orders':
                self.show_orders(value)
            elif kind == 'persist':
                values, ack = value
                self.settings.update(values)
                if 'last_weight_estimate' in values:
                    self.weight_estimate.set(values['last_weight_estimate'])
                try:
                    self.save()
                    self.pending_label.configure(text=self.pending_text())
                    ack.set()
                except OSError:
                    pass
            elif kind in ('log', 'error'):
                self.status.set(value)
                self.log.configure(state='normal')
                self.log.insert('end', datetime.now().strftime('%H:%M:%S ') + value + '\n')
                self.log.see('end')
                self.log.configure(state='disabled')
                if kind == 'error' and not self.closing:
                    messagebox.showerror('Operation stopped', value, parent=self)
            elif kind == 'done':
                self.progress.stop()
                for button in self.buttons:
                    button.configure(state='normal')
        self.after(100, self.pump)

    def close(self):
        self.closing = True
        self.cancel.set()
        self.dashboard_bridge.stop()
        self.save()
        # Keep the event pump alive until an in-flight upload/install has saved its state.
        # Abruptly killing a daemon worker could leave a successful upload unrecorded.
        self.withdraw()
        self.finish_close()

    def finish_close(self):
        if self.worker and self.worker.is_alive():
            self.after(100, self.finish_close)
        else:
            self.destroy()


if __name__ == '__main__':
    # One UI/worker per installation, to prevent two windows submitting the same project.
    import msvcrt
    lock = (ROOT / '.instance.lock').open('a+b')
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        dialog = tk.Tk()
        dialog.withdraw()
        messagebox.showinfo('AutoCraft Companion', 'The companion is already open. Switch to its existing window.')
        dialog.destroy()
    else:
        try:
            Companion().mainloop()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    lock.close()
