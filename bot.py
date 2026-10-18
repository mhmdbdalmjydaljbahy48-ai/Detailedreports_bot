# -*- coding: utf-8 -*-
"""بوت تلجرام (Webhook) لنظام إدارة المتجر والديون — نسخة الملف الواحد.

التشغيل:      python bot.py          (أو gunicorn bot:application)
المتطلبات:    pip install -r requirements.txt     (requests + oracledb)
المتغيرات:    انظر env.example.txt وضعها في إعدادات المنصة

هذا الملف يضم كل وحدات المشروع (config, db, tg, core, ... app) داخله ويحمّلها تلقائياً،
فلا حاجة لأي ملف آخر غير requirements.txt.
"""
import importlib.abc
import importlib.util
import sys

SOURCES = {}

# ════════════════════ config.py ════════════════════
SOURCES['config'] = r'''"""إعدادات البوت — كلها تُقرأ من متغيرات البيئة (Environment Variables).

لا تكتب كلمات المرور أو التوكن داخل الكود. ضعها في إعدادات المنصة التي تنشر عليها.
"""
import hashlib
import os
import re


def _s(name, default=""):
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


def _i(name, default):
    try:
        return int(_s(name, str(default)))
    except ValueError:
        return default


def _ids(name):
    out = set()
    for part in re.split(r"[,\s;]+", _s(name)):
        if part.isdigit():
            out.add(int(part))
    return out


def _public_url():
    """رابط الموقع العام (HTTPS). يُؤخذ من PUBLIC_URL أو يُكتشف تلقائياً من المنصة."""
    u = _s("PUBLIC_URL")
    if not u:
        candidates = (
            ("RENDER_EXTERNAL_URL", "{}"),
            ("RAILWAY_PUBLIC_DOMAIN", "https://{}"),
            ("KOYEB_PUBLIC_DOMAIN", "https://{}"),
            ("FLY_APP_NAME", "https://{}.fly.dev"),
            ("WEBSITE_HOSTNAME", "https://{}"),
            ("REPLIT_DEV_DOMAIN", "https://{}"),
            ("HEROKU_APP_NAME", "https://{}.herokuapp.com"),
        )
        for var, tmpl in candidates:
            v = _s(var)
            if v:
                u = tmpl.format(v)
                break
    u = u.rstrip("/")
    if u and not u.lower().startswith("http"):
        u = "https://" + u
    return u


class Config:
    def __init__(self):
        # ── تلجرام ──
        self.BOT_TOKEN = _s("BOT_TOKEN")
        secret = re.sub(r"[^A-Za-z0-9_-]", "", _s("WEBHOOK_SECRET"))
        self.WEBHOOK_SECRET = secret or hashlib.sha256(
            ("wh:" + self.BOT_TOKEN).encode()).hexdigest()[:40]
        self.PUBLIC_URL = _public_url()
        self.PORT = _i("PORT", 8000)
        self.ADMIN_IDS = _ids("ADMIN_IDS")          # أرقام تلجرام للمدراء (مفصولة بفاصلة)
        self.CRON_SECRET = _s("CRON_SECRET")        # لتفعيل رابط تذكيرات الاشتراك

        # ── قاعدة البيانات (Oracle) ──
        self.DB_USER = _s("DB_USER", "facilitation")
        self.DB_PASSWORD = _s("DB_PASSWORD")
        self.DB_DSN = _s("DB_DSN")                  # اختياري: بديل كامل عن HOST/PORT/SID
        self.DB_HOST = _s("DB_HOST", "localhost")
        self.DB_PORT = _i("DB_PORT", 1521)
        self.DB_SID = _s("DB_SID", "orcl")
        self.DB_SERVICE = _s("DB_SERVICE")          # لو عندك Service Name بدل SID
        self.DB_POOL_MAX = _i("DB_POOL_MAX", 4)
        self.ORACLE_CLIENT_DIR = _s("ORACLE_CLIENT_DIR")  # فقط لو Oracle أقدم من 12.1 (Thick mode)
        self.AUTO_MIGRATE = _s("AUTO_MIGRATE", "1") != "0"

        # ── الاشتراكات ──
        self.TRIAL_MONTHS = max(1, _i("TRIAL_MONTHS", 1))
        # first_only = مثل برنامج Java (التسجيل الذاتي فقط عند عدم وجود أي حساب)
        # open       = أي شخص يسجل ويأخذ الشهر المجاني
        # closed     = لا تسجيل ذاتي (الدخول فقط)
        self.REGISTRATION_MODE = _s("REGISTRATION_MODE", "first_only").lower()
        self.HASH_PASSWORDS = _s("HASH_PASSWORDS", "1") != "0"
        self.EMAIL_SUFFIX = os.environ.get("EMAIL_SUFFIX", ".com").strip()  # فارغ = بدون شرط
        self.SUB_PRICE_UNIT = _s("SUB_PRICE_UNIT", "ريال")
        self.PAY_CONTACT_NAME = _s("PAY_CONTACT_NAME", "المهندس/ محمد")
        self.PAY_CONTACT_PHONE = _s("PAY_CONTACT_PHONE", "785068462")
        self.PAY_TRANSFER_NUMBER = _s("PAY_TRANSFER_NUMBER", "738439579")

        # ── عام ──
        self.MAX_PHONE = _i("MAX_PHONE", 2147483647)  # حد int في Java حتى لا ينكسر البرنامج القديم
        self.LOG_LEVEL = _s("LOG_LEVEL", "INFO").upper()


cfg = Config()
'''

# ════════════════════ db.py ════════════════════
SOURCES['db'] = r'''"""الاتصال بقاعدة SQLite (بديل Oracle المجاني)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import re
import math
from contextlib import contextmanager

from config import cfg

log = logging.getLogger("db")

_local = threading.local()
FLAGS = {"network_manual_id": True}  # إجبار النظام على التعامل مع المعرفات تلقائياً

def get_conn():
    if not hasattr(_local, "conn"):
        # إنشاء/الاتصال بملف قاعدة البيانات محلياً
        conn = sqlite3.connect("shop.db", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        
        # تسجيل دوال مخصصة لتقليد Oracle 100%
        conn.create_function("NVL", 2, lambda a, b: b if a is None else a)
        conn.create_function("CEIL", 1, lambda x: math.ceil(x) if x is not None else None)
        
        # محاكاة جدول DUAL الخاص بأوراكل
        conn.execute("CREATE TABLE IF NOT EXISTS dual (dummy VARCHAR(1))")
        if not conn.execute("SELECT 1 FROM dual").fetchone():
            conn.execute("INSERT INTO dual (dummy) VALUES ('X')")
        
        _local.conn = conn
    return _local.conn


def translate_sql(sql):
    """مترجم ذكي يحول أوامر أوراكل إلى SQLite أثناء التشغيل دون المساس بالكود الأصلي"""
    
    # 1. ترجمة نظام الصفحات (Pagination) المعقد في أوراكل
    def page_repl(m):
        inner = m.group(1)
        upper = int(m.group(2))
        lower = int(m.group(3))
        limit = upper - lower
        return f"SELECT * FROM ({inner}) LIMIT {limit} OFFSET {lower}"
    sql = re.sub(r"(?i)SELECT \* FROM \(SELECT q\.\*, ROWNUM AS rn__ FROM \((.*?)\) q WHERE ROWNUM <= (\d+)\) WHERE rn__ > (\d+)", page_repl, sql, flags=re.DOTALL)
    
    # 2. ترجمة ROWNUM البسيطة (مثل التي في البحث)
    sql = re.sub(r"(?i)\s*WHERE\s+ROWNUM\s*<=\s*(\d+)", r" LIMIT \1", sql)
    
    # 3. ترجمة تواريخ TRUNC (التقارير اليومية والشهرية)
    sql = re.sub(r"(?i)TRUNC\((SYSDATE)\s*,\s*'MM'\)", r"date('now', 'localtime', 'start of month')", sql)
    sql = re.sub(r"(?i)TRUNC\(([^,]+?)\s*,\s*'MM'\)", r"date(\1, 'start of month')", sql)
    sql = re.sub(r"(?i)TRUNC\(SYSDATE\)", r"date('now', 'localtime')", sql)
    sql = re.sub(r"(?i)TRUNC\(([^,)]+?)\)", r"date(\1)", sql)
    
    # 4. ترجمة العمليات الحسابية على التواريخ (SYSDATE arithmetic)
    sql = re.sub(r"(?i)\(([^()]+)\s*-\s*SYSDATE\)", r"(julianday(\1) - julianday('now', 'localtime'))", sql)
    sql = re.sub(r"(?i)SYSDATE\s*-\s*(\d+)", r"datetime('now', 'localtime', '-\1 days')", sql)
    sql = re.sub(r"(?i)SYSDATE\s*\+\s*(\d+)", r"datetime('now', 'localtime', '+\1 days')", sql)
    
    # 5. ترجمة التواريخ المباشرة
    sql = re.sub(r"(?i)\bSYSDATE\b", "datetime('now', 'localtime')", sql)
    sql = re.sub(r"(?i)\bSYSTIMESTAMP\b", "datetime('now', 'localtime')", sql)
    
    # 6. ترجمة المتتاليات (Sequences) إلى NULL لتتكفل SQLite بالترقيم التلقائي
    sql = re.sub(r"(?i)bot_audit_seq\.NEXTVAL", "NULL", sql)
    sql = re.sub(r"(?i)network_sales_seq\.NEXTVAL", "NULL", sql)
    
    # 7. إزالة FOR UPDATE لأن SQLite تدير القفل تلقائياً
    sql = re.sub(r"(?i)\s+FOR\s+UPDATE\b", "", sql)
    
    return sql


class Tx:
    def __init__(self, conn):
        self.conn = conn

    def _cur(self, sql, p):
        cur = self.conn.cursor()
        
        # اعتراض خاص لتوليد رقم طلب الاشتراك (مثل متتالية أوراكل)
        if "bot_req_seq.NEXTVAL" in sql.upper():
            cur.execute("SELECT IFNULL(MAX(req_id), 0) + 1 FROM bot_sub_requests")
            return cur
            
        tsql = translate_sql(sql)
        try:
            if p:
                cur.execute(tsql, p)
            else:
                cur.execute(tsql)
        except Exception as e:
            log.error(f"SQL Error: {e}\nOriginal: {sql}\nTranslated: {tsql}")
            raise
        return cur

    def rows(self, sql, **p):
        cur = self._cur(sql, p)
        cols = [d[0].lower() for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def one(self, sql, **p):
        r = self.rows(sql, **p)
        return r[0] if r else None

    def val(self, sql, default=None, **p):
        cur = self._cur(sql, p)
        r = cur.fetchone()
        return default if not r or r[0] is None else r[0]

    def run(self, sql, **p):
        return self._cur(sql, p).rowcount


@contextmanager
def tx():
    conn = get_conn()
    try:
        yield Tx(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def rows(sql, **p):
    with tx() as t: return t.rows(sql, **p)

def one(sql, **p):
    with tx() as t: return t.one(sql, **p)

def val(sql, default=None, **p):
    with tx() as t: return t.val(sql, default, **p)

def run(sql, **p):
    with tx() as t: return t.run(sql, **p)

def ping():
    return val("SELECT 1 FROM dual")


# ───────────────────────── الجداول (التهيئة التلقائية) ─────────────────────────
def ensure_schema():
    report = {"missing_tables": [], "created": [], "altered": [], "errors": []}
    try:
        tables = [
            ("bot_users", """CREATE TABLE IF NOT EXISTS bot_users (
                telegram_id INTEGER PRIMARY KEY, client_num INTEGER, state VARCHAR(60), state_data TEXT, 
                fail_count INTEGER DEFAULT 0 NOT NULL, locked_until DATETIME, first_name VARCHAR(100), 
                username VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            
            ("bot_sub_requests", """CREATE TABLE IF NOT EXISTS bot_sub_requests (
                req_id INTEGER PRIMARY KEY, client_num INTEGER NOT NULL, telegram_id INTEGER, 
                months INTEGER NOT NULL, amount NUMERIC DEFAULT 0 NOT NULL, status VARCHAR(12) DEFAULT 'PENDING' NOT NULL, 
                note VARCHAR(300), created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, decided_at DATETIME, decided_by INTEGER)"""),
            
            ("bot_audit_log", """CREATE TABLE IF NOT EXISTS bot_audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER, telegram_id INTEGER, 
                action VARCHAR(40) NOT NULL, details VARCHAR(500), created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            
            ("bot_debts_archive", """CREATE TABLE IF NOT EXISTS bot_debts_archive (
                debt_id INTEGER, client_num INTEGER, customer_phone INTEGER, customer_name VARCHAR(100), 
                product_name VARCHAR(100), quantity NUMERIC, single_price NUMERIC, debt_amount NUMERIC, 
                paid_amount NUMERIC, debt_date DATETIME, invoice_num INTEGER, reason VARCHAR(30), 
                archived_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            
            ("bot_reminder_log", """CREATE TABLE IF NOT EXISTS bot_reminder_log (
                client_num INTEGER NOT NULL, expiry_date DATETIME NOT NULL, kind VARCHAR(4) NOT NULL, 
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, PRIMARY KEY (client_num, expiry_date, kind))"""),
            
            ("clients_table", """CREATE TABLE IF NOT EXISTS clients_table (
                client_id INTEGER PRIMARY KEY AUTOINCREMENT, num INTEGER UNIQUE, name VARCHAR(100), email VARCHAR(150), 
                password_hash VARCHAR(200), subscription_months INTEGER DEFAULT 1, subscription_duration VARCHAR(50), 
                money NUMERIC DEFAULT 0, start_date DATETIME DEFAULT CURRENT_TIMESTAMP, expiry_date DATETIME, 
                is_active INTEGER DEFAULT 1, account_type VARCHAR(50), shop_name VARCHAR(100), activity_type VARCHAR(100), 
                location VARCHAR(100), shop_location VARCHAR(50), currency VARCHAR(50))"""),
            
            ("products_table", """CREATE TABLE IF NOT EXISTS products_table (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT, product_name VARCHAR(150) UNIQUE, purchase_price NUMERIC DEFAULT 0, 
                selling_price NUMERIC DEFAULT 0, price NUMERIC DEFAULT 0, quantity NUMERIC DEFAULT 0, units_per_carton INTEGER DEFAULT 1, 
                is_active INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"""),
            
            ("shop_customers", """CREATE TABLE IF NOT EXISTS shop_customers (
                customer_phone INTEGER, client_num INTEGER, customer_name VARCHAR(150), PRIMARY KEY(customer_phone, client_num))"""),
            
            ("shop_debts", """CREATE TABLE IF NOT EXISTS shop_debts (
                debt_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER, customer_phone INTEGER, customer_name VARCHAR(150), 
                product_name VARCHAR(150), quantity NUMERIC, single_price NUMERIC, debt_amount NUMERIC, paid_amount NUMERIC DEFAULT 0, 
                invoice_num INTEGER, debt_date DATETIME DEFAULT CURRENT_TIMESTAMP)"""),
            
            ("cash_sales", """CREATE TABLE IF NOT EXISTS cash_sales (
                sale_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER, customer_name VARCHAR(100), customer_phone INTEGER, 
                product_name VARCHAR(100), quantity NUMERIC, single_price NUMERIC, total_amount NUMERIC, profit_amount NUMERIC DEFAULT 0, 
                invoice_num INTEGER, sale_date DATETIME DEFAULT CURRENT_TIMESTAMP)"""),
            
            ("network_sales", """CREATE TABLE IF NOT EXISTS network_sales (
                sale_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER, customer_name VARCHAR(100), customer_phone INTEGER, 
                product_name VARCHAR(100), quantity NUMERIC, single_price NUMERIC, total_amount NUMERIC, profit_amount NUMERIC DEFAULT 0, 
                invoice_num INTEGER, sale_date DATETIME DEFAULT CURRENT_TIMESTAMP)"""),
            
            ("imports_table", """CREATE TABLE IF NOT EXISTS imports_table (
                import_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER, merchant_name VARCHAR(100), product_name VARCHAR(100), 
                number_of_cartons NUMERIC, inside_carton NUMERIC, price_carton NUMERIC, full_amount NUMERIC, paid_amount NUMERIC, 
                residual_amount NUMERIC, single_item_price NUMERIC, item_cost NUMERIC, profit_amount NUMERIC, import_date DATETIME DEFAULT CURRENT_TIMESTAMP)"""),
            
            ("system_settings", """CREATE TABLE IF NOT EXISTS system_settings (id INTEGER PRIMARY KEY, month_price NUMERIC DEFAULT 0)"""),
            ("exchange_rates", """CREATE TABLE IF NOT EXISTS exchange_rates (id INTEGER PRIMARY KEY, usd_price NUMERIC DEFAULT 0, sar_price NUMERIC DEFAULT 0)""")
        ]
        
        for name, sql in tables:
            run(sql)
            report["created"].append(name)
            
        # محاكاة مشغلات أوراكل (Triggers) لحساب تاريخ انتهاء الاشتراك تلقائياً
        run("""CREATE TRIGGER IF NOT EXISTS trg_clients_ins 
               AFTER INSERT ON clients_table 
               BEGIN UPDATE clients_table SET expiry_date = datetime(NEW.start_date, '+' || NEW.subscription_months || ' months') WHERE rowid = NEW.rowid; END;""")
        run("""CREATE TRIGGER IF NOT EXISTS trg_clients_upd 
               AFTER UPDATE OF start_date, subscription_months ON clients_table 
               BEGIN UPDATE clients_table SET expiry_date = datetime(NEW.start_date, '+' || NEW.subscription_months || ' months') WHERE rowid = NEW.rowid; END;""")
               
    except Exception as e:
        log.error(f"Schema Error: {e}")
        report["errors"].append(str(e))
    return report

def schema_sql():
    return "-- يتم إنشاء الجداول في SQLite تلقائياً\n"
'''

# ════════════════════ tg.py ════════════════════
SOURCES['tg'] = r'''"""واجهة Telegram Bot API (باستخدام requests فقط)."""
from __future__ import annotations

import logging
import re

import requests

from config import cfg

log = logging.getLogger("tg")
_session = requests.Session()
_last_error = ""
MAX_LEN = 3800


def last_error():
    return _last_error


def _url(method):
    return "https://api.telegram.org/bot%s/%s" % (cfg.BOT_TOKEN, method)


def call(method, files=None, **params):
    """يرجع النتيجة عند النجاح أو None عند الفشل."""
    global _last_error
    _last_error = ""
    try:
        if files:
            r = _session.post(_url(method), data=params, files=files, timeout=60)
        else:
            r = _session.post(_url(method), json=params, timeout=30)
        data = r.json()
    except Exception as e:  # شبكة/مهلة
        _last_error = str(e)
        log.warning("telegram %s failed: %s", method, e)
        return None
    if not data.get("ok"):
        _last_error = data.get("description", "") or ""
        if "message is not modified" not in _last_error:
            log.warning("telegram %s error: %s", method, _last_error)
        return None
    res = data.get("result")
    return True if res is None else res


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "")


def _chunks(text, size=MAX_LEN):
    text = text or ""
    if len(text) <= size:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > size:               # سطر طويل جداً
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) + 1 > size:
            out.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    if cur:
        out.append(cur)
    return out


def send(chat_id, text, markup=None, parse_mode="HTML"):
    chunks = _chunks(text)
    res = None
    for i, ch in enumerate(chunks):
        params = dict(chat_id=chat_id, text=ch or "…", disable_web_page_preview=True)
        if parse_mode:
            params["parse_mode"] = parse_mode
        if markup and i == len(chunks) - 1:
            params["reply_markup"] = markup
        res = call("sendMessage", **params)
        if res is None and "parse entities" in _last_error:
            params.pop("parse_mode", None)
            params["text"] = strip_tags(ch) or "…"
            res = call("sendMessage", **params)
    return res


def edit(chat_id, message_id, text, markup=None):
    """يعدّل رسالة قائمة. يرجع True عند النجاح."""
    if len(text or "") > MAX_LEN:
        return False
    params = dict(chat_id=chat_id, message_id=message_id, text=text or "…",
                  parse_mode="HTML", disable_web_page_preview=True)
    if markup is not None:
        params["reply_markup"] = markup
    res = call("editMessageText", **params)
    if res is None and "message is not modified" in _last_error:
        return True
    if res is None and "parse entities" in _last_error:
        params.pop("parse_mode", None)
        params["text"] = strip_tags(text) or "…"
        res = call("editMessageText", **params)
    return res is not None


def answer_cb(cb_id, text=None, alert=False):
    params = dict(callback_query_id=cb_id)
    if text:
        params["text"] = text[:190]
        params["show_alert"] = bool(alert)
    return call("answerCallbackQuery", **params)


def delete(chat_id, message_id):
    return call("deleteMessage", chat_id=chat_id, message_id=message_id)


def forward(to_chat, from_chat, message_id):
    return call("forwardMessage", chat_id=to_chat, from_chat_id=from_chat, message_id=message_id)


def send_doc(chat_id, filename, content, caption=None):
    if isinstance(content, str):
        content = content.encode("utf-8")
    params = {"chat_id": chat_id}
    if caption:
        params["caption"] = caption[:1000]
    return call("sendDocument",
                files={"document": (filename, content, "text/plain; charset=utf-8")}, **params)


def set_webhook(url, secret):
    return call("setWebhook", url=url, secret_token=secret,
                allowed_updates=["message", "callback_query"], max_connections=1)


def delete_webhook():
    return call("deleteWebhook")


def set_commands():
    cmds = [
        ("start", "البدء / القائمة الرئيسية"),
        ("menu", "القائمة الرئيسية"),
        ("subscription", "اشتراكي وتجديد الاشتراك"),
        ("cancel", "إلغاء العملية الحالية"),
        ("logout", "تسجيل الخروج"),
        ("id", "معرفة رقم حسابي في تلجرام"),
        ("help", "مساعدة"),
    ]
    return call("setMyCommands",
                commands=[{"command": c, "description": d} for c, d in cmds])
'''

