import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import mysql.connector
import datetime
import os
import sys
import qrcode
from barcode import Code128
from barcode.writer import ImageWriter
from PIL import Image, ImageTk
import configparser
import subprocess
import shutil

# Conditional import for Windows printing support
if sys.platform.startswith('win'):
    try:
        import win32print
    except ImportError:
        print("Warning: win32print module not found. Windows printing might be limited to using os.startfile().")

# --- 1. CONFIGURATION AND DATABASE FUNCTIONS ---

CONFIG_FILE = 'config.ini'
CODES_DIR = 'codes_generated'

# Ensure the storage directory exists
os.makedirs(CODES_DIR, exist_ok=True)


def create_default_config():
    """Creates a default config file if one doesn't exist."""
    config = configparser.ConfigParser()
    config['mysql'] = {
        'host': 'localhost',
        'user': 'root',
        'password': '',
        'database': 'code_manager_db'
    }
    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)


def load_config():
    """Loads DB settings from the config file, creating a default if needed."""
    if not os.path.exists(CONFIG_FILE):
        create_default_config()

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    settings = {
        'host': config.get('mysql', 'host'),
        'user': config.get('mysql', 'user'),
        'password': config.get('mysql', 'password'),
        'database': config.get('mysql', 'database')
    }
    return settings


def save_config(settings):
    """Saves updated DB settings to the config file."""
    config = configparser.ConfigParser()
    config['mysql'] = settings
    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)


# Load the initial configuration
DB_CONFIG = load_config()


def get_db_connection(use_db_name=True):
    """Establishes and returns a database connection using current config."""
    global DB_CONFIG
    DB_CONFIG = load_config()

    connect_params = DB_CONFIG.copy()

    if not use_db_name:
        # Connect without specifying the DB name for setup/deletion operations
        connect_params.pop('database', None)

    # Remove password if it's empty, as mysql.connector can handle that better
    if not connect_params.get('password'):
        connect_params.pop('password', None)

    try:
        conn = mysql.connector.connect(**connect_params)

        if use_db_name:
            # Manually ensure the database is used if we connected successfully without specifying it
            if conn.database is None:
                conn.database = DB_CONFIG['database']

        return conn

    except mysql.connector.Error as err:
        return None


def setup_database_tables():
    """Creates the database and necessary tables if they don't exist."""
    # Connect without specifying the database name first
    conn = get_db_connection(use_db_name=False)
    if not conn:
        messagebox.showerror("DB Setup Error", "Cannot connect to MySQL server. Check configuration.")
        return False

    try:
        cursor = conn.cursor()

        db_name = DB_CONFIG['database']
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")

        conn.database = db_name  # Now use the new/existing database

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS created_codes
                       (
                           id
                           INT
                           AUTO_INCREMENT
                           PRIMARY
                           KEY,
                           type
                           VARCHAR
                       (
                           10
                       ) NOT NULL, -- 'QR' or 'BAR'
                           data TEXT NOT NULL,
                           image_path VARCHAR
                       (
                           255
                       ) NOT NULL,
                           date_created DATETIME NOT NULL
                           )
                       """)

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS scanned_codes
                       (
                           id
                           INT
                           AUTO_INCREMENT
                           PRIMARY
                           KEY,
                           data
                           TEXT
                           NOT
                           NULL,
                           date_scanned
                           DATETIME
                           NOT
                           NULL
                       )
                       """)

        conn.commit()
        cursor.close()
        conn.close()
        return True

    except mysql.connector.Error as err:
        messagebox.showerror("DB Error", f"Error setting up database: {err}")
        return False


