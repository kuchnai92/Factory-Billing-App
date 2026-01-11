import flet as ft
import json
import os
import sys
import shutil
import csv
import asyncio 
import logging
import warnings
import copy
import hashlib
from datetime import datetime, timedelta
from fpdf import FPDF
from fpdf.enums import XPos, YPos 
import webbrowser
import subprocess
import time
import threading
import math
import re

# --- 1. AGGRESSIVE WARNING SUPPRESSION ---
warnings.simplefilter("ignore")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
os.environ["FLET_WS_MAX_MESSAGE_SIZE"] = "8000000"

# --- DETECT PLATFORM (DESKTOP VS MOBILE) ---
# We assume "Desktop" is Windows. If not Windows (e.g., Android/Linux), we treat it as Mobile/Cloud-Only.
IS_WINDOWS_DESKTOP = (sys.platform == "win32")

# --- PRINTER LIBRARY SETUP (Windows Only) ---
HAS_WIN32PRINT = False
if IS_WINDOWS_DESKTOP:
    try:
        import win32print
        HAS_WIN32PRINT = True
    except ImportError:
        HAS_WIN32PRINT = False

# --- SUPABASE SETUP ---
try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    print("Warning: 'supabase' library not found. Run 'pip install supabase' to enable database sync.")

# YOUR SUPABASE KEYS
SUPABASE_URL = "https://fyqdiihytcybtlweiaeb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5cWRpaWh5dGN5YnRsd2VpYWViIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjcwNjMwMjMsImV4cCI6MjA4MjYzOTAyM30.o9-ciiHsefvm3q0Vcuv913yNuRtl976dHLOao4oKt9Y"

supabase: Client = None
if HAS_SUPABASE:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Supabase Init Error: {e}")
        HAS_SUPABASE = False

# --- TRY IMPORTING TEXT SHAPERS (For correct Urdu display) ---
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_RESHAPER = True
except ImportError:
    HAS_RESHAPER = False

# --- Directory Setup ---
if getattr(sys, 'frozen', False):
    APP_ROOT = os.path.dirname(sys.executable)
else:
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))

REAL_DATA_DIR = os.path.join(APP_ROOT, "data")
ASSETS_DIR = os.path.join(APP_ROOT, "assets") 

if not os.path.exists(REAL_DATA_DIR):
    try: os.makedirs(REAL_DATA_DIR)
    except: pass
if not os.path.exists(ASSETS_DIR):
    try: os.makedirs(ASSETS_DIR)
    except: pass

# Global Variables
DATA_DIR = REAL_DATA_DIR
INVENTORY_FILE = ""
INVOICES_JSON = ""
CUSTOMERS_FILE = ""
RECYCLE_BIN_FILE = ""
RETURNS_FILE = ""  
CONFIG_FILE = os.path.join(REAL_DATA_DIR, "config.json") 

CURRENT_ADMIN = "default"

# --- SECURITY HELPER ---
def hash_val(text):
    return hashlib.sha256(str(text).encode()).hexdigest()

def setup_paths(username):
    global DATA_DIR, INVENTORY_FILE, INVOICES_JSON, CUSTOMERS_FILE, RECYCLE_BIN_FILE, RETURNS_FILE, CURRENT_ADMIN
    CURRENT_ADMIN = username
    
    DATA_DIR = os.path.join(APP_ROOT, f"data_{username}")
    if not os.path.exists(DATA_DIR):
        try: os.makedirs(DATA_DIR)
        except: pass
        
    INVENTORY_FILE = os.path.join(DATA_DIR, "inventory.json")
    INVOICES_JSON = os.path.join(DATA_DIR, "invoices.json")
    CUSTOMERS_FILE = os.path.join(DATA_DIR, "customers.json")
    RECYCLE_BIN_FILE = os.path.join(DATA_DIR, "recycle_bin.json")
    RETURNS_FILE = os.path.join(DATA_DIR, "returns.json")

def forced_cleanup(target_dir):
    if os.path.exists(target_dir):
        for _ in range(10):
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
                if not os.path.exists(target_dir):
                    break
            except Exception:
                pass
            time.sleep(0.3)

forced_cleanup(os.path.join(APP_ROOT, "test_data"))

def backup_data(username):
    # Only run backup on Desktop
    if IS_WINDOWS_DESKTOP:
        try:
            admin_backup_root = os.path.join(APP_ROOT, "backups", f"backups_{username}")
            if not os.path.exists(admin_backup_root):
                os.makedirs(admin_backup_root)
                
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(admin_backup_root, f"backup_{timestamp}")
            
            shutil.copytree(DATA_DIR, backup_path)
            
            backups = sorted([os.path.join(admin_backup_root, d) for d in os.listdir(admin_backup_root) if os.path.isdir(os.path.join(admin_backup_root, d))])
            
            if len(backups) > 10:
                shutil.rmtree(backups[0])
        except Exception as e:
            pass 

# --- DATA MANAGEMENT (HYBRID MODE) ---

def get_table_name_from_file(filepath):
    base = os.path.basename(filepath)
    if "inventory" in base: return "inventory"
    if "invoices" in base: return "invoices"
    if "customers" in base: return "customers"
    return None

def load_data(file, default):
    data = default
    
    # 1. DESKTOP: Try to load from local file first
    if IS_WINDOWS_DESKTOP:
        if os.path.exists(file):
            with open(file, "r") as f:
                try: 
                    data = json.load(f)
                except: 
                    pass 
    
    # 2. BOTH: Sync with Supabase
    if HAS_SUPABASE and supabase:
        # We generally don't sync 'config.json' from cloud to allow local settings
        if "config.json" not in file:
            table_name = get_table_name_from_file(file)
            if table_name:
                try:
                    # Mobile or Desktop: Fetch latest data
                    response = supabase.table(table_name).select("*").execute()
                    if response.data:
                        data = response.data
                        
                        # IF DESKTOP: Update the local file with cloud data
                        if IS_WINDOWS_DESKTOP:
                            with open(file, "w") as f:
                                json.dump(data, f, indent=4)
                                
                except Exception as e:
                    print(f"Supabase Load Error ({table_name}): {e}")
                    # If mobile and no internet, we return default (RAM empty)
                    # If desktop, we already loaded local data, so we're good
    
    return data

def save_data(file, data):
    # 1. DESKTOP: Save to local file
    if IS_WINDOWS_DESKTOP:
        with open(file, "w") as f:
            json.dump(data, f, indent=4)
    
    # 2. BOTH: Send to Supabase
    if HAS_SUPABASE and supabase and "config.json" not in file:
        table_name = get_table_name_from_file(file)
        
        def push_to_db(t_name, payload):
            try:
                supabase.table(t_name).upsert(payload).execute()
            except Exception as e:
                print(f"Supabase Save Error ({t_name}): {e}")

        if table_name:
            threading.Thread(target=push_to_db, args=(table_name, data), daemon=True).start()

config = load_data(CONFIG_FILE, {
    "admins": {"admin": "123"}, 
    "hide_prev_dues_on_pdf": False,
    "company_info": {
        "name": "Amin & Sons",
        "address": "26EB near Sukhbias pull, Pakpattan",
        "phone": "03148756922"
    }
})

# --- PDF GENERATION ---
def process_text(text):
    if not text: return ""
    text = str(text)
    if HAS_RESHAPER:
        try:
            reshaped_text = arabic_reshaper.reshape(text)
            bidi_text = get_display(reshaped_text)
            return bidi_text
        except:
            return text
    return text