# ════════════════════ core.py ════════════════════
SOURCES['core'] = r'''"""أدوات مشتركة: الجلسة (Ctx)، التنسيق، التحقق من الإدخال، كلمات المرور، ومسجّل المعالجات."""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import math
import os
import re
import threading

import db
import tg
from config import cfg

log = logging.getLogger("bot")
LOCK = threading.RLock()

LIKE_ESC = " ESCAPE '\\'"            # يُلحق بعد LIKE :p_q
MAX_AMOUNT = 99_999_999.0           # حد NUMBER(10,2) في جداول المبيعات


# ───────────────────────── تنسيق ─────────────────────────
def esc(s):
    return html.escape("" if s is None else str(s), quote=False)


_DIGITS = str.maketrans({
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٫": ".", "٬": ",", "،": ",",
})


def norm(s):
    """يحوّل الأرقام العربية/الهندية إلى 0-9 (لوحة المفاتيح العربية تكتبها هكذا)."""
    return (s or "").translate(_DIGITS).strip()


def parse_int(s, lo=None, hi=None):
    s = norm(s).replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d{1,15}", s):
        return None
    v = int(s)
    if lo is not None and v < lo:
        return None
    if hi is not None and v > hi:
        return None
    return v


def parse_float(s, lo=0.0, hi=MAX_AMOUNT):
    s = norm(s).replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", s):
        return None
    v = float(s)
    if not math.isfinite(v) or v < lo or v > hi:
        return None
    return v


def clean_text(s, max_len=100, as_bytes=False):
    """ينظّف النص. as_bytes=True للأعمدة VARCHAR2(n) بالبايت (العربي = 2 بايت في UTF-8)."""
    s = re.sub(r"\s+", " ", (s or "")).strip()
    if not s:
        return None
    n = len(s.encode("utf-8")) if as_bytes else len(s)
    return None if n > max_len else s


def fit_bytes(s, n=100):
    """يقصّ النص ليناسب عمود VARCHAR2(n) بالبايت دون كسر حرف."""
    s = s or ""
    while len(s.encode("utf-8")) > n:
        s = s[:-1]
    return s


def fmt_num(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if abs(x - round(x)) < 0.005:
        return "{:,}".format(int(round(x)))
    return ("{:,.%df}" % nd).format(x).rstrip("0").rstrip(".")


def money(x, unit=""):
    return fmt_num(x) + (" " + unit if unit else "")


def fmt_dt(d):
    if not d:
        return "-"
    try:
        return d.strftime("%Y-%m-%d %I:%M ") + ("ص" if d.hour < 12 else "م")
    except Exception:
        return str(d)


def fmt_date(d):
    if not d:
        return "-"
    try:
        return d.strftime("%Y-%m-%d")
    except Exception:
        return str(d)


MONTH_LABELS = {
    0: "صفر شهر", 1: "شهر واحد", 2: "شهرين", 3: "ثلاثة اشهر", 4: "اربعة اشهر", 5: "خمسة اشهر",
    6: "ستة اشهر", 7: "سبعة اشهر", 8: "ثمانية اشهر", 9: "تسعة اشهر", 10: "عشرة اشهر",
    11: "احد عشر شهر", 12: "سنة",
}


def duration_label(months):
    return MONTH_LABELS.get(int(months or 0), "اكثر من سنة")


def unit_of(client):
    cur = (client or {}).get("currency") or ""
    if "يمني" in cur:
        return "ريال يمني"
    if "سعودي" in cur:
        return "ريال سعودي"
    if "دولار" in cur:
        return "دولار"
    return "ريال"


def stock_text(qty, per):
    qty = int(qty or 0)
    per = int(per or 0)
    if per > 1 and qty >= 0:
        c, l = divmod(qty, per)
        return "%s حبة (%s كرتون و %s حبة)" % (fmt_num(qty), c, l)
    return "%s حبة" % fmt_num(qty)


def like(s):
    s = (s or "").strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + s + "%"


def kb(*rows):
    out = []
    for row in rows:
        r = [{"text": t, "callback_data": d} for t, d in row]
        if r:
            out.append(r)
    return {"inline_keyboard": out}


BACK_HOME = ("🏠 القائمة الرئيسية", "m:home")
CANCEL_BTN = ("❌ إلغاء", "m:home")


# ───────────────────────── كلمات المرور ─────────────────────────
_ITER = 120_000


def hash_password(pw):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _ITER)
    return "pbkdf2$%d$%s$%s" % (_ITER, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def check_password(stored, pw):
    """يقبل كلمة المرور المشفّرة (pbkdf2) أو النص العادي (للحسابات التي أنشأها برنامج Java)."""
    stored = stored or ""
    if stored.startswith("pbkdf2$"):
        try:
            _, it, s, h = stored.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), base64.b64decode(s), int(it))
            return hmac.compare_digest(dk, base64.b64decode(h))
        except Exception:
            return False
    return hmac.compare_digest(stored.encode("utf-8"), pw.encode("utf-8"))


def store_password(pw):
    return hash_password(pw) if cfg.HASH_PASSWORDS else pw


# ───────────────────────── سجل العمليات ─────────────────────────
def audit(action, ctx=None, client_num=None, details="", t=None):
    num = client_num
    if num is None and ctx is not None and ctx.client:
        num = ctx.client.get("num")
    uid = ctx.user_id if ctx is not None else None
    sql = ("INSERT INTO bot_audit_log (log_id, client_num, telegram_id, action, details) "
           "VALUES (bot_audit_seq.NEXTVAL, :p_c, :p_t, :p_a, :p_d)")
    params = dict(p_c=num, p_t=uid, p_a=action[:40], p_d=(details or "")[:450])
    try:
        (t.run if t is not None else db.run)(sql, **params)
    except Exception:
        log.exception("audit failed")


# ───────────────────────── العميل (المشترك) ─────────────────────────
CLIENT_SQL = (
    "SELECT num, name, email, subscription_months, subscription_duration, money, start_date, "
    "expiry_date, (expiry_date - SYSDATE) AS days_left, is_active, account_type, shop_name, "
    "activity_type, location, shop_location, currency FROM clients_table WHERE num = :p_num")


def fetch_client(num):
    return db.one(CLIENT_SQL, p_num=num)


# ───────────────────────── المعالجات ─────────────────────────
STATE_H = {}
CB_H = {}
MEDIA_STATES = set()


def on_state(*names, media=False):
    def deco(fn):
        for n in names:
            STATE_H[n] = fn
            if media:
                MEDIA_STATES.add(n)
        return fn
    return deco


def on_cb(*names):
    def deco(fn):
        for n in names:
            CB_H[n] = fn
        return fn
    return deco


# ───────────────────────── سياق التحديث ─────────────────────────
class Ctx:
    def __init__(self, update):
        self.update = update
        self.update_id = update.get("update_id")
        cq = update.get("callback_query")
        if cq:
            msg = cq.get("message") or {}
            self.is_cb = True
            self.cb = cq.get("data") or ""
            self.cb_id = cq.get("id")
            self.user = cq.get("from") or {}
            self.text = None
        else:
            msg = update.get("message") or {}
            self.is_cb = False
            self.cb = ""
            self.cb_id = None
            self.user = msg.get("from") or {}
            self.text = msg.get("text")
        chat = msg.get("chat") or {}
        self.message = msg
        self.chat_id = chat.get("id")
        self.chat_type = chat.get("type")
        self.msg_id = msg.get("message_id")
        self.user_id = self.user.get("id")
        self.client = None          # صف clients_table للمشترك المسجّل دخوله
        self.sub = None             # حالة الاشتراك
        self.args = []              # أجزاء callback بعد الاسم الأول
        self.sess = {"state": None, "data": {}, "client_num": None,
                     "fail_count": 0, "locked_until": None}

    # ── الجلسة ──
    @property
    def is_admin(self):
        return self.user_id in cfg.ADMIN_IDS

    @property
    def state(self):
        return self.sess["state"]

    @property
    def data(self):
        return self.sess["data"]

    def load_session(self):
        row = db.one("SELECT client_num, state, state_data, fail_count, locked_until "
                     "FROM bot_users WHERE telegram_id = :p_t", p_t=self.user_id)
        if row is None:
            db.run("INSERT INTO bot_users (telegram_id, first_name, username) "
                   "VALUES (:p_t, :p_f, :p_u)",
                   p_t=self.user_id, p_f=(self.user.get("first_name") or "")[:100],
                   p_u=(self.user.get("username") or "")[:100])
            return
        data = {}
        if row.get("state_data"):
            try:
                data = json.loads(row["state_data"])
            except ValueError:
                data = {}
        self.sess.update(client_num=row.get("client_num"), state=row.get("state"), data=data,
                         fail_count=row.get("fail_count") or 0, locked_until=row.get("locked_until"))

    def _save(self):
        payload = json.dumps(self.sess["data"], ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 3900:
            self.sess["data"] = {}
            payload = "{}"
        db.run("UPDATE bot_users SET state = :p_s, state_data = :p_d, last_seen = SYSDATE "
               "WHERE telegram_id = :p_t", p_s=self.sess["state"], p_d=payload, p_t=self.user_id)

    def go(self, state, **data):
        """ينتقل لحالة جديدة ويدمج بيانات النموذج الجارية."""
        self.sess["state"] = state
        self.sess["data"].update(data)
        self._save()

    def put(self, **data):
        self.sess["data"].update(data)
        self._save()

    def reset(self):
        self.sess["state"] = None
        self.sess["data"] = {}
        self._save()

    def link(self, client_num):
        db.run("UPDATE bot_users SET client_num = :p_c, fail_count = 0, locked_until = NULL "
               "WHERE telegram_id = :p_t", p_c=client_num, p_t=self.user_id)
        self.sess["client_num"] = client_num

    def unlink(self):
        db.run("UPDATE bot_users SET client_num = NULL, state = NULL, state_data = NULL "
               "WHERE telegram_id = :p_t", p_t=self.user_id)
        self.sess.update(client_num=None, state=None, data={})
        self.client = None
        self.sub = None

    # ── الإرسال ──
    def answer(self, text=None, alert=False):
        if self.is_cb and self.cb_id:
            tg.answer_cb(self.cb_id, text, alert)

    def send(self, text, markup=None):
        return tg.send(self.chat_id, text, markup)

    def reply(self, text, markup=None):
        """في الأزرار: يعدّل الرسالة نفسها. في النصوص: يرسل رسالة جديدة."""
        if self.is_cb and self.msg_id and len(text) <= tg.MAX_LEN:
            if tg.edit(self.chat_id, self.msg_id, text, markup):
                return
        tg.send(self.chat_id, text, markup)

    def doc(self, filename, content, caption=None):
        return tg.send_doc(self.chat_id, filename, content, caption)

    def delete_user_message(self):
        if not self.is_cb and self.msg_id:
            tg.delete(self.chat_id, self.msg_id)
'''

# ════════════════════ menus.py ════════════════════
SOURCES['menus'] = r'''"""القائمة الرئيسية."""
from __future__ import annotations

from core import kb, esc, on_cb


def sub_line(ctx):
    s = ctx.sub or {}
    if s.get("days") is None:
        return ""
    d = s["days"]
    line = "⏳ متبقي من اشتراكك: <b>%s</b> يوم" % d
    if d <= 7:
        line += "\n⚠️ <b>تنبيه:</b> اشتراكك على وشك الانتهاء، جدّده من زر ⭐ اشتراكي"
    return line


def home(ctx, note=None):
    """يعرض القائمة الرئيسية حسب نوع الحساب (تجاري / فردي)."""
    ctx.reset()
    c = ctx.client
    if not c:
        ctx.send("أرسل /start للدخول.")
        return
    acc = (c.get("account_type") or "").strip()
    if not acc:
        from accounts import ask_account_type   # استيراد متأخر لتفادي الدوران
        ask_account_type(ctx)
        return

    title = esc(c.get("shop_name") or c.get("name") or "")
    lines = []
    if note:
        lines.append(note)
        lines.append("")
    lines.append("🏪 <b>%s</b>" % title if acc == "تجاري" else "👤 <b>%s</b>" % title)
    lines.append("=== أهلاً بك في نظام إدارة المتجر والديون ===")
    sl = sub_line(ctx)
    if sl:
        lines.append(sl)
    lines.append("")
    lines.append("===== القائمة الرئيسية =====")
    lines.append("اختر العملية:")

    if acc == "تجاري":
        rows = [
            [("🧮 حاسبة الصرف", "calc:menu"), ("📦 إضافة منتجات (استيراد)", "imp:start")],
            [("👤 إضافة عميل", "cust:add"), ("🛒 المبيعات", "sale:menu")],
            [("📊 التقارير والتعديلات", "rp:menu"), ("💸 تسديد الديون", "pay:menu")],
            [("⭐ اشتراكي", "sub:home"), ("🏪 حسابي", "acct:info")],
        ]
    else:  # فردي — القسم فارغ في مشروع Java حالياً
        rows = [
            [("🧮 حاسبة الصرف", "calc:menu")],
            [("⭐ اشتراكي", "sub:home"), ("🏪 حسابي", "acct:info")],
        ]
        lines.insert(len(lines) - 2, "ℹ️ بقية خدمات الحساب الفردي قيد التطوير.")
    if ctx.is_admin:
        rows.append([("🛡 لوحة الإدارة", "adm:home")])
    rows.append([("🚪 تسجيل الخروج", "acct:out")])
    ctx.reply("\n".join(lines), kb(*rows))


@on_cb("m")
def cb_m(ctx):
    home(ctx)
'''

# ════════════════════ accounts.py ════════════════════
SOURCES['accounts'] = r'''"""الحسابات: البدء، التسجيل (شهر مجاني)، الدخول، نوع الحساب (فردي/تجاري)، الخروج.

يطابق منطق Client / ClientDAO / Information / Main في مشروع Java.
"""
from __future__ import annotations

import logging

import core
import db
import menus
import subs
from config import cfg
from core import (BACK_HOME, clean_text, duration_label, esc, fetch_client, kb, on_cb, on_state,
                  parse_int, store_password, check_password)

log = logging.getLogger("accounts")

COUNTRIES = ["اليمن", "السعودية", "عمان", "مصر", "الامارات", "قطر",
             "البحرين", "الكويت", "العراق", "سوريا", "الاردن", "السودان"]
OTHER_COUNTRY = "دولة اخرى"
CURRENCIES = {1: "الريال اليمني", 2: "الريال السعودي", 3: "الدولار"}
MAX_NUM = 2147483647


# ───────────────────────── البدء ─────────────────────────
def can_register(ctx):
    mode = cfg.REGISTRATION_MODE
    if mode == "closed":
        return False, "التسجيل الذاتي مغلق حالياً. إذا كان لديك حساب اضغط «تسجيل الدخول»."
    if db.val("SELECT COUNT(*) FROM bot_audit_log WHERE telegram_id = :p_t AND action = 'REGISTER'",
              0, p_t=ctx.user_id):
        return False, "سبق أن أنشأت حساباً من هذا الحساب في تلجرام. اضغط «تسجيل الدخول»."
    if mode != "open":   # first_only (مثل برنامج Java)
        first_run = db.val("SELECT COUNT(*) FROM clients_table", 0) == 0
        if not first_run:
            return False, "الحسابات تُنشأ من الإدارة. إذا كان لديك رقم عميل وكلمة مرور اضغط «تسجيل الدخول»."
        if cfg.ADMIN_IDS and not ctx.is_admin:
            return False, "إنشاء أول حساب متاح للمدير فقط."
    return True, ""


def start(ctx, fresh=False):
    ctx.reset()
    if ctx.client:
        return menus.home(ctx)
    ok, why = can_register(ctx)
    text = ("========= مرحبا بك عزيزنا العميل =========\n"
            "=== أهلاً بك في نظام إدارة المتجر والديون ===\n\n")
    rows = [[("🔐 تسجيل الدخول", "auth:login")]]
    if ok:
        text += ("🎁 مرحبا بك في الفترة التجريبية مدتها <b>%s</b> كاملة.\n"
                 "يرجى إنشاء حسابك الأساسي (ستحصل على فترة مجانية):" % duration_label(cfg.TRIAL_MONTHS))
        rows.append([("🆕 إنشاء حساب جديد", "auth:reg")])
    else:
        text += esc(why)
    (ctx.send if fresh else ctx.reply)(text, kb(*rows))


@on_cb("auth")
def cb_auth(ctx):
    a = ctx.args[0] if ctx.args else ""
    if a == "login":
        if ctx.client:
            return menus.home(ctx)
        if is_locked(ctx):
            return
        ctx.go("login:num")
        ctx.reply("--- تسجيل الدخول ---\nأدخل رقم العميل:", kb([("❌ إلغاء", "auth:cancel")]))
    elif a == "reg":
        ok, why = can_register(ctx)
        if not ok:
            ctx.reply(esc(why), kb([("🔐 تسجيل الدخول", "auth:login")]))
            return
        ctx.go("reg:name")
        ctx.reply("أدخل اسمك:", kb([("❌ إلغاء", "auth:cancel")]))
    else:
        start(ctx)


# ───────────────────────── قفل المحاولات ─────────────────────────
def is_locked(ctx):
    mins = db.val("SELECT CEIL((locked_until - SYSDATE) * 1440) FROM bot_users "
                  "WHERE telegram_id = :p_t AND locked_until > SYSDATE", 0, p_t=ctx.user_id)
    if mins:
        ctx.send("⛔ تم إيقاف المحاولات مؤقتاً بسبب أخطاء متكررة. حاول بعد %s دقيقة." % int(mins))
        return True
    return False


def register_failure(ctx):
    n = (ctx.sess.get("fail_count") or 0) + 1
    if n >= 5:
        db.run("UPDATE bot_users SET fail_count = 0, locked_until = SYSDATE + 15/1440 "
               "WHERE telegram_id = :p_t", p_t=ctx.user_id)
    else:
        db.run("UPDATE bot_users SET fail_count = :p_n WHERE telegram_id = :p_t",
               p_n=n, p_t=ctx.user_id)


# ───────────────────────── تسجيل الدخول ─────────────────────────
@on_state("login:num")
def st_login_num(ctx):
    n = parse_int(ctx.text, 1, MAX_NUM)
    if n is None:
        ctx.send("أدخل رقم العميل بالأرقام فقط:")
        return
    ctx.go("login:pass", num=n)
    ctx.send("أدخل كلمة المرور:\n<i>(سيتم حذف رسالتك فور وصولها حفاظاً على الأمان)</i>")


@on_state("login:pass")
def st_login_pass(ctx):
    pw = ctx.text or ""
    ctx.delete_user_message()
    if is_locked(ctx):
        ctx.reset()
        return
    num = ctx.data.get("num")
    row = db.one("SELECT password_hash FROM clients_table WHERE num = :p_n", p_n=num)
    if not row or not check_password(row.get("password_hash"), pw):
        register_failure(ctx)
        ctx.reset()
        ctx.send("[خطأ]: رقم العميل أو كلمة المرور غير صحيحة!",
                 kb([("🔁 حاول مرة أخرى", "auth:login")]))
        return
    ctx.link(num)
    ctx.client = fetch_client(num)
    ctx.sub = subs.status(ctx.client)
    core.audit("LOGIN", ctx, client_num=num)
    after_login(ctx)


def after_login(ctx):
    ctx.reset()
    if not ctx.sub["ok"]:
        return subs.show_expired(ctx)
    msg = "✅ [نجاح]: تم تسجيل الدخول. اشتراكك ساري المفعول!"
    if ctx.sub.get("days") is not None:
        msg += "\nمتبقي من اشتراكك: %s يوم." % ctx.sub["days"]
    ctx.send(msg)
    menus.home(ctx)


# ───────────────────────── إنشاء حساب ─────────────────────────
def email_ok(e):
    e = (e or "").strip()
    if not e or " " in e or "@" not in e or len(e) > 150:
        return False
    suf = cfg.EMAIL_SUFFIX
    if suf and not e.lower().endswith(suf.lower()):
        return False
    local, _, domain = e.partition("@")
    return bool(local) and "." in domain


@on_state("reg:name")
def st_reg_name(ctx):
    name = clean_text(ctx.text, 100)
    if not name:
        ctx.send("أدخل اسماً صحيحاً (حتى 100 حرف):")
        return
    ctx.go("reg:num", name=name)
    ctx.send("أدخل رقمك (سيكون هو رقم الدخول للنظام):")


@on_state("reg:num")
def st_reg_num(ctx):
    n = parse_int(ctx.text, 1, MAX_NUM)
    if n is None:
        ctx.send("أدخل رقماً صحيحاً (أرقام فقط):")
        return
    if db.one("SELECT num FROM clients_table WHERE num = :p_n", p_n=n):
        ctx.send("عذراً، هذا الرقم مستخدم من قبل! اختر رقماً آخر:")
        return
    ctx.go("reg:email", num=n)
    ctx.send("تم قبول الرقم بنجاح ✅\nأدخل الايميل:")


@on_state("reg:email")
def st_reg_email(ctx):
    e = (ctx.text or "").strip()
    if not email_ok(e):
        suf = cfg.EMAIL_SUFFIX
        ctx.send("الايميل غير صحيح يجب ان يحتوي على @" + (" وينتهي بـ %s" % esc(suf) if suf else "") + "\nأعد المحاولة:")
        return
    if db.one("SELECT num FROM clients_table WHERE LOWER(email) = :p_e", p_e=e.lower()):
        ctx.send("هذا الايميل مستخدم من قبل. أدخل ايميلاً آخر:")
        return
    ctx.go("reg:pass", email=e)
    ctx.send("تم قبول الايميل بنجاح ✅\nأدخل كلمة المرور (8 احرف او ارقام على الاقل):\n"
             "<i>(سيتم حذف رسالتك فور وصولها حفاظاً على الأمان)</i>")


@on_state("reg:pass")
def st_reg_pass(ctx):
    pw = ctx.text or ""
    ctx.delete_user_message()
    if len(pw) < 8 or len(pw) > 100:
        ctx.send("غلط، يلزم ان يكون الباسورد 8 احرف او ارقام على الاقل. أعد المحاولة:")
        return
    d = ctx.data
    months = cfg.TRIAL_MONTHS
    try:
        db.run("INSERT INTO clients_table (num, name, email, password_hash, subscription_months, "
               "subscription_duration, money) VALUES (:p_num, :p_name, :p_email, :p_pw, :p_m, :p_d, :p_money)",
               p_num=d["num"], p_name=d["name"], p_email=d["email"], p_pw=store_password(pw),
               p_m=months, p_d=duration_label(months), p_money=0)
    except Exception as e:
        if "ORA-00001" in str(e):
            ctx.reset()
            ctx.send("❌ الرقم أو الايميل مستخدم من قبل. ابدأ من جديد:",
                     kb([("🆕 إنشاء حساب جديد", "auth:reg")]))
            return
        raise
    core.audit("REGISTER", ctx, client_num=d["num"], details="trial=%s" % months)
    num = d["num"]
    ctx.link(num)
    ctx.client = fetch_client(num)
    ctx.sub = subs.status(ctx.client)
    ctx.reset()
    ctx.send("✅ تم إنشاء الحساب بنجاح وتفعيل الشهر المجاني!\nتم تسجيل دخولك تلقائياً.")
    menus.home(ctx)


# ───────────────────────── نوع الحساب (مرة واحدة) ─────────────────────────
def ask_account_type(ctx):
    ctx.reset()
    ctx.send("[إعداد الحساب]: هذه الخطوة تظهر لمرة واحدة فقط.\nهل أنت:",
             kb([("👤 شخص فردي", "type:ind"), ("🏪 محل تجاري", "type:shop")]))


def _save_type(ctx, acc_type, info):
    info = info or {}
    db.run("UPDATE clients_table SET account_type = :p_t, shop_name = :p_sn, activity_type = :p_ac, "
           "location = :p_lo, shop_location = :p_sl, currency = :p_cu WHERE num = :p_n",
           p_t=acc_type, p_sn=info.get("shop_name"), p_ac=info.get("activity"),
           p_lo=info.get("location"), p_sl=info.get("country"), p_cu=info.get("currency"),
           p_n=ctx.client["num"])
    ctx.client = fetch_client(ctx.client["num"])


def _type_pending(ctx):
    return ctx.client and not (ctx.client.get("account_type") or "").strip()


@on_cb("type")
def cb_type(ctx):
    if not _type_pending(ctx):
        ctx.answer("تم تحديد نوع الحساب مسبقاً")
        return
    a = ctx.args
    kind = a[0] if a else ""
    if kind == "ind":
        _save_type(ctx, "فردي", None)
        core.audit("ACCOUNT_TYPE", ctx, details="فردي")
        ctx.send("تم اعتماد حسابك كـ (شخص فردي).")
        menus.home(ctx)
    elif kind == "shop":
        ctx.go("setup:shop_name")
        ctx.reply("أدخل اسم المحل:")
    elif kind == "ctry" and len(a) > 1 and a[1].isdigit():
        i = int(a[1])
        country = COUNTRIES[i - 1] if 1 <= i <= len(COUNTRIES) else OTHER_COUNTRY
        ctx.go("setup:currency", country=country)
        ctx.reply("اختر العملة:", kb([("الريال اليمني", "type:cur:1"), ("الريال السعودي", "type:cur:2")],
                                    [("الدولار", "type:cur:3")]))
    elif kind == "cur" and len(a) > 1 and a[1].isdigit():
        d = ctx.data
        if not d.get("shop_name"):
            ask_account_type(ctx)
            return
        info = dict(shop_name=d.get("shop_name"), activity=d.get("activity"),
                    location=d.get("location"), country=d.get("country"),
                    currency=CURRENCIES.get(int(a[1]), "الدولار"))
        _save_type(ctx, "تجاري", info)
        core.audit("ACCOUNT_TYPE", ctx, details="تجاري")
        ctx.send("✅ تم اعتماد حسابك وحفظ بيانات المحل التجاري بنجاح!")
        menus.home(ctx)


@on_state("setup:shop_name")
def st_shop_name(ctx):
    v = clean_text(ctx.text, 100, True)
    if not v:
        ctx.send("أدخل اسم المحل (حتى 50 حرفاً):")
        return
    ctx.go("setup:activity", shop_name=v)
    ctx.send("أدخل نوع النشاط:")


@on_state("setup:activity")
def st_shop_activity(ctx):
    v = clean_text(ctx.text, 100, True)
    if not v:
        ctx.send("أدخل نوع النشاط (حتى 50 حرفاً):")
        return
    ctx.go("setup:location", activity=v)
    ctx.send("أدخل الموقع/الشارع:")


@on_state("setup:location")
def st_shop_location(ctx):
    v = clean_text(ctx.text, 100, True)
    if not v:
        ctx.send("أدخل الموقع (حتى 50 حرفاً):")
        return
    ctx.go("setup:country", location=v)
    names = COUNTRIES + [OTHER_COUNTRY]
    buttons = [(n, "type:ctry:%d" % (i + 1)) for i, n in enumerate(names)]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    ctx.send("اختر الدولة:", kb(*rows))


# ───────────────────────── حسابي / خروج ─────────────────────────
@on_cb("acct")
def cb_acct(ctx):
    a = ctx.args[0] if ctx.args else ""
    if a == "info":
        info(ctx)
    elif a == "out":
        logout(ctx)


def info(ctx):
    c = ctx.client
    acc = (c.get("account_type") or "").strip()
    lines = ["🏪 <b>حسابي</b>", "",
             "الاسم: %s" % esc(c.get("name")),
             "رقم العميل (رقم الدخول): %s" % c.get("num"),
             "الايميل: %s" % esc(c.get("email")),
             "نوع الحساب: %s" % esc(acc or "غير محدد")]
    if acc == "تجاري":
        lines += ["", "<b>بيانات المحل</b>",
                  "اسم المحل: %s" % esc(c.get("shop_name")),
                  "النشاط: %s" % esc(c.get("activity_type")),
                  "الموقع: %s" % esc(c.get("location")),
                  "الدولة: %s" % esc((c.get("shop_location") or "").rstrip(":")),
                  "العملة: %s" % esc((c.get("currency") or "").rstrip(":"))]
    lines += ["", "<b>الاشتراك</b>",
              "ينتهي في: %s" % core.fmt_date(c.get("expiry_date"))]
    s = ctx.sub or {}
    if s.get("days") is not None:
        lines.append("المتبقي: %s يوم" % s["days"])
    ctx.reply("\n".join(lines), kb([("⭐ اشتراكي", "sub:home")], [BACK_HOME]))


def logout(ctx):
    num = (ctx.client or {}).get("num")
    core.audit("LOGOUT", ctx, client_num=num)
    ctx.unlink()
    ctx.reply("... تم تسجيل الخروج بنجاح. العودة لشاشة الدخول 🔄")
    start(ctx, fresh=True)
'''