def backup_database():
    """Performs a database backup using mysqldump."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"code_manager_backup_{timestamp}.sql"

    try:
        command = [
            "mysqldump",
            "-u", DB_CONFIG['user'],
        ]
        if DB_CONFIG['password']:
            command.append(f"--password={DB_CONFIG['password']}")

        command.extend([
            DB_CONFIG['database'],
            "-r", backup_file
        ])

        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        messagebox.showinfo("Success", f"Database backed up successfully to: {backup_file}")
        return True

    except FileNotFoundError:
        messagebox.showerror("Backup Error",
                             "mysqldump command not found. Ensure XAMPP's MySQL bin folder is in your system PATH.")
        return False
    except subprocess.CalledProcessError as e:
        messagebox.showerror("Backup Error", f"Error during backup: {e.stderr.decode()}")
        return False


# --- 2. CODE GENERATION AND DATABASE STORAGE ---

def format_wifi_payload(ssid, password, auth_type):
    """Formats the data into the Wi-Fi Configuration string."""
    auth_map = {'WPA/WPA2': 'WPA', 'WEP': 'WEP', 'None': 'nopass'}

    ssid_esc = ssid.replace('\\', '\\\\').replace(';', '\\;')
    pass_esc = password.replace('\\', '\\\\').replace(';', '\\;')

    payload = f"WIFI:T:{auth_map.get(auth_type, 'WPA')};S:{ssid_esc};P:{pass_esc};;"
    return payload


def insert_code_metadata(type, data, image_path):
    """Inserts metadata about the created code into the database."""
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        sql = """
              INSERT INTO created_codes (type, data, image_path, date_created)
              VALUES (%s, %s, %s, %s) \
              """
        now = datetime.datetime.now()
        metadata_data = data[:250]
        values = (type, metadata_data, image_path, now)
        try:
            cursor.execute(sql, values)
            conn.commit()
            return True
        except mysql.connector.Error as err:
            messagebox.showerror("DB Error", f"Failed to save metadata: {err}")
            return False
        finally:
            cursor.close()
            conn.close()


def generate_qr(data, filename):
    """Generates a QR code image, saves it, and records metadata."""
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        full_path = os.path.join(CODES_DIR, f"{filename}_QR.png")
        img.save(full_path)

        insert_code_metadata('QR', data, full_path)
        return full_path
    except Exception as e:
        messagebox.showerror("QR Error", f"Failed to generate QR code: {e}")
        return None


def generate_barcode(data, filename):
    """Generates a Code128 barcode image, saves it, and records metadata."""
    try:
        code128 = Code128(data, writer=ImageWriter())
        full_path_base = os.path.join(CODES_DIR, f"{filename}_BAR")

        code128.save(full_path_base)
        full_path = full_path_base + '.png'

        insert_code_metadata('BAR', data, full_path)
        return full_path
    except Exception as e:
        messagebox.showerror("Barcode Error",
                             f"Failed to generate barcode: {e}\n(Note: Code128 requires alphanumeric data)")
        return None


# --- START OF LATEST FEATURE: UPDATE AND REGENERATE ---

def update_code_and_regenerate(record_id, code_type, new_data, old_path):
    """
    Updates the database record with new data and regenerates the code image,
    replacing the old file. This operation is designed to be atomic with respect to the DB.
    """
    conn = get_db_connection()
    if not conn:
        return False, "Cannot connect to database."

    cursor = conn.cursor()

    try:
        conn.start_transaction()  # Start transaction for safety
        full_path = old_path

        # 1. Regenerate image
        # Delete old file first to ensure regeneration is clean
        if os.path.exists(old_path):
            os.remove(old_path)

        if code_type == 'QR':
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(new_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(full_path)

        elif code_type == 'BAR':
            # Extract the base filename without the extension
            filename_base = os.path.splitext(os.path.basename(full_path))[0]
            base_path_no_ext = os.path.join(CODES_DIR, filename_base)

            code128 = Code128(new_data, writer=ImageWriter())
            code128.save(base_path_no_ext)  # This saves as base_path_no_ext.png

            # Update full_path in case Code128 writer logic slightly alters the name/extension
            full_path = base_path_no_ext + '.png'
            # Ensure the newly created file name is consistent with what's stored/updated.

        # 2. Update the DB record
        metadata_data = new_data[:250]
        sql = "UPDATE created_codes SET data = %s, image_path = %s WHERE id = %s"
        cursor.execute(sql, (metadata_data, full_path, record_id))

        conn.commit()

        return True, "Code regenerated and database updated."

    except Exception as e:
        conn.rollback()  # Rollback the database changes if file operation failed
        raise e  # Re-raise the exception to be handled by the caller
    finally:
        cursor.close()
        conn.close()


# --- END OF LATEST FEATURE ---


# --- 3. PRINTER DETECTION AND PRINTING FUNCTIONS ---

def get_installed_printers():
    """Returns a list of installed printer names based on OS."""
    if sys.platform.startswith('win'):
        try:
            if 'win32print' in sys.modules:
                printers = [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)]
                return printers if printers else ["Windows Default Print Dialog"]
            else:
                return ["Windows Default Print Dialog (pywin32 not installed)"]
        except Exception:
            return ["Windows Default Print Dialog"]
    elif sys.platform == 'darwin' or sys.platform.startswith('linux'):  # macOS and Linux (CUPS)
        try:
            result = subprocess.run(['lpstat', '-p', '-d'], capture_output=True, text=True, check=False)
            printers = [line.split()[1] for line in result.stdout.splitlines() if line.startswith('printer')]
            return printers if printers else ["Default CUPS Printer (lpr)"]
        except FileNotFoundError:
            return ["Default CUPS Printer (lpr)"]
    else:
        return ["Printing Not Fully Supported"]


def print_file_os(file_path, printer_name=None):
    """
    Attempts to send a file to the printer using OS-specific commands.
    Returns (True/False, message).
    """
    if not os.path.exists(file_path):
        return False, "File not found."

    if sys.platform.startswith('win'):
        try:
            # Use os.startfile for a generic print dialog experience
            os.startfile(file_path, "print")
            return True, "Printing initiated via Windows OS dialog."
        except Exception as e:
            # Fallback for detailed print command if needed, but os.startfile is simplest
            return False, f"Windows printing failed. Error: {e}"
    elif sys.platform == 'darwin' or sys.platform.startswith('linux'):
        # Use lpr command for Unix-like systems
        command = ['lpr']
        # Do not use -P flag if the default option is selected
        if printer_name and "Default CUPS Printer" not in printer_name:
            command.extend(['-P', printer_name])

        command.append(file_path)

        try:
            subprocess.run(command, check=True, capture_output=True)
            return True, f"File sent to print spooler (Printer: {printer_name or 'Default'})."
        except subprocess.CalledProcessError as e:
            return False, f"Printing failed (lpr error): {e.stderr.decode()}"
        except FileNotFoundError:
            return False, "The 'lpr' command was not found. Is CUPS installed?"
    else:
        return False, "Printing not supported on this operating system."


# --- 4. GUI APPLICATION CLASS ---

class CodeManagerApp:
    def __init__(self, master):
        self.master = master
        master.title("Configurable Code Manager App (CRUD & Printing)")

        self.notebook = ttk.Notebook(master)
        self.notebook.pack(pady=10, padx=10, expand=True, fill="both")

        self.tab_setup = ttk.Frame(self.notebook)
        self.tab_create = ttk.Frame(self.notebook)
        self.tab_list = ttk.Frame(self.notebook)
        self.tab_crud = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_setup, text='Database Setup/Backup')
        self.notebook.add(self.tab_create, text='Create Code')
        self.notebook.add(self.tab_list, text='Manage Codes (View/Print/Export)')
        self.notebook.add(self.tab_crud, text='Edit/Delete Records')

        self.setup_tab_setup()
        self.setup_tab_create()
        self.setup_tab_list()
        self.setup_tab_crud()

        self.tkimage = None
        self.temp_tkimage = None

    # ----------------------------------------------------
    # --- SETUP TAB LAYOUT (Includes Delete Database) ---
    # ----------------------------------------------------
    def setup_tab_setup(self):
        ttk.Label(self.tab_setup, text="MySQL Database Management", font=('Arial', 14, 'bold')).pack(pady=10)

        config_frame = ttk.LabelFrame(self.tab_setup, text=" MySQL Connection Configuration ")
        config_frame.pack(pady=10, padx=20, fill='x')

        global DB_CONFIG
        DB_CONFIG = load_config()

        self.config_entries = {}
        for i, (key, value) in enumerate(DB_CONFIG.items()):
            ttk.Label(config_frame, text=f"{key.capitalize()}:").grid(row=i, column=0, padx=5, pady=2, sticky='w')
            entry = ttk.Entry(config_frame, width=30)
            entry.insert(0, value)
            entry.grid(row=i, column=1, padx=5, pady=2, sticky='w')
            self.config_entries[key] = entry

        ttk.Button(config_frame, text="Save & Test Settings", command=self.handle_save_config).grid(row=len(DB_CONFIG),
                                                                                                    column=0,
                                                                                                    columnspan=2,
                                                                                                    pady=5)

        ttk.Separator(self.tab_setup, orient='horizontal').pack(fill='x', padx=20, pady=10)

        # Database creation and backup
        action_frame = ttk.Frame(self.tab_setup)
        action_frame.pack(pady=5)

        ttk.Button(action_frame,
                   text="Setup Database & Tables",
                   command=self.handle_setup_db).pack(side='left', padx=5, ipadx=10)

        ttk.Button(action_frame,
                   text="Backup Database",
                   command=self.handle_backup_db).pack(side='left', padx=5, ipadx=10)

        ttk.Separator(self.tab_setup, orient='horizontal').pack(fill='x', padx=20, pady=10)

        # --- DANGER ZONE ---
        ttk.Label(self.tab_setup, text="DANGER ZONE: Permanent Deletion", foreground='red',
                  font=('Arial', 10, 'bold')).pack(pady=5)

        ttk.Button(self.tab_setup,
                   text="🚨 Delete Database",
                   command=self.handle_delete_db,
                   style='Danger.TButton').pack(pady=5, ipadx=20)

        # Define a custom style for the delete button to make it stand out
        self.master.style = ttk.Style()
        self.master.style.configure('Danger.TButton', foreground='red', font=('Arial', 10, 'bold'))

    def handle_save_config(self):
        new_settings = {key: entry.get() for key, entry in self.config_entries.items()}

        save_config(new_settings)
        global DB_CONFIG
        DB_CONFIG = new_settings

        temp_config = new_settings.copy()
        temp_config.pop('database', None)
        if not temp_config.get('password'):
            temp_config.pop('password', None)

        try:
            conn = mysql.connector.connect(**temp_config)
            conn.close()
            messagebox.showinfo("Success", "Configuration saved and connection test successful!")
        except mysql.connector.Error as err:
            messagebox.showerror("Error",
                                 f"Configuration saved, but connection test failed:\n{err}\n\nCheck your MySQL settings.")

    def handle_setup_db(self):
        if setup_database_tables():
            messagebox.showinfo("Success", f"Database '{DB_CONFIG['database']}' and tables are ready!")

    def handle_backup_db(self):
        backup_database()

    def handle_delete_db(self):
        db_name = DB_CONFIG['database']

        if not messagebox.askyesno("CONFIRM PERMANENT DELETION",
                                   f"WARNING: You are about to PERMANENTLY delete the database: '{db_name}'. This action cannot be undone. Are you absolutely sure?"):
            return

        # Second layer of confirmation
        if not messagebox.askyesno("FINAL CONFIRMATION",
                                   f"🚨 DOUBLE CHECK! Is the database name you want to delete correct: '{db_name}'?"):
            return

        conn = get_db_connection(use_db_name=False)  # Connect without DB name
        if not conn:
            messagebox.showerror("DB Error", "Cannot connect to MySQL server to perform deletion. Check config.")
            return

        try:
            cursor = conn.cursor()

            # Use backticks for database name for safety
            cursor.execute(f"DROP DATABASE `{db_name}`")
            conn.commit()

            # Optional: Delete local files too
            try:
                if os.path.exists(CODES_DIR):
                    shutil.rmtree(CODES_DIR)
                    os.makedirs(CODES_DIR)
                    file_msg = "\n(Associated local code files folder also reset.)"
                else:
                    file_msg = ""
            except Exception as e:
                file_msg = f"\n(Could not reset local code files folder: {e})"

            messagebox.showinfo("Success", f"Database '{db_name}' has been PERMANENTLY deleted." + file_msg)

            # Refresh lists if they are open
            self.update_code_list()
            self.update_crud_list()

        except mysql.connector.Error as err:
            messagebox.showerror("DB Deletion Error", f"Failed to delete database '{db_name}': {err}")
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if conn:
                conn.close()

    # --- CREATE TAB LAYOUT (No change) ---
    def setup_tab_create(self):
        ttk.Label(self.tab_create, text="Generate QR or Barcode", font=('Arial', 14, 'bold')).grid(row=0, column=0,
                                                                                                   columnspan=2,
                                                                                                   pady=10)

        ttk.Label(self.tab_create, text="Code Type:").grid(row=1, column=0, padx=5, pady=5, sticky='w')
        self.code_type = tk.StringVar(value='QR_TEXT')
        ttk.Radiobutton(self.tab_create, text="QR Code (General Text/Link)", variable=self.code_type, value='QR_TEXT',
                        command=self.update_create_fields).grid(row=1, column=1, padx=5, pady=5, sticky='w')
        ttk.Radiobutton(self.tab_create, text="QR Code (Wi-Fi Config)", variable=self.code_type, value='QR_WIFI',
                        command=self.update_create_fields).grid(row=2, column=1, padx=5, pady=5, sticky='w')
        ttk.Radiobutton(self.tab_create, text="Barcode (Numbers/Chars only)", variable=self.code_type, value='BAR',
                        command=self.update_create_fields).grid(row=3, column=1, padx=5, pady=5, sticky='w')

        ttk.Separator(self.tab_create, orient='horizontal').grid(row=4, column=0, columnspan=2, sticky='ew', pady=5)

        self.input_frame = ttk.Frame(self.tab_create)
        self.input_frame.grid(row=5, column=0, columnspan=2, padx=10, pady=5, sticky='ew')

        self.update_create_fields()

        ttk.Label(self.tab_create, text="File Name:").grid(row=6, column=0, padx=5, pady=5, sticky='w')
        self.filename_entry = ttk.Entry(self.tab_create, width=50)
        self.filename_entry.grid(row=6, column=1, padx=5, pady=5)

        ttk.Button(self.tab_create, text="Generate & Save Code", command=self.handle_generate_code).grid(row=7,
                                                                                                         column=0,
                                                                                                         columnspan=2,
                                                                                                         pady=10)

        self.image_preview_label = ttk.Label(self.tab_create, text="Code Preview")
        self.image_preview_label.grid(row=8, column=0, columnspan=2, pady=10)

    def update_create_fields(self):
        for widget in self.input_frame.winfo_children():
            widget.destroy()

        code_type = self.code_type.get()

        if code_type == 'QR_TEXT' or code_type == 'BAR':
            label_text = "Data / Link:" if code_type == 'QR_TEXT' else "Barcode Data:"
            ttk.Label(self.input_frame, text=label_text).grid(row=0, column=0, padx=5, pady=5, sticky='w')
            self.data_entry = ttk.Entry(self.input_frame, width=50)
            self.data_entry.grid(row=0, column=1, padx=5, pady=5)

        elif code_type == 'QR_WIFI':
            ttk.Label(self.input_frame, text="Network Name (SSID):").grid(row=0, column=0, padx=5, pady=2, sticky='w')
            self.wifi_ssid = ttk.Entry(self.input_frame, width=30)
            self.wifi_ssid.grid(row=0, column=1, padx=5, pady=2, sticky='w')

            ttk.Label(self.input_frame, text="Password:").grid(row=1, column=0, padx=5, pady=2, sticky='w')
            self.wifi_pass = ttk.Entry(self.input_frame, width=30, show='*')
            self.wifi_pass.grid(row=1, column=1, padx=5, pady=2, sticky='w')

            ttk.Label(self.input_frame, text="Encryption Type:").grid(row=2, column=0, padx=5, pady=2, sticky='w')
            self.wifi_auth = ttk.Combobox(self.input_frame, values=['WPA/WPA2', 'WEP', 'None'], state='readonly',
                                          width=28)
            self.wifi_auth.set('WPA/WPA2')
            self.wifi_auth.grid(row=2, column=1, padx=5, pady=2, sticky='w')

    def handle_generate_code(self):
        filename = self.filename_entry.get().strip()
        code_type = self.code_type.get()
        data = None

        if not filename:
            messagebox.showwarning("Input Error", "File Name field cannot be empty.")
            return

        if code_type == 'QR_TEXT' or code_type == 'BAR':
            data = self.data_entry.get().strip()
            if not data:
                messagebox.showwarning("Input Error", "Data field cannot be empty.")
                return

        elif code_type == 'QR_WIFI':
            ssid = self.wifi_ssid.get().strip()
            password = self.wifi_pass.get().strip()
            auth = self.wifi_auth.get()

            if not ssid:
                messagebox.showwarning("Input Error", "Wi-Fi Network Name (SSID) cannot be empty.")
                return

            data = format_wifi_payload(ssid, password, auth)

        # --- Generation Logic ---
        if code_type.startswith('QR'):
            path = generate_qr(data, filename)
            code_name = "QR Code"
        elif code_type == 'BAR':
            if not data.isalnum() and not all(c in ' -$./+%' for c in data):
                messagebox.showwarning("Barcode Error",
                                       "Barcode data should primarily contain numbers and basic alphanumeric characters.")
                return
            path = generate_barcode(data, filename)
            code_name = "Barcode"
        else:
            path = None

        if path:
            messagebox.showinfo("Success", f"{code_name} saved and recorded successfully.")
            self.show_image_preview(path)
            self.update_code_list()
            self.update_crud_list()

    def show_image_preview(self, path):
        try:
            img = Image.open(path)
            img = img.resize((200, 200), Image.LANCZOS)
            self.tkimage = ImageTk.PhotoImage(img)
            self.image_preview_label.config(image=self.tkimage, text="")
        except Exception:
            self.image_preview_label.config(image=None, text="Error loading image.")

    # --- LIST/MANAGE TAB LAYOUT (VIEW/PRINT/EXPORT) ---
    def setup_tab_list(self):
        ttk.Label(self.tab_list, text="List of Created Codes", font=('Arial', 14, 'bold')).pack(pady=10)

        self.tree = ttk.Treeview(self.tab_list, columns=("ID", "Type", "Data", "Date Created", "Path"), show='headings')
        self.tree.heading("ID", text="ID")
        self.tree.heading("Type", text="Type")
        self.tree.heading("Data", text="Data")
        self.tree.heading("Date Created", text="Date Created")
        self.tree.heading("Path", text="File Path (Hidden)", anchor='w')

        self.tree.column("ID", width=50, anchor='center')
        self.tree.column("Type", width=70, anchor='center')
        self.tree.column("Data", width=300)
        self.tree.column("Date Created", width=150)
        self.tree.column("Path", width=0, stretch=tk.NO)

        self.tree.pack(fill='both', expand=True, padx=10)

        # --- Printer Selection and Action Frame ---
        print_frame = ttk.LabelFrame(self.tab_list, text=" Actions on Selected Code ")
        print_frame.pack(pady=10, padx=10, fill='x')

        printers = get_installed_printers()
        self.printer_var = tk.StringVar(value=printers[0] if printers else "No Printers Found")

        ttk.Label(print_frame, text="Select Printer:").grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.printer_combo = ttk.Combobox(print_frame, textvariable=self.printer_var, values=printers, state='readonly',
                                          width=30)
        self.printer_combo.grid(row=0, column=1, padx=5, pady=5, sticky='ew')

        action_row = 1
        ttk.Button(print_frame, text="Refresh List", command=self.update_code_list).grid(row=action_row, column=0,
                                                                                         padx=5, pady=5, sticky='ew')
        ttk.Button(print_frame, text="View Code Image", command=self.handle_view_image).grid(row=action_row, column=1,
                                                                                             padx=5, pady=5,
                                                                                             sticky='ew')

        print_row = 2
        ttk.Button(print_frame, text="Export Code Image", command=self.handle_export_image).grid(row=print_row,
                                                                                                 column=0, padx=5,
                                                                                                 pady=5, sticky='ew')
        ttk.Button(print_frame,
                   text="Print Selected Code",
                   command=self.handle_print_selected_code).grid(row=print_row, column=1, padx=5, pady=5, sticky='ew')

        self.update_code_list()

    def update_code_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            sql = "SELECT id, type, data, date_created, image_path FROM created_codes ORDER BY date_created DESC"
            try:
                cursor.execute(sql)
                records = cursor.fetchall()

                for rec in records:
                    date_str = rec[3].strftime("%Y-%m-%d %H:%M:%S")
                    self.tree.insert('', 'end', values=(rec[0], rec[1], rec[2], date_str, rec[4]))

            except mysql.connector.Error as err:
                messagebox.showerror("DB Error", f"Failed to load records: {err}")
            finally:
                cursor.close()
                conn.close()

    def handle_view_image(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a code from the list to view its image.")
            return

        item_values = self.tree.item(selected_item, 'values')
        image_path = item_values[4]

        if os.path.exists(image_path):
            try:
                img_window = tk.Toplevel(self.master)
                img_window.title(f"Code Image: ID {item_values[0]}")

                img = Image.open(image_path)
                img = img.resize((300, 300), Image.LANCZOS)

                self.temp_tkimage = ImageTk.PhotoImage(img)

                ttk.Label(img_window, image=self.temp_tkimage).pack(padx=10, pady=10)
                ttk.Label(img_window, text=f"Data: {item_values[2]}", font=('Arial', 10, 'bold')).pack(pady=5)
                ttk.Label(img_window, text=f"Type: {item_values[1]}").pack(pady=2)

            except Exception as e:
                messagebox.showerror("Image Load Error", f"Failed to load image from disk:\n{e}")
        else:
            messagebox.showerror("File Error", f"Image file not found at path:\n{image_path}")

    def handle_export_image(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a code from the list to export its image.")
            return

        item_values = self.tree.item(selected_item, 'values')
        source_path = item_values[4]

        if not os.path.exists(source_path):
            messagebox.showerror("File Error", f"Image file not found at path:\n{source_path}")
            return

        # Get original file name and extension
        original_filename = os.path.basename(source_path)
        name, ext = os.path.splitext(original_filename)

        # Ask user for save location and filename
        # Suggest a filename based on the ID and original name
        suggested_name = f"Code_{item_values[0]}_{name}"

        save_path = filedialog.asksaveasfilename(
            defaultextension=ext,
            initialfile=suggested_name,
            filetypes=[("PNG files", "*.png"), ("All files", "*.*")],
            title="Export Code Image As"
        )

        if save_path:
            try:
                shutil.copyfile(source_path, save_path)
                messagebox.showinfo("Export Success", f"Image successfully exported to:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Export Failed", f"Could not export file:\n{e}")

    def handle_print_selected_code(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please select a code from the list to print.")
            return

        item_values = self.tree.item(selected_item, 'values')
        image_path = item_values[4]
        printer_name = self.printer_var.get()

        if not os.path.exists(image_path):
            messagebox.showerror("File Error", f"Image file not found at path:\n{image_path}")
            return

        if not printer_name or printer_name == "No Printers Found":
            messagebox.showwarning("Printer Error",
                                   "No printer is selected or detected. Please check your system settings.")
            return

        success, message = print_file_os(image_path, printer_name)

        if success:
            messagebox.showinfo("Printing Success", f"Successfully sent file to printer.\n{message}")
        else:
            messagebox.showerror("Printing Failed",
                                 f"Could not initiate printing. Please check permissions and the selected printer.\nError Details: {message}")

    # --- CRUD TAB LAYOUT (UPDATE/DELETE) ---
    def setup_tab_crud(self):
        ttk.Label(self.tab_crud, text="Edit or Delete Existing Codes", font=('Arial', 14, 'bold')).pack(pady=10)

        # Ensure column settings are consistent with the list view
        self.crud_tree = ttk.Treeview(self.tab_crud, columns=("ID", "Type", "Data", "Date Created", "Path"),
                                      show='headings')
        self.crud_tree.heading("ID", text="ID")
        self.crud_tree.heading("Type", text="Type")
        self.crud_tree.heading("Data", text="Data")
        self.crud_tree.heading("Date Created", text="Date Created")
        self.crud_tree.heading("Path", text="File Path (Hidden)", anchor='w')

        self.crud_tree.column("ID", width=50, anchor='center')
        self.crud_tree.column("Type", width=70, anchor='center')
        self.crud_tree.column("Data", width=250)
        self.crud_tree.column("Date Created", width=150)
        self.crud_tree.column("Path", width=0, stretch=tk.NO)

        self.crud_tree.pack(fill='x', padx=10)

        # Binding the selection event to load data for edit/delete
        self.crud_tree.bind('<<TreeviewSelect>>', self.load_selected_record)

        ttk.Button(self.tab_crud, text="Refresh Records", command=self.update_crud_list).pack(pady=5)

        ttk.Separator(self.tab_crud, orient='horizontal').pack(fill='x', padx=20, pady=10)

        edit_frame = ttk.LabelFrame(self.tab_crud, text=" Selected Record Details (Update) ")
        edit_frame.pack(pady=5, padx=20, fill='x')

        ttk.Label(edit_frame, text="Record ID:").grid(row=0, column=0, padx=5, pady=2, sticky='w')
        self.crud_id = ttk.Label(edit_frame, text="", font=('Arial', 10, 'bold'))
        self.crud_id.grid(row=0, column=1, padx=5, pady=2, sticky='w')

        ttk.Label(edit_frame, text="Code Type:").grid(row=1, column=0, padx=5, pady=2, sticky='w')
        self.crud_type = ttk.Label(edit_frame, text="")
        self.crud_type.grid(row=1, column=1, padx=5, pady=2, sticky='w')

        ttk.Label(edit_frame, text="New Data:").grid(row=2, column=0, padx=5, pady=2, sticky='w')
        self.crud_data_entry = ttk.Entry(edit_frame, width=50)
        self.crud_data_entry.grid(row=2, column=1, padx=5, pady=2, sticky='w')

        action_frame = ttk.Frame(self.tab_crud)
        action_frame.pack(pady=10)

        ttk.Button(action_frame, text="Update Record Data", command=self.handle_update_record).pack(side='left',
                                                                                                    padx=10, ipadx=10)
        ttk.Button(action_frame, text="Delete Record", command=self.handle_delete_record).pack(side='left', padx=10,
                                                                                               ipadx=10)

        self.update_crud_list()

    def update_crud_list(self):
        for item in self.crud_tree.get_children():
            self.crud_tree.delete(item)

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            sql = "SELECT id, type, data, date_created, image_path FROM created_codes ORDER BY id DESC"
            try:
                cursor.execute(sql)
                records = cursor.fetchall()

                for rec in records:
                    date_str = rec[3].strftime("%Y-%m-%d %H:%M:%S")
                    self.crud_tree.insert('', 'end', values=(rec[0], rec[1], rec[2], date_str, rec[4]))

            except mysql.connector.Error as err:
                messagebox.showerror("DB Error", f"Failed to load records for CRUD: {err}")
            finally:
                cursor.close()
                conn.close()

        self.update_code_list()

    def load_selected_record(self, event):
        selected_item = self.crud_tree.focus()
        if not selected_item:
            return

        values = self.crud_tree.item(selected_item, 'values')

        self.crud_id.config(text=values[0])
        self.crud_type.config(text=values[1])

        self.crud_data_entry.delete(0, tk.END)
        self.crud_data_entry.insert(0, values[2])

    # MODIFIED: Includes call to update_code_and_regenerate (the latest feature)
    def handle_update_record(self):
        record_id = self.crud_id.cget("text")
        code_type = self.crud_type.cget("text")
        new_data = self.crud_data_entry.get().strip()

        if not record_id:
            messagebox.showwarning("Input Error", "Please select a record using the list above.")
            return

        if not new_data:
            messagebox.showwarning("Input Error", "New Data field cannot be empty.")
            return

        # Get the current image path from the Treeview selection
        selected_item = self.crud_tree.focus()
        if not selected_item:
            messagebox.showwarning("Selection Error", "Please re-select a record to perform the update.")
            return

        # Values are (ID, Type, Data, Date Created, Path)
        item_values = self.crud_tree.item(selected_item, 'values')
        old_path = item_values[4]

        # Barcode validation check for Code128 (BAR) type
        if code_type == 'BAR':
            # Check for non-alphanumeric/non-standard chars only if the type is BAR
            if not new_data.isalnum() and not all(c in ' -$./+%' for c in new_data):
                messagebox.showwarning("Barcode Error",
                                       "Barcode data should primarily contain numbers and basic alphanumeric characters.")
                return

        try:
            # Call the new feature function to update DB and regenerate image
            success, result_msg = update_code_and_regenerate(record_id, code_type, new_data, old_path)

            if success:
                messagebox.showinfo("Success", f"Record ID {record_id} updated and image regenerated successfully!")
                self.update_crud_list()
            else:
                # Should not be reached if exception is raised, but as a safeguard
                messagebox.showerror("Update Failed", f"Update failed. Error: {result_msg}")

        except Exception as e:
            messagebox.showerror("Update/Regen Failed", f"An error occurred during update and regeneration: {e}")

    def handle_delete_record(self):
        record_id = self.crud_id.cget("text")

        if not record_id:
            messagebox.showwarning("Input Error", "Please select a record to delete.")
            return

        if not messagebox.askyesno("Confirm Delete",
                                   f"Are you sure you want to permanently delete Record ID {record_id}?"):
            return

        selected_item = self.crud_tree.focus()
        image_path = self.crud_tree.item(selected_item, 'values')[4] if selected_item else None

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            sql = "DELETE FROM created_codes WHERE id = %s"
            try:
                cursor.execute(sql, (record_id,))
                conn.commit()

                file_msg = ""
                if image_path and os.path.exists(image_path):
                    os.remove(image_path)
                    file_msg = "\n(Associated file deleted.)"

                messagebox.showinfo("Success", f"Record ID {record_id} deleted successfully!" + file_msg)
                self.update_crud_list()
                self.crud_id.config(text="")
                self.crud_type.config(text="")
                self.crud_data_entry.delete(0, tk.END)

            except mysql.connector.Error as err:
                messagebox.showerror("DB Error", f"Failed to delete record: {err}")
            finally:
                cursor.close()
                conn.close()


if __name__ == '__main__':
    root = tk.Tk()
    app = CodeManagerApp(root)
    root.mainloop()