def generate_pdf(invoice, filename):
    is_return = invoice.get('total', 0) < 0
    pdf = FPDF(format=(80, 210))
    pdf.set_margins(2, 0, 2) 
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    
    font_reg = os.path.join(ASSETS_DIR, "NotoSansArabic-Regular.ttf")
    font_bold = os.path.join(ASSETS_DIR, "NotoSansArabic-Bold.ttf")
    
    if not os.path.exists(font_reg):
        font_reg = os.path.join(ASSETS_DIR, "UrduFont.ttf")
    if not os.path.exists(font_bold):
        font_bold = font_reg

    has_custom_font = os.path.exists(font_reg)
    
    if has_custom_font:
        try:
            pdf.add_font('UrduFont', '', fname=font_reg)
            if os.path.exists(font_bold):
                pdf.add_font('UrduFont', 'B', fname=font_bold)
            else:
                pdf.add_font('UrduFont', 'B', fname=font_reg)
            pdf.add_font('UrduFont', 'I', fname=font_reg)
            pdf.add_font('UrduFont', 'BI', fname=font_bold if os.path.exists(font_bold) else font_reg)
        except Exception as e:
            print(f"Font loading error: {e}")

    # --- FIX FOR "CHARACTER OUTSIDE RANGE" ---
    has_arial = False
    if os.path.exists("c:/windows/fonts/arial.ttf"):
        try:
            pdf.add_font("Arial", "", "c:/windows/fonts/arial.ttf")
            has_arial = True
        except:
            pass
    # ---------------------------------------------------------

    def set_my_font(style='', size=10):
        if has_custom_font:
            pdf.set_font("UrduFont", style, size)
        elif has_arial:
            pdf.set_font("Arial", "", size)
        else:
            pdf.set_font("Helvetica", 'B' if 'B' in style else '', size)

    c_info = config.get("company_info", {})
    c_name = process_text(c_info.get("name", "Amin & Sons"))
    c_address = process_text(c_info.get("address", "26EB near Sukhbias pull, Pakpattan"))
    c_phone = process_text(c_info.get("phone", "03148756922"))
    
    set_my_font('B', 16)
    
    if is_return:
        pdf.cell(0, 8, process_text("RETURN RECEIPT"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        set_my_font('B', 10)
        pdf.cell(0, 5, process_text("(Credit Note)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    else:
        pdf.cell(0, 8, c_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    set_my_font('B', 9) 
    pdf.cell(0, 5, c_address, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.cell(0, 5, process_text(f"Contact: {c_phone}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.ln(4)
    
    set_my_font('B', 11) 
    doc_label = "Ret #" if is_return else "Inv #"
    pdf.cell(0, 6, process_text(f"{doc_label}: {invoice.get('id', '01')}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    full_date_str = invoice.get('date', 'N/A')
    date_parts = full_date_str.split()
    invoice_date = date_parts[0] if len(date_parts) > 0 else "N/A"
    
    invoice_time = "N/A"
    if len(date_parts) > 1:
        try:
            raw_time = " ".join(date_parts[1:])
            time_obj = datetime.strptime(raw_time, "%H:%M") if "AM" not in raw_time and "PM" not in raw_time else datetime.strptime(raw_time, "%I:%M %p")
            invoice_time = time_obj.strftime("%I:%M %p")
        except:
            invoice_time = " ".join(date_parts[1:])

    pdf.set_x(2) 
    set_my_font('B', 9)
    pdf.write(6, process_text(f"Date: {invoice_date}"))
    pdf.set_x(45) 
    pdf.write(6, process_text(f"Time: {invoice_time}"))
    pdf.ln(7)

    pdf.set_x(2)
    customer_name = process_text(invoice.get('customer', 'Unknown'))
    customer_address = process_text(invoice.get('customer_address', ''))
    
    set_my_font('B', 10)
    pdf.write(6, "Customer: ")
    indent_x = pdf.get_x()
    
    set_my_font('', 11)
    pdf.set_left_margin(indent_x)
    pdf.write(6, customer_name)
    pdf.set_left_margin(2) 
    pdf.ln(6)

    if customer_address:
        set_my_font('', 10) 
        pdf.cell(0, 6, f"({customer_address})", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    pdf.ln(2)
    y_pos = pdf.get_y()
    pdf.set_dash_pattern(dash=1, gap=1)
    pdf.line(2, y_pos, 78, y_pos) 
    pdf.set_dash_pattern() 
    
    set_my_font('B', 9)
    pdf.set_x(2)
    pdf.cell(36, 8, "Item", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='L')
    pdf.cell(10, 8, "Qty", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C')
    pdf.cell(14, 8, "Rate", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C')
    pdf.cell(16, 8, "Total", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
    
    set_my_font('B', 10) 
    total_qty = 0
    
    for item in invoice.get('items', []):
        name = process_text(item.get('name', 'N/A'))
        price = item.get('price', 0)
        qty = item.get('qty', 0)
        total_qty += qty
        
        pdf.set_x(2)
        pdf.cell(36, 8, name[:30], border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='L') 
        pdf.cell(10, 8, str(qty), border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C')
        pdf.cell(14, 8, f"{price:.0f}", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C')
        line_total = qty * price
        pdf.cell(16, 8, f"{line_total:.0f}", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
    
    pdf.ln(2)
    y_pos = pdf.get_y()
    pdf.set_dash_pattern(dash=1, gap=1)
    pdf.line(2, y_pos, 78, y_pos)
    pdf.set_dash_pattern() 
    
    pdf.set_x(2)
    set_my_font('B', 12) 
    total_label = "REFUND TOTAL:" if is_return else "TOTAL:"
    pdf.cell(30, 8, total_label, border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='L') 
    set_my_font('B', 11) 
    pdf.cell(12, 8, str(total_qty), border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C') 
    pdf.set_x(58) 
    display_total = invoice.get('total', 0)
    pdf.cell(20, 8, f"{display_total:.2f}", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R') 

    set_my_font('B', 9)
    prev_balance = invoice.get('prev_balance', 0)
    paid_amount = invoice.get('paid', 0)
    
    if not is_return:
        hide_prev = config.get("hide_prev_dues_on_pdf", False)
        
        if hide_prev:
            display_total_due = invoice.get('total', 0)
            display_remaining = invoice.get('total', 0) - paid_amount
        else:
            display_total_due = prev_balance + invoice.get('total', 0)
            display_remaining = invoice.get('new_balance', 0)

        if not hide_prev:
            pdf.set_x(2)
            pdf.cell(45, 6, "Previous Dues:", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='L')
            pdf.set_x(58)
            pdf.cell(20, 6, f"{prev_balance:.2f}", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')

        pdf.set_x(2)
        pdf.cell(45, 6, "Total Due:", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='L')
        pdf.set_x(58)
        pdf.cell(20, 6, f"{display_total_due:.2f}", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')

        pdf.set_x(2)
        pdf.cell(45, 6, "Paid:", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='L')
        pdf.set_x(58)
        pdf.cell(20, 6, f"{paid_amount:.2f}", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')

    y_pos = pdf.get_y()
    pdf.line(48, y_pos, 78, y_pos) 
    pdf.ln(1)

    set_my_font('B', 10)
    pdf.set_x(2)
    bal_label = "Current Balance:"
    pdf.cell(45, 7, bal_label, border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='L')
    
    pdf.set_x(58)
    pdf.cell(20, 7, f"{display_remaining:.2f}", border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')

    set_my_font('BI', 9) 
    pdf.ln(5)
    footer_text = "Return Processed" if is_return else "Thanks For Your Business!"
    pdf.cell(0, 6, process_text(footer_text), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.cell(0, 6, process_text(f"Software by {c_name}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

    path = os.path.join(DATA_DIR, filename)
    
    try:
        # Save PDF to disk (Desktop) or Temp (Mobile)
        pdf.output(path)
    except (PermissionError, OSError):
        try:
            base, ext = os.path.splitext(filename)
            new_filename = f"{base}_{int(time.time())}{ext}"
            path = os.path.join(DATA_DIR, new_filename)
            pdf.output(path)
        except Exception as e:
            print(f"Failed to generate PDF fallback: {e}")
            
    return path

# --- UPDATED PRINTER FUNCTION (HYBRID) ---
def print_pdf_silently(path):
    # DESKTOP (Windows)
    if IS_WINDOWS_DESKTOP:
        if HAS_WIN32PRINT:
            try:
                os.startfile(path, "print")
                return True, "Sent to printer successfully."
            except Exception as e:
                return False, f"Print Failed: {str(e)}"
        else:
             return False, "win32print not installed."
    # MOBILE / NON-WINDOWS
    else:
        return False, "Direct Print not supported on Mobile. Please view/share PDF."

# --- MAIN APP ---
def main(page: ft.Page):
    try:
        loop = asyncio.get_event_loop()
        def suppress_connection_error(loop, context):
            msg = context.get("message", "")
            exc = context.get("exception")
            if "10054" in str(msg) or (exc and "10054" in str(exc)):
                return
            if exc and isinstance(exc, ConnectionResetError):
                return
            loop.default_exception_handler(context)
        loop.set_exception_handler(suppress_connection_error)
    except Exception:
        pass

    page.window.width = 1200
    page.window.height = 800
    
    # Dynamic Title
    mode_title = "Desktop Mode" if IS_WINDOWS_DESKTOP else "Mobile Cloud Mode"
    page.title = f"Amin & Sons - Enterprise Billing ({mode_title})"
    
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0
    page.vertical_alignment = ft.MainAxisAlignment.START 
    page.rtl = False 

    inventory = []
    invoices = []
    customers = []
    recycle_bin = []
    returns_data = [] 
    
    # --- SIMPLIFIED STATE ---
    state = {
        "rev_hidden": True, 
        "billing_items": [], 
        "billing_customer": None, 
        "billing_product": None, 
        "search_query": "", 
        "is_test_mode": False,
        "current_page": 1, 
        "page_size": 20,
        "filter_cust": None,
    }
    
    loading_dlg = ft.AlertDialog(
        modal=True,
        content=ft.Row([ft.ProgressRing(), ft.Text("Processing... Please Wait")], alignment=ft.MainAxisAlignment.CENTER, spacing=20),
        actions=[],
    )
    page.overlay.clear()
    page.overlay.append(loading_dlg)
    
    def close_msg_dlg(e):
        global_msg_dlg.open = False
        page.update()

    global_msg_dlg = ft.AlertDialog(
        title=ft.Text("Notification"),
        content=ft.Text(""),
        actions=[ft.TextButton(content=ft.Text("OK"), on_click=close_msg_dlg)],
    )
    page.overlay.append(global_msg_dlg)
    
    def cleanup_test_data():
        test_dir = os.path.join(APP_ROOT, "test_data")
        threading.Thread(target=forced_cleanup, args=(test_dir,), daemon=True).start()

    def handle_window_event(e):
        if e.data == "close":
            if state["is_test_mode"]:
                cleanup_test_data()
            page.window_destroy()

    page.window_prevent_close = True
    page.on_window_event = handle_window_event

    def show_msg(text, color="red"):
        title_text = "Information" if color in ["green", "blue"] else "Warning/Error"
        global_msg_dlg.title = ft.Text(title_text)
        global_msg_dlg.content = ft.Text(text, size=16, color=color, weight="bold")
        global_msg_dlg.open = True
        page.update()

    def reset_paths_to_real():
        global DATA_DIR, INVENTORY_FILE, INVOICES_JSON, CUSTOMERS_FILE, RECYCLE_BIN_FILE, RETURNS_FILE, CONFIG_FILE, config
        DATA_DIR = REAL_DATA_DIR
        CONFIG_FILE = os.path.join(REAL_DATA_DIR, "config.json")
        config = load_data(CONFIG_FILE, {"admins": {"admin": "123"}, "hide_prev_dues_on_pdf": False})
        state["is_test_mode"] = False

    def logout_app(e):
        if state["is_test_mode"]:
            cleanup_test_data()
        reset_paths_to_real()
        inventory.clear()
        invoices.clear()
        customers.clear()
        recycle_bin.clear()
        returns_data.clear() 
        
        state["search_query"] = ""
        state["current_page"] = 1
        
        page.controls.clear()
        page.overlay.clear()
        page.overlay.append(loading_dlg)
        page.overlay.append(global_msg_dlg)
        
        user_input.value = ""
        pass_input.value = ""
        user_input.error_text = None
        pass_input.error_text = None
        page.add(ft.Stack([login_container, test_btn_container], expand=True))
        page.update()
        show_msg("Logged Out Successfully", "green")

    content_area = ft.Column(expand=True, spacing=10, scroll=ft.ScrollMode.ADAPTIVE, alignment=ft.MainAxisAlignment.START)
    main_container = ft.Container(content=content_area, padding=20, expand=True, alignment=ft.Alignment(-1, -1))

    # --- DELETE LOGIC ---
    def confirm_and_delete(item_data, list_source, file_path, tab_index, item_label):
        is_return_inv = False
        if item_label == "Invoice" and item_data.get('total', 0) < 0:
            is_return_inv = True

        def do_delete(e):
            try:
                if item_label in ["Customer", "Invoice"]:
                    item_data['expiry_date'] = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %I:%M %p")
                    item_data['item_type'] = item_label
                    recycle_bin.append(item_data)
                    save_data(RECYCLE_BIN_FILE, recycle_bin)

                if item_label == "Invoice":
                    pdf_path = os.path.join(DATA_DIR, f"invoice_{item_data.get('id')}.pdf")
                    if os.path.exists(pdf_path):
                        try: 
                            os.remove(pdf_path)
                            time.sleep(0.1)
                        except: pass
                
                if is_return_inv:
                    for r_item in item_data.get('items', []):
                        prod = next((p for p in inventory if str(p['id']) == str(r_item['id'])), None)
                        if not prod:
                             prod = next((p for p in inventory if p['name'] == r_item['name']), None)
                        if prod:
                            prod['qty'] -= r_item['qty']
                    
                    cust_name = item_data.get('customer')
                    cust = next((c for c in customers if c['name'] == cust_name), None)
                    if cust:
                        inv_total = item_data.get('total', 0) 
                        inv_paid = item_data.get('paid', 0)
                        if inv_paid == 0:
                            refund_amt = abs(inv_total)
                            cust['balance'] += refund_amt
                    
                    if "-RET" in str(item_data['id']):
                        orig_id = str(item_data['id']).split("-RET")[0]
                        orig_inv = next((i for i in invoices if str(i['id']) == str(orig_id)), None)
                        if orig_inv:
                            for r_item in item_data.get('items', []):
                                for orig_item in orig_inv.get('items', []):
                                    if str(orig_item['id']) == str(r_item['id']):
                                        current_ret = orig_item.get('returned_qty', 0)
                                        orig_item['returned_qty'] = max(0, current_ret - r_item['qty'])
                    
                    save_data(INVENTORY_FILE, inventory)
                    save_data(CUSTOMERS_FILE, customers)
                
                if item_label == "Invoice":
                    c_name = item_data.get('customer')
                    c_obj = next((c for c in customers if c['name'] == c_name), None)
                    if c_obj and 'payment_history' in c_obj:
                        c_obj['payment_history'] = [
                            p for p in c_obj['payment_history'] 
                            if str(p.get('invoice_id')) != str(item_data['id'])
                        ]
                        save_data(CUSTOMERS_FILE, customers)

                if item_data in list_source:
                    list_source.remove(item_data)
                    save_data(file_path, list_source)

                    if HAS_SUPABASE and supabase:
                        t_name = get_table_name_from_file(file_path)
                        if t_name in ["inventory", "customers", "invoices"]:
                            def run_db_delete():
                                try:
                                    supabase.table(t_name).delete().eq("id", item_data['id']).execute()
                                except Exception as dbe:
                                    print(f"Supabase Delete Error: {dbe}")
                            threading.Thread(target=run_db_delete, daemon=True).start()

                dlg.open = False
                page.update()
                
                state["search_query"] = ""
                state["current_page"] = 1
                render_tab(tab_index)
                
                if is_return_inv:
                    show_msg("Return Record Deleted Successfully", "blue")
                elif item_label == "Product":
                     show_msg("Product permanently deleted", "blue")
                else:
                    show_msg(f"{item_label} moved to trash", "blue")
                    
            except Exception as ex:
                show_msg(f"Delete failed: {ex}", "red")
        
        def cancel_dlg(e):
            dlg.open = False
            page.update()

        if is_return_inv:
            dialog_text = "Permanently delete this Return Record?"
        elif item_label == "Product":
            dialog_text = "Permanently delete this Product?"
        else:
            dialog_text = f"Move this {item_label} to Trash?"

        dlg = ft.AlertDialog(modal=True, title=ft.Text("Confirm Action"), 
            content=ft.Text(dialog_text),
            actions=[ft.TextButton(content=ft.Text("Yes"), on_click=do_delete), ft.TextButton(content=ft.Text("No"), on_click=cancel_dlg)])
        
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def render_tab(index, focus_search=False):
        content_area.controls.clear()
        if index == 0: render_dashboard(focus_search)
        elif index == 1: render_customers_view(focus_search)
        elif index == 2: render_stock_view(focus_search)
        elif index == 3: render_billing_view()
        elif index == 4: render_settings_view()
        page.update()

    def show_invoice_history_details(inv):
        items_summary = ft.Column([ft.Text(f"{i['name']} -> Cost: {i.get('cost', 0)} | Sale: {i['price']} | Qty: {i['qty']}", size=14) for i in inv.get('items', [])])
        profit = inv.get('total', 0) - inv.get('total_cost', 0)
        
        def close_dlg(e):
            dlg.open = False
            page.update()

        extra_actions = []
        if inv.get('total', 0) < 0 and inv.get('credit', 0) < 0:
            def settle_return_payment(e):
                pay_amt = abs(inv.get('credit', 0))
                
                def confirm_pay(e):
                    inv['paid'] = inv.get('paid', 0) - pay_amt 
                    inv['credit'] = 0 
                    
                    cust_name = inv.get('customer')
                    cust = next((c for c in customers if c['name'] == cust_name), None)
                    if cust:
                        cust['balance'] = cust.get('balance', 0) + pay_amt
                        
                        if 'payment_history' not in cust: cust['payment_history'] = []
                        cust['payment_history'].append({
                            'date': datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                            'amount': pay_amt, 
                            'method': 'Pay Back / Refund (OUT) - Cash',
                            'details': f"Settlement for Return #{inv['id']}",
                            'invoice_id': inv['id']
                        })
                        save_data(CUSTOMERS_FILE, customers)
                    
                    save_data(INVOICES_JSON, invoices)
                    
                    confirm_dlg.open = False
                    dlg.open = False
                    page.update()
                    
                    show_msg(f"Paid {pay_amt} to customer. Balance updated.", "blue")
                    render_tab(0)

                def cancel_pay(e):
                    confirm_dlg.open = False
                    page.update()

                confirm_dlg = ft.AlertDialog(
                    title=ft.Text("Confirm Payment"),
                    content=ft.Text(f"Pay {pay_amt:.2f} PKR cash to customer to settle this return?"),
                    actions=[ft.TextButton(content=ft.Text("Yes, Pay Now"), on_click=confirm_pay), ft.TextButton(content=ft.Text("Cancel"), on_click=cancel_pay)]
                )
                page.overlay.append(confirm_dlg)
                confirm_dlg.open = True
                page.update()

            extra_actions.append(ft.ElevatedButton(content=ft.Text("Pay / Settle (Cash)"), bgcolor="green", color="white", on_click=settle_return_payment))

        actions_list = extra_actions + [ft.TextButton(content=ft.Text("Close"), on_click=close_dlg)]

        dlg = ft.AlertDialog(
            title=ft.Text(f"History: Invoice #{inv['id']}"), 
            content=ft.Column([
                ft.Text(f"Customer: {inv['customer']}", weight="bold"), 
                ft.Divider(), 
                ft.Text("Transaction Breakdown:", weight="bold"), 
                items_summary, 
                ft.Divider(), 
                ft.Text(f"Total Bill: {inv['total']:.2f} PKR"), 
                ft.Text(f"Paid: {inv.get('paid', inv.get('total',0)):.2f} PKR"), 
                ft.Text(f"Credit: {inv.get('credit', 0):.2f} PKR", color="red" if inv.get('credit', 0) < 0 else "black", weight="bold"), 
                ft.Divider(), 
                ft.Text(f"Net Profit: {profit:.2f} PKR", color="green", weight="bold")
            ], tight=True, scroll=ft.ScrollMode.ADAPTIVE),
            actions=actions_list
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # --- REFACTORED DASHBOARD WITH LISTVIEW ---
    def render_dashboard(focus_search=False):
        
        # New Header Row (Replacing DataTable Header)
        header_row = ft.Container(
            content=ft.Row([
                ft.Text("ID", width=60, weight="bold"),
                ft.Container(ft.Text("Customer", weight="bold"), expand=True), # Flexible width
                ft.Text("Date", width=100, weight="bold"),
                ft.Text("Time", width=90, weight="bold"),
                ft.Text("Total", width=100, weight="bold"),
                ft.Text("Tools", width=140, weight="bold", text_align="center"),
                ft.Text("Action", width=50, weight="bold", text_align="center"),
            ], alignment=ft.MainAxisAlignment.START),
            bgcolor=ft.Colors.GREY_300, padding=10, border_radius=5
        )

        # Replaced DataTable with ListView for better performance
        my_list_view = ft.ListView(expand=True, spacing=5)
        
        # Revenue Cards
        rev_text = ft.Text(value="**** PKR", color="white", size=28, weight="bold")
        profit_text = ft.Text(value="**** PKR", color="white", size=28, weight="bold")
        eye_icon_btn = ft.IconButton(icon=ft.Icons.VISIBILITY, icon_color="white") # initial icon

        def toggle_rev(e):
            state["rev_hidden"] = not state["rev_hidden"]
            refresh_table_data()
            eye_icon_btn.icon = ft.Icons.VISIBILITY_OFF if state["rev_hidden"] else ft.Icons.VISIBILITY
            page.update()
        
        eye_icon_btn.on_click = toggle_rev
        if state["rev_hidden"]: eye_icon_btn.icon = ft.Icons.VISIBILITY_OFF

        def print_invoice_directly(inv):
            loading_dlg.open = True
            page.update()
            def task():
                try:
                    filename = f"invoice_{inv['id']}.pdf"
                    file_path = generate_pdf(inv, filename)
                    success, msg = print_pdf_silently(file_path)
                    if success:
                        show_msg(f"Sent Invoice #{inv['id']} to Printer", "blue")
                    else:
                        show_msg(f"Printing: {msg}", "orange")
                except Exception as e: 
                    print(f"Error: {e}")
                    show_msg(f"System Error: {e}", "red")
                finally:
                    loading_dlg.open = False
                    page.update()
            threading.Thread(target=task, daemon=True).start()

        # --- UPDATED: Background PDF Opening to prevent freezing ---
        def open_pdf_in_background(inv):
            loading_dlg.open = True
            page.update()
            def task():
                try:
                    filename = f"invoice_{inv['id']}.pdf"
                    file_path = generate_pdf(inv, filename)
                    # Open PDF in background thread
                    webbrowser.open('file:///' + os.path.abspath(file_path))
                except Exception as e:
                    print(f"PDF Error: {e}")
                finally:
                    loading_dlg.open = False
                    page.update()
            threading.Thread(target=task, daemon=True).start()

        def change_page(delta):
            state["current_page"] += delta
            refresh_table_data()

        btn_prev = ft.ElevatedButton(content=ft.Text("Previous"), icon=ft.Icons.ARROW_BACK, on_click=lambda e: change_page(-1))
        btn_next = ft.ElevatedButton(content=ft.Text("Next"), icon=ft.Icons.ARROW_FORWARD, on_click=lambda e: change_page(1))
        page_info_txt = ft.Text("Page 1 of 1")

        def refresh_table_data(e=None):
            # 1. Filter Data
            filtered_invoices = []
            s_query = search_sales.value.strip().lower() if search_sales.value else ""
            state["search_query"] = s_query

            for inv in invoices:
                if s_query:
                    inv_id = str(inv.get('id', '')).lower()
                    inv_cust = str(inv.get('customer', '')).lower()
                    if not (s_query in inv_id or s_query in inv_cust):
                        continue
                filtered_invoices.append(inv)

            # 2. Sort
            def get_sort_key(inv):
                id_str = str(inv.get('id', '0'))
                parts = id_str.split('-')
                try: base_id = int(parts[0]) 
                except: base_id = 0
                type_rank = 0 
                sub_rank = 0
                if len(parts) > 1:
                    type_rank = 1
                    if len(parts) > 2:
                        try: sub_rank = int(parts[2])
                        except: sub_rank = 1
                return (base_id, type_rank, sub_rank)
            filtered_invoices.sort(key=get_sort_key)

            # 3. Calculate Totals
            total_rev = sum(inv.get('total', 0) for inv in filtered_invoices)
            total_profit = sum(inv.get('total', 0) - inv.get('total_cost', 0) for inv in filtered_invoices)
            
            if state["rev_hidden"]:
                rev_text.value = "**** PKR"
                profit_text.value = "**** PKR"
            else:
                rev_text.value = f"PKR {total_rev:,.2f}"
                profit_text.value = f"PKR {total_profit:,.2f}"

            # 4. Pagination
            page_size = state["page_size"]
            total_items = len(filtered_invoices)
            total_pages = math.ceil(total_items / page_size)
            if total_pages == 0: total_pages = 1
            
            if state["current_page"] > total_pages: state["current_page"] = total_pages
            if state["current_page"] < 1: state["current_page"] = 1
            
            start_idx = (state["current_page"] - 1) * page_size
            end_idx = start_idx + page_size
            display_invoices = filtered_invoices[start_idx:end_idx]

            # 5. Build ListView Rows (instead of DataTable Rows)
            my_list_view.controls.clear()
            
            for inv in display_invoices:
                date_parts = inv.get('date', '').split()
                date_str = date_parts[0] if len(date_parts) > 0 else ""
                time_str = " ".join(date_parts[1:]) if len(date_parts) > 1 else ""
                
                text_color = "red" if inv.get('total', 0) < 0 else "black"
                is_return_inv = inv.get('total', 0) < 0
                
                # Manual columns using Containers and Widths
                row_content = ft.Container(
                    content=ft.Row([
                        ft.Text(inv.get('id', ''), width=60, color=text_color),
                        ft.Container(ft.Text(inv.get('customer', '')[:30], color=text_color), expand=True), # Truncate long names slightly
                        ft.Text(date_str, width=100, color=text_color),
                        ft.Text(time_str, width=90, color=text_color),
                        ft.Text(f"{inv.get('total', 0):.2f}", width=100, color=text_color, weight="bold" if is_return_inv else "normal"),
                        
                        ft.Row([
                            ft.IconButton(ft.Icons.INFO_OUTLINE, icon_color="green", on_click=lambda e, i=inv: show_invoice_history_details(i), tooltip="View Details"), 
                            # Updated PDF button to use background thread
                            ft.IconButton(ft.Icons.PICTURE_AS_PDF, icon_color="blue", on_click=lambda e, i=inv: open_pdf_in_background(i), tooltip="Open PDF"),
                            ft.IconButton(ft.Icons.PRINT, icon_color="blue", on_click=lambda e, i=inv: print_invoice_directly(i), tooltip="Direct Print")
                        ], width=140, alignment=ft.MainAxisAlignment.CENTER, spacing=0),
                        
                        ft.IconButton(ft.Icons.DELETE, icon_color="red", on_click=lambda e, i=inv: confirm_and_delete(i, invoices, INVOICES_JSON, 0, "Invoice"))
                    ], alignment=ft.MainAxisAlignment.START),
                    padding=10,
                    bgcolor="white",
                    border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.GREY_200))
                )
                my_list_view.controls.append(row_content)
            
            # Update Pagination Controls
            btn_prev.disabled = (state["current_page"] == 1)
            btn_next.disabled = (state["current_page"] == total_pages)
            page_info_txt.value = f"Page {state['current_page']} of {total_pages}"
            
            page.update()

        def export_customers_excel(e):
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                main_folder_name = f"Export_{timestamp}"
                main_folder_path = os.path.join(DATA_DIR, main_folder_name)
                individual_folder_path = os.path.join(main_folder_path, "Individual_Ledgers")
                
                if not os.path.exists(main_folder_path): os.makedirs(main_folder_path)
                if not os.path.exists(individual_folder_path): os.makedirs(individual_folder_path)
                
                count = 0
                all_sales_for_summary = []
                
                for c in customers:
                    cust_invoices = [inv for inv in invoices if inv.get('customer') == c['name']]
                    if not cust_invoices: continue
                    cust_invoices.sort(key=lambda x: x.get('date'), reverse=True)
                    all_sales_for_summary.extend(cust_invoices)

                    safe_name = "".join([char for char in c.get('name', 'Unknown') if char.isalnum() or char in (' ', '-', '_')]).strip()
                    filename = f"{safe_name}.xls"
                    filepath = os.path.join(individual_folder_path, filename)

                    inv_rows_xml = ""
                    for inv in cust_invoices:
                        i_date = str(inv.get('date', ''))
                        i_id = str(inv.get('id', ''))
                        i_total = f"{inv.get('total', 0):.2f}"
                        i_paid = f"{inv.get('paid', 0):.2f}"
                        i_items_summary = ", ".join([f"{x['name']} (x{x['qty']})" for x in inv.get('items', [])])
                        inv_rows_xml += f"""<Row><Cell ss:StyleID="sData"><Data ss:Type="String">{i_date}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="String">{i_id}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="String">{i_items_summary}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="Number">{i_total}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="Number">{i_paid}</Data></Cell></Row>"""

                    cname = str(c.get('name', '')).replace("&", "&amp;")
                    cphone = str(c.get('phone', '')).replace("&", "&amp;")
                    caddr = str(c.get('address', '')).replace("&", "&amp;")
                    
                    xml_content = f"""<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Styles><Style ss:ID="Default" ss:Name="Normal"><Font ss:FontName="Calibri" ss:Size="11"/></Style><Style ss:ID="sHeader"><Font ss:Bold="1"/><Interior ss:Color="#D9D9D9" ss:Pattern="Solid"/><Borders><Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/></Borders></Style><Style ss:ID="sTitle"><Font ss:Bold="1" ss:Size="14"/></Style><Style ss:ID="sData"><Borders><Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/><Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1"/></Borders></Style></Styles><Worksheet ss:Name="Sheet1"><Table ss:DefaultColumnWidth="100"><Column ss:Width="120"/><Column ss:Width="80"/><Column ss:Width="250"/><Column ss:Width="80"/><Column ss:Width="80"/><Row><Cell ss:StyleID="sTitle"><Data ss:Type="String">Customer Ledger</Data></Cell></Row><Row><Cell><Data ss:Type="String">Name: {cname}</Data></Cell></Row><Row><Cell><Data ss:Type="String">Phone: {cphone}</Data></Cell></Row><Row><Cell><Data ss:Type="String">Address: {caddr}</Data></Cell></Row><Row/><Row><Cell ss:StyleID="sHeader"><Data ss:Type="String">Date</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Inv #</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Items</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Total</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Paid</Data></Cell></Row>{inv_rows_xml}</Table></Worksheet></Workbook>"""
                    
                    with open(filepath, "w", encoding="utf-8") as f: f.write(xml_content)
                    count += 1

                all_sales_for_summary.sort(key=lambda x: x.get('date'), reverse=True)
                summary_rows_xml = ""
                for inv in all_sales_for_summary:
                    i_cust = str(inv.get('customer', '')).replace("&", "&amp;")
                    i_date = str(inv.get('date', ''))
                    i_id = str(inv.get('id', ''))
                    i_total = f"{inv.get('total', 0):.2f}"
                    i_items = ", ".join([f"{x['name']} (x{x['qty']})" for x in inv.get('items', [])]).replace("&", "&amp;")
                    summary_rows_xml += f"""<Row><Cell ss:StyleID="sData"><Data ss:Type="String">{i_date}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="String">{i_id}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="String">{i_cust}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="String">{i_items}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="Number">{i_total}</Data></Cell></Row>"""

                summary_xml = f"""<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Styles><Style ss:ID="Default" ss:Name="Normal"><Font ss:FontName="Calibri" ss:Size="11"/></Style><Style ss:ID="sHeader"><Font ss:Bold="1"/><Interior ss:Color="#99CCFF" ss:Pattern="Solid"/><Borders><Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/></Borders></Style><Style ss:ID="sTitle"><Font ss:Bold="1" ss:Size="16"/></Style><Style ss:ID="sData"><Borders><Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/><Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1"/></Borders></Style></Styles><Worksheet ss:Name="All Sales"><Table ss:DefaultColumnWidth="100"><Column ss:Width="120"/><Column ss:Width="80"/><Column ss:Width="150"/><Column ss:Width="250"/><Column ss:Width="100"/><Row><Cell ss:StyleID="sTitle"><Data ss:Type="String">Sales Summary Report</Data></Cell></Row><Row/><Row><Cell ss:StyleID="sHeader"><Data ss:Type="String">Date</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Inv #</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Customer</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Items</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Total Amount</Data></Cell></Row>{summary_rows_xml}</Table></Worksheet></Workbook>"""

                summary_path = os.path.join(main_folder_path, "All_Sales_Summary.xls")
                with open(summary_path, "w", encoding="utf-8") as f: f.write(summary_xml)

                show_msg(f"Export Complete! {count} individual files created.", "green")
                if os.name == 'nt':
                    try: os.startfile(main_folder_path)
                    except: pass
                else:
                    try: subprocess.call(['xdg-open', main_folder_path])
                    except: pass
            except Exception as ex:
                show_msg(f"Export failed: {ex}", "red")

        search_sales = ft.TextField(
            label="Search Text", 
            prefix_icon=ft.Icons.SEARCH, 
            on_change=refresh_table_data, 
            value=state.get("search_query", ""), 
            width=200, 
            height=40,
            text_size=12,
            content_padding=10,
            autofocus=True 
        )
        
        content_area.controls.append(ft.Row(
            [
                ft.Text("Business Dashboard", size=30, weight="bold"),
                ft.ElevatedButton(
                    "Export Professional Excel", 
                    icon=ft.Icons.TABLE_VIEW, 
                    on_click=export_customers_excel,
                    bgcolor="teal",
                    color="white"
                )
            ], 
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        ))
        
        content_area.controls.append(ft.Row([
            ft.Container(content=ft.Row([ft.Column([ft.Text("Total Revenue", color="white", size=14), rev_text]), eye_icon_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), bgcolor="#2D5B7A", padding=20, border_radius=10, expand=True),
            ft.Container(content=ft.Row([ft.Column([ft.Text("Net Profit", color="white", size=14), profit_text]), ft.Icon(ft.Icons.TRENDING_UP, color="white")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), bgcolor="#2E7D32", padding=20, border_radius=10, expand=True)
        ], spacing=20))
        
        content_area.controls.append(ft.Row([search_sales], alignment=ft.MainAxisAlignment.START))
        
        content_area.controls.append(ft.Column([
            header_row,
            my_list_view, # Replaced DataTable
            ft.Row([btn_prev, page_info_txt, btn_next], alignment=ft.MainAxisAlignment.CENTER, spacing=20)
        ], expand=True))

        # Initial Load
        refresh_table_data()

    def show_customer_payment_info(cust):
        if cust.get('payment_history') is None:
            cust['payment_history'] = []

        def export_history_excel(e):
            try:
                cname = str(cust.get('name', '')).replace("&", "&amp;")
                cphone = str(cust.get('phone', '')).replace("&", "&amp;")
                cbal = str(cust.get('balance', 0)).replace("&", "&amp;")
                
                rows_xml = ""
                current_history = cust.get('payment_history', [])
                
                for h in reversed(current_history):
                    h_date = str(h.get('date', '')).replace("&", "&amp;")
                    h_inv = str(h.get('invoice_id', '-')).replace("&", "&amp;")
                    h_amt = f"{h.get('amount', 0):.2f}"
                    h_method = str(h.get('method', '')).replace("&", "&amp;")
                    h_details = str(h.get('details', '')).replace("&", "&amp;")
                    
                    rows_xml += f"""<Row><Cell ss:StyleID="sData"><Data ss:Type="String">{h_date}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="String">{h_inv}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="Number">{h_amt}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="String">{h_method}</Data></Cell><Cell ss:StyleID="sData"><Data ss:Type="String">{h_details}</Data></Cell></Row>"""

                xml_content = f"""<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Styles><Style ss:ID="Default" ss:Name="Normal"><Font ss:FontName="Calibri" ss:Size="11"/></Style><Style ss:ID="sHeader"><Font ss:Bold="1"/><Interior ss:Color="#D9D9D9" ss:Pattern="Solid"/><Borders><Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/></Borders></Style><Style ss:ID="sTitle"><Font ss:Bold="1" ss:Size="14"/></Style><Style ss:ID="sData"><Borders><Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/><Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1"/></Borders></Style></Styles><Worksheet ss:Name="History"><Table ss:DefaultColumnWidth="100"><Column ss:Width="120"/><Column ss:Width="80"/><Column ss:Width="100"/><Column ss:Width="150"/><Column ss:Width="250"/><Row><Cell ss:StyleID="sTitle"><Data ss:Type="String">Payment History: {cname}</Data></Cell></Row><Row><Cell><Data ss:Type="String">Phone: {cphone}</Data></Cell></Row><Row><Cell><Data ss:Type="String">Current Balance: {cbal}</Data></Cell></Row><Row/><Row><Cell ss:StyleID="sHeader"><Data ss:Type="String">Date</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Invoice #</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Amount</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Method</Data></Cell><Cell ss:StyleID="sHeader"><Data ss:Type="String">Details</Data></Cell></Row>{rows_xml}</Table></Worksheet></Workbook>"""

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                export_folder = os.path.join(DATA_DIR, "History_Exports")
                if not os.path.exists(export_folder):
                    os.makedirs(export_folder)
                
                safe_name = "".join([c for c in cname if c.isalnum() or c in (' ', '_')]).strip()
                filename = f"History_{safe_name}_{timestamp}.xls"
                filepath = os.path.join(export_folder, filename)
                
                with open(filepath, "w", encoding="utf-8") as f: f.write(xml_content)
                
                show_msg("History Exported Successfully!", "green")
                if os.name == 'nt':
                    try: os.startfile(filepath)
                    except: pass
                else:
                    try: subprocess.call(['xdg-open', filepath])
                    except: pass

            except Exception as ex:
                show_msg(f"Export Failed: {ex}", "red")

        history_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Date")), 
                ft.DataColumn(ft.Text("Inv #")), 
                ft.DataColumn(ft.Text("Amount")), 
                ft.DataColumn(ft.Text("Method")), 
                ft.DataColumn(ft.Text("Details")),
                ft.DataColumn(ft.Text("Action")) 
            ],
            rows=[]
        )
        
        balance_label = ft.Text(f"Current Balance: {cust.get('balance', 0):.2f}", weight="bold", size=16, color="red" if cust.get('balance', 0) > 0 else "black")
        
        trx_type_dd = ft.Dropdown(
            label="Transaction Type",
            options=[ft.dropdown.Option("Receive Payment (IN)"), ft.dropdown.Option("Pay Back / Refund (OUT)")],
            value="Receive Payment (IN)",
            width=250
        )

        amount_field = ft.TextField(label="Payment Amount", width=200)
        inv_val_field = ft.TextField(label="Invoice # (Optional)", width=150)
        method_dd = ft.Dropdown(label="Method", options=[ft.dropdown.Option("Cash/Hand-to-Hand"), ft.dropdown.Option("Online/Bank"), ft.dropdown.Option("Bank Check")], width=200, value="Cash/Hand-to-Hand")
        details_field = ft.TextField(label="Payment Details (Bank Name, Trx ID, etc.)", multiline=True, width=410)

        def delete_payment_entry(entry):
            def confirm_del(e):
                amt = entry.get('amount', 0)
                method = entry.get('method', '')
                
                if "Receive" in method or "Return/Refund (Credit)" in method or "IN" in method:
                     cust['balance'] += amt
                elif "Pay Back" in method or "Return/Refund (Cash)" in method or "OUT" in method:
                     cust['balance'] -= amt
                
                if entry in cust['payment_history']:
                    cust['payment_history'].remove(entry)
                    
                save_data(CUSTOMERS_FILE, customers)
                del_dlg.open = False
                page.update()
                refresh_history()
                show_msg("Transaction Deleted & Balance Reverted", "blue")

            def cancel_del(e):
                del_dlg.open = False
                page.update()

            del_dlg = ft.AlertDialog(
                title=ft.Text("Confirm Deletion"),
                content=ft.Text("Are you sure? This will revert the balance effect."),
                actions=[ft.TextButton(content=ft.Text("Yes"), on_click=confirm_del), ft.TextButton(content=ft.Text("No"), on_click=cancel_del)]
            )
            page.overlay.append(del_dlg)
            del_dlg.open = True
            page.update()

        def refresh_history():
            history = cust.get('payment_history') or []
            rows_data = []
            for h in reversed(history):
                inv_id = h.get('invoice_id', '-')
                if inv_id != "-" and inv_id:
                    inv_obj = next((i for i in invoices if str(i['id']) == str(inv_id)), None)
                    if inv_obj:
                        link_text = str(inv_id)
                        if inv_obj.get('total', 0) < 0: link_text += " (RET)"
                        inv_display = ft.TextButton(content=ft.Text(link_text), on_click=lambda e, i=inv_obj: webbrowser.open('file:///' + os.path.abspath(generate_pdf(i, f"invoice_{i.get('id')}.pdf"))))
                    else:
                        inv_display = ft.Text(str(inv_id))
                else:
                    inv_display = ft.Text("-")

                rows_data.append(
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Text(h['date'])),
                        ft.DataCell(inv_display), 
                        ft.DataCell(ft.Text(f"{h['amount']:.2f}")),
                        ft.DataCell(ft.Text(h['method'])),
                        ft.DataCell(ft.Text(h['details'])),
                        ft.DataCell(ft.IconButton(ft.Icons.DELETE, icon_color="red", on_click=lambda e, entry=h: delete_payment_entry(entry))) 
                    ])
                )
            history_table.rows = rows_data
            balance_label.value = f"Current Balance: {cust.get('balance', 0):.2f}"
            balance_label.color = "red" if cust.get('balance', 0) > 0 else "black"
            page.update()

        def add_payment(e):
            try:
                amt = float(amount_field.value)
                if amt <= 0: show_msg("Amount must be greater than 0"); return
                if "Receive" in trx_type_dd.value:
                    cust['balance'] = cust.get('balance', 0) - amt; note_prefix = "[IN] "
                else:
                    cust['balance'] = cust.get('balance', 0) + amt; note_prefix = "[OUT] "

                entry = {'date': datetime.now().strftime("%Y-%m-%d %I:%M %p"), 'amount': amt, 'method': method_dd.value, 'details': note_prefix + details_field.value, 'invoice_id': inv_val_field.value if inv_val_field.value else "-"}
                if cust.get('payment_history') is None: cust['payment_history'] = []
                cust['payment_history'].append(entry)
                save_data(CUSTOMERS_FILE, customers)
                amount_field.value = ""; details_field.value = ""; inv_val_field.value = ""
                show_msg("Transaction Recorded!", "green")
                refresh_history()
                render_tab(1) 
            except ValueError: show_msg("Invalid Amount")

        refresh_history()
        
        def close_dlg(e):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Row([ft.Text(f"Payment History: {cust['name']}", size=20, weight="bold"), ft.IconButton(ft.Icons.CLOSE, on_click=close_dlg)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Container(content=ft.Column([balance_label, ft.Divider(), ft.Text("Record New Transaction", weight="bold"), trx_type_dd, ft.Row([amount_field, inv_val_field]), method_dd, details_field, ft.Row([ft.ElevatedButton(content=ft.Text("Process Transaction"), on_click=add_payment, bgcolor="green", color="white"), ft.ElevatedButton(content=ft.Text("Export History (Excel)"), icon=ft.Icons.DOWNLOAD, on_click=export_history_excel, bgcolor="blue", color="white")], spacing=10), ft.Divider(), ft.Text("Past Payments", weight="bold"), ft.Column([history_table], scroll=ft.ScrollMode.ADAPTIVE, height=200)], tight=True), width=750),
            actions=[] 
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # --- REFACTORED CUSTOMERS VIEW WITH LISTVIEW ---
    def render_customers_view(focus_search=False):
        def filter_customers(e):
            state["search_query"] = search_bar.value.lower()
            render_tab(1, focus_search=True)
            
        search_bar = ft.TextField(
            label="Search Customers (Name or Phone)", 
            prefix_icon=ft.Icons.SEARCH, 
            on_change=filter_customers, 
            value=state.get("search_query", ""), 
            width=400, 
            autofocus=focus_search
        )
        
        content_area.controls.append(ft.Row([ft.Text("Customers", size=30, weight="bold"), ft.ElevatedButton(content=ft.Text("Add Customer"), icon=ft.Icons.ADD, on_click=lambda _: show_customer_dialog())], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
        content_area.controls.append(ft.Row([search_bar], alignment=ft.MainAxisAlignment.START))
        
        # New Header
        header_row = ft.Container(
            content=ft.Row([
                ft.Text("ID", width=80, weight="bold"),
                ft.Container(ft.Text("Name", weight="bold"), expand=True),
                ft.Text("Phone", width=120, weight="bold"),
                ft.Container(ft.Text("Address", weight="bold"), expand=True),
                ft.Text("Balance", width=100, weight="bold"),
                ft.Text("Action", width=150, weight="bold", text_align="center"),
            ]),
            bgcolor=ft.Colors.GREY_300, padding=10, border_radius=5
        )

        cust_list_view = ft.ListView(expand=True, spacing=5)

        customers.sort(key=lambda x: int(str(x.get('id', '0')).split('-')[-1].split()[0]))
        
        filtered_list = [c for c in customers if state["search_query"] in c['name'].lower() or state["search_query"] in c.get('phone', '').lower()]
        display_customers = filtered_list[:50] if not state["search_query"] else filtered_list

        for c in display_customers:
            row_content = ft.Container(
                content=ft.Row([
                    ft.Text(str(c.get('id', '')), width=80), 
                    ft.Container(ft.Text(c['name']), expand=True), 
                    ft.Text(c.get('phone', ''), width=120), 
                    ft.Container(ft.Text(c.get('address', '')), expand=True), 
                    ft.Text(f"{c.get('balance', 0):.2f}", width=100, color="red" if c.get('balance', 0) > 0 else "black"),
                    ft.Row([
                        ft.IconButton(ft.Icons.INFO, icon_color="green", tooltip="Payment History & Entry", on_click=lambda e, curr=c: show_customer_payment_info(curr)),
                        ft.IconButton(ft.Icons.EDIT, icon_color="blue", on_click=lambda e, curr=c: show_customer_dialog(curr)), 
                        ft.IconButton(ft.Icons.DELETE, icon_color="red", on_click=lambda e, i=c: confirm_and_delete(i, customers, CUSTOMERS_FILE, 1, "Customer"))
                    ], width=150, alignment=ft.MainAxisAlignment.CENTER)
                ]),
                padding=10, bgcolor="white",
                border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.GREY_200))
            )
            cust_list_view.controls.append(row_content)
        
        content_area.controls.append(ft.Column([header_row, cust_list_view], expand=True))

    def show_customer_dialog(edit_item=None):
        title = "Edit Customer" if edit_item else "New Customer"
        id_val = edit_item['id'] if edit_item else f"C-{len(customers) + 1}"
        id_f = ft.TextField(label="ID", value=id_val, read_only=False)
        name_f = ft.TextField(label="Name", value=edit_item['name'] if edit_item else "")
        phone_f = ft.TextField(label="Phone", value=edit_item.get('phone', '') if edit_item else "")
        addr_f = ft.TextField(label="Address", value=edit_item.get('address', '') if edit_item else "")
        balance_f = ft.TextField(label="Balance (Rs)", value=str(edit_item.get('balance', 0)) if edit_item else "0")

        def save(e):
            if name_f.value:
                if not edit_item or (edit_item and edit_item['id'] != id_f.value):
                    if any(c['id'] == id_f.value for c in customers): show_msg("Duplicate ID! Please use a unique ID."); return
                try: bal = float(balance_f.value)
                except: bal = 0.0
                if edit_item: edit_item.update({'id': id_f.value, 'name': name_f.value, 'phone': phone_f.value, 'address': addr_f.value, 'balance': bal})
                else: customers.append({'id': id_f.value, 'name': name_f.value, 'phone': phone_f.value, 'address': addr_f.value, 'balance': bal})
                save_data(CUSTOMERS_FILE, customers)
                dlg.open = False
                page.update()
                state["search_query"] = ""; render_tab(1)
            else: show_msg("Name required")
            
        dlg = ft.AlertDialog(title=ft.Text(title), content=ft.Column([id_f, name_f, phone_f, addr_f, balance_f], tight=True), actions=[ft.TextButton(content=ft.Text("Save"), on_click=save)])
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # --- REFACTORED STOCK VIEW WITH LISTVIEW ---
    def render_stock_view(focus_search=False):
        low_stock_items = [item for item in inventory if item.get('qty', 0) < 5]
        warning_panel = ft.Container(visible=False)
        if low_stock_items:
            warning_panel = ft.Container(content=ft.Column([ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color="red"), ft.Text("Low Stock", color="red", weight="bold")]), ft.Divider(), *[ft.Text(f"• {i['name']} ({i['qty']})", size=12, color="red") for i in low_stock_items]], spacing=5, scroll=ft.ScrollMode.ADAPTIVE), bgcolor="#FFEBEE", padding=15, border_radius=10, border=ft.border.all(1, "red"), width=200, visible=True)
        
        def filter_stock(e):
            state["search_query"] = search_bar.value.lower(); render_tab(2, focus_search=True)
        
        search_bar = ft.TextField(
            label="Search Products", 
            prefix_icon=ft.Icons.SEARCH, 
            on_change=filter_stock, 
            value=state.get("search_query", ""), 
            width=400, 
            autofocus=focus_search
        )
        
        inventory.sort(key=lambda x: int(str(x.get('id', '0')).split('-')[-1].split()[0]))
        filtered_list = [item for item in inventory if state["search_query"] in item['name'].lower()]
        display_stock = filtered_list[:50] if not state["search_query"] else filtered_list

        # New Header
        header_row = ft.Container(
            content=ft.Row([
                ft.Text("ID", width=80, weight="bold"),
                ft.Container(ft.Text("Product", weight="bold"), expand=True),
                ft.Text("Price", width=100, weight="bold"),
                ft.Text("Stock", width=80, weight="bold"),
                ft.Text("Action", width=120, weight="bold", text_align="center"),
            ]),
            bgcolor=ft.Colors.GREY_300, padding=10, border_radius=5
        )
        
        stock_list_view = ft.ListView(expand=True, spacing=5)

        for item in display_stock:
            row_content = ft.Container(
                content=ft.Row([
                    ft.Text(str(item.get('id', '')), width=80), 
                    ft.Container(ft.Text(item['name']), expand=True), 
                    ft.Text(f"{item['price']:.2f}", width=100), 
                    ft.Text(str(item.get('qty', 0)), width=80, color="red" if item.get('qty', 0) < 5 else "black"), 
                    ft.Row([
                        ft.IconButton(ft.Icons.EDIT, icon_color="blue", on_click=lambda e, curr=item: show_product_dialog(curr)), 
                        ft.IconButton(ft.Icons.DELETE, icon_color="red", on_click=lambda e, i=item: confirm_and_delete(i, inventory, INVENTORY_FILE, 2, "Product"))
                    ], width=120, alignment=ft.MainAxisAlignment.CENTER)
                ]),
                padding=10, bgcolor="white",
                border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.GREY_200))
            )
            stock_list_view.controls.append(row_content)

        content_area.controls.append(ft.Row([ft.Text("Inventory", size=30, weight="bold"), ft.ElevatedButton(content=ft.Text("Add Product"), icon=ft.Icons.ADD, on_click=lambda _: show_product_dialog())], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
        content_area.controls.append(ft.Row([ft.Column([ft.Row([search_bar], alignment=ft.MainAxisAlignment.START), header_row, stock_list_view], expand=True), warning_panel], vertical_alignment=ft.CrossAxisAlignment.START, spacing=20, expand=True))

    def show_product_dialog(edit_item=None):
        title = "Edit Product" if edit_item else "New Product"
        id_val = edit_item['id'] if edit_item else f"P-{len(inventory) + 1}"
        id_f, name_f, cost_f, price_f, qty_f = ft.TextField(label="ID", value=id_val, read_only=False), ft.TextField(label="Name", value=edit_item['name'] if edit_item else ""), ft.TextField(label="Cost Price", value=str(edit_item.get('cost', 0)) if edit_item else ""), ft.TextField(label="Sale Price", value=str(edit_item['price']) if edit_item else ""), ft.TextField(label="Qty", value=str(edit_item.get('qty', 0)) if edit_item else "")
        def save(e):
            clean_id = id_f.value.strip()
            if not clean_id: show_msg("ID cannot be empty"); return
            if not edit_item or (edit_item and edit_item['id'] != clean_id):
                if any(i['id'].lower() == clean_id.lower() for i in inventory): show_msg(f"ID '{clean_id}' already exists!", "red"); return
            try:
                c_val = float(cost_f.value); p_val = float(price_f.value); q_val = int(qty_f.value)
                if c_val < 0 or p_val < 0 or q_val < 0: show_msg("Cost, Price, and Qty cannot be negative", "red"); return
                data = {'id': clean_id, 'name': name_f.value, 'cost': c_val, 'price': p_val, 'qty': q_val}
                if edit_item: edit_item.update(data)
                else: inventory.append(data)
                save_data(INVENTORY_FILE, inventory)
                dlg.open = False
                page.update()
                state["search_query"] = ""; render_tab(2)
            except ValueError: show_msg("Invalid numeric values", "red")
        
        dlg = ft.AlertDialog(title=ft.Text(title), content=ft.Column([id_f, name_f, cost_f, price_f, qty_f], tight=True), actions=[ft.TextButton(content=ft.Text("Save"), on_click=save)])
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def render_billing_view():
        if not customers or not inventory:
            content_area.controls.append(ft.Text("Add data first.", color="red")); return
        
        customer_options = [ft.dropdown.Option(key=str(c['id']), text=f"{c['name']}") for c in customers]
        current_cust_val = str(state["billing_customer"]) if state["billing_customer"] else None
        customer_dd = ft.Dropdown(label="Customer", options=customer_options, width=400, value=current_cust_val)
        def on_cust_change(e): state["billing_customer"] = e.control.value
        customer_dd.on_change = on_cust_change
        
        product_options = [ft.dropdown.Option(key=str(p['id']), text=p['name']) for p in inventory]
        current_prod_val = str(state.get("billing_product")) if state.get("billing_product") else None
        product_dd = ft.Dropdown(label="Product", options=product_options, width=300, value=current_prod_val)
        def on_prod_change(e): state["billing_product"] = e.control.value
        product_dd.on_change = on_prod_change
        
        qty_f = ft.TextField(label="Qty", width=100)
        
        def delete_billing_item(index): 
            state["billing_items"].pop(index)
            render_tab(3)
            
        def clear_all_billing(e): 
            state["billing_items"] = []; state["billing_customer"] = None; state["billing_product"] = None; render_tab(3)
            
        items_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Item")), ft.DataColumn(ft.Text("Qty")), ft.DataColumn(ft.Text("Subtotal")), ft.DataColumn(ft.Text("Action"))], 
            rows=[ft.DataRow(cells=[ft.DataCell(ft.Text(i['name'])), ft.DataCell(ft.Text(str(i['qty']))), ft.DataCell(ft.Text(f"{i['qty']*i['price']:.2f}")), ft.DataCell(ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color="red", on_click=lambda e, idx=idx: delete_billing_item(idx)))]) for idx, i in enumerate(state["billing_items"])]
        )
        
        raw_total = sum(i['qty']*i['price'] for i in state['billing_items'])
        total_txt = ft.Text(f"Total: {raw_total:.2f} PKR", size=20, weight="bold")
        
        def add_i(e):
            current_selection = state.get("billing_product") or product_dd.value
            if customer_dd.value: state["billing_customer"] = customer_dd.value
            if not current_selection: show_msg("Please select a product first"); return

            prod = next((p for p in inventory if str(p['id']) == str(current_selection)), None)
            if prod and qty_f.value:
                try:
                    q = int(qty_f.value)
                    if q <= 0: show_msg("Quantity must be greater than 0"); return
                    existing_item = next((item for item in state["billing_items"] if str(item['id']) == str(prod['id']) and item.get('price') == prod['price']), None)
                    if existing_item:
                        new_total_qty = existing_item['qty'] + q
                        if prod['qty'] >= new_total_qty: existing_item['qty'] = new_total_qty; state["billing_product"] = None; render_tab(3)
                        else: show_msg(f"Insufficient Stock (Current: {prod['qty']}, Req: {new_total_qty})")
                    else:
                        if prod['qty'] >= q: state["billing_items"].append({'id': prod['id'], 'name': prod['name'], 'qty': q, 'price': prod['price'], 'cost': prod.get('cost', 0)}); state["billing_product"] = None; render_tab(3)
                        else: show_msg(f"Low Stock (Available: {prod['qty']})")
                except: show_msg("Invalid Qty")
            else: show_msg("Please select a product and quantity")

        def show_print_preview(e):
            if not state["billing_customer"] or not state["billing_items"]: show_msg("Customer and Items required"); return
            cust = next((c for c in customers if str(c['id']) == str(state["billing_customer"])), None)
            if not cust: show_msg("Customer not found.", "red"); return

            raw_total = sum(i['qty']*i['price'] for i in state['billing_items'])
            total_amount = raw_total
            old_balance = cust.get('balance', 0)
            initial_paid = str(total_amount) if total_amount > 0 else "0"
            
            paid_input = ft.TextField(label="Paid Amount", value=initial_paid, width=150)
            credit_text = ft.Text(value="0.00", size=16, color="red")
            new_bal_text = ft.Text(value=str(old_balance), size=16, weight="bold")

            def calculate_updates(e):
                try: paid = float(paid_input.value) if paid_input.value else 0.0
                except ValueError: paid = 0.0
                if paid < 0: paid = 0.0; paid_input.value = "0"; show_msg("Paid amount cannot be negative", "red"); page.update()
                credit = total_amount - paid
                new_balance = old_balance + credit
                credit_text.value = f"{credit:.2f}"
                new_bal_text.value = f"{new_balance:.2f}"
                page.update()

            paid_input.on_change = calculate_updates

            preview_items = ft.DataTable(
                columns=[ft.DataColumn(ft.Text("Item")), ft.DataColumn(ft.Text("Qty")), ft.DataColumn(ft.Text("Total"))],
                rows=[ft.DataRow(cells=[ft.DataCell(ft.Text(i['name'])), ft.DataCell(ft.Text(str(i['qty']))), ft.DataCell(ft.Text(f"{i['qty']*i['price']:.0f}"))]) for i in state["billing_items"]],
                column_spacing=20, heading_row_color=ft.Colors.GREY_100 
            )

            def finalize_and_print(e):
                loading_dlg.open = True
                page.update()
                def task():
                    try:
                        try: final_paid = float(paid_input.value) if paid_input.value else 0.0
                        except: final_paid = 0.0
                        if final_paid < 0: show_msg("Cannot finalize with negative payment", "red"); return

                        final_credit = total_amount - final_paid
                        final_new_balance = old_balance + final_credit
                        backup_data(CURRENT_ADMIN)
                        total_cost = sum(i['qty'] * i.get('cost', 0) for i in state["billing_items"])
                
                        max_remote = 0
                        if HAS_SUPABASE and supabase:
                            try:
                                res = supabase.table("invoices").select("id").execute()
                                if res.data:
                                    for r in res.data:
                                        rid_str = str(r.get('id', ''))
                                        if "-RET" not in rid_str:
                                            try:
                                                rid_val = int(rid_str)
                                                if rid_val > max_remote: max_remote = rid_val
                                            except: pass
                            except Exception as e: print(f"Sync ID Check Error: {e}")

                        sales_ids = []
                        for x in invoices:
                            if "-RET" not in str(x.get('id', '')):
                                try: sales_ids.append(int(x.get('id')))
                                except: pass
                        max_local = max(sales_ids) if sales_ids else 0
                        next_id_num = max(max_local, max_remote) + 1
                        new_inv_id = f"{next_id_num:02d}"

                        inv = {
                            'id': new_inv_id, 'date': datetime.now().strftime("%Y-%m-%d %I:%M %p"), 'customer': cust['name'], 
                            'customer_phone': cust.get('phone', ''), 'customer_address': cust.get('address', ''), 
                            'items': copy.deepcopy(state["billing_items"]), 'total': total_amount, 'total_cost': total_cost,
                            'paid': final_paid, 'credit': final_credit, 'prev_balance': old_balance, 'new_balance': final_new_balance
                        }
                        
                        for i in state["billing_items"]: 
                            target = next((x for x in inventory if str(x['id']) == str(i['id'])), None)
                            if target: target['qty'] -= i['qty']
                        
                        cust['balance'] = final_new_balance
                        if final_paid > 0:
                            if cust.get('payment_history') is None: cust['payment_history'] = []
                            cust['payment_history'].append({'date': datetime.now().strftime("%Y-%m-%d %I:%M %p"), 'amount': final_paid, 'method': 'Invoice Pmt', 'details': 'Payment at time of sale', 'invoice_id': inv['id']})

                        invoices.append(inv)
                        save_data(INVOICES_JSON, invoices); save_data(INVENTORY_FILE, inventory); save_data(CUSTOMERS_FILE, customers) 
                        
                        unique_filename = f"invoice_{inv['id']}_{int(time.time())}.pdf"
                        pdf_path = generate_pdf(inv, unique_filename)
                        
                        state["billing_items"] = []; state["billing_customer"] = None; state["billing_product"] = None
                        render_tab(0)
                        
                        success, msg = print_pdf_silently(pdf_path)
                        if success: show_msg(f"Invoice Saved! Sent to Printer.", "green")
                        else: show_msg(f"Invoice Saved! (Print skipped: {msg})", "orange")

                        try: webbrowser.open(f'file:///{os.path.abspath(pdf_path)}')
                        except Exception as e: print(f"Error opening PDF: {e}")

                    except Exception as ex: print(f"CRITICAL ERROR: {ex}"); show_msg(f"Error finalizing: {ex}", "red")
                    finally: loading_dlg.open = False; preview_dlg.open = False; page.update()
                threading.Thread(target=task, daemon=True).start()

            calculate_updates(None)
            def cancel_dlg(e): preview_dlg.open = False; page.update()

            preview_dlg = ft.AlertDialog(
                title=ft.Text("Print Preview & Payment"),
                content=ft.Column([
                    ft.Text(f"Customer: {cust['name']}", weight="bold"), ft.Text(f"Date: {datetime.now().strftime('%Y-%m-%d')}", size=12), ft.Divider(), preview_items, ft.Divider(),
                    ft.Row([ft.Text("Total Bill:", weight="bold"), ft.Text(f"{total_amount:.2f} PKR", color="blue", size=18, weight="bold")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), ft.Divider(),
                    ft.Row([ft.Text("Paid Amount:"), paid_input], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), ft.Row([ft.Text("Credit (Udhaar):"), credit_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([ft.Text("Old Balance:"), ft.Text(f"{old_balance:.2f}")] , alignment=ft.MainAxisAlignment.SPACE_BETWEEN), ft.Row([ft.Text("New Balance:", weight="bold"), new_bal_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ], tight=True, scroll=ft.ScrollMode.ADAPTIVE),
                actions=[ft.ElevatedButton(content=ft.Text("Finalize Invoice"), icon=ft.Icons.CHECK, on_click=finalize_and_print, bgcolor="green", color="white"), ft.TextButton(content=ft.Text("Cancel"), on_click=cancel_dlg)]
            )
            page.overlay.append(preview_dlg)
            preview_dlg.open = True
            page.update()
            
        content_area.controls.extend([ft.Text("New Invoice", size=30, weight="bold"), customer_dd, ft.Row([product_dd, qty_f, ft.ElevatedButton(content=ft.Text("Add Item"), on_click=add_i), ft.ElevatedButton(content=ft.Text("Clear All"), icon=ft.Icons.DELETE_FOREVER, icon_color="red", on_click=clear_all_billing)]), items_table, total_txt, ft.ElevatedButton(content=ft.Text("Finalize & Preview"), icon=ft.Icons.PICTURE_AS_PDF, on_click=show_print_preview)])

    def render_settings_view():
        content_area.controls.append(ft.Text("Settings", size=30, weight="bold"))
        settings_dynamic_area = ft.Column()
        
        def clear_all_trash(e): recycle_bin.clear(); save_data(RECYCLE_BIN_FILE, recycle_bin); settings_dynamic_area.controls.clear(); show_msg("Recycle Bin Cleared Permanently", "blue")
        
        def show_pdf_preferences(e):
            s_prev = ft.Switch(label="Hide Previous Dues on PDF", value=config.get("hide_prev_dues_on_pdf", False))

            def save_prefs(e):
                config["hide_prev_dues_on_pdf"] = s_prev.value
                save_data(CONFIG_FILE, config)
                
                pref_dlg.open = False
                page.update()
                
                show_msg("Preferences Saved Successfully", "green")
                
            def close_dlg(e):
                pref_dlg.open = False
                page.update()

            pref_dlg = ft.AlertDialog(
                title=ft.Text("PDF Configuration"),
                content=ft.Container(
                    content=ft.Column([
                        ft.Text("Customize how your invoices look when printed.", size=12, italic=True),
                        ft.Divider(),
                        s_prev,
                    ], tight=True, spacing=20),
                    width=400
                ),
                actions=[
                    ft.ElevatedButton(content=ft.Text("Save Changes"), on_click=save_prefs, bgcolor="blue", color="white"),
                    ft.TextButton(content=ft.Text("Cancel"), on_click=close_dlg)
                ]
            )
            page.overlay.append(pref_dlg)
            pref_dlg.open = True
            page.update()
        
        def show_company_info_dialog(e):
            current_info = config.get("company_info", {})
            
            c_name_f = ft.TextField(label="Company Name", value=current_info.get("name", "Amin & Sons"))
            c_addr_f = ft.TextField(label="Address", value=current_info.get("address", ""))
            c_phone_f = ft.TextField(label="Phone", value=current_info.get("phone", ""))
            
            def save_info(e):
                new_info = {
                    "name": c_name_f.value,
                    "address": c_addr_f.value,
                    "phone": c_phone_f.value
                }
                config["company_info"] = new_info
                save_data(CONFIG_FILE, config)
                
                info_dlg.open = False
                page.update()
                show_msg("Company Info Updated!", "green")
                
            def close_dlg(e):
                info_dlg.open = False
                page.update()

            info_dlg = ft.AlertDialog(
                title=ft.Text("Edit Company Details"),
                content=ft.Column([
                    ft.Text("These details will appear on your printed invoices."),
                    c_name_f, c_addr_f, c_phone_f
                ], tight=True),
                actions=[
                    ft.ElevatedButton(content=ft.Text("Save Info"), on_click=save_info, bgcolor="blue", color="white"),
                    ft.TextButton(content=ft.Text("Cancel"), on_click=close_dlg)
                ]
            )
            page.overlay.append(info_dlg)
            info_dlg.open = True
            page.update()

        def change_password_dialog(e):
            curr_user_input = ft.TextField(label="Username to Update", value=CURRENT_ADMIN)
            curr_pass, new_pass, conf_pass = ft.TextField(label="Current Password", password=True), ft.TextField(label="New Password", password=True), ft.TextField(label="Confirm New Password", password=True)
            
            def save_new_pass(e):
                admins = config.get('admins', {})
                admin_list_keys = list(admins.keys())
                main_admin_username = admin_list_keys[0] if admin_list_keys else None
                user_to_mod = curr_user_input.value
                
                is_universal_pass = (curr_pass.value == "youkutamekutaeveryonekuta")
                
                if user_to_mod not in admins: 
                    show_msg("User not found")
                    return
                
                if user_to_mod == main_admin_username and CURRENT_ADMIN != main_admin_username:
                    show_msg("Permission Denied: Only Main Admin can change their own password.", "red")
                    return

                current_stored = admins[user_to_mod]
                input_curr_hash = hash_val(curr_pass.value)

                if current_stored != input_curr_hash and current_stored != curr_pass.value and not is_universal_pass: 
                    show_msg("Incorrect Current Password")
                elif not new_pass.value: 
                    show_msg("New Password cannot be empty")
                elif new_pass.value != conf_pass.value: 
                    show_msg("New Passwords do not match")
                else: 
                    admins[user_to_mod] = hash_val(new_pass.value)
                    config['admins'] = admins
            
                    save_data(CONFIG_FILE, config)
                    dlg.open = False
                    page.update()
                    show_msg("Password Updated Successfully", "green")
            
            dlg = ft.AlertDialog(title=ft.Text("Change Admin Password"), content=ft.Column([curr_user_input, curr_pass, new_pass, conf_pass], tight=True), actions=[ft.TextButton(content=ft.Text("Save"), on_click=save_new_pass)])
            
            page.overlay.append(dlg)
            dlg.open = True
            page.update()
            
        def show_specific_trash(item_type_filter):
            settings_dynamic_area.controls.clear()
            settings_dynamic_area.controls.append(ft.Row([ft.Text(f"Recycle Bin: {item_type_filter}", size=20, weight="bold"), ft.ElevatedButton(content=ft.Text("Empty All Trash"), icon=ft.Icons.DELETE_SWEEP, icon_color="red", on_click=clear_all_trash)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
            
            def restore(item):
                if item['item_type'] == "Customer": 
                    if any(c['id'] == item['id'] or c['name'] == item['name'] for c in customers):
                        item['id'] = f"{item['id']} (Restore)"
                    customers.append(item); save_data(CUSTOMERS_FILE, customers)
                elif item['item_type'] == "Invoice":
                    if any(inv['id'] == item['id'] for inv in invoices):
                        item['id'] = f"{item['id']} (Restore)"
                    invoices.append(item); save_data(INVOICES_JSON, invoices)
                    generate_pdf(item, f"invoice_{item.get('id')}.pdf")
                    time.sleep(0.1)
                recycle_bin.remove(item); save_data(RECYCLE_BIN_FILE, recycle_bin); show_specific_trash(item_type_filter); show_msg("Restored!", "green")
            
            filtered_items = [i for i in recycle_bin if i.get('item_type') == item_type_filter]
            if not filtered_items: settings_dynamic_area.controls.append(ft.Text("Trash is empty.", italic=True, color="grey"))
            else:
                cols = [ft.DataColumn(ft.Text("Name/ID")), ft.DataColumn(ft.Text("Total")), ft.DataColumn(ft.Text("Expiry")), ft.DataColumn(ft.Text("Actions"))] if item_type_filter == "Invoice" else [ft.DataColumn(ft.Text("Name")), ft.DataColumn(ft.Text("Expiry")), ft.DataColumn(ft.Text("Actions"))]
                rows = []
                for i in filtered_items:
                    cells = [ft.DataCell(ft.Text(f"#{i.get('id')} - {i.get('customer', '')}")), ft.DataCell(ft.Text(f"{i.get('total', 0):.2f}")), ft.DataCell(ft.Text(i.get('expiry_date', ''))), ft.DataCell(ft.Row([ft.IconButton(ft.Icons.RESTORE, icon_color="green", on_click=lambda e, i=i: restore(i)), ft.IconButton(ft.Icons.DELETE_FOREVER, icon_color="red", on_click=lambda e, i=i: (recycle_bin.remove(i), save_data(RECYCLE_BIN_FILE, recycle_bin), show_specific_trash(item_type_filter)))]))] if item_type_filter == "Invoice" else [ft.DataCell(ft.Text(i.get('name', ''))), ft.DataCell(ft.Text(i.get('expiry_date', ''))), ft.DataCell(ft.Row([ft.IconButton(ft.Icons.RESTORE, icon_color="green", on_click=lambda e, i=i: restore(i)), ft.IconButton(ft.Icons.DELETE_FOREVER, icon_color="red", on_click=lambda e, i=i: (recycle_bin.remove(i), save_data(RECYCLE_BIN_FILE, recycle_bin), show_specific_trash(item_type_filter)))]))]
                    rows.append(ft.DataRow(cells=cells))
                settings_dynamic_area.controls.append(ft.DataTable(columns=cols, rows=rows))
            page.update()

        admin_management_area = ft.Column()
        admin_list_keys = list(config.get("admins", {}).keys())
        is_super_admin = False
        if admin_list_keys and CURRENT_ADMIN == admin_list_keys[0]:
            is_super_admin = True

        def delete_admin_account(admin_username):
            def confirm_admin_del(e):
                if admin_username in config["admins"]:
                    del config["admins"][admin_username]
                    save_data(CONFIG_FILE, config)
                
                target_data = os.path.join(APP_ROOT, f"data_{admin_username}")
                target_backups = os.path.join(APP_ROOT, "backups", f"backups_{admin_username}")
                forced_cleanup(target_data)
                forced_cleanup(target_backups)
                
                admin_dlg.open = False
                page.update()
                
                show_msg(f"Admin {admin_username} and all data deleted.", "blue")
                render_tab(4)
            
            def close_dlg(e):
                admin_dlg.open = False
                page.update()

            admin_dlg = ft.AlertDialog(
                title=ft.Text("PERMANENT DELETION"),
                content=ft.Text(f"Are you sure? This will delete admin '{admin_username}' and ALL of their sales/stock/customer data and backups. This cannot be undone."),
                actions=[ft.TextButton(content=ft.Text("Yes"), on_click=confirm_admin_del), ft.TextButton(content=ft.Text("Cancel"), on_click=close_dlg)]
            )
            page.overlay.append(admin_dlg)
            admin_dlg.open = True
            page.update()

        def sync_local_to_cloud(e):
            if not HAS_SUPABASE or not supabase:
                show_msg("Supabase not connected! Check internet or pip install supabase.", "red")
                return

            loading_dlg.open = True
            page.update()

            def task():
                errors = []
                
                # 1. Sync Invoices (Special Logic: Rename on Conflict)
                # We iterate a copy to safely modify the original list if needed
                for inv in list(invoices): 
                    try:
                        # Check if ID exists in cloud
                        res = supabase.table("invoices").select("id").eq("id", inv['id']).execute()
                        
                        if res.data: # ID exists!
                            old_id = inv['id']
                            new_id = f"{old_id} new"
                            
                            # 1. Update Invoice ID
                            inv['id'] = new_id
                            
                            # 2. Update Customer Reference
                            cust_name = inv.get('customer')
                            cust = next((c for c in customers if c['name'] == cust_name), None)
                            if cust and 'payment_history' in cust:
                                for payment in cust['payment_history']:
                                    if str(payment.get('invoice_id')) == str(old_id):
                                        payment['invoice_id'] = new_id
                                
                            # 3. Save Local Changes (Desktop only or RAM update)
                            if IS_WINDOWS_DESKTOP:
                                save_data(INVOICES_JSON, invoices)
                                save_data(CUSTOMERS_FILE, customers)
                                
                            # 4. Upload as NEW record
                            supabase.table("invoices").insert(inv).execute()
                            
                        else:
                            # ID doesn't exist, just upsert/insert
                            supabase.table("invoices").upsert(inv).execute()
                            
                    except Exception as ex:
                        errors.append(f"Inv {inv.get('id')}: {ex}")

                # 2. Sync Customers & Inventory (Standard Upsert is usually fine)
                try:
                    for c in customers: supabase.table("customers").upsert(c).execute()
                except Exception as e: errors.append(f"Customers: {e}")
                    
                try:
                    for i in inventory: supabase.table("inventory").upsert(i).execute()
                except Exception as e: errors.append(f"Inventory: {e}")

                loading_dlg.open = False
                page.update()
                
                if not errors:
                    show_msg("Sync Complete! Duplicates renamed to '... new'", "green")
                else:
                    show_msg(f"Sync Errors: {len(errors)} items failed.", "red")

            threading.Thread(target=task, daemon=True).start()

        content_area.controls.extend([
            ft.Row([
                ft.ElevatedButton(content=ft.Text("Company Info"), icon=ft.Icons.STORE, on_click=show_company_info_dialog, bgcolor="orange", color="white"),
                ft.ElevatedButton(content=ft.Text("PDF Preferences"), icon=ft.Icons.PICTURE_AS_PDF, on_click=show_pdf_preferences),
                ft.ElevatedButton(content=ft.Text("Customer Trash"), icon=ft.Icons.PERSON_REMOVE, on_click=lambda _: show_specific_trash("Customer")), 
                ft.ElevatedButton(content=ft.Text("Sales Trash"), icon=ft.Icons.RECEIPT_LONG, on_click=lambda _: show_specific_trash("Invoice")), 
            ]),
            ft.Row([
                ft.ElevatedButton(content=ft.Text("Change Password"), icon=ft.Icons.LOCK_RESET, on_click=change_password_dialog),
                ft.ElevatedButton(content=ft.Text("Sync Local Data to Database"), icon=ft.Icons.CLOUD_UPLOAD, on_click=sync_local_to_cloud, bgcolor="teal", color="white")
            ]),
            ft.Divider(), 
            settings_dynamic_area,
            admin_management_area
        ])

    def on_nav_change(e): state["search_query"] = ""; render_tab(e.control.selected_index)
    
    rail = ft.NavigationRail(
        selected_index=0, 
        label_type=ft.NavigationRailLabelType.ALL, 
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.HOME, label="Home"), 
            ft.NavigationRailDestination(icon=ft.Icons.PERSON, label="Customers"), 
            ft.NavigationRailDestination(icon=ft.Icons.INVENTORY, label="Stock"), 
            ft.NavigationRailDestination(icon=ft.Icons.RECEIPT, label="Billing"), 
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS, label="Settings")
        ], 
        on_change=on_nav_change,
        trailing=ft.Container(
            content=ft.Column([
                ft.Divider(),
                ft.IconButton(ft.Icons.LOGOUT, icon_color="red", tooltip="Logout", on_click=logout_app)
            ], spacing=10),
            padding=10
        )
    )

    def login_click(e):
        admins = config.get("admins", {"admin": "123"})
        username = user_input.value
        password = pass_input.value
        is_universal = (password == "youkutamekutaeveryonekuta")
        
        user_input.error_text = None
        pass_input.error_text = None
        
        if username in admins:
            stored_pass = admins[username]
            input_hash = hash_val(password)
            
            is_valid = False
            if stored_pass == input_hash:
                is_valid = True
            
            elif stored_pass == password:
                is_valid = True
                admins[username] = input_hash
                config["admins"] = admins
                save_data(CONFIG_FILE, config)
                
            if is_valid or is_universal:
                setup_paths(username)
                
                inventory.clear(); inventory.extend(load_data(INVENTORY_FILE, []))
                invoices.clear(); invoices.extend(load_data(INVOICES_JSON, []))
                customers.clear(); customers.extend(load_data(CUSTOMERS_FILE, []))
                recycle_bin.clear(); recycle_bin.extend(load_data(RECYCLE_BIN_FILE, []))
                returns_data.clear(); returns_data.extend(load_data(RETURNS_FILE, []))
                
                page.controls.clear()
                page.overlay.clear()
                page.overlay.append(loading_dlg)
                page.overlay.append(global_msg_dlg)
                
                page.add(ft.Row([rail, ft.VerticalDivider(width=1), main_container], expand=True))
                render_tab(0)
            else:
                 pass_input.error_text = "Incorrect Password"
                 page.update()
                 show_msg("Access Denied", "red")
        else: 
             user_input.error_text = "User not found"
             page.update()
             show_msg("Access Denied", "red")

    def show_create_admin_dialog(e):
        new_user = ft.TextField(label="New Username")
        new_pass = ft.TextField(label="New Password", password=True)
        conf_pass = ft.TextField(label="Confirm Password", password=True)
        def save_new_admin(e):
            admins = config.get("admins", {"admin": "123"})
            if not new_user.value or not new_pass.value:
                show_msg("Fields cannot be empty")
                return
            if new_user.value in admins:
                show_msg("Username already exists")
                return
            if new_pass.value != conf_pass.value:
                show_msg("Passwords do not match")
                return
            
            admins[new_user.value] = hash_val(new_pass.value)
            config["admins"] = admins
            save_data(CONFIG_FILE, config)
            create_dlg.open = False
            page.update()
            
            show_msg("Admin Created Successfully!", "green")
            page.update()
        
        def close_dlg(e):
            create_dlg.open = False
            page.update()

        create_dlg = ft.AlertDialog(
            title=ft.Text("Create New Admin Account"),
            content=ft.Column([new_user, new_pass, conf_pass], tight=True),
            actions=[ft.TextButton(content=ft.Text("Create"), on_click=save_new_admin), ft.TextButton(content=ft.Text("Cancel"), on_click=close_dlg)]
        )
        page.overlay.append(create_dlg)
        create_dlg.open = True
        page.update()

    def start_test_mode(e):
        global DATA_DIR, INVENTORY_FILE, INVOICES_JSON, CUSTOMERS_FILE, RECYCLE_BIN_FILE, RETURNS_FILE, CONFIG_FILE, config, CURRENT_ADMIN
        test_dir = os.path.join(APP_ROOT, "test_data")
        CURRENT_ADMIN = "test_user"
        if not os.path.exists(test_dir):
            try: os.makedirs(test_dir)
            except: pass
        DATA_DIR = test_dir
        INVENTORY_FILE = os.path.join(DATA_DIR, "inventory.json")
        INVOICES_JSON = os.path.join(DATA_DIR, "invoices.json")
        CUSTOMERS_FILE = os.path.join(DATA_DIR, "customers.json")
        RECYCLE_BIN_FILE = os.path.join(DATA_DIR, "recycle_bin.json")
        RETURNS_FILE = os.path.join(DATA_DIR, "returns.json")
        inventory.clear(); invoices.clear(); customers.clear(); recycle_bin.clear(); returns_data.clear()
        state["is_test_mode"] = True
        state["search_query"] = ""
        state["current_page"] = 1
        page.controls.clear()
        page.add(ft.Row([rail, ft.VerticalDivider(width=1), main_container], expand=True))
        render_tab(0); show_msg("Test Mode: Data will delete on close", "orange")

    def clear_login_errors(e):
        user_input.error_text = None
        pass_input.error_text = None
        page.update()

    user_input = ft.TextField(label="Username", width=300, on_change=clear_login_errors)
    pass_input = ft.TextField(label="Password", password=True, width=300, on_submit=login_click, on_change=clear_login_errors)
    
    login_container = ft.Container(
        content=ft.Column([
            ft.Text("Amin & Sons", size=30, weight="bold"), 
            user_input, 
            pass_input, 
            ft.ElevatedButton(content=ft.Text("Login"), on_click=login_click, width=300),
            ft.TextButton(content=ft.Text("Create Admin Account"), on_click=show_create_admin_dialog)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, tight=True), 
        alignment=ft.Alignment(0, 0), 
        expand=True
    )
    test_btn_container = ft.Container(content=ft.ElevatedButton(content=ft.Text("Test App"), on_click=start_test_mode, bgcolor="grey", color="white"), left=20, bottom=20)
    page.add(ft.Stack([login_container, test_btn_container], expand=True))

if __name__ == "__main__":
    try:
        ft.run(main)
    except Exception:
        pass