# ════════════════════ subs.py ════════════════════
SOURCES['subs'] = r'''"""الاشتراكات: الحالة، الفترة التجريبية، طلبات التجديد، تفعيل المدير، التذكيرات.

منطق التواريخ يعتمد على trigger الجدول (trg_clients_bi):
    expiry_date = ADD_MONTHS(start_date, subscription_months)
لذلك نحدّث subscription_months (و start_date عند الانتهاء) ولا نكتب expiry_date مباشرة.
"""
from __future__ import annotations

import logging

import core
import db
import tg
from config import cfg
from core import (BACK_HOME, duration_label, esc, fmt_date, fmt_num, kb, on_cb, on_state)

log = logging.getLogger("subs")

STATUS_AR = {"PENDING": "⏳ قيد المراجعة", "APPROVED": "✅ تم التفعيل",
             "REJECTED": "❌ مرفوض", "CANCELLED": "🚫 ملغي"}
MAX_TOTAL_MONTHS = 999


# ───────────────────────── الحالة ─────────────────────────
def status(client):
    dl = client.get("days_left")
    flag = client.get("is_active")
    blocked = flag is not None and int(flag) == 0
    expired = dl is not None and dl < 0
    return {
        "ok": (not blocked) and (not expired),
        "blocked": blocked,
        "expired": expired,
        "days": None if dl is None else int(dl),     # نفس قص Java (getInt)
        "expiry": client.get("expiry_date"),
    }


def month_price():
    return int(db.val("SELECT month_price FROM system_settings WHERE id = 1", 0) or 0)


def pay_text():
    return ("يرجى تحويل المبلغ ثم الاتصال بـ %s على الرقم: <b>%s</b>\n"
            "للتحويل: <b>%s</b>\n"
            "أو إرسال رسالة برقم حسابك ليتم تفعيل النظام فوراً من قبل الإدارة."
            % (esc(cfg.PAY_CONTACT_NAME), esc(cfg.PAY_CONTACT_PHONE), esc(cfg.PAY_TRANSFER_NUMBER)))


def show_expired(ctx):
    s = ctx.sub or {}
    if s.get("blocked"):
        ctx.reply("⛔ <b>حسابك موقوف.</b>\nيرجى التواصل مع الإدارة: <b>%s</b>" % esc(cfg.PAY_CONTACT_PHONE),
                  kb([("🚪 تسجيل الخروج", "acct:out")]))
        return
    text = ("==================================\n"
            "عذراً، انتهت فترة اشتراكك في النظام.\n"
            "تاريخ الانتهاء: <b>%s</b>\n"
            "يرجى اختيار باقة التجديد المناسبة لك:\n"
            "==================================" % fmt_date(s.get("expiry")))
    ctx.reply(text, kb([("🔄 تجديد الاشتراك", "sub:plans")],
                       [("📜 طلباتي", "sub:list"), ("🏪 حسابي", "acct:info")],
                       [("🚪 تسجيل الخروج", "acct:out")]))


# ───────────────────────── شاشات الاشتراك ─────────────────────────
@on_cb("sub")
def cb_sub(ctx):
    a = ctx.args
    act = a[0] if a else "home"
    if act == "home":
        home(ctx)
    elif act == "plans":
        plans(ctx)
    elif act == "pick" and len(a) > 1 and a[1].isdigit():
        pick(ctx, int(a[1]))
    elif act == "send" and len(a) > 1 and a[1].isdigit():
        send_request(ctx, int(a[1]))
    elif act == "list":
        my_requests(ctx)
    elif act == "proof" and len(a) > 1 and a[1].isdigit():
        ask_proof(ctx, int(a[1]))
    elif act == "cancel" and len(a) > 1 and a[1].isdigit():
        cancel_request(ctx, int(a[1]))


def home(ctx):
    ctx.reset()
    c = ctx.client
    s = ctx.sub or {}
    price = month_price()
    lines = ["⭐ <b>اشتراكي</b>", "",
             "الحساب: %s (رقم: %s)" % (esc(c.get("name")), c.get("num")),
             "المدة المسجلة: %s" % esc((c.get("subscription_duration") or duration_label(c.get("subscription_months"))).rstrip(":")),
             "بدأ في: %s" % fmt_date(c.get("start_date")),
             "ينتهي في: <b>%s</b>" % fmt_date(c.get("expiry_date"))]
    if s.get("blocked"):
        lines.append("الحالة: ⛔ موقوف")
    elif s.get("expired"):
        lines.append("الحالة: ❌ منتهي")
    else:
        lines.append("الحالة: ✅ ساري" + (" — متبقي %s يوم" % s["days"] if s.get("days") is not None else ""))
    lines.append("سعر الشهر: %s %s" % (fmt_num(price), cfg.SUB_PRICE_UNIT) if price else "سعر الشهر: يحدده المدير")
    ctx.reply("\n".join(lines), kb([("🔄 تجديد / تمديد الاشتراك", "sub:plans")],
                                   [("📜 طلباتي", "sub:list")],
                                   [BACK_HOME]))


def plans(ctx):
    price = month_price()
    lines = ["🔄 <b>باقات التجديد</b>", ""]
    if price:
        lines.append("سعر الشهر الواحد: <b>%s</b> %s" % (fmt_num(price), cfg.SUB_PRICE_UNIT))
    else:
        lines.append("⚠️ لم يتم تحديد سعر الاشتراك بعد، سيحدده المدير عند التفعيل.")
    lines.append("اختر الباقة:")
    btns = []
    for m in range(1, 13):
        label = duration_label(m)
        btns.append((label + (" • %s" % fmt_num(price * m) if price else ""), "sub:pick:%d" % m))
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([BACK_HOME])
    ctx.reply("\n".join(lines), kb(*rows))


def pick(ctx, months):
    if not 1 <= months <= 12:
        return
    price = month_price()
    total = months * price
    lines = ["📦 الباقة: <b>%s</b>" % duration_label(months)]
    if price:
        lines.append("المبلغ المطلوب للتجديد: <b>%s</b> %s" % (fmt_num(total), cfg.SUB_PRICE_UNIT))
    else:
        lines.append("المبلغ المطلوب: يحدده المدير")
    lines += ["", pay_text()]
    ctx.reply("\n".join(lines), kb([("✅ أرسل طلب التجديد للإدارة", "sub:send:%d" % months)],
                                   [("⬅️ الباقات", "sub:plans"), BACK_HOME]))


def _pending(num):
    return db.one("SELECT req_id, months, amount FROM bot_sub_requests "
                  "WHERE client_num = :p_c AND status = 'PENDING' ORDER BY req_id DESC", p_c=num)


def send_request(ctx, months):
    if not 1 <= months <= 12:
        return
    c = ctx.client
    pend = _pending(c["num"])
    if pend:
        ctx.reply("لديك طلب تجديد قيد المراجعة رقم <b>#%s</b> (%s).\n"
                  "ألغِه أولاً إذا أردت طلباً جديداً، أو أرسل إشعار التحويل."
                  % (pend["req_id"], duration_label(pend["months"])),
                  kb([("📎 إرسال إشعار التحويل", "sub:proof:%d" % pend["req_id"])],
                     [("🗑 إلغاء الطلب", "sub:cancel:%d" % pend["req_id"])], [BACK_HOME]))
        return
    amount = months * month_price()
    with db.tx() as t:
        rid = t.val("SELECT bot_req_seq.NEXTVAL FROM dual")
        t.run("INSERT INTO bot_sub_requests (req_id, client_num, telegram_id, months, amount) "
              "VALUES (:p_id, :p_c, :p_t, :p_m, :p_a)",
              p_id=rid, p_c=c["num"], p_t=ctx.user_id, p_m=months, p_a=amount)
        core.audit("SUB_REQUEST", ctx, details="req=%s months=%s amount=%s" % (rid, months, amount), t=t)
    rid = int(rid)
    notify_admins_request(ctx, rid, months, amount)
    ctx.reply("✅ تم إرسال طلب التجديد رقم <b>#%s</b> للإدارة.\n"
              "يمكنك إرفاق صورة إشعار التحويل ليتم التفعيل بسرعة." % rid,
              kb([("📎 إرسال إشعار التحويل", "sub:proof:%d" % rid)], [BACK_HOME]))
    if not cfg.ADMIN_IDS:
        ctx.send("ℹ️ لم يتم تعيين مدير في البوت بعد، تواصل مع الإدارة مباشرة على: %s" % esc(cfg.PAY_CONTACT_PHONE))


def my_requests(ctx):
    rows = db.rows("SELECT * FROM (SELECT req_id, months, amount, status, created_at FROM bot_sub_requests "
                   "WHERE client_num = :p_c ORDER BY req_id DESC) WHERE ROWNUM <= 8", p_c=ctx.client["num"])
    if not rows:
        ctx.reply("لا توجد طلبات تجديد سابقة.", kb([("🔄 تجديد الاشتراك", "sub:plans")], [BACK_HOME]))
        return
    lines = ["📜 <b>طلبات التجديد</b>", ""]
    for r in rows:
        lines.append("#%s • %s • %s %s • %s\n    %s" % (
            r["req_id"], duration_label(r["months"]), fmt_num(r["amount"]), cfg.SUB_PRICE_UNIT,
            STATUS_AR.get(r["status"], r["status"]), core.fmt_dt(r["created_at"])))
    ctx.reply("\n".join(lines), kb([("🔄 تجديد الاشتراك", "sub:plans")], [BACK_HOME]))


def cancel_request(ctx, rid):
    n = db.run("UPDATE bot_sub_requests SET status = 'CANCELLED', decided_at = SYSDATE "
               "WHERE req_id = :p_id AND client_num = :p_c AND status = 'PENDING'",
               p_id=rid, p_c=ctx.client["num"])
    core.audit("SUB_CANCEL", ctx, details="req=%s" % rid)
    ctx.reply("🚫 تم إلغاء الطلب." if n else "لا يوجد طلب معلّق بهذا الرقم.",
              kb([("🔄 تجديد الاشتراك", "sub:plans")], [BACK_HOME]))


def ask_proof(ctx, rid):
    req = db.one("SELECT req_id FROM bot_sub_requests WHERE req_id = :p_id AND client_num = :p_c "
                 "AND status = 'PENDING'", p_id=rid, p_c=ctx.client["num"])
    if not req:
        ctx.reply("لا يوجد طلب معلّق بهذا الرقم.", kb([BACK_HOME]))
        return
    ctx.go("sub:proof", rid=rid)
    ctx.reply("📎 أرسل الآن صورة إشعار التحويل (أو رقم العملية) لطلبك <b>#%s</b>:" % rid,
              kb([("❌ إلغاء", "sub:home")]))


@on_state("sub:proof", media=True)
def st_proof(ctx):
    rid = ctx.data.get("rid")
    req = db.one("SELECT req_id, months, amount FROM bot_sub_requests WHERE req_id = :p_id "
                 "AND client_num = :p_c AND status = 'PENDING'", p_id=rid, p_c=ctx.client["num"])
    ctx.reset()
    if not req:
        ctx.send("لا يوجد طلب معلّق بهذا الرقم.", kb([BACK_HOME]))
        return
    if not cfg.ADMIN_IDS:
        ctx.send("لم يتم تعيين مدير في البوت. تواصل مع الإدارة: %s" % esc(cfg.PAY_CONTACT_PHONE))
        return
    c = ctx.client
    head = ("📎 <b>إشعار تحويل للطلب #%s</b>\nالعميل: %s (رقم: %s)\nالمدة: %s • المبلغ: %s %s"
            % (rid, esc(c.get("name")), c.get("num"), duration_label(req["months"]),
               fmt_num(req["amount"]), cfg.SUB_PRICE_UNIT))
    markup = kb([("✅ تفعيل", "adm:ok:%d" % rid), ("❌ رفض", "adm:no:%d" % rid)])
    for adm in cfg.ADMIN_IDS:
        tg.send(adm, head, markup)
        tg.forward(adm, ctx.chat_id, ctx.msg_id)
    core.audit("SUB_PROOF", ctx, details="req=%s" % rid)
    ctx.send("✅ تم إرسال إشعار التحويل للإدارة. سيتم التفعيل بعد المراجعة.", kb([BACK_HOME]))


# ───────────────────────── إشعارات المدير ─────────────────────────
def notify_admins_request(ctx, rid, months, amount):
    c = ctx.client
    s = ctx.sub or {}
    now = "منتهي" if s.get("expired") else ("ساري — متبقي %s يوم" % s.get("days") if s.get("days") is not None else "ساري")
    text = ("🔔 <b>طلب تجديد اشتراك #%s</b>\n"
            "العميل: %s (رقم: %s)\n"
            "المحل: %s\n"
            "المدة: %s\n"
            "المبلغ: %s %s\n"
            "حالة الاشتراك الآن: %s"
            % (rid, esc(c.get("name")), c.get("num"), esc(c.get("shop_name") or "-"),
               duration_label(months), fmt_num(amount), cfg.SUB_PRICE_UNIT, now))
    markup = kb([("✅ تفعيل", "adm:ok:%d" % rid), ("❌ رفض", "adm:no:%d" % rid)])
    for adm in cfg.ADMIN_IDS:
        tg.send(adm, text, markup)


def notify_client(num, text, markup=None):
    for r in db.rows("SELECT telegram_id FROM bot_users WHERE client_num = :p_c", p_c=num):
        tg.send(int(r["telegram_id"]), text, markup)


# ───────────────────────── التفعيل (للمدير) ─────────────────────────
def grant(t, num, months, amount):
    """يجدّد أو يمدّد اشتراك العميل داخل Transaction. يرجع (تاريخ الانتهاء الجديد، إجمالي الأشهر)."""
    c = t.one("SELECT subscription_months, (expiry_date - SYSDATE) AS days_left "
              "FROM clients_table WHERE num = :p_n FOR UPDATE", p_n=num)
    if c is None:
        raise ValueError("العميل غير موجود")
    dl = c.get("days_left")
    if dl is not None and dl < 0:
        # منتهي: نبدأ فترة جديدة من الآن
        total = months
        t.run("UPDATE clients_table SET start_date = SYSDATE, subscription_months = :p_m, "
              "subscription_duration = :p_d, money = :p_a, is_active = 1 WHERE num = :p_n",
              p_m=total, p_d=duration_label(total), p_a=amount, p_n=num)
    else:
        # ساري: نمدّد من تاريخ الانتهاء الحالي
        total = int(c.get("subscription_months") or 0) + months
        if total > MAX_TOTAL_MONTHS:
            raise ValueError("إجمالي الأشهر يتجاوز %d" % MAX_TOTAL_MONTHS)
        t.run("UPDATE clients_table SET subscription_months = :p_m, subscription_duration = :p_d, "
              "money = NVL(money, 0) + :p_a, is_active = 1 WHERE num = :p_n",
              p_m=total, p_d=duration_label(total), p_a=amount, p_n=num)
    exp = t.val("SELECT expiry_date FROM clients_table WHERE num = :p_n", None, p_n=num)
    return exp, total


def approve_request(ctx, rid):
    """يرجع (طلب، رسالة). عند النجاح الرسالة = تاريخ الانتهاء الجديد."""
    with db.tx() as t:
        req = t.one("SELECT req_id, client_num, months, amount, status FROM bot_sub_requests "
                    "WHERE req_id = :p_id FOR UPDATE", p_id=rid)
        if not req:
            return None, "الطلب غير موجود."
        if req["status"] != "PENDING":
            return None, "هذا الطلب تمت معالجته مسبقاً (%s)." % STATUS_AR.get(req["status"], req["status"])
        exp, total = grant(t, req["client_num"], req["months"], req["amount"])
        t.run("UPDATE bot_sub_requests SET status = 'APPROVED', decided_at = SYSDATE, decided_by = :p_by "
              "WHERE req_id = :p_id", p_by=ctx.user_id, p_id=rid)
        core.audit("SUB_APPROVED", ctx, client_num=req["client_num"],
                   details="req=%s months=%s amount=%s" % (rid, req["months"], req["amount"]), t=t)
    notify_client(req["client_num"],
                  "✅ <b>تم تفعيل اشتراكك</b> لمدة %s.\nينتهي في: <b>%s</b>\nشكراً لك 🌹"
                  % (duration_label(req["months"]), fmt_date(exp)),
                  kb([BACK_HOME]))
    return req, exp


def reject_request(ctx, rid):
    with db.tx() as t:
        req = t.one("SELECT req_id, client_num, months, status FROM bot_sub_requests "
                    "WHERE req_id = :p_id FOR UPDATE", p_id=rid)
        if not req:
            return None, "الطلب غير موجود."
        if req["status"] != "PENDING":
            return None, "هذا الطلب تمت معالجته مسبقاً (%s)." % STATUS_AR.get(req["status"], req["status"])
        t.run("UPDATE bot_sub_requests SET status = 'REJECTED', decided_at = SYSDATE, decided_by = :p_by "
              "WHERE req_id = :p_id", p_by=ctx.user_id, p_id=rid)
        core.audit("SUB_REJECTED", ctx, client_num=req["client_num"], details="req=%s" % rid, t=t)
    notify_client(req["client_num"],
                  "❌ تم رفض طلب التجديد #%s.\nللاستفسار تواصل مع الإدارة: %s" % (rid, esc(cfg.PAY_CONTACT_PHONE)),
                  kb([("🔄 طلب جديد", "sub:plans")]))
    return req, "ok"


# ───────────────────────── التذكيرات (يستدعيها cron) ─────────────────────────
def _kind(dl):
    if dl < 0:
        return "EXP"
    if dl <= 1:
        return "D1"
    if dl <= 3:
        return "D3"
    if dl <= 7:
        return "D7"
    return None


def run_reminders():
    """يرسل تذكيرات الاشتراك (قبل 7/3/1 يوم وعند الانتهاء) مرة واحدة لكل مرحلة. يرجع عدد الرسائل."""
    sent = 0
    rows = db.rows("SELECT num, name, expiry_date, (expiry_date - SYSDATE) AS days_left FROM clients_table "
                   "WHERE is_active = 1 AND expiry_date IS NOT NULL "
                   "AND expiry_date BETWEEN SYSDATE - 3 AND SYSDATE + 7")
    for r in rows:
        kind = _kind(r["days_left"])
        if not kind:
            continue
        done = db.val("SELECT COUNT(*) FROM bot_reminder_log WHERE client_num = :p_c "
                      "AND expiry_date = :p_e AND kind = :p_k", 0, p_c=r["num"], p_e=r["expiry_date"], p_k=kind)
        if done:
            continue
        if kind == "EXP":
            text = ("⛔ <b>انتهى اشتراكك</b> بتاريخ %s.\nجدّد اشتراكك لمتابعة استخدام النظام."
                    % fmt_date(r["expiry_date"]))
        else:
            d = max(int(r["days_left"]), 0)
            text = ("⏰ <b>تنبيه:</b> ينتهي اشتراكك بتاريخ %s (متبقي %s يوم).\n"
                    "جدّد الآن حتى لا ينقطع النظام عنك." % (fmt_date(r["expiry_date"]), d))
        markup = kb([("🔄 تجديد الاشتراك", "sub:plans")])
        targets = db.rows("SELECT telegram_id FROM bot_users WHERE client_num = :p_c", p_c=r["num"])
        for tt in targets:
            if tg.send(int(tt["telegram_id"]), text, markup):
                sent += 1
        db.run("INSERT INTO bot_reminder_log (client_num, expiry_date, kind) VALUES (:p_c, :p_e, :p_k)",
               p_c=r["num"], p_e=r["expiry_date"], p_k=kind)
    return sent
'''

# ════════════════════ pickers.py ════════════════════
SOURCES['pickers'] = r'''"""أدوات البحث والاختيار المشتركة (عملاء ومنتجات) + استعلامات مساعدة.

في برنامج Java كان البحث يأخذ أول نتيجة فقط. هنا إذا تطابق أكثر من عنصر يظهر للمستخدم
قائمة أزرار ليختار منها بدقة (يمنع بيع/حذف عنصر خاطئ).
"""
from __future__ import annotations

import db
from config import cfg
from core import (LIKE_ESC, esc, fmt_num, kb, like, on_cb, on_state, parse_int)

CUST = {}     # purpose -> fn(ctx, {"name":..., "phone":...})
PROD = {}     # purpose -> fn(ctx, product_dict)
LIMIT = 10


def cust_purpose(name):
    def deco(fn):
        CUST[name] = fn
        return fn
    return deco


def prod_purpose(name):
    def deco(fn):
        PROD[name] = fn
        return fn
    return deco


# ───────────────────────── استعلامات مساعدة ─────────────────────────
PROD_COLS = ("product_id, product_name, NVL(price, 0) AS price, NVL(quantity, 0) AS quantity, "
             "NVL(units_per_carton, 1) AS units_per_carton, NVL(purchase_price, 0) AS purchase_price")


def find_products(q):
    return db.rows("SELECT * FROM (SELECT " + PROD_COLS + " FROM products_table "
                   "WHERE LOWER(product_name) LIKE :p_q" + LIKE_ESC + " ORDER BY product_name) "
                   "WHERE ROWNUM <= " + str(LIMIT + 1), p_q=like(q))


def get_product(pid):
    return db.one("SELECT " + PROD_COLS + " FROM products_table WHERE product_id = :p_id", p_id=pid)


def find_customers(cn, name=None, phone=None):
    if phone is not None:
        return db.rows("SELECT customer_name, customer_phone FROM shop_customers "
                       "WHERE customer_phone = :p_ph AND client_num = :p_cn", p_ph=phone, p_cn=cn)
    return db.rows("SELECT * FROM (SELECT customer_name, customer_phone FROM shop_customers "
                   "WHERE LOWER(customer_name) LIKE :p_q" + LIKE_ESC + " AND client_num = :p_cn "
                   "ORDER BY customer_name) WHERE ROWNUM <= " + str(LIMIT + 1), p_q=like(name), p_cn=cn)


def get_customer(cn, phone):
    r = db.one("SELECT customer_name, customer_phone FROM shop_customers "
               "WHERE customer_phone = :p_ph AND client_num = :p_cn", p_ph=phone, p_cn=cn)
    return {"name": r["customer_name"], "phone": int(r["customer_phone"])} if r else None


def debt_totals(phone, cn):
    """(إجمالي الدين، إجمالي المسدد، المتبقي) — نفس حساب Java."""
    r = db.one("SELECT NVL(SUM(debt_amount), 0) AS t_debt, NVL(SUM(paid_amount), 0) AS t_paid "
               "FROM shop_debts WHERE customer_phone = :p_ph AND client_num = :p_cn", p_ph=phone, p_cn=cn)
    td, tp = float(r["t_debt"]), float(r["t_paid"])
    return td, tp, td - tp


def _short(s, n=28):
    s = s or ""
    return s if len(s) <= n else s[:n - 1] + "…"


# ───────────────────────── اختيار العميل ─────────────────────────
def start_cust_search(ctx, purpose, back="m:home"):
    ctx.go(None, cp_purpose=purpose, cp_back=back)
    ctx.reply("ابحث عن العميل بـ:", kb([("🔤 الاسم", "cp:by:name"), ("📞 الرقم", "cp:by:phone")],
                                       [("❌ إلغاء", back)]))


@on_cb("cp")
def cb_cp(ctx):
    a = ctx.args
    d = ctx.data
    purpose, back = d.get("cp_purpose"), d.get("cp_back") or "m:home"
    if purpose not in CUST:
        ctx.reply("انتهت صلاحية هذه الشاشة. افتح القائمة الرئيسية /menu")
        return
    act = a[0] if a else ""
    if act == "by" and len(a) > 1 and a[1] in ("name", "phone"):
        ctx.go("cp:q", cp_by=a[1])
        ctx.reply("أدخل اسم العميل:" if a[1] == "name" else "أدخل رقم العميل:", kb([("❌ إلغاء", back)]))
    elif act == "again":
        start_cust_search(ctx, purpose, back)
    elif act == "pick" and len(a) > 1 and a[1].isdigit():
        c = get_customer(ctx.client["num"], int(a[1]))
        if not c:
            ctx.reply("⚠️ العميل غير موجود.", kb([("🔁 بحث آخر", "cp:again")]))
            return
        CUST[purpose](ctx, c)


@on_state("cp:q")
def st_cp(ctx):
    d = ctx.data
    purpose, back = d.get("cp_purpose"), d.get("cp_back") or "m:home"
    if purpose not in CUST:
        ctx.reset()
        ctx.send("انتهت صلاحية هذه الشاشة. افتح القائمة الرئيسية /menu")
        return
    cn = ctx.client["num"]
    if d.get("cp_by") == "phone":
        ph = parse_int(ctx.text, 0, cfg.MAX_PHONE)
        if ph is None:
            ctx.send("أدخل رقماً صحيحاً (أرقام فقط):")
            return
        rows = find_customers(cn, phone=ph)
    else:
        q = (ctx.text or "").strip()
        if not q:
            ctx.send("أدخل اسم العميل:")
            return
        rows = find_customers(cn, name=q)
    if not rows:
        ctx.send("⚠️ العميل غير موجود.", kb([("🔁 بحث آخر", "cp:again")], [("❌ إلغاء", back)]))
        return
    if len(rows) == 1:
        CUST[purpose](ctx, {"name": rows[0]["customer_name"], "phone": int(rows[0]["customer_phone"])})
        return
    btns = [[("%s (%s)" % (_short(r["customer_name"]), r["customer_phone"]), "cp:pick:%s" % r["customer_phone"])]
            for r in rows[:LIMIT]]
    btns.append([("🔁 بحث آخر", "cp:again"), ("❌ إلغاء", back)])
    note = "\n(يوجد أكثر من %d نتيجة، حدّد الاسم بدقة أكثر)" % LIMIT if len(rows) > LIMIT else ""
    ctx.send("اختر العميل:" + note, kb(*btns))


# ───────────────────────── اختيار المنتج ─────────────────────────
def start_prod_search(ctx, purpose, prompt="أدخل اسم المنتج للبحث:", back="m:home"):
    ctx.go("pp:q", pp_purpose=purpose, pp_back=back)
    ctx.reply(prompt, kb([("❌ إلغاء", back)]))


@on_cb("pp")
def cb_pp(ctx):
    a = ctx.args
    d = ctx.data
    purpose, back = d.get("pp_purpose"), d.get("pp_back") or "m:home"
    if purpose not in PROD:
        ctx.reply("انتهت صلاحية هذه الشاشة. افتح القائمة الرئيسية /menu")
        return
    act = a[0] if a else ""
    if act == "again":
        start_prod_search(ctx, purpose, back=back)
    elif act == "pick" and len(a) > 1 and a[1].isdigit():
        p = get_product(int(a[1]))
        if not p:
            ctx.reply("⚠️ المنتج غير موجود.", kb([("🔁 بحث آخر", "pp:again")]))
            return
        PROD[purpose](ctx, p)


@on_state("pp:q")
def st_pp(ctx):
    d = ctx.data
    purpose, back = d.get("pp_purpose"), d.get("pp_back") or "m:home"
    if purpose not in PROD:
        ctx.reset()
        ctx.send("انتهت صلاحية هذه الشاشة. افتح القائمة الرئيسية /menu")
        return
    q = (ctx.text or "").strip()
    if not q:
        ctx.send("أدخل اسم المنتج للبحث:")
        return
    rows = find_products(q)
    if not rows:
        extra = PROD_EXTRA.get(purpose, [])
        ctx.send("⚠️ المنتج غير موجود.", kb(*(extra + [[("🔁 بحث آخر", "pp:again"), ("❌ إلغاء", back)]])))
        return
    if len(rows) == 1:
        PROD[purpose](ctx, rows[0])
        return
    btns = [[("%s • %s • %s حبة" % (_short(r["product_name"], 24), fmt_num(r["price"]), fmt_num(r["quantity"])),
              "pp:pick:%s" % r["product_id"])] for r in rows[:LIMIT]]
    btns.append([("🔁 بحث آخر", "pp:again"), ("❌ إلغاء", back)])
    note = "\n(يوجد أكثر من %d نتيجة، حدّد الاسم بدقة أكثر)" % LIMIT if len(rows) > LIMIT else ""
    ctx.send("اختر المنتج:" + note, kb(*btns))


PROD_EXTRA = {}   # أزرار إضافية عند عدم وجود نتيجة (مثل «إضافته كمنتج جديد» في الاستيراد)
'''

# ════════════════════ shop.py ════════════════════
SOURCES['shop'] = r'''"""العمليات اليومية: حاسبة الصرف، الاستيراد، إضافة عميل، المبيعات (دين/كاش/شبكة)، الفواتير، تسديد الديون.

يطابق Calculator / Importe / Debts في مشروع Java.
"""
from __future__ import annotations

import logging
import time

import core
import db
from config import cfg
from core import (BACK_HOME, CANCEL_BTN, MAX_AMOUNT, clean_text, esc, fmt_dt, fmt_num, kb,
                  on_cb, on_state, parse_float, parse_int, unit_of)
from pickers import (PROD_EXTRA, cust_purpose, debt_totals, get_customer, prod_purpose,
                     start_cust_search, start_prod_search)

log = logging.getLogger("shop")


def _unit(ctx):
    return unit_of(ctx.client)


# ═══════════════════════════ حاسبة الصرف ═══════════════════════════
CALC_OPS = {
    1: ("من دولار إلى ريال يمني", "دولار", "ريال يمني"),
    2: ("من ريال سعودي إلى ريال يمني", "ريال سعودي", "ريال يمني"),
    3: ("من ريال يمني إلى دولار", "ريال يمني", "دولار"),
    4: ("من ريال يمني إلى ريال سعودي", "ريال يمني", "ريال سعودي"),
    5: ("من دولار إلى ريال سعودي", "دولار", "ريال سعودي"),
    6: ("من ريال سعودي إلى دولار", "ريال سعودي", "دولار"),
}


def get_rates():
    r = db.one("SELECT usd_price, sar_price FROM exchange_rates WHERE id = 1")
    if not r:
        return 0.0, 0.0
    return float(r["usd_price"] or 0), float(r["sar_price"] or 0)


def convert(op, amount, usd, sar):
    if op == 1:
        return amount * usd
    if op == 2:
        return amount * sar
    if op == 3:
        return amount / usd
    if op == 4:
        return amount / sar
    if op == 5:
        return amount * (usd / sar)
    return amount * (sar / usd)


@on_cb("calc")
def cb_calc(ctx):
    a = ctx.args
    act = a[0] if a else "menu"
    usd, sar = get_rates()
    if usd == 0 or sar == 0:
        rows = [[BACK_HOME]]
        if ctx.is_admin:
            rows.insert(0, [("💱 تحديث أسعار الصرف", "adm:rates")])
        ctx.reply("عذراً، لا يمكن تشغيل الحاسبة لعدم توفر أسعار الصرف الحالية.", kb(*rows))
        return
    if act == "op" and len(a) > 1 and a[1].isdigit() and int(a[1]) in CALC_OPS:
        op = int(a[1])
        ctx.go("calc:amt", op=op)
        ctx.reply("%s\nأدخل المبلغ:" % CALC_OPS[op][0], kb([("⬅️ رجوع", "calc:menu")]))
        return
    ctx.reset()
    lines = ["=== 🧮 حاسبة الصرف الآلية ===",
             "💵 الدولار = %s ريال يمني" % fmt_num(usd),
             "🇸🇦 الريال السعودي = %s ريال يمني" % fmt_num(sar), "",
             "اختر العملية المطلوبة:"]
    rows = [[(CALC_OPS[i][0], "calc:op:%d" % i)] for i in range(1, 7)]
    rows.append([BACK_HOME])
    ctx.reply("\n".join(lines), kb(*rows))


@on_state("calc:amt")
def st_calc(ctx):
    op = ctx.data.get("op")
    amount = parse_float(ctx.text, 0.0, 1e12)
    if op not in CALC_OPS or amount is None or amount <= 0:
        ctx.send("أدخل مبلغاً صحيحاً (رقم أكبر من صفر):")
        return
    usd, sar = get_rates()
    if usd == 0 or sar == 0:
        ctx.reset()
        ctx.send("عذراً، لا يمكن تشغيل الحاسبة لعدم توفر أسعار الصرف الحالية.")
        return
    res = convert(op, amount, usd, sar)
    _, src, dst = CALC_OPS[op]
    ctx.send("🧮 %s %s\n<b>النتيجة: %s %s</b>" % (fmt_num(amount), src, fmt_num(res), dst),
             kb([("🔁 عملية أخرى", "calc:menu")], [BACK_HOME]))


# ═══════════════════════════ إضافة عميل ═══════════════════════════
@on_cb("cust")
def cb_cust(ctx):
    if (ctx.args[0] if ctx.args else "") == "add":
        ctx.go("cust:name")
        ctx.reply("--- إضافة عميل جديد ---\nأدخل اسم العميل:", kb([CANCEL_BTN]))


@on_state("cust:name")
def st_cust_name(ctx):
    name = clean_text(ctx.text, 100, True)
    if not name:
        ctx.send("أدخل اسم العميل (حتى 50 حرفاً):")
        return
    ctx.go("cust:phone", c_name=name)
    ctx.send("أدخل رقم العميل:")


@on_state("cust:phone")
def st_cust_phone(ctx):
    ph = parse_int(ctx.text, 1, cfg.MAX_PHONE)
    if ph is None:
        ctx.send("أدخل رقماً صحيحاً (أرقام فقط، بدون مفتاح الدولة):")
        return
    cn = ctx.client["num"]
    name = ctx.data.get("c_name")
    old = db.one("SELECT customer_name, client_num FROM shop_customers WHERE customer_phone = :p_ph", p_ph=ph)
    if old:
        if int(old["client_num"]) == int(cn):
            ctx.send("❌ هذا الرقم مسجل مسبقاً باسم: <b>%s</b>. أدخل رقماً آخر:" % esc(old["customer_name"]))
        else:
            ctx.send("❌ هذا الرقم مسجل مسبقاً. أدخل رقماً آخر:")
        return
    try:
        db.run("INSERT INTO shop_customers (customer_phone, customer_name, client_num) "
               "VALUES (:p_ph, :p_n, :p_cn)", p_ph=ph, p_n=name, p_cn=cn)
    except Exception as e:
        if "ORA-00001" in str(e):
            ctx.send("❌ هذا الرقم مسجل مسبقاً. أدخل رقماً آخر:")
            return
        raise
    core.audit("CUSTOMER_ADD", ctx, details="%s %s" % (ph, name))
    ctx.reset()
    ctx.send("✅ تم إضافة العميل بنجاح!\n👤 %s — 📞 %s" % (esc(name), ph),
             kb([("👤 إضافة عميل آخر", "cust:add")], [BACK_HOME]))


# ═══════════════════════════ الاستيراد (التوريد) ═══════════════════════════
PROD_EXTRA["imp"] = [[("🆕 إضافته كمنتج جديد", "imp:asnew")]]


@on_cb("imp")
def cb_imp(ctx):
    a = ctx.args
    act = a[0] if a else "start"
    if act == "start":
        ctx.reset()
        ctx.reply("📦 <b>إضافة منتجات (استيراد)</b>\nهل المنتج موجود سابقاً؟",
                  kb([("🆕 لا، منتج جديد", "imp:new"), ("📦 نعم، موجود", "imp:old")], [BACK_HOME]))
    elif act in ("new", "asnew"):
        ctx.go("imp:newname", i_mode="new", i_pid=None)
        ctx.reply("أدخل اسم المنتج الجديد:", kb([CANCEL_BTN]))
    elif act == "old":
        start_prod_search(ctx, "imp", prompt="ادخل اسم المنتج (أو جزء منه) للبحث:")
    elif act == "p0" and ctx.state == "imp:profit":
        _after_profit(ctx, 0.0)
    elif act == "pay" and ctx.state == "imp:paid" and len(a) > 1:
        _after_paid(ctx, float(ctx.data.get("i_full") or 0) if a[1] == "full" else 0.0)
    elif act == "ok":
        save_import(ctx)


@prod_purpose("imp")
def imp_picked(ctx, p):
    ctx.go("imp:merchant", i_mode="old", i_pid=p["product_id"], i_name=p["product_name"])
    ctx.reply("📦 المنتج المختار: <b>%s</b>\nالسعر الحالي: %s | المتوفر: %s\n\nأدخل اسم التاجر/المورد:"
              % (esc(p["product_name"]), fmt_num(p["price"]), fmt_num(p["quantity"])), kb([CANCEL_BTN]))


@on_state("imp:newname")
def st_imp_newname(ctx):
    name = clean_text(ctx.text, 100, True)
    if not name:
        ctx.send("أدخل اسم المنتج (حتى 50 حرفاً):")
        return
    ex = db.one("SELECT product_id, product_name FROM products_table WHERE LOWER(product_name) = :p_n",
                p_n=name.lower())
    if ex:
        ctx.go("imp:merchant", i_mode="old", i_pid=ex["product_id"], i_name=ex["product_name"])
        ctx.send("ℹ️ المنتج [<b>%s</b>] موجود مسبقاً، سيتم تحديثه (إضافة الكمية وتحديث الأسعار).\n\n"
                 "أدخل اسم التاجر/المورد:" % esc(ex["product_name"]), kb([CANCEL_BTN]))
        return
    ctx.go("imp:merchant", i_mode="new", i_pid=None, i_name=name)
    ctx.send("أدخل اسم التاجر/المورد:", kb([CANCEL_BTN]))


@on_state("imp:merchant")
def st_imp_merchant(ctx):
    m = clean_text(ctx.text, 100, True)
    if not m:
        ctx.send("أدخل اسم التاجر/المورد (حتى 50 حرفاً):")
        return
    ctx.go("imp:cartons", i_merchant=m)
    ctx.send("أدخل عدد الكراتين:")


@on_state("imp:cartons")
def st_imp_cartons(ctx):
    v = parse_int(ctx.text, 1, 1_000_000)
    if v is None:
        ctx.send("أدخل عدداً صحيحاً أكبر من صفر:")
        return
    ctx.go("imp:inside", i_cartons=v)
    ctx.send("أدخل العدد داخل الكرتون الواحد:")


@on_state("imp:inside")
def st_imp_inside(ctx):
    v = parse_int(ctx.text, 1, 100_000)
    if v is None:
        ctx.send("أدخل عدداً صحيحاً أكبر من صفر:")
        return
    ctx.go("imp:price", i_inside=v)
    ctx.send("أدخل سعر الكرتون الواحد:")


@on_state("imp:price")
def st_imp_price(ctx):
    p = parse_float(ctx.text, 0.0)
    if p is None:
        ctx.send("أدخل سعراً صحيحاً (رقم):")
        return
    d = ctx.data
    full = round(d["i_cartons"] * p, 2)
    if full > MAX_AMOUNT:
        ctx.send("إجمالي الفاتورة كبير جداً. تحقق من الأرقام وأعد إدخال سعر الكرتون:")
        return
    cost = round(p / d["i_inside"], 2)
    ctx.go("imp:profit", i_price=p, i_full=full, i_cost=cost)
    u = _unit(ctx)
    ctx.send("[النظام]: إجمالي مبلغ الفاتورة = <b>%s</b> %s\n"
             "[النظام]: تكلفة الحبة الواحدة عليك (سعر الشراء) = <b>%s</b>\n\n"
             "أدخل مبلغ الربح للحبة الواحدة (أو 0 لبيعها برأس المال):" % (fmt_num(full), u, fmt_num(cost)),
             kb([("0️⃣ بيعها برأس المال", "imp:p0")], [CANCEL_BTN]))


def _after_profit(ctx, profit):
    d = ctx.data
    single = round(d["i_cost"] + profit, 2)
    if single > MAX_AMOUNT:
        ctx.send("سعر البيع كبير جداً. أدخل ربحاً أقل:")
        return
    ctx.go("imp:paid", i_profit=profit, i_single=single)
    ctx.reply("[النظام]: السعر النهائي لبيع الحبة الواحدة سيكون = <b>%s</b>\n\nأدخل المبلغ المدفوع للتاجر:"
              % fmt_num(single),
              kb([("💵 دفعت كامل المبلغ", "imp:pay:full"), ("⏳ لم أدفع شيئاً", "imp:pay:none")], [CANCEL_BTN]))


@on_state("imp:profit")
def st_imp_profit(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None:
        ctx.send("أدخل مبلغ الربح (0 أو أكثر):")
        return
    _after_profit(ctx, v)


def _after_paid(ctx, paid):
    d = ctx.data
    full = float(d["i_full"])
    if paid > full + 0.001:
        ctx.send("المبلغ المدفوع أكبر من إجمالي الفاتورة (%s). أعد الإدخال:" % fmt_num(full))
        return
    paid = round(paid, 2)
    resid = round(full - paid, 2)
    ctx.go("imp:confirm", i_paid=paid)
    u = _unit(ctx)
    total_qty = d["i_cartons"] * d["i_inside"]
    text = ("🧾 <b>ملخص فاتورة التوريد</b>\n"
            "التاجر: %s\n"
            "المنتج: %s (%s)\n"
            "الكراتين: %s × %s حبة = %s حبة\n"
            "سعر الكرتون: %s\n"
            "إجمالي الفاتورة: <b>%s</b> %s\n"
            "المدفوع: %s | المتبقي (دين آجل): <b>%s</b>\n"
            "تكلفة الحبة: %s | الربح: %s | سعر البيع: <b>%s</b>"
            % (esc(d["i_merchant"]), esc(d["i_name"]), "جديد" if d["i_mode"] == "new" else "موجود",
               fmt_num(d["i_cartons"]), fmt_num(d["i_inside"]), fmt_num(total_qty),
               fmt_num(d["i_price"]), fmt_num(full), u, fmt_num(paid), fmt_num(resid),
               fmt_num(d["i_cost"]), fmt_num(d["i_profit"]), fmt_num(d["i_single"])))
    ctx.reply(text, kb([("✅ حفظ الفاتورة", "imp:ok")], [CANCEL_BTN]))


@on_state("imp:paid")
def st_imp_paid(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None:
        ctx.send("أدخل المبلغ المدفوع (0 أو أكثر):")
        return
    _after_paid(ctx, v)


def save_import(ctx):
    d = ctx.data
    need = ["i_mode", "i_name", "i_merchant", "i_cartons", "i_inside", "i_price", "i_full",
            "i_cost", "i_profit", "i_single", "i_paid"]
    if d.get("i_mode") == "old":
        need.append("i_pid")
    if ctx.state != "imp:confirm" or any(d.get(k) is None for k in need):
        ctx.reply("انتهت صلاحية هذه الفاتورة. ابدأ من جديد.",
                  kb([("📦 توريد جديد", "imp:start")], [BACK_HOME]))
        return
    cn = ctx.client["num"]
    total_qty = d["i_cartons"] * d["i_inside"]
    resid = round(d["i_full"] - d["i_paid"], 2)
    try:
        with db.tx() as t:
            t.run("INSERT INTO imports_table (client_num, merchant_name, product_name, number_of_cartons, "
                  "inside_carton, price_carton, full_amount, paid_amount, residual_amount, "
                  "single_item_price, item_cost, profit_amount) "
                  "VALUES (:p_cn, :p_m, :p_pn, :p_nc, :p_ic, :p_pc, :p_fa, :p_pa, :p_ra, :p_sp, :p_co, :p_pr)",
                  p_cn=cn, p_m=d["i_merchant"], p_pn=d["i_name"], p_nc=d["i_cartons"], p_ic=d["i_inside"],
                  p_pc=d["i_price"], p_fa=d["i_full"], p_pa=d["i_paid"], p_ra=resid,
                  p_sp=d["i_single"], p_co=d["i_cost"], p_pr=d["i_profit"])
            if d["i_mode"] == "new":
                # نرسل selling_price أيضاً لأن trigger الجدول يضبط price = selling_price
                t.run("INSERT INTO products_table (product_name, price, selling_price, purchase_price, "
                      "quantity, units_per_carton) VALUES (:p_n, :p_sp, :p_sp, :p_pp, :p_q, :p_u)",
                      p_n=d["i_name"], p_sp=d["i_single"], p_pp=d["i_cost"], p_q=total_qty, p_u=d["i_inside"])
            else:
                n = t.run("UPDATE products_table SET price = :p_sp, selling_price = :p_sp, "
                          "purchase_price = :p_pp, quantity = NVL(quantity, 0) + :p_q, "
                          "units_per_carton = :p_u WHERE product_id = :p_id",
                          p_sp=d["i_single"], p_pp=d["i_cost"], p_q=total_qty, p_u=d["i_inside"],
                          p_id=d["i_pid"])
                if n == 0:
                    raise ValueError("المنتج لم يعد موجوداً")
            core.audit("IMPORT", ctx, details="%s x%s paid=%s" % (d["i_name"], total_qty, d["i_paid"]), t=t)
    except ValueError as e:
        ctx.reset()
        ctx.reply("⚠️ %s" % esc(e), kb([("📦 توريد جديد", "imp:start")], [BACK_HOME]))
        return
    except Exception as e:
        if "ORA-00001" in str(e):
            ctx.reset()
            ctx.reply("❌ يوجد منتج بنفس الاسم مسبقاً. ابدأ من جديد واختر «منتج موجود».",
                      kb([("📦 توريد جديد", "imp:start")], [BACK_HOME]))
            return
        raise
    u = _unit(ctx)
    name, single, mode = d["i_name"], d["i_single"], d["i_mode"]
    ctx.reset()
    ctx.reply("✅ تم حفظ فاتورة التوريد وتفاصيل الأرباح بنجاح!\n" +
              ("📦 تم إدراج [<b>%s</b>] بسعر (%s) للحبة في قائمة منتجات المحل." % (esc(name), fmt_num(single))
               if mode == "new" else
               "🔄 تم تحديث سعر [<b>%s</b>] إلى (%s) %s للحبة وإضافة %s حبة للمخزون."
               % (esc(name), fmt_num(single), u, fmt_num(total_qty))),
              kb([("📦 توريد جديد", "imp:start")], [BACK_HOME]))


# ═══════════════════════════ المبيعات (دين / كاش / شبكة) ═══════════════════════════
KIND_LABEL = {"d": "آجلة (دين)", "c": "كاش", "n": "شبكة"}
GENERAL = {"c": "عميل كاش عام", "n": "عميل شبكة عام"}
TABLE = {"c": "cash_sales", "n": "network_sales"}


@on_cb("sale")
def cb_sale(ctx):
    a = ctx.args
    act = a[0] if a else "menu"
    st = ctx.state
    if act == "menu":
        ctx.reset()
        ctx.reply("--- 🛒 قسم المبيعات ---\nاختر نوع العملية:",
                  kb([("📝 دين", "sale:type:d")], [("💰 كاش", "sale:type:c"), ("💳 شبكة", "sale:type:n")],
                     [BACK_HOME]))
    elif act == "type" and len(a) > 1 and a[1] in KIND_LABEL:
        kind = a[1]
        ctx.reset()
        if kind == "d":
            ctx.put(s_type="d")
            start_cust_search(ctx, "sale", back="sale:menu")
        else:
            ctx.go("sale:cname", s_type=kind)
            ctx.reply("أدخل اسم الزبون (أو اضغط تخطي لتسجيله كـ «%s»):" % GENERAL[kind],
                      kb([("⏭ تخطي", "sale:skip:name")], [("❌ إلغاء", "sale:menu")]))
    elif act == "skip" and len(a) > 1:
        kind = ctx.data.get("s_type")
        if a[1] == "name" and st == "sale:cname" and kind in GENERAL:
            ctx.go("sale:cphone", s_cname=GENERAL[kind])
            ctx.reply("أدخل رقم هاتف الزبون (أو اضغط تخطي):", kb([("⏭ تخطي", "sale:skip:phone")],
                                                              [("❌ إلغاء", "sale:menu")]))
        elif a[1] == "phone" and st == "sale:cphone":
            ctx.put(s_cphone=0)
            start_prod_search(ctx, "sale", back="sale:menu")
    elif act == "neg" and len(a) > 1 and st == "sale:negq":
        if a[1] == "y":
            _confirm_sale(ctx, ctx.data["s_qty"])
        else:
            ctx.reset()
            ctx.reply("تم إلغاء عملية البيع.", kb([("🛒 المبيعات", "sale:menu"), BACK_HOME]))
    elif act == "ok":
        _save_sale(ctx)


@on_state("sale:cname")
def st_sale_cname(ctx):
    name = clean_text(ctx.text, 100, True)
    if not name:
        ctx.send("أدخل اسم الزبون (حتى 50 حرفاً) أو اضغط تخطي:", kb([("⏭ تخطي", "sale:skip:name")]))
        return
    ctx.go("sale:cphone", s_cname=name)
    ctx.send("أدخل رقم هاتف الزبون (أو اضغط تخطي):",
             kb([("⏭ تخطي", "sale:skip:phone")], [("❌ إلغاء", "sale:menu")]))


@on_state("sale:cphone")
def st_sale_cphone(ctx):
    ph = parse_int(ctx.text, 0, 999_999_999_999_999)
    if ph is None:
        ctx.send("أدخل رقماً صحيحاً (أرقام فقط) أو اضغط تخطي:", kb([("⏭ تخطي", "sale:skip:phone")]))
        return
    ctx.put(s_cphone=ph)
    start_prod_search(ctx, "sale", back="sale:menu")


@cust_purpose("sale")
def sale_cust_picked(ctx, c):
    ctx.put(s_cname=c["name"], s_cphone=c["phone"])
    start_prod_search(ctx, "sale", back="sale:menu",
                      prompt="👤 تم اختيار العميل: <b>%s</b>\n\nأدخل اسم المنتج للبحث:" % esc(c["name"]))


@prod_purpose("sale")
def sale_prod_picked(ctx, p):
    ctx.go("sale:qty", s_pid=p["product_id"], s_pname=p["product_name"], s_price=float(p["price"]),
           s_stock=int(p["quantity"]), s_cost=float(p["purchase_price"]))
    ctx.reply("📦 المنتج: <b>%s</b>\nالسعر: %s %s | المتوفر في المخزن: %s\n\nأدخل الكمية المطلوبة:"
              % (esc(p["product_name"]), fmt_num(p["price"]), _unit(ctx), core.stock_text(p["quantity"], p["units_per_carton"])),
              kb([("❌ إلغاء", "sale:menu")]))


@on_state("sale:qty")
def st_sale_qty(ctx):
    q = parse_int(ctx.text, 1, 1_000_000)
    if q is None:
        ctx.send("أدخل كمية صحيحة (عدد صحيح أكبر من صفر):")
        return
    stock = ctx.data.get("s_stock", 0)
    if q > stock:
        ctx.go("sale:negq", s_qty=q)
        ctx.send("⚠️ تنبيه: الكمية المطلوبة غير متوفرة! (المتبقي: %s فقط)\n"
                 "هل تريد مواصلة البيع وتقييد المخزون بالسالب؟" % fmt_num(stock),
                 kb([("✅ نعم، واصل", "sale:neg:y"), ("❌ لا، إلغاء", "sale:neg:n")]))
        return
    _confirm_sale(ctx, q)


def _confirm_sale(ctx, qty):
    d = ctx.data
    total = round(qty * d["s_price"], 2)
    if total > MAX_AMOUNT:
        ctx.go("sale:qty")
        ctx.reply("الإجمالي كبير جداً. أدخل كمية أقل:")
        return
    ctx.go("sale:confirm", s_qty=qty, s_total=total)
    u = _unit(ctx)
    kind = d["s_type"]
    ctx.reply("🧾 <b>ملخص العملية (%s)</b>\nالزبون: %s\nالمنتج: %s\nالكمية: %s\nسعر الحبة: %s %s\n"
              "الإجمالي: <b>%s</b> %s\n\n%s"
              % (KIND_LABEL[kind], esc(d.get("s_cname")), esc(d["s_pname"]), fmt_num(qty),
                 fmt_num(d["s_price"]), u, fmt_num(total), u,
                 "تأكيد الدين؟" if kind == "d" else "تأكيد الفاتورة؟"),
              kb([("✅ تأكيد", "sale:ok")], [("❌ إلغاء", "sale:menu")]))


def _new_invoice(t):
    """رقم فاتورة من 8 خانات كما في Java مع التأكد من عدم تكراره."""
    for _ in range(8):
        n = int(time.time() * 1000) % 100000000 or 1
        used = t.val("SELECT COUNT(*) FROM (SELECT invoice_num FROM cash_sales WHERE invoice_num = :p_n "
                     "UNION ALL SELECT invoice_num FROM network_sales WHERE invoice_num = :p_n "
                     "UNION ALL SELECT invoice_num FROM shop_debts WHERE invoice_num = :p_n)", 0, p_n=n)
        if not used:
            return n
        time.sleep(0.003)
    raise RuntimeError("تعذر توليد رقم فاتورة فريد، حاول مرة أخرى")


def _save_sale(ctx):
    d = ctx.data
    if ctx.state != "sale:confirm" or d.get("s_pid") is None or d.get("s_qty") is None:
        ctx.reply("انتهت صلاحية هذه العملية. ابدأ من جديد.", kb([("🛒 المبيعات", "sale:menu"), BACK_HOME]))
        return
    kind, cn = d["s_type"], ctx.client["num"]
    qty, price, total = d["s_qty"], d["s_price"], d["s_total"]
    cname = core.fit_bytes(d.get("s_cname") or GENERAL.get(kind, ""), 100)
    pname = core.fit_bytes(d["s_pname"], 100)       # أعمدة المبيعات 100 بايت بينما المنتجات 150 حرفاً
    cphone = int(d.get("s_cphone") or 0)
    profit = round((price - d.get("s_cost", 0)) * qty, 2)
    try:
        with db.tx() as t:
            inv = _new_invoice(t)
            if kind == "d":
                t.run("INSERT INTO shop_debts (client_num, customer_phone, customer_name, product_name, "
                      "quantity, single_price, debt_amount, invoice_num, debt_date) "
                      "VALUES (:p_cn, :p_ph, :p_cu, :p_pn, :p_q, :p_pr, :p_tot, :p_inv, SYSTIMESTAMP)",
                      p_cn=cn, p_ph=cphone, p_cu=cname, p_pn=pname, p_q=qty, p_pr=price,
                      p_tot=total, p_inv=inv)
            else:
                cols = ("client_num, customer_name, customer_phone, product_name, quantity, single_price, "
                        "total_amount, invoice_num, sale_date, profit_amount")
                vals = ":p_cn, :p_cu, :p_ph, :p_pn, :p_q, :p_pr, :p_tot, :p_inv, SYSTIMESTAMP, :p_pf"
                if kind == "n" and db.FLAGS.get("network_manual_id"):
                    cols, vals = "sale_id, " + cols, "network_sales_seq.NEXTVAL, " + vals
                t.run("INSERT INTO %s (%s) VALUES (%s)" % (TABLE[kind], cols, vals),
                      p_cn=cn, p_cu=cname, p_ph=cphone, p_pn=pname, p_q=qty, p_pr=price,
                      p_tot=total, p_inv=inv, p_pf=profit)
            n = t.run("UPDATE products_table SET quantity = NVL(quantity, 0) - :p_q WHERE product_id = :p_id",
                      p_q=qty, p_id=d["s_pid"])
            if n == 0:
                raise ValueError("المنتج لم يعد موجوداً في القائمة")
            core.audit("SALE_" + kind.upper(), ctx,
                       details="inv=%s %s x%s total=%s" % (inv, d["s_pname"], qty, total), t=t)
    except ValueError as e:
        ctx.reset()
        ctx.reply("⚠️ %s" % esc(e), kb([("🛒 المبيعات", "sale:menu"), BACK_HOME]))
        return
    ctx.reset()
    head = ("✅ تم تسجيل الدين! رقم الفاتورة: <b>%s</b>" if kind == "d"
            else "✅ تم الحفظ! رقم الفاتورة: <b>%s</b>") % inv
    body = "\n".join(esc(x) for x in invoice_lines(kind, cname, pname, qty, price, total, inv,
                                                  ctx.client, None))
    ctx.reply(head + "\n\n" + body,
              kb([("🖨️ ملف الفاتورة", "inv:%s:%s" % (kind, inv))],
                 [("🛒 عملية بيع جديدة", "sale:menu"), BACK_HOME]))


# ═══════════════════════════ الفواتير ═══════════════════════════
def invoice_lines(kind, customer, product, qty, price, total, inv, client, dt):
    u = unit_of(client)
    shop = (client or {}).get("shop_name")
    L = ["====================================", "          فاتورة مبيعات             ",
         "===================================="]
    if shop:
        L.append("المحل: %s" % shop)
    L += ["رقم الفاتورة: %s" % inv, "نوع الفاتورة: %s" % KIND_LABEL[kind], "اسم العميل: %s" % customer]
    if dt:
        L.append("التاريخ: %s" % fmt_dt(dt))
    L += ["------------------------------------", "المنتج: %s" % product, "الكمية: %s" % fmt_num(qty),
          "سعر الحبة: %s %s" % (fmt_num(price), u), "------------------------------------",
          "الإجمالي المطلوب: %s %s" % (fmt_num(total), u),
          "====================================", "        شكراً لتسوقكم معنا!         "]
    return L


INV_SQL = {
    "d": "SELECT customer_name, product_name, quantity, single_price, debt_amount AS total, debt_date AS dt "
         "FROM shop_debts WHERE invoice_num = :p_n AND client_num = :p_cn",
    "c": "SELECT customer_name, product_name, quantity, single_price, total_amount AS total, sale_date AS dt "
         "FROM cash_sales WHERE invoice_num = :p_n AND client_num = :p_cn",
    "n": "SELECT customer_name, product_name, quantity, single_price, total_amount AS total, sale_date AS dt "
         "FROM network_sales WHERE invoice_num = :p_n AND client_num = :p_cn",
}


@on_cb("inv")
def cb_inv(ctx):
    a = ctx.args
    if len(a) < 2 or a[0] not in INV_SQL or not a[1].isdigit():
        return
    kind, num = a[0], int(a[1])
    r = db.one(INV_SQL[kind], p_n=num, p_cn=ctx.client["num"])
    if not r:
        ctx.send("⚠️ لم يتم العثور على الفاتورة.")
        return
    text = "\n".join(invoice_lines(kind, r["customer_name"], r["product_name"], r["quantity"],
                                   r["single_price"], r["total"], num, ctx.client, r["dt"]))
    ctx.doc("Invoice_%s.txt" % num, text, caption="🖨️ فاتورة رقم %s" % num)


# ═══════════════════════════ تسديد الديون ═══════════════════════════
def archive_and_delete_debts(t, cn, phone, reason):
    """ينقل سجلات ديون العميل للأرشيف ثم يحذفها من shop_debts (نفس سلوك Java مع حفظ نسخة)."""
    t.run("INSERT INTO bot_debts_archive (debt_id, client_num, customer_phone, customer_name, product_name, "
          "quantity, single_price, debt_amount, paid_amount, debt_date, invoice_num, reason) "
          "SELECT debt_id, client_num, customer_phone, customer_name, product_name, quantity, single_price, "
          "debt_amount, paid_amount, debt_date, invoice_num, :p_r FROM shop_debts "
          "WHERE customer_phone = :p_ph AND client_num = :p_cn", p_r=reason, p_ph=phone, p_cn=cn)
    return t.run("DELETE FROM shop_debts WHERE customer_phone = :p_ph AND client_num = :p_cn",
                 p_ph=phone, p_cn=cn)


@on_cb("pay")
def cb_pay(ctx):
    a = ctx.args
    act = a[0] if a else "menu"
    if act == "menu":
        ctx.reset()
        ctx.reply("===== 💸 قسم تسديد الديون =====",
                  kb([("💸 تسديد ديون", "pay:go")], [("📝 كشف الديون (حالة الرصيد)", "pay:bal")], [BACK_HOME]))
    elif act == "go":
        start_cust_search(ctx, "pay", back="pay:menu")
    elif act == "bal":
        start_cust_search(ctx, "bal", back="pay:menu")
    elif len(a) > 1 and a[1].isdigit():
        phone = int(a[1])
        cn = ctx.client["num"]
        cust = get_customer(cn, phone)
        if not cust:
            ctx.reply("⚠️ العميل غير موجود.", kb([("↩️ رجوع", "pay:menu")]))
            return
        if act == "det":
            _debt_details(ctx, cust)
        elif act == "do":
            ctx.go("pay:amt", pay_phone=phone)
            ctx.reply("أدخل المبلغ الذي سيسدده العميل الآن:", kb([("❌ إلغاء", "pay:menu")]))
        elif act == "full":
            _settle_full(ctx, cust)


@cust_purpose("pay")
def pay_cust_picked(ctx, c):
    cn = ctx.client["num"]
    td, tp, rem = debt_totals(c["phone"], cn)
    u = _unit(ctx)
    if rem <= 0:
        ctx.reset()
        ctx.reply("✅ العميل [<b>%s</b>] ليس عليه أي ديون مسجلة (حسابه مصفر)." % esc(c["name"]),
                  kb([("↩️ رجوع", "pay:menu"), BACK_HOME]))
        return
    ctx.reset()
    ctx.reply("👤 اسم العميل: <b>%s</b>\n📞 رقم العميل: %s\n💰 إجمالي الدين المتبقي عليه: <b>%s</b> %s"
              % (esc(c["name"]), c["phone"], fmt_num(rem), u),
              kb([("📋 كشف تفاصيل الدين", "pay:det:%s" % c["phone"])],
                 [("💸 تسديد الدين", "pay:do:%s" % c["phone"])], [("↩️ رجوع", "pay:menu")]))


def _debt_details(ctx, cust):
    cn = ctx.client["num"]
    rows = db.rows("SELECT * FROM (SELECT product_name, quantity, debt_amount, NVL(paid_amount, 0) AS paid, "
                   "debt_date, invoice_num FROM shop_debts WHERE customer_phone = :p_ph AND client_num = :p_cn "
                   "ORDER BY debt_id) WHERE ROWNUM <= 40", p_ph=cust["phone"], p_cn=cn)
    u = _unit(ctx)
    lines = ["--- 📋 تفاصيل الديون: <b>%s</b> ---" % esc(cust["name"])]
    for r in rows:
        lines.append("- %s | الكمية: %s | المبلغ: %s %s | التاريخ: %s%s"
                     % (esc(r["product_name"]), fmt_num(r["quantity"]), fmt_num(r["debt_amount"]), u,
                        fmt_dt(r["debt_date"]), " | فاتورة: %s" % r["invoice_num"] if r.get("invoice_num") else ""))
    td, tp, rem = debt_totals(cust["phone"], cn)
    lines += ["", "إجمالي الدين: %s | المسدد: %s | المتبقي: <b>%s</b> %s" % (fmt_num(td), fmt_num(tp), fmt_num(rem), u)]
    ctx.reply("\n".join(lines), kb([("💸 تسديد الدين", "pay:do:%s" % cust["phone"])], [("↩️ رجوع", "pay:menu")]))


@on_state("pay:amt")
def st_pay_amt(ctx):
    amt = parse_float(ctx.text, 0.0)
    if amt is None or amt <= 0:
        ctx.send("أدخل مبلغاً صحيحاً أكبر من صفر:")
        return
    cn = ctx.client["num"]
    phone = ctx.data.get("pay_phone")
    cust = get_customer(cn, phone) if phone is not None else None
    if not cust:
        ctx.reset()
        ctx.send("⚠️ العميل غير موجود.", kb([("↩️ رجوع", "pay:menu")]))
        return
    td, tp, rem = debt_totals(phone, cn)
    u = _unit(ctx)
    if rem <= 0:
        ctx.reset()
        ctx.send("✅ العميل [<b>%s</b>] ليس عليه أي ديون مسجلة." % esc(cust["name"]), kb([BACK_HOME]))
        return
    amt = round(amt, 2)
    if amt >= rem - 0.001:
        extra = "\nالمبلغ المستلم أكبر من المتبقي بـ %s %s (الزيادة تُرجع للعميل)." % (fmt_num(amt - rem), u) if amt > rem + 0.001 else ""
        ctx.go("pay:fullq", pay_phone=phone)
        ctx.send("سيتم تسديد كامل الدين (<b>%s</b> %s) وتصفير حساب العميل.%s\n"
                 "<i>(تُنقل سجلات الديون إلى الأرشيف ثم تُحذف من القائمة)</i>\nتأكيد؟"
                 % (fmt_num(rem), u, extra),
                 kb([("✅ تأكيد التسديد الكامل", "pay:full:%s" % phone)], [("❌ إلغاء", "pay:menu")]))
        return
    with db.tx() as t:
        t.run("UPDATE shop_debts SET paid_amount = NVL(paid_amount, 0) + :p_a WHERE debt_id = "
              "(SELECT MAX(debt_id) FROM shop_debts WHERE customer_phone = :p_ph AND client_num = :p_cn)",
              p_a=amt, p_ph=phone, p_cn=cn)
        core.audit("DEBT_PAY", ctx, details="phone=%s amount=%s" % (phone, amt), t=t)
    ctx.reset()
    ctx.send("✅ تم تسجيل الدفعة بنجاح! المتبقي عليه الآن: <b>%s</b> %s" % (fmt_num(rem - amt), u),
             kb([("💸 تسديد آخر", "pay:go")], [BACK_HOME]))


def _settle_full(ctx, cust):
    cn = ctx.client["num"]
    td, tp, rem = debt_totals(cust["phone"], cn)
    if rem <= 0:
        ctx.reply("✅ العميل [<b>%s</b>] ليس عليه أي ديون مسجلة." % esc(cust["name"]), kb([BACK_HOME]))
        return
    with db.tx() as t:
        n = archive_and_delete_debts(t, cn, cust["phone"], "PAID_FULL")
        core.audit("DEBT_FULL", ctx, details="phone=%s paid=%s rows=%s" % (cust["phone"], rem, n), t=t)
    ctx.reset()
    ctx.reply("✅ تم تسديد الدين بالكامل وتصفير جميع سجلات العميل بنجاح!",
              kb([("💸 تسديد آخر", "pay:go")], [BACK_HOME]))


@cust_purpose("bal")
def bal_cust_picked(ctx, c):
    cn = ctx.client["num"]
    td, tp, rem = debt_totals(c["phone"], cn)
    u = _unit(ctx)
    ctx.reset()
    lines = ["--- 📝 كشف رصيد الديون للعميل [<b>%s</b>] ---" % esc(c["name"])]
    if td == 0:
        lines.append("✅ العميل سدد بالكامل، وسجلاته مصفرة (لا يوجد عليه دين حالياً).")
    else:
        lines += ["مجموع الدين كان: %s %s" % (fmt_num(td), u), "سدد منه: %s %s" % (fmt_num(tp), u),
                  "المتبقي عليه: <b>%s</b> %s" % (fmt_num(rem), u)]
    ctx.reply("\n".join(lines), kb([("📝 كشف آخر", "pay:bal")], [("↩️ رجوع", "pay:menu"), BACK_HOME]))
'''

# ════════════════════ reports.py ════════════════════
SOURCES['reports'] = r'''"""التقارير الشاملة والتعديلات (حذف) — يطابق Statement.java بأقسامه الثمانية.

القوائم الطويلة تُعرض بصفحات (◀️ السابق / التالي ▶️) لأن رسالة تلجرام محدودة الحجم.
"""
from __future__ import annotations

import logging

import core
import db
from core import (BACK_HOME, LIKE_ESC, clean_text, esc, fmt_dt, fmt_num, kb, like, on_cb, on_state,
                  parse_int, stock_text, unit_of)
from pickers import (cust_purpose, debt_totals, find_products, get_customer, prod_purpose,
                     start_cust_search, start_prod_search)
from shop import KIND_LABEL, archive_and_delete_debts

log = logging.getLogger("reports")

SALES_TABLE = {"c": ("cash_sales", "sale_date", "total_amount"),
               "n": ("network_sales", "sale_date", "total_amount"),
               "d": ("shop_debts", "debt_date", "debt_amount")}
SEP = "─────────────"


def _u(ctx):
    return unit_of(ctx.client)


def _cond(col, period):
    """شرط الفترة (اليوم / الشهر الحالي). period قيمة ثابتة من الكود فقط."""
    if period == "day":
        return "TRUNC(%s) = TRUNC(SYSDATE)" % col
    return "TRUNC(%s, 'MM') = TRUNC(SYSDATE, 'MM')" % col


def page_sql(sql, page, size):
    lo = page * size
    return ("SELECT * FROM (SELECT q.*, ROWNUM AS rn__ FROM (%s) q WHERE ROWNUM <= %d) WHERE rn__ > %d"
            % (sql, lo + size + 1, lo))


def _page_arg(r, idx):
    return int(r[idx]) if len(r) > idx and r[idx].isdigit() else 0


def show_page(ctx, title, lines, page, has_next, base, back, header=None):
    text = title
    if header:
        text += "\n" + header
    text += "\n\n" + ("\n".join(lines) if lines else "⚠️ لا توجد بيانات.")
    if page or has_next:
        text += "\n\n<i>صفحة %d</i>" % (page + 1)
    nav = []
    if page > 0:
        nav.append(("◀️ السابق", "%s:%d" % (base, page - 1)))
    if has_next:
        nav.append(("التالي ▶️", "%s:%d" % (base, page + 1)))
    rows = ([nav] if nav else []) + [[("↩️ رجوع", back), BACK_HOME]]
    ctx.reply(text, kb(*rows))


def _back(ctx, text, back, extra_rows=None):
    rows = (extra_rows or []) + [[("↩️ رجوع", back), BACK_HOME]]
    ctx.reply(text, kb(*rows))


# ═══════════════════════════ القائمة ═══════════════════════════
@on_cb("rp")
def cb_rp(ctx):
    a = ctx.args
    sec = a[0] if a else "menu"
    fn = SECTIONS.get(sec)
    if sec == "menu" or fn is None:
        ctx.reset()
        ctx.reply("===== 📊 شاشة التقارير الشاملة والتعديلات =====\nاختر رقم التقرير:",
                  kb([("1. المنتجات", "rp:1"), ("2. العملاء", "rp:2")],
                     [("3. كشف المبيعات والاستيراد", "rp:3")],
                     [("4. الأرباح", "rp:4"), ("5. الديون", "rp:5")],
                     [("6. التعديلات (حذف)", "rp:6")],
                     [("7. بحث عن عمليات بيع", "rp:7")],
                     [("8. تقرير حركة المنتجات", "rp:8")],
                     [BACK_HOME]))
        return
    fn(ctx, a[1:])


# ═══════════════════════════ 1) المنتجات ═══════════════════════════
def sec_products(ctx, r):
    cn = ctx.client["num"]
    sub = r[0] if r else None
    u = _u(ctx)
    if sub is None:
        ctx.reset()
        total = db.val("SELECT COUNT(*) FROM products_table", 0)
        ctx.reply("--- 📦 تقارير المنتجات ---\n📦 إجمالي عدد المنتجات المسجلة: <b>%s</b> منتج" % total,
                  kb([("🚚 حساب عدد الكراتين المستوردة", "rp:1:cartons")],
                     [("🔎 بحث عن منتج معين", "rp:1:search")],
                     [("📋 كشف بجميع المنتجات (مع التفاصيل)", "rp:1:all:0")],
                     [("↩️ رجوع", "rp:menu"), BACK_HOME]))
    elif sub == "cartons":
        v = db.val("SELECT NVL(SUM(number_of_cartons), 0) FROM imports_table WHERE client_num = :p_cn", 0, p_cn=cn)
        _back(ctx, "📦 إجمالي الكراتين التي قمت باستيرادها: <b>%s</b> كرتون" % fmt_num(v), "rp:1")
    elif sub == "search":
        ctx.go("rp:psearch")
        ctx.reply("أدخل اسم المنتج للبحث:", kb([("↩️ رجوع", "rp:1")]))
    elif sub == "all":
        page = _page_arg(r, 1)
        rows = db.rows(page_sql("SELECT product_name, NVL(purchase_price, 0) AS pp, NVL(price, 0) AS sp, "
                                "NVL(quantity, 0) AS qty, NVL(units_per_carton, 1) AS upc "
                                "FROM products_table ORDER BY product_name", page, 8))
        has_next = len(rows) > 8
        lines = []
        for x in rows[:8]:
            lines.append("📦 <b>%s</b>\nالشراء: %s | البيع: %s | الربح: %s\nالمتبقي: %s"
                         % (esc(x["product_name"]), fmt_num(x["pp"]), fmt_num(x["sp"]),
                            fmt_num(float(x["sp"]) - float(x["pp"])), stock_text(x["qty"], x["upc"])))
        show_page(ctx, "--- 📋 كشف جميع المنتجات (التفصيلي) ---", lines, page, has_next, "rp:1:all", "rp:1")


@on_state("rp:psearch")
def st_psearch(ctx):
    q = (ctx.text or "").strip()
    if not q:
        ctx.send("أدخل اسم المنتج للبحث:")
        return
    rows = find_products(q)
    ctx.reset()
    if not rows:
        ctx.send("⚠️ المنتج غير موجود.", kb([("🔁 بحث آخر", "rp:1:search"), ("↩️ رجوع", "rp:1")]))
        return
    u = _u(ctx)
    lines = ["📦 <b>%s</b> | السعر: %s %s | المتبقي: %s"
             % (esc(x["product_name"]), fmt_num(x["price"]), u, stock_text(x["quantity"], x["units_per_carton"]))
             for x in rows[:10]]
    if len(rows) > 10:
        lines.append("… (يوجد نتائج أكثر، حدّد الاسم بدقة)")
    ctx.send("\n".join(lines), kb([("🔁 بحث آخر", "rp:1:search"), ("↩️ رجوع", "rp:1")]))


# ═══════════════════════════ 2) العملاء ═══════════════════════════
def sec_customers(ctx, r):
    cn = ctx.client["num"]
    sub = r[0] if r else None
    u = _u(ctx)
    if sub is None:
        ctx.reset()
        total = db.val("SELECT COUNT(*) FROM shop_customers WHERE client_num = :p_cn", 0, p_cn=cn)
        ctx.reply("--- 👥 تقارير العملاء ---\n👥 إجمالي عدد عملائك: <b>%s</b> عميل" % total,
                  kb([("🔎 بحث عن عميل (كشف حساب للديون)", "rp:2:search")],
                     [("📋 كشف بجميع العملاء (مع إجمالي الديون)", "rp:2:all:0")],
                     [("↩️ رجوع", "rp:menu"), BACK_HOME]))
    elif sub == "search":
        start_cust_search(ctx, "rp_cust", back="rp:2")
    elif sub == "all":
        page = _page_arg(r, 1)
        rows = db.rows(page_sql(
            "SELECT c.customer_name AS cname, c.customer_phone AS cphone, "
            "NVL(SUM(d.debt_amount - NVL(d.paid_amount, 0)), 0) AS remain "
            "FROM shop_customers c LEFT JOIN shop_debts d ON c.customer_phone = d.customer_phone "
            "AND c.client_num = d.client_num WHERE c.client_num = :p_cn "
            "GROUP BY c.customer_name, c.customer_phone ORDER BY c.customer_name", page, 15), p_cn=cn)
        has_next = len(rows) > 15
        lines = ["- العميل: <b>%s</b> | الرقم: %s | دينه المتبقي: %s %s"
                 % (esc(x["cname"]), x["cphone"], fmt_num(x["remain"]), u) for x in rows[:15]]
        show_page(ctx, "--- 📋 قائمة جميع العملاء (مع الأرصدة) ---", lines, page, has_next, "rp:2:all", "rp:2")


@cust_purpose("rp_cust")
def rp_cust_picked(ctx, c):
    td, tp, rem = debt_totals(c["phone"], ctx.client["num"])
    u = _u(ctx)
    ctx.reset()
    _back(ctx, "👤 العميل: <b>%s</b> | الرقم: %s\nإجمالي الدين: %s | إجمالي ما سدده: %s | المتبقي عليه: <b>%s</b> %s"
          % (esc(c["name"]), c["phone"], fmt_num(td), fmt_num(tp), fmt_num(rem), u), "rp:2",
          [[("📄 ملف كشف الحساب", "stm:%s" % c["phone"])]])


# ═══════════════════════════ 3) كشف المبيعات والاستيراد ═══════════════════════════
def sec_sales(ctx, r):
    cn = ctx.client["num"]
    sub = r[0] if r else None
    u = _u(ctx)
    if sub is None:
        ctx.reset()
        ctx.reply("--- 📊 تقارير المبيعات والاستيراد ---",
                  kb([("💰 المبيعات اليومية (كاش فقط)", "rp:3:1")],
                     [("📅 المبيعات الشهرية (كاش + تسديدات الديون)", "rp:3:2")],
                     [("🚛 الاستيراد الشهري", "rp:3:3")],
                     [("💵 تسديدات الديون (المسددة فقط)", "rp:3:4")],
                     [("📊 كشف المبيعات التحليلي الشامل", "rp:3:5")],
                     [("↩️ رجوع", "rp:menu"), BACK_HOME]))
    elif sub == "1":
        cash = db.val("SELECT NVL(SUM(total_amount), 0) FROM cash_sales WHERE client_num = :p_cn AND "
                      + _cond("sale_date", "day"), 0, p_cn=cn)
        net = db.val("SELECT NVL(SUM(total_amount), 0) FROM network_sales WHERE client_num = :p_cn AND "
                     + _cond("sale_date", "day"), 0, p_cn=cn)
        _back(ctx, "💰 إجمالي المبيعات اليومية (نقداً فقط): <b>%s</b> %s\n💳 مبيعات الشبكة اليوم: %s %s"
              % (fmt_num(cash), u, fmt_num(net), u), "rp:3")
    elif sub == "2":
        cash = db.val("SELECT NVL(SUM(total_amount), 0) FROM cash_sales WHERE client_num = :p_cn AND "
                      + _cond("sale_date", "month"), 0, p_cn=cn)
        net = db.val("SELECT NVL(SUM(total_amount), 0) FROM network_sales WHERE client_num = :p_cn AND "
                     + _cond("sale_date", "month"), 0, p_cn=cn)
        paid = db.val("SELECT NVL(SUM(paid_amount), 0) FROM shop_debts WHERE client_num = :p_cn AND "
                      + _cond("debt_date", "month"), 0, p_cn=cn)
        _back(ctx, "📅 <b>مبيعات هذا الشهر</b>\n💰 كاش: %s %s\n💳 شبكة: %s %s\n💵 تسديدات الديون: %s %s\n%s\n"
              "الإجمالي (كاش + تسديدات) كما في البرنامج: <b>%s</b> %s\nالإجمالي مع مبيعات الشبكة: <b>%s</b> %s"
              % (fmt_num(cash), u, fmt_num(net), u, fmt_num(paid), u, SEP,
                 fmt_num(float(cash) + float(paid)), u, fmt_num(float(cash) + float(net) + float(paid)), u), "rp:3")
    elif sub == "3":
        v = db.val("SELECT NVL(SUM(full_amount), 0) FROM imports_table WHERE client_num = :p_cn AND "
                   + _cond("import_date", "month"), 0, p_cn=cn)
        _back(ctx, "🚛 إجمالي الاستيراد هذا الشهر: <b>%s</b> %s" % (fmt_num(v), u), "rp:3")
    elif sub == "4":
        v = db.val("SELECT NVL(SUM(paid_amount), 0) FROM shop_debts WHERE client_num = :p_cn", 0, p_cn=cn)
        _back(ctx, "💵 إجمالي تسديدات الديون المستلمة: <b>%s</b> %s" % (fmt_num(v), u), "rp:3")
    elif sub == "5":
        _analytic(ctx)


def _analytic(ctx):
    cn = ctx.client["num"]
    u = _u(ctx)
    row = db.one(
        "SELECT "
        "(SELECT NVL(SUM(total_amount),0) FROM cash_sales WHERE client_num = :p_cn AND TRUNC(sale_date) = TRUNC(SYSDATE)) AS today_cash, "
        "(SELECT NVL(SUM(total_amount),0) FROM network_sales WHERE client_num = :p_cn AND TRUNC(sale_date) = TRUNC(SYSDATE)) AS today_network, "
        "(SELECT NVL(SUM(debt_amount),0) FROM shop_debts WHERE client_num = :p_cn AND TRUNC(debt_date) = TRUNC(SYSDATE)) AS today_debt, "
        "(SELECT NVL(SUM(total_amount),0) FROM cash_sales WHERE client_num = :p_cn AND TRUNC(sale_date, 'MM') = TRUNC(SYSDATE, 'MM')) AS month_cash, "
        "(SELECT NVL(SUM(total_amount),0) FROM network_sales WHERE client_num = :p_cn AND TRUNC(sale_date, 'MM') = TRUNC(SYSDATE, 'MM')) AS month_network, "
        "(SELECT NVL(SUM(debt_amount),0) FROM shop_debts WHERE client_num = :p_cn AND TRUNC(debt_date, 'MM') = TRUNC(SYSDATE, 'MM')) AS month_new_debt, "
        "(SELECT NVL(SUM(paid_amount),0) FROM shop_debts WHERE client_num = :p_cn AND TRUNC(debt_date, 'MM') = TRUNC(SYSDATE, 'MM')) AS month_paid_debt, "
        "(SELECT NVL(SUM(debt_amount - NVL(paid_amount, 0)),0) FROM shop_debts WHERE client_num = :p_cn) AS total_remaining_debts "
        "FROM dual", p_cn=cn)
    f = lambda k: float(row[k] or 0)
    text = ("===== 📊 كشف المبيعات التحليلي =====\n\n"
            "<b>🟢 المبيعات اليومية (اليوم)</b>\n💰 كاش: %s %s\n💳 شبكة: %s %s\n📝 ديون مسجلة اليوم: %s %s\n"
            "إجمالي مبيعات اليوم: <b>%s</b> %s\n\n"
            "<b>🔵 المبيعات الشهرية (هذا الشهر)</b>\n💰 كاش: %s %s\n💳 شبكة: %s %s\n📝 ديون جديدة هذا الشهر: %s %s\n\n"
            "<b>🔴 حركة الديون</b>\n✅ الديون المُسددة (المستلمة) هذا الشهر: %s %s\n"
            "⚠️ إجمالي الديون المتبقية في السوق: <b>%s</b> %s"
            % (fmt_num(f("today_cash")), u, fmt_num(f("today_network")), u, fmt_num(f("today_debt")), u,
               fmt_num(f("today_cash") + f("today_network") + f("today_debt")), u,
               fmt_num(f("month_cash")), u, fmt_num(f("month_network")), u, fmt_num(f("month_new_debt")), u,
               fmt_num(f("month_paid_debt")), u, fmt_num(f("total_remaining_debts")), u))
    _back(ctx, text, "rp:3")


# ═══════════════════════════ 4) الأرباح ═══════════════════════════
def _profit_sql(period):
    parts = []
    for src, table, col in (("cash", "cash_sales", "sale_date"), ("net", "network_sales", "sale_date"),
                            ("debt", "shop_debts", "debt_date")):
        parts.append("SELECT '%s' AS src, product_name, single_price, quantity FROM %s "
                     "WHERE client_num = :p_cn AND %s" % (src, table, _cond(col, period)))
    return ("SELECT s.src AS src, NVL(SUM((s.single_price - NVL(p.purchase_price, 0)) * s.quantity), 0) AS profit "
            "FROM (" + " UNION ALL ".join(parts) + ") s "
            "JOIN products_table p ON LOWER(s.product_name) = LOWER(p.product_name) GROUP BY s.src")


def sec_profits(ctx, r):
    sub = r[0] if r else None
    u = _u(ctx)
    if sub is None:
        ctx.reset()
        ctx.reply("--- 💹 تقارير الأرباح الصافية ---",
                  kb([("📈 الأرباح اليومية", "rp:4:day")], [("📊 الأرباح الشهرية", "rp:4:month")],
                     [("↩️ رجوع", "rp:menu"), BACK_HOME]))
    elif sub in ("day", "month"):
        rows = db.rows(_profit_sql(sub), p_cn=ctx.client["num"])
        v = {x["src"].strip(): float(x["profit"] or 0) for x in rows}
        cash, net, debt = v.get("cash", 0.0), v.get("net", 0.0), v.get("debt", 0.0)
        title = "📈 صافي أرباح اليوم" if sub == "day" else "📊 صافي أرباح هذا الشهر"
        _back(ctx, "%s (بعد خصم رأس المال)\n💰 أرباح الكاش (كما في البرنامج): <b>%s</b> %s\n"
                   "💳 أرباح الشبكة: %s %s\n📝 أرباح الديون المسجلة: %s %s\n%s\nالإجمالي: <b>%s</b> %s"
              % (title, fmt_num(cash), u, fmt_num(net), u, fmt_num(debt), u, SEP,
                 fmt_num(cash + net + debt), u), "rp:4")


# ═══════════════════════════ 5) الديون ═══════════════════════════
def sec_debts(ctx, r):
    cn = ctx.client["num"]
    sub = r[0] if r else None
    u = _u(ctx)
    if sub is None:
        ctx.reset()
        total = db.val("SELECT NVL(SUM(debt_amount - NVL(paid_amount, 0)), 0) FROM shop_debts "
                       "WHERE client_num = :p_cn", 0, p_cn=cn)
        ctx.reply("--- 🔴 تقارير الديون ---\n🔴 إجمالي الديون في السوق (لجميع العملاء): <b>%s</b> %s"
                  % (fmt_num(total), u),
                  kb([("👤 كشف حساب لعميل محدد", "rp:5:cust")],
                     [("📋 كشف ديون جميع العملاء (الشامل)", "rp:5:all:0")],
                     [("🔢 بحث عن دين برقم الفاتورة", "rp:5:inv")],
                     [("↩️ رجوع", "rp:menu"), BACK_HOME]))
    elif sub == "cust":
        start_cust_search(ctx, "rp_debt", back="rp:5")
    elif sub == "all":
        page = _page_arg(r, 1)
        rows = db.rows(page_sql(
            "SELECT customer_name, product_name, quantity, debt_amount, NVL(paid_amount, 0) AS paid, "
            "debt_date, invoice_num FROM shop_debts WHERE client_num = :p_cn ORDER BY customer_name, debt_id",
            page, 10), p_cn=cn)
        has_next = len(rows) > 10
        lines = ["العميل: <b>%s</b> | المنتج: %s | الكمية: %s | المبلغ: %s %s%s | الوقت: %s"
                 % (esc(x["customer_name"]), esc(x["product_name"]), fmt_num(x["quantity"]),
                    fmt_num(x["debt_amount"]), u,
                    " (مسدد %s)" % fmt_num(x["paid"]) if float(x["paid"] or 0) else "", fmt_dt(x["debt_date"]))
                 for x in rows[:10]]
        if not rows and page == 0:
            lines = ["السوق نظيف، لا توجد ديون حالياً!"]
        show_page(ctx, "--- 📋 الكشف الشامل لجميع ديون السوق ---", lines, page, has_next, "rp:5:all", "rp:5")
    elif sub == "inv":
        ctx.go("rp:dinv")
        ctx.reply("أدخل رقم الفاتورة للبحث:", kb([("↩️ رجوع", "rp:5")]))


@on_state("rp:dinv")
def st_dinv(ctx):
    n = parse_int(ctx.text, 0)
    if n is None:
        ctx.send("أدخل رقم الفاتورة (أرقام فقط):")
        return
    x = db.one("SELECT customer_name, product_name, quantity, debt_amount, debt_date FROM shop_debts "
               "WHERE invoice_num = :p_n AND client_num = :p_cn", p_n=n, p_cn=ctx.client["num"])
    ctx.reset()
    if not x:
        ctx.send("⚠️ لم يتم العثور على أي دين يحمل رقم الفاتورة هذا.", kb([("↩️ رجوع", "rp:5")]))
        return
    ctx.send("--- 🧾 تفاصيل فاتورة الدين رقم [%s] ---\n👤 العميل: %s\n📦 المنتج: %s\n🔢 الكمية: %s\n"
             "💰 إجمالي الدين: <b>%s</b> %s\n📅 تاريخ الفاتورة: %s"
             % (n, esc(x["customer_name"]), esc(x["product_name"]), fmt_num(x["quantity"]),
                fmt_num(x["debt_amount"]), _u(ctx), fmt_dt(x["debt_date"])),
             kb([("🖨️ ملف الفاتورة", "inv:d:%s" % n)], [("↩️ رجوع", "rp:5"), BACK_HOME]))


@cust_purpose("rp_debt")
def rp_debt_picked(ctx, c):
    cn = ctx.client["num"]
    u = _u(ctx)
    rows = db.rows("SELECT * FROM (SELECT product_name, quantity, debt_amount, debt_date FROM shop_debts "
                   "WHERE customer_phone = :p_ph AND client_num = :p_cn ORDER BY debt_id) WHERE ROWNUM <= 40",
                   p_ph=c["phone"], p_cn=cn)
    td, tp, rem = debt_totals(c["phone"], cn)
    ctx.reset()
    lines = ["--- كشف حساب العميل [<b>%s</b>] ---" % esc(c["name"])]
    if not rows:
        lines.append("لا توجد ديون مسجلة باسم هذا العميل.")
        _back(ctx, "\n".join(lines), "rp:5")
        return
    for x in rows:
        lines.append("المنتج: %s | الكمية: %s | المبلغ: %s %s | الوقت: %s"
                     % (esc(x["product_name"]), fmt_num(x["quantity"]), fmt_num(x["debt_amount"]), u,
                        fmt_dt(x["debt_date"])))
    lines += [SEP, "إجمالي الديون المسجلة عليه: <b>%s</b> %s" % (fmt_num(td), u),
              "المسدد: %s | المتبقي: <b>%s</b> %s" % (fmt_num(tp), fmt_num(rem), u)]
    _back(ctx, "\n".join(lines), "rp:5", [[("🖨️ طباعة كشف الحساب (ملف)", "stm:%s" % c["phone"])]])


@on_cb("stm")
def cb_stm(ctx):
    if not ctx.args or not ctx.args[0].isdigit():
        return
    cn = ctx.client["num"]
    c = get_customer(cn, int(ctx.args[0]))
    if not c:
        ctx.send("⚠️ العميل غير موجود.")
        return
    u = _u(ctx)
    rows = db.rows("SELECT product_name, quantity, debt_amount, debt_date FROM shop_debts "
                   "WHERE customer_phone = :p_ph AND client_num = :p_cn ORDER BY debt_id",
                   p_ph=c["phone"], p_cn=cn)
    td, tp, rem = debt_totals(c["phone"], cn)
    L = ["====================================", "         كشف حساب ديون عميل         ",
         "===================================="]
    if ctx.client.get("shop_name"):
        L.append("المحل: %s" % ctx.client["shop_name"])
    L += ["اسم العميل: %s" % c["name"], "رقم الهاتف: %s" % c["phone"], "------------------------------------"]
    for x in rows:
        L += ["المنتج: %s" % x["product_name"],
              "الكمية: %s | المبلغ: %s %s" % (fmt_num(x["quantity"]), fmt_num(x["debt_amount"]), u),
              "التاريخ: %s" % fmt_dt(x["debt_date"]), "------------------------------------"]
    L += ["إجمالي الديون المسجلة: %s %s" % (fmt_num(td), u), "المسدد: %s %s" % (fmt_num(tp), u),
          "المتبقي: %s %s" % (fmt_num(rem), u), "====================================",
          "       يرجى سداد المبالغ قريباً     "]
    ctx.doc("Debt_Statement_%s.txt" % c["phone"], "\n".join(L), caption="🖨️ كشف حساب %s" % c["name"])


# ═══════════════════════════ 6) التعديلات (حذف) ═══════════════════════════
def sec_modify(ctx, r):
    sub = r[0] if r else None
    if sub is None:
        ctx.reset()
        ctx.reply("--- ✏️ قسم التعديلات ---\n⚠️ الحذف يتم بعد تأكيدك.",
                  kb([("🗑 حذف عميل", "rp:6:c")], [("🗑 حذف منتج", "rp:6:p")],
                     [("🗑 حذف ديون عميل", "rp:6:d")], [("↩️ رجوع", "rp:menu"), BACK_HOME]))
    elif sub == "c":
        start_cust_search(ctx, "delc", back="rp:6")
    elif sub == "p":
        start_prod_search(ctx, "delp", prompt="أدخل اسم المنتج لحذفه:", back="rp:6")
    elif sub == "d":
        start_cust_search(ctx, "deld", back="rp:6")


@cust_purpose("delc")
def delc_picked(ctx, c):
    td, tp, rem = debt_totals(c["phone"], ctx.client["num"])
    warn = "\n⚠️ عليه دين متبقي %s %s (ستبقى سجلات الدين ولن تُحذف)." % (fmt_num(rem), _u(ctx)) if rem > 0 else ""
    ctx.reset()
    ctx.reply("🗑 تأكيد حذف العميل <b>%s</b> (%s)؟%s" % (esc(c["name"]), c["phone"], warn),
              kb([("✅ نعم، احذف", "del:c:%s" % c["phone"])], [("❌ إلغاء", "rp:6")]))


@prod_purpose("delp")
def delp_picked(ctx, p):
    ctx.reset()
    ctx.reply("🗑 تأكيد حذف المنتج <b>%s</b>؟\n⚠️ المنتجات مشتركة بين جميع الحسابات في قاعدة البيانات."
              % esc(p["product_name"]),
              kb([("✅ نعم، احذف", "del:p:%s" % p["product_id"])], [("❌ إلغاء", "rp:6")]))


@cust_purpose("deld")
def deld_picked(ctx, c):
    td, tp, rem = debt_totals(c["phone"], ctx.client["num"])
    ctx.reset()
    ctx.reply("🗑 تأكيد تصفير وحذف جميع ديون العميل <b>%s</b>؟\nالمتبقي عليه: %s %s\n"
              "<i>(تُحفظ نسخة في الأرشيف)</i>" % (esc(c["name"]), fmt_num(rem), _u(ctx)),
              kb([("✅ نعم، احذف", "del:d:%s" % c["phone"])], [("❌ إلغاء", "rp:6")]))


@on_cb("del")
def cb_del(ctx):
    a = ctx.args
    if len(a) < 2 or not a[1].isdigit():
        return
    kind, ident, cn = a[0], int(a[1]), ctx.client["num"]
    back = [[("↩️ رجوع", "rp:6"), BACK_HOME]]
    if kind == "c":
        n = db.run("DELETE FROM shop_customers WHERE customer_phone = :p_ph AND client_num = :p_cn",
                   p_ph=ident, p_cn=cn)
        core.audit("DELETE_CUSTOMER", ctx, details="phone=%s" % ident)
    elif kind == "p":
        try:
            n = db.run("DELETE FROM products_table WHERE product_id = :p_id", p_id=ident)
        except Exception as e:
            if "ORA-02292" in str(e):
                ctx.reply("❌ لا يمكن حذف المنتج لوجود سجلات مرتبطة به في قاعدة البيانات.", kb(*back))
                return
            raise
        core.audit("DELETE_PRODUCT", ctx, details="id=%s" % ident)
    elif kind == "d":
        with db.tx() as t:
            n = archive_and_delete_debts(t, cn, ident, "DELETED")
            core.audit("DELETE_DEBTS", ctx, details="phone=%s rows=%s" % (ident, n), t=t)
    else:
        return
    ctx.reset()
    ctx.reply("✅ تم الحذف بنجاح!" if n else "⚠️ لم يتم العثور على بيانات مطابقة للحذف.", kb(*back))


# ═══════════════════════════ 7) بحث عن عمليات بيع ═══════════════════════════
def _union_sql(period):
    parts = []
    for typ, (table, col, amt) in (("cash", SALES_TABLE["c"]), ("net", SALES_TABLE["n"]), ("debt", SALES_TABLE["d"])):
        parts.append("SELECT '%s' AS s_type, invoice_num, customer_name, customer_phone, product_name, quantity, "
                     "%s AS amt, %s AS dt FROM %s WHERE client_num = :p_cn AND %s"
                     % (typ, amt, col, table, _cond(col, period)))
    return " UNION ALL ".join(parts)


def sec_search(ctx, r):
    cn = ctx.client["num"]
    sub = r[0] if r else None
    u = _u(ctx)
    if sub is None:
        ctx.reset()
        ctx.reply("--- 🔍 بحث وتقارير المبيعات التفصيلية ---",
                  kb([("💳 مبيعات الشبكة", "rp:7:n"), ("💰 مبيعات الكاش", "rp:7:c")],
                     [("📝 مبيعات الديون", "rp:7:d")],
                     [("📋 تقرير مفصل بجميع عمليات اليوم", "rp:7:day:0")],
                     [("📋 تقرير مفصل بجميع عمليات الشهر", "rp:7:month:0")],
                     [("↩️ رجوع", "rp:menu"), BACK_HOME]))
    elif sub in SALES_TABLE:
        label = {"c": "الكاش", "n": "الشبكة", "d": "الديون"}[sub]
        ctx.reply("طريقة البحث في مبيعات %s:" % label,
                  kb([("🔢 برقم الفاتورة", "rp:7:q:%s:inv" % sub)],
                     [("👤 باسم الزبون", "rp:7:q:%s:name" % sub)],
                     [("📞 برقم هاتف الزبون", "rp:7:q:%s:phone" % sub)],
                     [("↩️ رجوع", "rp:7")]))
    elif sub == "q" and len(r) > 2 and r[1] in SALES_TABLE and r[2] in ("inv", "name", "phone"):
        ctx.go("rp:sq", rq_kind=r[1], rq_crit=r[2])
        ctx.reply({"inv": "أدخل رقم الفاتورة:", "name": "أدخل اسم الزبون:", "phone": "أدخل رقم الهاتف:"}[r[2]],
                  kb([("↩️ رجوع", "rp:7")]))
    elif sub in ("day", "month"):
        page = _page_arg(r, 1)
        union = _union_sql(sub)
        rows = db.rows(page_sql("SELECT s_type, invoice_num, customer_name, customer_phone, product_name, "
                                "quantity, amt, dt FROM (" + union + ") ORDER BY dt DESC", page, 8), p_cn=cn)
        has_next = len(rows) > 8
        names = {"cash": "كاش", "net": "شبكة", "debt": "دين"}
        lines = []
        for x in rows[:8]:
            lines.append("🔖 [%s] | الفاتورة: %s | %s\n👤 %s (%s)\n📦 %s | الكمية: %s | <b>%s</b> %s"
                         % (names[x["s_type"].strip()], x["invoice_num"] if x["invoice_num"] is not None else "-",
                            fmt_dt(x["dt"]), esc(x["customer_name"]), x["customer_phone"] or 0,
                            esc(x["product_name"]), fmt_num(x["quantity"]), fmt_num(x["amt"]), u))
        header = None
        if page == 0:
            tot = {x["s_type"].strip(): float(x["total"] or 0) for x in db.rows(
                "SELECT s_type, NVL(SUM(amt), 0) AS total FROM (" + union + ") GROUP BY s_type", p_cn=cn)}
            if tot:
                header = ("💰 إجمالي الكاش: %s\n💳 إجمالي الشبكة: %s\n📝 إجمالي الديون: %s\n💵 الإجمالي الكلي: <b>%s</b> %s"
                          % (fmt_num(tot.get("cash", 0)), fmt_num(tot.get("net", 0)), fmt_num(tot.get("debt", 0)),
                             fmt_num(sum(tot.values())), u))
        title = "=== 📋 التقرير المفصل لجميع عمليات (%s) ===" % ("اليوم" if sub == "day" else "هذا الشهر")
        if not rows and page == 0:
            lines = ["⚠️ لا توجد أي مبيعات مسجلة في %s." % ("اليوم" if sub == "day" else "هذا الشهر")]
        show_page(ctx, title, lines, page, has_next, "rp:7:" + sub, "rp:7", header)


@on_state("rp:sq")
def st_sq(ctx):
    kind, crit = ctx.data.get("rq_kind"), ctx.data.get("rq_crit")
    if kind not in SALES_TABLE or crit not in ("inv", "name", "phone"):
        ctx.reset()
        ctx.send("انتهت صلاحية هذه الشاشة.", kb([("🔍 بحث", "rp:7")]))
        return
    table, dcol, amt = SALES_TABLE[kind]
    sql = ("SELECT customer_name, customer_phone, product_name, quantity, single_price, %s AS total_amt, "
           "invoice_num, %s AS d_date FROM %s WHERE client_num = :p_cn AND " % (amt, dcol, table))
    if crit == "name":
        v = (ctx.text or "").strip()
        if not v:
            ctx.send("أدخل اسم الزبون:")
            return
        sql += "LOWER(customer_name) LIKE :p_v" + LIKE_ESC
        v = like(v)
    else:
        v = parse_int(ctx.text, 0, 999_999_999_999_999)
        if v is None:
            ctx.send("أدخل رقماً صحيحاً (أرقام فقط):")
            return
        sql += ("invoice_num = :p_v" if crit == "inv" else "customer_phone = :p_v")
    rows = db.rows("SELECT * FROM (" + sql + " ORDER BY " + dcol + " DESC) WHERE ROWNUM <= 16",
                   p_cn=ctx.client["num"], p_v=v)
    ctx.reset()
    u = _u(ctx)
    label = {"c": "الكاش", "n": "الشبكة", "d": "الديون"}[kind]
    if not rows:
        ctx.send("⚠️ لا توجد نتائج مطابقة لبحثك.", kb([("🔁 بحث آخر", "rp:7:%s" % kind), ("↩️ رجوع", "rp:7")]))
        return
    lines = ["--- 🧾 نتائج البحث في قسم (%s) ---" % label]
    for x in rows[:15]:
        lines.append("الفاتورة: %s | الزبون: %s (%s)\nالمنتج: %s | الكمية: %s | الإجمالي: <b>%s</b> %s | %s\n%s"
                     % (x["invoice_num"] if x["invoice_num"] is not None else "-", esc(x["customer_name"]),
                        x["customer_phone"] or 0, esc(x["product_name"]), fmt_num(x["quantity"]),
                        fmt_num(x["total_amt"]), u, fmt_dt(x["d_date"]), SEP))
    if len(rows) > 15:
        lines.append("… (يوجد نتائج أكثر، حدّد البحث)")
    btns = [[("🖨️ فاتورة %s" % x["invoice_num"], "inv:%s:%s" % (kind, x["invoice_num"]))]
            for x in rows[:5] if x["invoice_num"] is not None]
    ctx.send("\n".join(lines), kb(*(btns + [[("🔁 بحث آخر", "rp:7:%s" % kind), ("↩️ رجوع", "rp:7")]])))


# ═══════════════════════════ 8) حركة المنتجات ═══════════════════════════
def _sold_sql():
    parts = []
    for table, col in (("cash_sales", "sale_date"), ("network_sales", "sale_date"), ("shop_debts", "debt_date")):
        parts.append("SELECT product_name, quantity AS month_qty, CASE WHEN TRUNC(%s) = TRUNC(SYSDATE) "
                     "THEN quantity ELSE 0 END AS today_qty FROM %s WHERE client_num = :p_cn AND %s"
                     % (col, table, _cond(col, "month")))
    return ("SELECT product_name, SUM(month_qty) AS total_month, SUM(today_qty) AS total_today FROM ("
            + " UNION ALL ".join(parts) + ") GROUP BY product_name")


def sec_movement(ctx, r):
    cn = ctx.client["num"]
    page = _page_arg(r, 1) if r and r[0] == "p" else 0
    u = _u(ctx)
    header = None
    if page == 0:
        top = db.one("SELECT * FROM (" + _sold_sql() + " ORDER BY total_month DESC) WHERE ROWNUM = 1", p_cn=cn)
        if top:
            header = ("🌟 <b>المنتج الأكثر مبيعاً:</b> %s\n   - بيع منه هذا الشهر: %s حبة\n   - بيع منه اليوم: %s حبة"
                      % (esc(top["product_name"]), fmt_num(top["total_month"]), fmt_num(top["total_today"])))
        else:
            header = "🌟 المنتج الأكثر مبيعاً: لا توجد مبيعات مسجلة هذا الشهر."
    rows = db.rows(page_sql(
        "SELECT p.product_name AS pname, NVL(p.purchase_price, 0) AS pp, NVL(p.price, 0) AS sp, "
        "(NVL(p.price, 0) - NVL(p.purchase_price, 0)) AS prof, NVL(p.quantity, 0) AS stock_qty, "
        "NVL(p.units_per_carton, 1) AS ucarton, NVL(s.total_today, 0) AS today_sold, "
        "NVL(s.total_month, 0) AS month_sold FROM products_table p LEFT JOIN (" + _sold_sql() + ") s "
        "ON p.product_name = s.product_name ORDER BY p.product_name", page, 6), p_cn=cn)
    has_next = len(rows) > 6
    lines = []
    for x in rows[:6]:
        uc = int(x["ucarton"] or 1) or 1
        stock = int(x["stock_qty"])
        lines.append("📦 <b>%s</b>\n💵 الشراء: %s | 💰 البيع: %s | 📈 الربح: %s %s\n"
                     "📊 بيع اليوم: %s حبة | الشهر: %s حبة\n🏢 المتبقي: %s كرتون و %s حبة (إجمالي %s)"
                     % (esc(x["pname"]), fmt_num(x["pp"]), fmt_num(x["sp"]), fmt_num(x["prof"]), u,
                        fmt_num(x["today_sold"]), fmt_num(x["month_sold"]),
                        stock // uc if stock >= 0 else 0, stock % uc if stock >= 0 else stock, fmt_num(stock)))
    if not rows and page == 0:
        lines = ["⚠️ لم يتم العثور على أي منتجات في قاعدة البيانات."]
    show_page(ctx, "===== 📦 تقرير حركة المنتجات والأرباح الشامل =====", lines, page, has_next, "rp:8:p", "rp:menu", header)


SECTIONS = {"1": sec_products, "2": sec_customers, "3": sec_sales, "4": sec_profits,
            "5": sec_debts, "6": sec_modify, "7": sec_search, "8": sec_movement}
'''

# ════════════════════ admin.py ════════════════════
SOURCES['admin'] = r'''"""لوحة الإدارة (للمدراء فقط: ADMIN_IDS).

تحلّ محل «التفعيل من Toad»: الموافقة على طلبات التجديد، التمديد اليدوي، إيقاف/تفعيل حساب،
سعر الشهر (System_Settings) وأسعار الصرف (Exchange_Rates).
"""
from __future__ import annotations

import logging

import core
import db
import subs
from config import cfg
from core import (BACK_HOME, duration_label, esc, fmt_date, fmt_num, kb, on_cb, on_state,
                  parse_float, parse_int)
from reports import page_sql

log = logging.getLogger("admin")
HOME_BTN = ("🛡 لوحة الإدارة", "adm:home")


def _guard(ctx):
    if not ctx.is_admin:
        ctx.answer("غير مسموح", True)
        return False
    return True


@on_cb("adm")
def cb_adm(ctx):
    if not _guard(ctx):
        return
    a = ctx.args
    act = a[0] if a else "home"
    arg = a[1] if len(a) > 1 else ""
    if act == "home":
        home(ctx)
    elif act == "pend":
        pending(ctx)
    elif act == "ok" and arg.isdigit():
        decide(ctx, int(arg), True)
    elif act == "no" and arg.isdigit():
        decide(ctx, int(arg), False)
    elif act == "subs":
        subscribers(ctx, int(arg) if arg.isdigit() else 0)
    elif act == "c" and arg.isdigit():
        client_detail(ctx, int(arg))
    elif act == "act":
        ctx.go("adm:num")
        ctx.reply("أدخل <b>رقم العميل</b> الذي تريد تفعيل/تمديد اشتراكه:", kb([HOME_BTN]))
    elif act == "ext" and arg.isdigit():
        ask_months(ctx, int(arg))
    elif act == "toggle" and arg.isdigit():
        toggle(ctx, int(arg))
    elif act == "price":
        ctx.go("adm:price")
        ctx.reply("💰 سعر الشهر الحالي: <b>%s</b> %s\nأدخل السعر الجديد (رقم صحيح):"
                  % (fmt_num(subs.month_price()), cfg.SUB_PRICE_UNIT), kb([HOME_BTN]))
    elif act == "rates":
        usd, sar = _rates()
        ctx.go("adm:usd")
        ctx.reply("💱 الأسعار الحالية: الدولار = %s | الريال السعودي = %s\n\nأدخل سعر <b>الدولار</b> الجديد (بالريال اليمني):"
                  % (fmt_num(usd), fmt_num(sar)), kb([HOME_BTN]))


def _rates():
    r = db.one("SELECT usd_price, sar_price FROM exchange_rates WHERE id = 1")
    return (float(r["usd_price"] or 0), float(r["sar_price"] or 0)) if r else (0.0, 0.0)


def home(ctx):
    ctx.reset()
    pend = db.val("SELECT COUNT(*) FROM bot_sub_requests WHERE status = 'PENDING'", 0)
    total = db.val("SELECT COUNT(*) FROM clients_table", 0)
    soon = db.val("SELECT COUNT(*) FROM clients_table WHERE expiry_date BETWEEN SYSDATE AND SYSDATE + 7", 0)
    expired = db.val("SELECT COUNT(*) FROM clients_table WHERE expiry_date < SYSDATE", 0)
    ctx.reply("🛡 <b>لوحة الإدارة</b>\n\n📥 طلبات تجديد معلّقة: <b>%s</b>\n👥 المشتركون: %s\n"
              "⏰ ينتهي خلال 7 أيام: %s\n⛔ منتهي: %s\n💰 سعر الشهر: %s %s"
              % (pend, total, soon, expired, fmt_num(subs.month_price()), cfg.SUB_PRICE_UNIT),
              kb([("📥 الطلبات المعلّقة (%s)" % pend, "adm:pend")],
                 [("👥 المشتركون", "adm:subs:0"), ("➕ تفعيل/تمديد يدوي", "adm:act")],
                 [("💰 سعر الشهر", "adm:price"), ("💱 أسعار الصرف", "adm:rates")],
                 [BACK_HOME]))


# ───────────────────────── طلبات التجديد ─────────────────────────
def pending(ctx):
    rows = db.rows("SELECT * FROM (SELECT r.req_id, r.months, r.amount, r.created_at, c.name, c.num "
                   "FROM bot_sub_requests r JOIN clients_table c ON c.num = r.client_num "
                   "WHERE r.status = 'PENDING' ORDER BY r.req_id) WHERE ROWNUM <= 10")
    if not rows:
        ctx.reply("لا توجد طلبات تجديد معلّقة ✅", kb([HOME_BTN]))
        return
    lines = ["📥 <b>طلبات التجديد المعلّقة</b>", ""]
    btns = []
    for r in rows:
        lines.append("#%s • %s (رقم %s) • %s • %s %s\n    %s" % (
            r["req_id"], esc(r["name"]), r["num"], duration_label(r["months"]), fmt_num(r["amount"]),
            cfg.SUB_PRICE_UNIT, core.fmt_dt(r["created_at"])))
        btns.append([("✅ تفعيل #%s" % r["req_id"], "adm:ok:%s" % r["req_id"]),
                     ("❌ رفض #%s" % r["req_id"], "adm:no:%s" % r["req_id"])])
    btns.append([HOME_BTN])
    ctx.reply("\n".join(lines), kb(*btns))


def decide(ctx, rid, ok):
    try:
        req, res = (subs.approve_request if ok else subs.reject_request)(ctx, rid)
    except ValueError as e:
        ctx.reply("⚠️ %s" % esc(e), kb([HOME_BTN]))
        return
    if not req:
        ctx.reply("⚠️ %s" % esc(res), kb([("📥 الطلبات", "adm:pend"), HOME_BTN]))
        return
    if ok:
        ctx.reply("✅ تم تفعيل الطلب <b>#%s</b> (العميل رقم %s).\nينتهي الاشتراك في: <b>%s</b>"
                  % (rid, req["client_num"], fmt_date(res)),
                  kb([("📥 الطلبات", "adm:pend"), HOME_BTN]))
    else:
        ctx.reply("❌ تم رفض الطلب <b>#%s</b>." % rid, kb([("📥 الطلبات", "adm:pend"), HOME_BTN]))


# ───────────────────────── المشتركون ─────────────────────────
def subscribers(ctx, page):
    rows = db.rows(page_sql("SELECT num, name, shop_name, expiry_date, (expiry_date - SYSDATE) AS days_left, "
                            "is_active FROM clients_table ORDER BY expiry_date", page, 8))
    has_next = len(rows) > 8
    lines = ["👥 <b>المشتركون</b>", ""]
    btns = []
    for r in rows[:8]:
        dl = r["days_left"]
        if r["is_active"] is not None and int(r["is_active"]) == 0:
            st = "⛔ موقوف"
        elif dl is not None and dl < 0:
            st = "❌ منتهي"
        else:
            st = "✅ %s يوم" % ("∞" if dl is None else int(dl))
        lines.append("<b>%s</b> (رقم %s) — %s — ينتهي %s" % (esc(r["name"]), r["num"], st, fmt_date(r["expiry_date"])))
        btns.append([("👤 %s (%s)" % ((r["name"] or "")[:22], r["num"]), "adm:c:%s" % r["num"])])
    if not rows:
        lines.append("لا يوجد مشتركون.")
    nav = []
    if page > 0:
        nav.append(("◀️ السابق", "adm:subs:%d" % (page - 1)))
    if has_next:
        nav.append(("التالي ▶️", "adm:subs:%d" % (page + 1)))
    if nav:
        btns.append(nav)
    btns.append([HOME_BTN])
    ctx.reply("\n".join(lines), kb(*btns))


def client_detail(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ العميل غير موجود.", kb([("👥 المشتركون", "adm:subs:0"), HOME_BTN]))
        return
    st = subs.status(c)
    state = "⛔ موقوف" if st["blocked"] else ("❌ منتهي" if st["expired"] else "✅ ساري")
    ctx.reply("👤 <b>%s</b> (رقم %s)\nالايميل: %s\nالمحل: %s\nنوع الحساب: %s\n"
              "بدأ: %s\nينتهي: <b>%s</b> (%s)\nالمدة المسجلة: %s شهر\nإجمالي المدفوع: %s %s"
              % (esc(c["name"]), c["num"], esc(c["email"]), esc(c.get("shop_name") or "-"),
                 esc(c.get("account_type") or "غير محدد"), fmt_date(c.get("start_date")),
                 fmt_date(c.get("expiry_date")), state, c.get("subscription_months") or 0,
                 fmt_num(c.get("money") or 0), cfg.SUB_PRICE_UNIT),
              kb([("➕ تمديد / تجديد", "adm:ext:%s" % num)],
                 [("✅ تفعيل الحساب" if st["blocked"] else "⛔ إيقاف الحساب", "adm:toggle:%s" % num)],
                 [("👥 المشتركون", "adm:subs:0"), HOME_BTN]))


def toggle(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ العميل غير موجود.", kb([HOME_BTN]))
        return
    blocked = subs.status(c)["blocked"]
    db.run("UPDATE clients_table SET is_active = :p_v WHERE num = :p_n", p_v=1 if blocked else 0, p_n=num)
    core.audit("ACCOUNT_TOGGLE", ctx, client_num=num, details="active=%s" % (1 if blocked else 0))
    if blocked:
        subs.notify_client(num, "✅ تم تفعيل حسابك من قبل الإدارة.", kb([BACK_HOME]))
    client_detail(ctx, num)


# ───────────────────────── التمديد اليدوي ─────────────────────────
@on_state("adm:num")
def st_num(ctx):
    n = parse_int(ctx.text, 1, 2147483647)
    if n is None:
        ctx.send("أدخل رقم العميل (أرقام فقط):")
        return
    if not core.fetch_client(n):
        ctx.send("⚠️ لا يوجد عميل بهذا الرقم. أعد المحاولة:", kb([HOME_BTN]))
        return
    ask_months(ctx, n)


def ask_months(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ العميل غير موجود.", kb([HOME_BTN]))
        return
    ctx.go("adm:months", adm_num=num)
    price = subs.month_price()
    ctx.reply("👤 <b>%s</b> — ينتهي اشتراكه: %s\n\nأدخل <b>عدد الأشهر</b> للإضافة.\n"
              "(اختيارياً اكتب المبلغ المدفوع بعدها، مثال: <code>3</code> أو <code>3 0</code> للتمديد المجاني)\n"
              "المبلغ الافتراضي = الأشهر × %s" % (esc(c["name"]), fmt_date(c.get("expiry_date")), fmt_num(price)),
              kb([HOME_BTN]))


@on_state("adm:months")
def st_months(ctx):
    num = ctx.data.get("adm_num")
    parts = core.norm(ctx.text or "").split()
    months = parse_int(parts[0], 1, 120) if parts else None
    if months is None or num is None or len(parts) > 2:
        ctx.send("أدخل عدد أشهر صحيحاً (1 إلى 120)، ويمكن إضافة المبلغ بعده:")
        return
    amount = subs.month_price() * months
    if len(parts) == 2:
        amount = parse_float(parts[1], 0.0, 99_999_999_999.0)
        if amount is None:
            ctx.send("المبلغ غير صحيح. أعد الإدخال (مثال: 3 أو 3 0):")
            return
    try:
        with db.tx() as t:
            exp, total = subs.grant(t, num, months, amount)
            core.audit("SUB_MANUAL", ctx, client_num=num, details="months=%s amount=%s" % (months, amount), t=t)
    except ValueError as e:
        ctx.reset()
        ctx.send("⚠️ %s" % esc(e), kb([HOME_BTN]))
        return
    ctx.reset()
    subs.notify_client(num, "✅ <b>تم تمديد اشتراكك</b> %s.\nينتهي في: <b>%s</b>" % (duration_label(months), fmt_date(exp)),
                       kb([BACK_HOME]))
    ctx.send("✅ تم تمديد اشتراك العميل رقم %s لمدة %s.\nينتهي في: <b>%s</b>" % (num, duration_label(months), fmt_date(exp)),
             kb([("👤 تفاصيل العميل", "adm:c:%s" % num), HOME_BTN]))


# ───────────────────────── الأسعار ─────────────────────────
@on_state("adm:price")
def st_price(ctx):
    v = parse_int(ctx.text, 0, 999_999_999_999)
    if v is None:
        ctx.send("أدخل سعراً صحيحاً (رقم صحيح بدون كسور):")
        return
    n = db.run("UPDATE system_settings SET month_price = :p_v, updated_at = SYSDATE WHERE id = 1", p_v=v)
    if not n:
        db.run("INSERT INTO system_settings (id, month_price) VALUES (1, :p_v)", p_v=v)
    core.audit("SET_MONTH_PRICE", ctx, details=str(v))
    ctx.reset()
    ctx.send("✅ تم تحديث سعر الشهر إلى <b>%s</b> %s" % (fmt_num(v), cfg.SUB_PRICE_UNIT), kb([HOME_BTN]))


@on_state("adm:usd")
def st_usd(ctx):
    v = parse_float(ctx.text, 0.0001, 10_000_000.0)
    if v is None:
        ctx.send("أدخل سعر الدولار (رقم أكبر من صفر):")
        return
    ctx.go("adm:sar", adm_usd=v)
    ctx.send("أدخل سعر <b>الريال السعودي</b> الجديد (بالريال اليمني):")


@on_state("adm:sar")
def st_sar(ctx):
    v = parse_float(ctx.text, 0.0001, 10_000_000.0)
    usd = ctx.data.get("adm_usd")
    if v is None or usd is None:
        ctx.send("أدخل سعر الريال السعودي (رقم أكبر من صفر):")
        return
    n = db.run("UPDATE exchange_rates SET usd_price = :p_u, sar_price = :p_s, updated_at = SYSDATE WHERE id = 1",
               p_u=usd, p_s=v)
    if not n:
        db.run("INSERT INTO exchange_rates (id, usd_price, sar_price) VALUES (1, :p_u, :p_s)", p_u=usd, p_s=v)
    core.audit("SET_RATES", ctx, details="usd=%s sar=%s" % (usd, v))
    ctx.reset()
    ctx.send("✅ تم تحديث أسعار الصرف:\n💵 الدولار = %s\n🇸🇦 الريال السعودي = %s" % (fmt_num(usd), fmt_num(v)),
             kb([HOME_BTN]))
'''

# ════════════════════ router.py ════════════════════
SOURCES['router'] = r'''"""توجيه التحديثات القادمة من تلجرام: الأوامر، الأزرار، النصوص، وفحص الاشتراك."""
from __future__ import annotations

import collections
import logging

import accounts
import admin      # noqa: F401  (استيراد لتسجيل المعالجات)
import core
import menus
import pickers    # noqa: F401
import reports    # noqa: F401
import shop       # noqa: F401
import subs
import tg
from config import cfg
from core import CB_H, LOCK, MEDIA_STATES, STATE_H, Ctx, esc

log = logging.getLogger("router")

# أزرار/أوامر مسموحة حتى لو انتهى الاشتراك (لتمكين التجديد)
FREE_CB_WHEN_EXPIRED = {"sub", "acct", "adm", "auth"}
# حالات تنتظر الضغط على زر (النص فيها لا معنى له)
BUTTON_STATES = {"sale:negq", "sale:confirm", "imp:confirm", "pay:fullq", "setup:country", "setup:currency"}

HELP = ("ℹ️ <b>المساعدة</b>\n\n"
        "/start — البدء / القائمة الرئيسية\n"
        "/menu — القائمة الرئيسية\n"
        "/subscription — اشتراكي وتجديد الاشتراك\n"
        "/cancel — إلغاء العملية الحالية\n"
        "/logout — تسجيل الخروج\n"
        "/id — معرفة رقم حسابك في تلجرام\n\n"
        "💡 يمكنك كتابة الأرقام بالعربية أو الإنجليزية.")

_seen = collections.deque()
_seen_set = set()
_SEEN_MAX = 3000


def _dup(update_id):
    """يمنع معالجة نفس التحديث مرتين (تلجرام يعيد الإرسال عند التأخر)."""
    if update_id is None:
        return False
    if update_id in _seen_set:
        return True
    if len(_seen) >= _SEEN_MAX:
        _seen_set.discard(_seen.popleft())
    _seen.append(update_id)
    _seen_set.add(update_id)
    return False


def handle_update(update):
    ctx = Ctx(update)
    if ctx.chat_id is None or ctx.user_id is None or ctx.chat_type != "private":
        return
    with LOCK:
        if _dup(ctx.update_id):
            return
        try:
            _process(ctx)
        except Exception as e:  # لا نترك المستخدم بدون رد
            log.exception("update %s failed", ctx.update_id)
            _fail(ctx, e)


def _fail(ctx, e):
    try:
        ctx.answer()
        msg = "⚠️ حدث خطأ غير متوقع. حاول مرة أخرى أو أرسل /menu."
        if ctx.is_admin:
            msg += "\n<code>%s</code>" % esc(str(e)[:350])
        tg.send(ctx.chat_id, msg)
    except Exception:
        log.exception("failed to report error")


def _process(ctx):
    if ctx.is_cb:
        ctx.answer()                       # يوقف دوران الزر فوراً
    ctx.load_session()
    num = ctx.sess.get("client_num")
    if num:
        ctx.client = core.fetch_client(num)
        if ctx.client is None:             # الحساب حُذف من القاعدة
            ctx.unlink()
        else:
            ctx.sub = subs.status(ctx.client)
    if ctx.is_cb:
        return _cb(ctx)
    text = (ctx.text or "").strip()
    if text.startswith("/"):
        return _cmd(ctx, text)
    return _state(ctx)


# ───────────────────────── الأوامر ─────────────────────────
def _home_or_expired(ctx):
    if ctx.sub and not ctx.sub["ok"]:
        return subs.show_expired(ctx)
    return menus.home(ctx)


def _cmd(ctx, text):
    cmd = text.split()[0].split("@")[0].lower()
    if cmd == "/id":
        ctx.send("🆔 رقم حسابك في تلجرام: <code>%s</code>" % ctx.user_id)
        return
    if cmd == "/help":
        ctx.send(HELP)
        return
    ctx.reset()                            # أي أمر آخر يلغي العملية الجارية
    if cmd in ("/start", "/menu", "/cancel"):
        if ctx.client:
            return _home_or_expired(ctx)
        return accounts.start(ctx, fresh=True)
    if cmd in ("/subscription", "/sub"):
        if ctx.client:
            return subs.home(ctx) if ctx.sub["ok"] else subs.show_expired(ctx)
        return accounts.start(ctx, fresh=True)
    if cmd == "/logout":
        if ctx.client:
            return accounts.logout(ctx)
        return accounts.start(ctx, fresh=True)
    if cmd == "/admin":
        if not ctx.is_admin:
            ctx.send("⛔ هذا الأمر للمدير فقط.")
            return
        return CB_H["adm"](_as_cb(ctx, "adm:home"))
    ctx.send("أمر غير معروف. أرسل /help للمساعدة.")


def _as_cb(ctx, data):
    ctx.args = data.split(":")[1:]
    return ctx


# ───────────────────────── الأزرار ─────────────────────────
def _cb(ctx):
    parts = ctx.cb.split(":")
    prefix, ctx.args = parts[0], parts[1:]
    h = CB_H.get(prefix)
    if h is None:
        ctx.answer("زر غير معروف")
        return
    if prefix in ("adm", "auth"):
        return h(ctx)
    if not ctx.client:
        ctx.send("سجّل الدخول أولاً: /start")
        return
    if not ctx.sub["ok"] and prefix not in FREE_CB_WHEN_EXPIRED:
        return subs.show_expired(ctx)
    return h(ctx)


# ───────────────────────── النصوص (حسب الحالة) ─────────────────────────
def _state(ctx):
    st = ctx.state
    if not st:
        if ctx.client:
            if ctx.sub["ok"]:
                return menus.home(ctx, note="👇 اختر من القائمة")
            return subs.show_expired(ctx)
        return accounts.start(ctx, fresh=True)
    if st in BUTTON_STATES:
        ctx.send("👆 اضغط أحد الأزرار في الرسالة السابقة، أو أرسل /cancel للإلغاء.")
        return
    h = STATE_H.get(st)
    if h is None:
        ctx.reset()
        return _home_or_expired(ctx) if ctx.client else accounts.start(ctx, fresh=True)
    if st.startswith(("reg:", "login:")):
        if ctx.client:
            ctx.reset()
            return _home_or_expired(ctx)
    elif st.startswith("adm:"):
        if not ctx.is_admin:
            ctx.reset()
            ctx.send("⛔ غير مسموح.")
            return
    else:
        if not ctx.client:
            ctx.reset()
            return accounts.start(ctx, fresh=True)
        if not ctx.sub["ok"] and st != "sub:proof":
            ctx.reset()
            return subs.show_expired(ctx)
    if ctx.text is None and st not in MEDIA_STATES:
        ctx.send("أرسل نصاً من فضلك (أو /cancel للإلغاء).")
        return
    return h(ctx)
'''

# ════════════════════ server.py ════════════════════
SOURCES['server'] = r'''"""خادم الويب (Webhook) — يعمل بمكتبة بايثون القياسية، ويصلح لأي منصة (Render / Railway / Koyeb / Fly / Heroku / VPS).

المسارات:
  POST /webhook          ← تحديثات تلجرام (محمي بـ secret token)
  GET  /                 ← فحص حياة بسيط للمنصة
  GET  /health           ← حالة قاعدة البيانات والويب هوك (التفاصيل مع ?key=CRON_SECRET)
  GET  /cron/reminders   ← تذكيرات الاشتراك (يستدعيها cron خارجي مع ?key=CRON_SECRET)
"""
from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db
import router
import subs
import tg
from config import cfg

log = logging.getLogger("server")
STATE = {"schema": None, "webhook": None, "db_error": None}
_started = False
_start_lock = threading.Lock()

STATUS_LINES = {200: "200 OK", 400: "400 Bad Request", 401: "401 Unauthorized", 403: "403 Forbidden",
                404: "404 Not Found", 413: "413 Payload Too Large", 500: "500 Internal Server Error"}


# ───────────────────────── الإقلاع ─────────────────────────
def startup():
    if not cfg.BOT_TOKEN:
        log.error("BOT_TOKEN غير موجود في متغيرات البيئة")
        return
    try:
        STATE["schema"] = db.ensure_schema()
        STATE["db_error"] = None
        log.info("schema report: %s", STATE["schema"])
    except Exception as e:  # قاعدة البيانات غير متاحة الآن — سنحاول لاحقاً عند أول طلب
        STATE["db_error"] = str(e)[:300]
        log.error("DB init failed: %s", e)
    tg.set_commands()
    if cfg.PUBLIC_URL:
        url = cfg.PUBLIC_URL + "/webhook"
        ok = tg.set_webhook(url, cfg.WEBHOOK_SECRET)
        STATE["webhook"] = url if ok else "FAILED: " + tg.last_error()
        log.info("webhook %s", STATE["webhook"])
    else:
        STATE["webhook"] = "PUBLIC_URL غير محدد"
        log.warning("PUBLIC_URL غير محدد: لن يتم تسجيل الويب هوك تلقائياً")


def ensure_started():
    global _started
    if _started:
        return
    with _start_lock:
        if not _started:
            _started = True
            threading.Thread(target=startup, daemon=True).start()


# ───────────────────────── معالجة الطلبات ─────────────────────────
def _json(status, obj):
    return status, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _text(status, s):
    return status, "text/plain; charset=utf-8", s.encode("utf-8")


def _key_ok(query, headers):
    if not cfg.CRON_SECRET:
        return False
    k = (query.get("key") or [""])[0] or headers.get("x-cron-key", "")
    return hmac.compare_digest(k, cfg.CRON_SECRET)


def process_http(method, path, query, headers, body):
    """يرجع (status, content_type, bytes)."""
    ensure_started()
    path = path.rstrip("/") or "/"
    if path == "/" and method in ("GET", "HEAD"):
        return _text(200, "OK")

    if path == "/webhook":
        if method != "POST":
            return _text(404, "not found")
        if not hmac.compare_digest(headers.get("x-telegram-bot-api-secret-token", ""), cfg.WEBHOOK_SECRET):
            return _text(403, "forbidden")
        try:
            update = json.loads(body.decode("utf-8"))
        except Exception:
            return _text(400, "bad request")
        try:
            router.handle_update(update)
        except Exception:
            log.exception("unhandled error in handle_update")
        return _text(200, "ok")            # دائماً 200 حتى لا يعيد تلجرام الإرسال

    if path == "/health" and method in ("GET", "HEAD"):
        try:
            db.ping()
            db_state = "ok"
        except Exception as e:
            db_state = "error"
            STATE["db_error"] = str(e)[:300]
        out = {"status": "ok", "db": db_state}
        if _key_ok(query, headers):
            out.update(webhook=STATE["webhook"], schema=STATE["schema"], db_error=STATE["db_error"],
                       registration=cfg.REGISTRATION_MODE, admins=len(cfg.ADMIN_IDS))
        return _json(200, out)

    if path == "/cron/reminders" and method in ("GET", "POST"):
        if not _key_ok(query, headers):
            return _text(403, "forbidden")
        try:
            return _json(200, {"sent": subs.run_reminders()})
        except Exception as e:
            log.exception("reminders failed")
            return _json(500, {"error": str(e)[:200]})

    return _text(404, "not found")


# ───────────────────────── خادم http.server ─────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ShopBot"

    def _do(self, method):
        u = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 1_000_000:
            status, ctype, data = _text(413, "too large")
        else:
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, ctype, data = process_http(method, u.path, parse_qs(u.query), headers, body)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        self._do("GET")

    def do_HEAD(self):
        self._do("HEAD")

    def do_POST(self):
        self._do("POST")

    def log_message(self, fmt, *args):  # لا نطبع الروابط (قد تحتوي مفاتيح)
        log.debug("http: " + fmt, *args)


def run():
    ensure_started()
    srv = ThreadingHTTPServer(("0.0.0.0", cfg.PORT), Handler)
    srv.daemon_threads = True
    log.info("listening on 0.0.0.0:%s", cfg.PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ───────────────────────── WSGI (اختياري: gunicorn app:application) ─────────────────────────
def application(environ, start_response):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(length) if 0 < length <= 1_000_000 else b""
    headers = {}
    for k, v in environ.items():
        if k.startswith("HTTP_"):
            headers[k[5:].replace("_", "-").lower()] = v
    status, ctype, data = process_http(environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO", "/"),
                                       parse_qs(environ.get("QUERY_STRING", "")), headers, body)
    start_response(STATUS_LINES.get(status, "%d" % status),
                   [("Content-Type", ctype), ("Content-Length", str(len(data)))])
    return [data]
'''

# ════════════════════ app.py ════════════════════
SOURCES['app'] = r'''"""نقطة التشغيل:  python app.py     (أو WSGI:  gunicorn app:application)"""
import logging

from config import cfg

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from server import application, run  # noqa: E402,F401

if __name__ == "__main__":
    run()
'''


class _Loader(importlib.abc.Loader):
    def __init__(self, name):
        self.name = name

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        code = compile(SOURCES[self.name], self.name + ".py", "exec", dont_inherit=True)
        exec(code, module.__dict__)


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if path is None and fullname in SOURCES:
            return importlib.util.spec_from_loader(fullname, _Loader(fullname))
        return None


sys.meta_path.insert(0, _Finder())


def main():
    import app
    app.run()


def __getattr__(name):          # لـ gunicorn:  gunicorn bot:application
    if name == "application":
        import server
        return server.application
    raise AttributeError(name)


if __name__ == "__main__":
    main()
