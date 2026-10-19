# -*- coding: utf-8 -*-
"""بوت تلجرام (Webhook) — النسخة النهائية الموحّدة مع كل الإضافات."""
import importlib.abc
import importlib.util
import sys

SOURCES = {}

# ════════════════════ config.py ════════════════════
SOURCES['config'] = r'''"""إعدادات البوت — كلها تُقرأ من متغيرات البيئة."""
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
        self.ADMIN_IDS = _ids("ADMIN_IDS")
        self.CRON_SECRET = _s("CRON_SECRET")

        # ── قاعدة البيانات ──
        self.DB_PATH = _s("DB_PATH", "shop.db")

        # ── الاشتراكات ──
        self.TRIAL_MONTHS = max(1, _i("TRIAL_MONTHS", 1))
        self.REGISTRATION_MODE = _s("REGISTRATION_MODE", "first_only").lower()
        self.HASH_PASSWORDS = _s("HASH_PASSWORDS", "1") != "0"
        self.EMAIL_SUFFIX = os.environ.get("EMAIL_SUFFIX", ".com").strip()
        self.SUB_PRICE_UNIT = _s("SUB_PRICE_UNIT", "ريال")
        self.PAY_CONTACT_NAME = _s("PAY_CONTACT_NAME", "المهندس/ محمد")
        self.PAY_CONTACT_PHONE = _s("PAY_CONTACT_PHONE", "785068462")
        self.PAY_TRANSFER_NUMBER = _s("PAY_TRANSFER_NUMBER", "738439579")

        # ── التواصل / الدعم (يظهر قبل التسجيل وبعده) ──
        self.SUPPORT_PHONE_1 = _s("SUPPORT_PHONE_1", "738439579")
        self.SUPPORT_PHONE_2 = _s("SUPPORT_PHONE_2", "785068462")
        self.SUPPORT_COUNTRY_CODE = _s("SUPPORT_COUNTRY_CODE", "967")
        self.SUPPORT_INSTAGRAM = _s("SUPPORT_INSTAGRAM", "")
        self.SUPPORT_MESSENGER = _s("SUPPORT_MESSENGER", "")
        self.SUPPORT_WHATSAPP_MSG = _s("SUPPORT_WHATSAPP_MSG", "مرحباً، أريد الاستفسار عن النظام")

        # ── عام ──
        self.MAX_PHONE = _i("MAX_PHONE", 2147483647)
        self.LOG_LEVEL = _s("LOG_LEVEL", "INFO").upper()


cfg = Config()
'''

# ════════════════════ db.py ════════════════════
SOURCES['db'] = r'''"""الاتصال بقاعدة SQLite مع مترجم SQL يحاكي Oracle."""
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
FLAGS = {"network_manual_id": True}


def get_conn():
    if not hasattr(_local, "conn"):
        conn = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.create_function("NVL", 2, lambda a, b: b if a is None else a)
        conn.create_function("CEIL", 1, lambda x: math.ceil(x) if x is not None else None)
        conn.execute("CREATE TABLE IF NOT EXISTS dual (dummy VARCHAR(1))")
        if not conn.execute("SELECT 1 FROM dual").fetchone():
            conn.execute("INSERT INTO dual (dummy) VALUES ('X')")
        _local.conn = conn
    return _local.conn


def translate_sql(sql):
    def page_repl(m):
        inner = m.group(1)
        upper = int(m.group(2))
        lower = int(m.group(3))
        return f"SELECT * FROM ({inner}) LIMIT {upper - lower} OFFSET {lower}"
    sql = re.sub(r"(?i)SELECT \* FROM \(SELECT q\.\*, ROWNUM AS rn__ FROM \((.*?)\) q WHERE ROWNUM <= (\d+)\) WHERE rn__ > (\d+)", page_repl, sql, flags=re.DOTALL)
    sql = re.sub(r"(?i)\s*WHERE\s+ROWNUM\s*<=\s*(\d+)", r" LIMIT \1", sql)
    sql = re.sub(r"(?i)TRUNC\((SYSDATE)\s*,\s*'MM'\)", r"date('now', 'localtime', 'start of month')", sql)
    sql = re.sub(r"(?i)TRUNC\(([^,]+?)\s*,\s*'MM'\)", r"date(\1, 'start of month')", sql)
    sql = re.sub(r"(?i)TRUNC\(SYSDATE\)", r"date('now', 'localtime')", sql)
    sql = re.sub(r"(?i)TRUNC\(([^,)]+?)\)", r"date(\1)", sql)
    sql = re.sub(r"(?i)\(([^()]+)\s*-\s*SYSDATE\)", r"(julianday(\1) - julianday('now', 'localtime'))", sql)
    sql = re.sub(r"(?i)SYSDATE\s*-\s*(\d+)", r"datetime('now', 'localtime', '-\1 days')", sql)
    sql = re.sub(r"(?i)SYSDATE\s*\+\s*(\d+)", r"datetime('now', 'localtime', '+\1 days')", sql)
    sql = re.sub(r"(?i)SYSDATE\s*\+\s*(\d+)\s*/\s*1440", r"datetime('now', 'localtime', '+\1 minutes')", sql)
    sql = re.sub(r"(?i)SYSDATE\s*\+\s*(\d+)\s*/\s*24", r"datetime('now', 'localtime', '+\1 hours')", sql)
    sql = re.sub(r"(?i)\bSYSDATE\b", "datetime('now', 'localtime')", sql)
    sql = re.sub(r"(?i)\bSYSTIMESTAMP\b", "datetime('now', 'localtime')", sql)
    sql = re.sub(r"(?i)bot_audit_seq\.NEXTVAL", "NULL", sql)
    sql = re.sub(r"(?i)network_sales_seq\.NEXTVAL", "NULL", sql)
    sql = re.sub(r"(?i)\s+FOR\s+UPDATE\b", "", sql)
    sql = re.sub(r"(?i)ADD_MONTHS\(([^,]+),\s*([^)]+)\)", r"date(\1, '+' || \2 || ' months')", sql)
    return sql


class Tx:
    def __init__(self, conn):
        self.conn = conn

    def _cur(self, sql, p):
        cur = self.conn.cursor()
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


def ensure_schema():
    report = {"missing_tables": [], "created": [], "altered": [], "errors": []}
    try:
        tables = [
            ("bot_users", """CREATE TABLE IF NOT EXISTS bot_users (
                telegram_id INTEGER PRIMARY KEY, client_num INTEGER, state VARCHAR(60), state_data TEXT,
                fail_count INTEGER DEFAULT 0 NOT NULL, locked_until DATETIME, first_name VARCHAR(100),
                username VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            ("bot_user_accounts", """CREATE TABLE IF NOT EXISTS bot_user_accounts (
                telegram_id INTEGER NOT NULL, client_num INTEGER NOT NULL,
                added_by INTEGER, added_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (telegram_id, client_num))"""),
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
            ("exchange_rates", """CREATE TABLE IF NOT EXISTS exchange_rates (id INTEGER PRIMARY KEY, usd_price NUMERIC DEFAULT 0, sar_price NUMERIC DEFAULT 0)"""),
            ("personal_expenses", """CREATE TABLE IF NOT EXISTS personal_expenses (
                expense_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER NOT NULL,
                category VARCHAR(50) NOT NULL, amount NUMERIC NOT NULL DEFAULT 0,
                details VARCHAR(300), created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            ("personal_income", """CREATE TABLE IF NOT EXISTS personal_income (
                income_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER NOT NULL,
                source VARCHAR(100) NOT NULL, amount NUMERIC NOT NULL DEFAULT 0,
                period VARCHAR(20) NOT NULL DEFAULT 'daily',
                notes VARCHAR(300), created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            ("personal_debts", """CREATE TABLE IF NOT EXISTS personal_debts (
                pdebt_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER NOT NULL,
                direction VARCHAR(10) NOT NULL, person_name VARCHAR(100) NOT NULL, person_phone VARCHAR(30) NOT NULL,
                amount NUMERIC NOT NULL DEFAULT 0, paid_amount NUMERIC NOT NULL DEFAULT 0,
                reason VARCHAR(300), created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                last_update DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(client_num, direction, person_name, person_phone))"""),
            ("personal_debt_payments", """CREATE TABLE IF NOT EXISTS personal_debt_payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT, pdebt_id INTEGER NOT NULL,
                client_num INTEGER NOT NULL, amount NUMERIC NOT NULL, note VARCHAR(200),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            ("personal_notes", """CREATE TABLE IF NOT EXISTS personal_notes (
                note_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER NOT NULL,
                title VARCHAR(200) NOT NULL, content VARCHAR(2000),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            ("personal_goals", """CREATE TABLE IF NOT EXISTS personal_goals (
                goal_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL, target_amount NUMERIC NOT NULL DEFAULT 0,
                saved_amount NUMERIC NOT NULL DEFAULT 0, notes VARCHAR(300),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
            ("personal_obligations", """CREATE TABLE IF NOT EXISTS personal_obligations (
                obligation_id INTEGER PRIMARY KEY AUTOINCREMENT, client_num INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL, amount NUMERIC NOT NULL DEFAULT 0,
                due_day INTEGER DEFAULT 1, is_paid_this_month INTEGER DEFAULT 0,
                last_paid_at DATETIME, notes VARCHAR(300),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"""),
        ]
        for name, sql in tables:
            run(sql)
            report["created"].append(name)
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
    global _last_error
    _last_error = ""
    try:
        if files:
            r = _session.post(_url(method), data=params, files=files, timeout=60)
        else:
            r = _session.post(_url(method), json=params, timeout=30)
        data = r.json()
    except Exception as e:
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
        while len(line) > size:
            if cur:
                out.append(cur); cur = ""
            out.append(line[:size]); line = line[size:]
        if len(cur) + len(line) + 1 > size:
            out.append(cur); cur = line
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
        ("contact", "تواصل مع الإدارة"),
        ("help", "مساعدة"),
    ]
    return call("setMyCommands",
                commands=[{"command": c, "description": d} for c, d in cmds])
'''

# ════════════════════ core.py ════════════════════
SOURCES['core'] = r'''"""أدوات مشتركة: الجلسة (Ctx)، التنسيق، التحقق، كلمات المرور، ومسجّل المعالجات."""
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

LIKE_ESC = " ESCAPE '\\'"
MAX_AMOUNT = 99_999_999.0


def esc(s):
    return html.escape("" if s is None else str(s), quote=False)


_DIGITS = str.maketrans({
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٫": ".", "٬": ",", "،": ",",
})


def norm(s):
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
    s = re.sub(r"\s+", " ", (s or "")).strip()
    if not s:
        return None
    n = len(s.encode("utf-8")) if as_bytes else len(s)
    return None if n > max_len else s


def fit_bytes(s, n=100):
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
        if isinstance(d, str):
            return d
        return d.strftime("%Y-%m-%d %I:%M ") + ("ص" if d.hour < 12 else "م")
    except Exception:
        return str(d)


def fmt_date(d):
    if not d:
        return "-"
    try:
        if isinstance(d, str):
            return d.split(" ")[0] if " " in d else d
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


_ITER = 120_000


def hash_password(pw):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _ITER)
    return "pbkdf2$%d$%s$%s" % (_ITER, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def check_password(stored, pw):
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


CLIENT_SQL = (
    "SELECT num, name, email, subscription_months, subscription_duration, money, start_date, "
    "expiry_date, (julianday(expiry_date) - julianday('now', 'localtime')) AS days_left, "
    "is_active, account_type, shop_name, "
    "activity_type, location, shop_location, currency FROM clients_table WHERE num = :p_num")


def fetch_client(num):
    return db.one(CLIENT_SQL, p_num=num)


def user_accounts(tg_id):
    return db.rows(
        "SELECT bua.client_num, c.name, c.account_type, c.is_active, c.expiry_date, "
        "(julianday(c.expiry_date) - julianday('now','localtime')) AS days_left, "
        "c.shop_name FROM bot_user_accounts bua "
        "JOIN clients_table c ON c.num = bua.client_num "
        "WHERE bua.telegram_id = :t ORDER BY bua.added_at", t=tg_id)


def link_account(tg_id, client_num, added_by=None):
    n = db.val("SELECT COUNT(*) FROM bot_user_accounts WHERE telegram_id = :t AND client_num = :c",
               0, t=tg_id, c=client_num)
    if not n:
        db.run("INSERT INTO bot_user_accounts (telegram_id, client_num, added_by) "
               "VALUES (:t, :c, :a)", t=tg_id, c=client_num, a=added_by)
    db.run("UPDATE bot_users SET client_num = :c WHERE telegram_id = :t", c=client_num, t=tg_id)


def active_account(tg_id):
    return db.val("SELECT client_num FROM bot_users WHERE telegram_id = :t", None, t=tg_id)


def switch_account(tg_id, client_num):
    owns = db.val("SELECT COUNT(*) FROM bot_user_accounts WHERE telegram_id = :t AND client_num = :c",
                  0, t=tg_id, c=client_num)
    if not owns:
        return False
    db.run("UPDATE bot_users SET client_num = :c, state = NULL, state_data = NULL WHERE telegram_id = :t",
           c=client_num, t=tg_id)
    return True


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
        self.client = None
        self.sub = None
        self.args = []
        self.sess = {"state": None, "data": {}, "client_num": None,
                     "fail_count": 0, "locked_until": None}

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
        try:
            payload = json.dumps(self.sess["data"], ensure_ascii=False, separators=(",", ":"))
        except Exception:
            payload = "{}"
        if len(payload.encode("utf-8")) > 3900:
            self.sess["data"] = {}
            payload = "{}"
        db.run("UPDATE bot_users SET state = :p_s, state_data = :p_d, last_seen = SYSDATE "
               "WHERE telegram_id = :p_t", p_s=self.sess["state"], p_d=payload, p_t=self.user_id)

    def go(self, state, **data):
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

    def answer(self, text=None, alert=False):
        if self.is_cb and self.cb_id:
            tg.answer_cb(self.cb_id, text, alert)

    def send(self, text, markup=None):
        return tg.send(self.chat_id, text, markup)

    def reply(self, text, markup=None):
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

# ════════════════════ support.py (جديد) ════════════════════
SOURCES['support'] = r'''"""قسم التواصل بنا: هاتف + واتساب + إنستغرام + ماسنجر. يظهر قبل التسجيل وبعده وللحسابات المنتهية."""
from __future__ import annotations
from urllib.parse import quote
import core
from config import cfg
from core import BACK_HOME, esc, on_cb, kb


def _full_phone(num):
    n = (num or "").strip().lstrip("+")
    if n.startswith(cfg.SUPPORT_COUNTRY_CODE):
        return n
    return cfg.SUPPORT_COUNTRY_CODE + n


def _url_kb(*rows):
    out = []
    for row in rows:
        r = []
        for item in row:
            if item is None:
                continue
            t, action = item[0], item[1]
            if action.startswith(("https://", "http://", "tg://", "tel:")):
                r.append({"text": t, "url": action})
            else:
                r.append({"text": t, "callback_data": action})
        if r:
            out.append(r)
    return {"inline_keyboard": out}


def support_home(ctx, note=None):
    p1 = cfg.SUPPORT_PHONE_1
    p2 = cfg.SUPPORT_PHONE_2
    full1 = _full_phone(p1)
    full2 = _full_phone(p2)
    wa_msg = quote(cfg.SUPPORT_WHATSAPP_MSG)

    text = (("📞 <b>تواصل معنا</b>\n" if not note else note + "\n\n📞 <b>تواصل معنا</b>\n")
            + "\nنحن هنا لمساعدتك في أي وقت.\n\n"
            + f"<b>الهاتف الأول:</b> {esc(p1)}\n"
            + f"<b>الهاتف الثاني:</b> {esc(p2)}\n\n"
            + "💡 اختر قناة التواصل المناسبة لك:")
    rows = [
        [("💬 واتساب 1", f"https://wa.me/{full1}?text={wa_msg}"),
         ("💬 واتساب 2", f"https://wa.me/{full2}?text={wa_msg}")],
    ]
    if cfg.SUPPORT_INSTAGRAM:
        insta = cfg.SUPPORT_INSTAGRAM.lstrip("@").strip()
        rows.append([("📸 إنستغرام", f"https://instagram.com/{insta}")])
    if cfg.SUPPORT_MESSENGER:
        m = cfg.SUPPORT_MESSENGER.strip()
        m_url = m if m.startswith(("http://", "https://")) else f"https://m.me/{m}"
        rows.append([("💬 ماسنجر", m_url)])
    rows.append([("📞 اتصال 1", f"tel:+{full1}"), ("📞 اتصال 2", f"tel:+{full2}")])
    rows.append([BACK_HOME])
    ctx.reply(text, _url_kb(*rows))


@on_cb("support")
def cb_support(ctx):
    support_home(ctx)
'''

# ════════════════════ menus.py ════════════════════
SOURCES['menus'] = r'''"""القائمة الرئيسية."""
from __future__ import annotations
import core
from core import kb, esc, on_cb


def sub_line(ctx):
    s = ctx.sub or {}
    if s.get("days") is None:
        return ""
    d = int(s["days"])
    line = "⏳ متبقي من اشتراكك: <b>%s</b> يوم" % d
    if d <= 7:
        line += "\n⚠️ <b>تنبيه:</b> اشتراكك على وشك الانتهاء، جدّده من زر ⭐ اشتراكي"
    return line


def _has_multi(ctx):
    n = core.db.val("SELECT COUNT(*) FROM bot_user_accounts WHERE telegram_id = :t", 0, t=ctx.user_id)
    return (n or 0) > 1


def home(ctx, note=None):
    ctx.reset()
    c = ctx.client
    if not c:
        ctx.send("أرسل /start للدخول.")
        return
    acc = (c.get("account_type") or "").strip()
    if not acc:
        from accounts import ask_account_type
        ask_account_type(ctx)
        return
    title = esc(c.get("shop_name") or c.get("name") or "")
    lines = []
    if note:
        lines.append(note); lines.append("")
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
    else:
        rows = [
            [("💸 المصاريف اليومية", "per:exp")],
            [("💰 الدخل والميزانية", "per:inc")],
            [("💼 محفظتي الصافية", "per:wallet")],
            [("🤝 الديون الشخصية (لي / عليّ)", "per:debt")],
            [("📝 المذكرات والمفكرة", "per:note")],
            [("🎯 حصالة الأهداف والادخار", "per:goal")],
            [("🔔 الالتزامات الشهرية", "per:obl")],
            [("📊 التقرير الشخصي الشامل", "per:report")],
            [("⭐ اشتراكي", "sub:home"), ("🏪 حسابي", "acct:info")],
        ]
    if _has_multi(ctx):
        rows.append([("🔄 تبديل الحساب", "acct:switch")])
    rows.append([("📞 تواصل معنا", "support:home")])
    if ctx.is_admin:
        rows.append([("🛡 لوحة الإدارة الشاملة", "adm:home")])
    rows.append([("🚪 تسجيل الخروج", "acct:out")])
    ctx.reply("\n".join(lines), kb(*rows))


@on_cb("m")
def cb_m(ctx):
    home(ctx)
'''

# ════════════════════ accounts.py ════════════════════
SOURCES['accounts'] = r'''"""الحسابات: التسجيل (مرة واحدة فقط)، الدخول، النوع، الخروج، تبديل الحساب."""
from __future__ import annotations
import logging
import core, db, menus, subs
from config import cfg
from core import (BACK_HOME, clean_text, duration_label, esc, fetch_client, kb, on_cb, on_state,
                  parse_int, store_password, check_password)
log = logging.getLogger("accounts")

COUNTRIES = ["اليمن", "السعودية", "عمان", "مصر", "الامارات", "قطر",
             "البحرين", "الكويت", "العراق", "سوريا", "الاردن", "السودان"]
OTHER_COUNTRY = "دولة اخرى"
CURRENCIES = {1: "الريال اليمني", 2: "الريال السعودي", 3: "الدولار"}
MAX_NUM = 2147483647


def can_register(ctx):
    mode = cfg.REGISTRATION_MODE
    if mode == "closed":
        return False, "التسجيل الذاتي مغلق حالياً. إذا كان لديك حساب اضغط «تسجيل الدخول»."
    if db.val("SELECT COUNT(*) FROM bot_audit_log WHERE telegram_id = :p_t AND action = 'REGISTER'",
              0, p_t=ctx.user_id):
        return False, "سبق أن أنشأت حساباً من هذا الحساب في تلجرام. اضغط «تسجيل الدخول»."
    if db.val("SELECT COUNT(*) FROM bot_user_accounts WHERE telegram_id = :p_t", 0, p_t=ctx.user_id):
        return False, "لديك حساب مرتبط بالفعل من قبل الإدارة. اضغط «تسجيل الدخول»."
    if mode != "open":
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
    rows.append([("📞 تواصل معنا", "support:home")])
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
            ctx.reply(esc(why), kb([("🔐 تسجيل الدخول", "auth:login")], [("📞 تواصل معنا", "support:home")]))
            return
        ctx.go("reg:name")
        ctx.reply("أدخل اسمك:", kb([("❌ إلغاء", "auth:cancel")]))
    else:
        start(ctx)


def is_locked(ctx):
    mins = db.val("SELECT CEIL((julianday(locked_until) - julianday('now', 'localtime')) * 1440) "
                  "FROM bot_users WHERE telegram_id = :p_t AND locked_until > datetime('now', 'localtime')",
                  0, p_t=ctx.user_id)
    if mins and float(mins) > 0:
        ctx.send("⛔ تم إيقاف المحاولات مؤقتاً بسبب أخطاء متكررة. حاول بعد %s دقيقة." % int(mins))
        return True
    return False


def register_failure(ctx):
    n = (ctx.sess.get("fail_count") or 0) + 1
    if n >= 5:
        db.run("UPDATE bot_users SET fail_count = 0, locked_until = datetime('now', 'localtime', '+15 minutes') "
               "WHERE telegram_id = :p_t", p_t=ctx.user_id)
    else:
        db.run("UPDATE bot_users SET fail_count = :p_n WHERE telegram_id = :p_t", p_n=n, p_t=ctx.user_id)


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
                 kb([("🔁 حاول مرة أخرى", "auth:login")], [("📞 تواصل معنا", "support:home")]))
        return
    core.link_account(ctx.user_id, num)
    ctx.sess["client_num"] = num
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
        msg += "\nمتبقي من اشتراكك: %s يوم." % int(ctx.sub["days"])
    ctx.send(msg)
    menus.home(ctx)


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
        if "UNIQUE" in str(e) or "ORA-00001" in str(e):
            ctx.reset()
            ctx.send("❌ الرقم أو الايميل مستخدم من قبل. ابدأ من جديد:",
                     kb([("🆕 إنشاء حساب جديد", "auth:reg")], [("📞 تواصل معنا", "support:home")]))
            return
        raise
    core.audit("REGISTER", ctx, client_num=d["num"], details="trial=%s" % months)
    num = d["num"]
    core.link_account(ctx.user_id, num)
    ctx.sess["client_num"] = num
    ctx.client = fetch_client(num)
    ctx.sub = subs.status(ctx.client)
    ctx.reset()
    ctx.send("✅ تم إنشاء الحساب بنجاح وتفعيل الشهر المجاني!\nتم تسجيل دخولك تلقائياً.")
    menus.home(ctx)


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


@on_cb("acct")
def cb_acct(ctx):
    a = ctx.args[0] if ctx.args else ""
    if a == "info":
        info(ctx)
    elif a == "out":
        logout(ctx)
    elif a == "switch":
        switch_list(ctx)
    elif a == "do" and len(a) > 1 and a[1].isdigit():
        do_switch(ctx, int(a[1]))


def switch_list(ctx):
    rows = core.user_accounts(ctx.user_id)
    if len(rows) <= 1:
        ctx.reply("لديك حساب واحد فقط.", kb([BACK_HOME]))
        return
    lines = ["🔄 <b>اختر الحساب:</b>", ""]
    btns = []
    active = core.active_account(ctx.user_id)
    for r in rows:
        mark = " ✅" if int(r["client_num"]) == int(active or 0) else ""
        dl = r.get("days_left")
        status = "⛔" if (r.get("is_active") is not None and int(r["is_active"]) == 0) else (
            "❌" if (dl is not None and dl < 0) else "✅")
        lines.append("%s <b>%s</b> (رقم %s)" % (status, esc(r["name"]), r["client_num"]))
        btns.append([(mark + "👤 %s (رقم %s)" % (r["name"][:20], r["client_num"]),
                      "acct:do:%s" % r["client_num"])])
    btns.append([("📞 تواصل معنا", "support:home")])
    btns.append([BACK_HOME])
    ctx.reply("\n".join(lines), kb(*btns))


def do_switch(ctx, num):
    if not core.switch_account(ctx.user_id, num):
        ctx.reply("⚠️ هذا الحساب غير مرتبط بك.", kb([("📞 تواصل معنا", "support:home"), BACK_HOME]))
        return
    ctx.sess["client_num"] = num
    ctx.client = fetch_client(num)
    ctx.sub = subs.status(ctx.client)
    core.audit("ACCOUNT_SWITCH", ctx, client_num=num)
    if not ctx.client:
        return start(ctx, fresh=True)
    if not ctx.sub["ok"]:
        return subs.show_expired(ctx)
    ctx.send("✅ تم التبديل إلى: <b>%s</b> (رقم %s)" % (esc(ctx.client.get("name")), num))
    menus.home(ctx)


def info(ctx):
    c = ctx.client
    acc = (c.get("account_type") or "").strip()
    lines = ["🏪 <b>حسابي</b>", "",
             "الاسم: %s" % esc(c.get("name")),
             "رقم العميل: %s" % c.get("num"),
             "الايميل: %s" % esc(c.get("email")),
             "نوع الحساب: %s" % esc(acc or "غير محدد")]
    if acc == "تجاري":
        lines += ["", "<b>بيانات المحل</b>",
                  "اسم المحل: %s" % esc(c.get("shop_name")),
                  "النشاط: %s" % esc(c.get("activity_type")),
                  "الموقع: %s" % esc(c.get("location")),
                  "الدولة: %s" % esc((c.get("shop_location") or "").rstrip(":")),
                  "العملة: %s" % esc((c.get("currency") or "").rstrip(":"))]
    lines += ["", "<b>الاشتراك</b>", "ينتهي في: %s" % core.fmt_date(c.get("expiry_date"))]
    s = ctx.sub or {}
    if s.get("days") is not None:
        lines.append("المتبقي: %s يوم" % int(s["days"]))
    rows = [[("⭐ اشتراكي", "sub:home")]]
    if core.db.val("SELECT COUNT(*) FROM bot_user_accounts WHERE telegram_id = :t", 0, t=ctx.user_id) > 1:
        rows.append([("🔄 تبديل الحساب", "acct:switch")])
    rows.append([("📞 تواصل معنا", "support:home")])
    rows.append([BACK_HOME])
    ctx.reply("\n".join(lines), kb(*rows))


def logout(ctx):
    num = (ctx.client or {}).get("num")
    core.audit("LOGOUT", ctx, client_num=num)
    db.run("UPDATE bot_users SET client_num = NULL, state = NULL, state_data = NULL WHERE telegram_id = :t",
           t=ctx.user_id)
    ctx.sess.update(client_num=None, state=None, data={})
    ctx.client = None
    ctx.sub = None
    ctx.reply("... تم تسجيل الخروج بنجاح.")
    start(ctx, fresh=True)
'''

# ════════════════════ subs.py ════════════════════
SOURCES['subs'] = r'''"""الاشتراكات."""
from __future__ import annotations
import logging
import core, db, tg
from config import cfg
from core import (BACK_HOME, duration_label, esc, fmt_date, fmt_num, kb, on_cb, on_state)
log = logging.getLogger("subs")

STATUS_AR = {"PENDING": "⏳ قيد المراجعة", "APPROVED": "✅ تم التفعيل",
             "REJECTED": "❌ مرفوض", "CANCELLED": "🚫 ملغي"}
MAX_TOTAL_MONTHS = 999


def status(client):
    dl = client.get("days_left")
    flag = client.get("is_active")
    blocked = flag is not None and int(flag) == 0
    expired = dl is not None and dl < 0
    return {"ok": (not blocked) and (not expired), "blocked": blocked, "expired": expired,
            "days": None if dl is None else int(dl), "expiry": client.get("expiry_date")}


def month_price():
    return int(db.val("SELECT month_price FROM system_settings WHERE id = 1", 0) or 0)


def pay_text():
    return ("يرجى تحويل المبلغ ثم الاتصال بـ %s على الرقم: <b>%s</b>\n"
            "للتحويل: <b>%s</b>\n"
            "أو إرسال رسالة برقم حسابك ليتم التفعيل فوراً."
            % (esc(cfg.PAY_CONTACT_NAME), esc(cfg.PAY_CONTACT_PHONE), esc(cfg.PAY_TRANSFER_NUMBER)))


def show_expired(ctx):
    s = ctx.sub or {}
    if s.get("blocked"):
        ctx.reply("⛔ <b>حسابك موقوف.</b>\nيرجى التواصل مع الإدارة: <b>%s</b>" % esc(cfg.PAY_CONTACT_PHONE),
                  kb([("📞 تواصل معنا", "support:home")], [("🚪 تسجيل الخروج", "acct:out")]))
        return
    text = ("==================================\n"
            "عذراً، انتهت فترة اشتراكك في النظام.\n"
            "تاريخ الانتهاء: <b>%s</b>\n"
            "يرجى اختيار باقة التجديد المناسبة لك:\n"
            "==================================" % fmt_date(s.get("expiry")))
    ctx.reply(text, kb([("🔄 تجديد الاشتراك", "sub:plans")],
                       [("📜 طلباتي", "sub:list"), ("📞 تواصل معنا", "support:home")],
                       [("🏪 حسابي", "acct:info")],
                       [("🚪 تسجيل الخروج", "acct:out")]))


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
        lines.append("الحالة: ✅ ساري" + (" — متبقي %s يوم" % int(s["days"]) if s.get("days") is not None else ""))
    lines.append("سعر الشهر: %s %s" % (fmt_num(price), cfg.SUB_PRICE_UNIT) if price else "سعر الشهر: يحدده المدير")
    ctx.reply("\n".join(lines), kb([("🔄 تجديد / تمديد الاشتراك", "sub:plans")],
                                   [("📜 طلباتي", "sub:list")],
                                   [("📞 تواصل معنا", "support:home")], [BACK_HOME]))


def plans(ctx):
    price = month_price()
    lines = ["🔄 <b>باقات التجديد</b>", ""]
    if price:
        lines.append("سعر الشهر الواحد: <b>%s</b> %s" % (fmt_num(price), cfg.SUB_PRICE_UNIT))
    else:
        lines.append("⚠️ لم يتم تحديد سعر الاشتراك بعد.")
    lines.append("اختر الباقة:")
    btns = []
    for m in range(1, 13):
        label = duration_label(m)
        btns.append((label + (" • %s" % fmt_num(price * m) if price else ""), "sub:pick:%d" % m))
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([("📞 تواصل معنا", "support:home")])
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
    ctx.reply("\n".join(lines), kb([("✅ أرسل طلب التجديد", "sub:send:%d" % months)],
                                   [("⬅️ الباقات", "sub:plans"), ("📞 تواصل معنا", "support:home")], [BACK_HOME]))


def _pending(num):
    return db.one("SELECT req_id, months, amount FROM bot_sub_requests "
                  "WHERE client_num = :p_c AND status = 'PENDING' ORDER BY req_id DESC", p_c=num)


def send_request(ctx, months):
    if not 1 <= months <= 12:
        return
    c = ctx.client
    pend = _pending(c["num"])
    if pend:
        ctx.reply("لديك طلب تجديد قيد المراجعة رقم <b>#%s</b> (%s).\nألغِه أولاً إذا أردت طلباً جديداً."
                  % (pend["req_id"], duration_label(pend["months"])),
                  kb([("📎 إرسال إشعار التحويل", "sub:proof:%d" % pend["req_id"])],
                     [("🗑 إلغاء الطلب", "sub:cancel:%d" % pend["req_id"])],
                     [("📞 تواصل معنا", "support:home")], [BACK_HOME]))
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
              kb([("📎 إرسال إشعار التحويل", "sub:proof:%d" % rid)],
                 [("📞 تواصل معنا", "support:home")], [BACK_HOME]))
    if not cfg.ADMIN_IDS:
        ctx.send("ℹ️ تواصل مع الإدارة مباشرة على: %s" % esc(cfg.PAY_CONTACT_PHONE))


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
    ctx.reply("\n".join(lines), kb([("🔄 تجديد الاشتراك", "sub:plans")],
                                   [("📞 تواصل معنا", "support:home")], [BACK_HOME]))


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
    ctx.reply("📎 أرسل الآن صورة إشعار التحويل لطلبك <b>#%s</b>:" % rid,
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
        ctx.send("لم يتم تعيين مدير. تواصل مع الإدارة: %s" % esc(cfg.PAY_CONTACT_PHONE))
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
    ctx.send("✅ تم إرسال إشعار التحويل للإدارة.", kb([BACK_HOME]))


def notify_admins_request(ctx, rid, months, amount):
    c = ctx.client
    s = ctx.sub or {}
    now = "منتهي" if s.get("expired") else ("ساري — متبقي %s يوم" % int(s["days"]) if s.get("days") is not None else "ساري")
    text = ("🔔 <b>طلب تجديد اشتراك #%s</b>\nالعميل: %s (رقم: %s)\nالمحل: %s\nالمدة: %s\n"
            "المبلغ: %s %s\nحالة الاشتراك الآن: %s"
            % (rid, esc(c.get("name")), c.get("num"), esc(c.get("shop_name") or "-"),
               duration_label(months), fmt_num(amount), cfg.SUB_PRICE_UNIT, now))
    markup = kb([("✅ تفعيل", "adm:ok:%d" % rid), ("❌ رفض", "adm:no:%d" % rid)])
    for adm in cfg.ADMIN_IDS:
        tg.send(adm, text, markup)


def notify_client(num, text, markup=None):
    for r in db.rows("SELECT telegram_id FROM bot_user_accounts WHERE client_num = :p_c", p_c=num):
        tg.send(int(r["telegram_id"]), text, markup)


def grant(t, num, months, amount):
    c = t.one("SELECT subscription_months, (julianday(expiry_date) - julianday('now', 'localtime')) AS days_left "
              "FROM clients_table WHERE num = :p_n", p_n=num)
    if c is None:
        raise ValueError("العميل غير موجود")
    dl = c.get("days_left")
    if dl is not None and dl < 0:
        total = months
        t.run("UPDATE clients_table SET start_date = SYSDATE, subscription_months = :p_m, "
              "subscription_duration = :p_d, money = :p_a, is_active = 1 WHERE num = :p_n",
              p_m=total, p_d=duration_label(total), p_a=amount, p_n=num)
    else:
        total = int(c.get("subscription_months") or 0) + months
        if total > MAX_TOTAL_MONTHS:
            raise ValueError("إجمالي الأشهر يتجاوز %d" % MAX_TOTAL_MONTHS)
        t.run("UPDATE clients_table SET subscription_months = :p_m, subscription_duration = :p_d, "
              "money = NVL(money, 0) + :p_a, is_active = 1 WHERE num = :p_n",
              p_m=total, p_d=duration_label(total), p_a=amount, p_n=num)
    exp = t.val("SELECT expiry_date FROM clients_table WHERE num = :p_n", None, p_n=num)
    return exp, total


def grant_precise(t, num, minutes=0, hours=0, days=0, months=0, amount=0):
    c = t.one("SELECT expiry_date, subscription_months, "
              "(julianday(expiry_date) - julianday('now', 'localtime')) AS days_left "
              "FROM clients_table WHERE num = :p_n", p_n=num)
    if c is None:
        raise ValueError("العميل غير موجود")
    total_minutes = int(minutes or 0) + int(hours or 0) * 60 + int(days or 0) * 24 * 60
    parts = []
    if total_minutes > 0:
        parts.append("+%d minutes" % total_minutes)
    if int(months or 0) > 0:
        parts.append("+%d months" % int(months))
    if not parts:
        raise ValueError("لم تحدد أي مدة")
    dl = c.get("days_left") or 0
    base_expr = "datetime('now', 'localtime')" if dl < 0 else "expiry_date"
    modifier = ", ".join(parts)
    t.run("UPDATE clients_table SET expiry_date = datetime(%s, '%s'), is_active = 1, "
          "money = NVL(money, 0) + :p_a WHERE num = :p_n" % (base_expr, modifier), p_a=amount, p_n=num)
    new_months = int(c.get("subscription_months") or 0) + int(months or 0)
    if new_months > 0:
        t.run("UPDATE clients_table SET subscription_months = :p_m, subscription_duration = :p_d WHERE num = :p_n",
              p_m=new_months, p_d=duration_label(new_months), p_n=num)
    exp = t.val("SELECT expiry_date FROM clients_table WHERE num = :p_n", None, p_n=num)
    return exp


def approve_request(ctx, rid):
    with db.tx() as t:
        req = t.one("SELECT req_id, client_num, months, amount, status FROM bot_sub_requests "
                    "WHERE req_id = :p_id", p_id=rid)
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
                  % (duration_label(req["months"]), fmt_date(exp)), kb([BACK_HOME]))
    return req, exp


def reject_request(ctx, rid):
    with db.tx() as t:
        req = t.one("SELECT req_id, client_num, months, status FROM bot_sub_requests WHERE req_id = :p_id", p_id=rid)
        if not req:
            return None, "الطلب غير موجود."
        if req["status"] != "PENDING":
            return None, "هذا الطلب تمت معالجته مسبقاً (%s)." % STATUS_AR.get(req["status"], req["status"])
        t.run("UPDATE bot_sub_requests SET status = 'REJECTED', decided_at = SYSDATE, decided_by = :p_by "
              "WHERE req_id = :p_id", p_by=ctx.user_id, p_id=rid)
        core.audit("SUB_REJECTED", ctx, client_num=req["client_num"], details="req=%s" % rid, t=t)
    notify_client(req["client_num"],
                  "❌ تم رفض طلب التجديد #%s.\nللاستفسار: %s" % (rid, esc(cfg.PAY_CONTACT_PHONE)),
                  kb([("🔄 طلب جديد", "sub:plans")], [("📞 تواصل معنا", "support:home")]))
    return req, "ok"


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
    sent = 0
    rows = db.rows("SELECT num, name, expiry_date, (julianday(expiry_date) - julianday('now', 'localtime')) AS days_left "
                   "FROM clients_table WHERE is_active = 1 AND expiry_date IS NOT NULL "
                   "AND expiry_date BETWEEN datetime('now', 'localtime', '-3 days') "
                   "AND datetime('now', 'localtime', '+7 days')")
    for r in rows:
        kind = _kind(r["days_left"])
        if not kind:
            continue
        done = db.val("SELECT COUNT(*) FROM bot_reminder_log WHERE client_num = :p_c "
                      "AND expiry_date = :p_e AND kind = :p_k", 0, p_c=r["num"], p_e=r["expiry_date"], p_k=kind)
        if done:
            continue
        if kind == "EXP":
            text = "⛔ <b>انتهى اشتراكك</b> بتاريخ %s.\nجدّد للاستمرار." % fmt_date(r["expiry_date"])
        else:
            d = max(int(r["days_left"]), 0)
            text = "⏰ <b>تنبيه:</b> ينتهي اشتراكك %s (متبقي %s يوم).\nجدّد الآن." % (fmt_date(r["expiry_date"]), d)
        markup = kb([("🔄 تجديد", "sub:plans")], [("📞 تواصل معنا", "support:home")])
        targets = db.rows("SELECT telegram_id FROM bot_user_accounts WHERE client_num = :p_c", p_c=r["num"])
        for tt in targets:
            if tg.send(int(tt["telegram_id"]), text, markup):
                sent += 1
        db.run("INSERT INTO bot_reminder_log (client_num, expiry_date, kind) VALUES (:p_c, :p_e, :p_k)",
               p_c=r["num"], p_e=r["expiry_date"], p_k=kind)
    return sent
'''

# ════════════════════ pickers.py ════════════════════
SOURCES['pickers'] = r'''"""أدوات البحث والاختيار المشتركة (عملاء ومنتجات)."""
from __future__ import annotations
import db
from config import cfg
from core import (LIKE_ESC, esc, fmt_num, kb, like, on_cb, on_state, parse_int)

CUST = {}
PROD = {}
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
    r = db.one("SELECT NVL(SUM(debt_amount), 0) AS t_debt, NVL(SUM(paid_amount), 0) AS t_paid "
               "FROM shop_debts WHERE customer_phone = :p_ph AND client_num = :p_cn", p_ph=phone, p_cn=cn)
    td, tp = float(r["t_debt"]), float(r["t_paid"])
    return td, tp, td - tp


def _short(s, n=28):
    s = s or ""
    return s if len(s) <= n else s[:n - 1] + "…"


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
        ctx.reply("انتهت الصلاحية. افتح /menu")
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
        ctx.send("انتهت الصلاحية. افتح /menu")
        return
    cn = ctx.client["num"]
    if d.get("cp_by") == "phone":
        ph = parse_int(ctx.text, 0, cfg.MAX_PHONE)
        if ph is None:
            ctx.send("أدخل رقماً صحيحاً:")
            return
        rows = find_customers(cn, phone=ph)
    else:
        q = (ctx.text or "").strip()
        if not q:
            ctx.send("أدخل اسم العميل:")
            return
        rows = find_customers(cn, name=q)
    if not rows:
        ctx.send("⚠️ غير موجود.", kb([("🔁 بحث آخر", "cp:again")], [("❌ إلغاء", back)]))
        return
    if len(rows) == 1:
        CUST[purpose](ctx, {"name": rows[0]["customer_name"], "phone": int(rows[0]["customer_phone"])})
        return
    btns = [[("%s (%s)" % (_short(r["customer_name"]), r["customer_phone"]), "cp:pick:%s" % r["customer_phone"])]
            for r in rows[:LIMIT]]
    btns.append([("🔁 بحث آخر", "cp:again"), ("❌ إلغاء", back)])
    note = "\n(يوجد أكثر من %d نتيجة)" % LIMIT if len(rows) > LIMIT else ""
    ctx.send("اختر العميل:" + note, kb(*btns))


def start_prod_search(ctx, purpose, prompt="أدخل اسم المنتج للبحث:", back="m:home"):
    ctx.go("pp:q", pp_purpose=purpose, pp_back=back)
    ctx.reply(prompt, kb([("❌ إلغاء", back)]))


@on_cb("pp")
def cb_pp(ctx):
    a = ctx.args
    d = ctx.data
    purpose, back = d.get("pp_purpose"), d.get("pp_back") or "m:home"
    if purpose not in PROD:
        ctx.reply("انتهت الصلاحية. افتح /menu")
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
        ctx.send("انتهت الصلاحية. افتح /menu")
        return
    q = (ctx.text or "").strip()
    if not q:
        ctx.send("أدخل اسم المنتج:")
        return
    rows = find_products(q)
    if not rows:
        extra = PROD_EXTRA.get(purpose, [])
        ctx.send("⚠️ غير موجود.", kb(*(extra + [[("🔁 بحث آخر", "pp:again"), ("❌ إلغاء", back)]])))
        return
    if len(rows) == 1:
        PROD[purpose](ctx, rows[0])
        return
    btns = [[("%s • %s • %s حبة" % (_short(r["product_name"], 24), fmt_num(r["price"]), fmt_num(r["quantity"])),
              "pp:pick:%s" % r["product_id"])] for r in rows[:LIMIT]]
    btns.append([("🔁 بحث آخر", "pp:again"), ("❌ إلغاء", back)])
    note = "\n(يوجد أكثر من %d نتيجة)" % LIMIT if len(rows) > LIMIT else ""
    ctx.send("اختر المنتج:" + note, kb(*btns))


PROD_EXTRA = {}
'''

# ════════════════════ shop.py ════════════════════
SOURCES['shop'] = r'''"""العمليات اليومية للمتجر: حاسبة الصرف، الاستيراد، إضافة عميل، المبيعات، الفواتير، تسديد الديون."""
from __future__ import annotations
import logging, time
import core, db
from config import cfg
from core import (BACK_HOME, CANCEL_BTN, MAX_AMOUNT, clean_text, esc, fmt_dt, fmt_num, kb,
                  on_cb, on_state, parse_float, parse_int, unit_of)
from pickers import (PROD_EXTRA, cust_purpose, debt_totals, get_customer, prod_purpose,
                     start_cust_search, start_prod_search)
log = logging.getLogger("shop")


def _unit(ctx): return unit_of(ctx.client)


CALC_OPS = {1: ("من دولار إلى ريال يمني", "دولار", "ريال يمني"),
            2: ("من ريال سعودي إلى ريال يمني", "ريال سعودي", "ريال يمني"),
            3: ("من ريال يمني إلى دولار", "ريال يمني", "دولار"),
            4: ("من ريال يمني إلى ريال سعودي", "ريال يمني", "ريال سعودي"),
            5: ("من دولار إلى ريال سعودي", "دولار", "ريال سعودي"),
            6: ("من ريال سعودي إلى دولار", "ريال سعودي", "دولار")}


def get_rates():
    r = db.one("SELECT usd_price, sar_price FROM exchange_rates WHERE id = 1")
    if not r: return 0.0, 0.0
    return float(r["usd_price"] or 0), float(r["sar_price"] or 0)


def convert(op, amount, usd, sar):
    if op == 1: return amount * usd
    if op == 2: return amount * sar
    if op == 3: return amount / usd
    if op == 4: return amount / sar
    if op == 5: return amount * (usd / sar)
    return amount * (sar / usd)


@on_cb("calc")
def cb_calc(ctx):
    a = ctx.args; act = a[0] if a else "menu"
    usd, sar = get_rates()
    if usd == 0 or sar == 0:
        rows = [[("📞 تواصل معنا", "support:home"), BACK_HOME]]
        if ctx.is_admin: rows.insert(0, [("💱 تحديث أسعار الصرف", "adm:rates")])
        ctx.reply("لا يمكن تشغيل الحاسبة لعدم توفر أسعار الصرف.", kb(*rows)); return
    if act == "op" and len(a) > 1 and a[1].isdigit() and int(a[1]) in CALC_OPS:
        op = int(a[1])
        ctx.go("calc:amt", op=op)
        ctx.reply("%s\nأدخل المبلغ:" % CALC_OPS[op][0], kb([("⬅️ رجوع", "calc:menu")])); return
    ctx.reset()
    lines = ["=== 🧮 حاسبة الصرف ===", "💵 الدولار = %s ريال يمني" % fmt_num(usd),
             "🇸🇦 الريال السعودي = %s ريال يمني" % fmt_num(sar), "", "اختر العملية:"]
    rows = [[(CALC_OPS[i][0], "calc:op:%d" % i)] for i in range(1, 7)]
    rows.append([BACK_HOME])
    ctx.reply("\n".join(lines), kb(*rows))


@on_state("calc:amt")
def st_calc(ctx):
    op = ctx.data.get("op")
    amount = parse_float(ctx.text, 0.0, 1e12)
    if op not in CALC_OPS or amount is None or amount <= 0:
        ctx.send("أدخل مبلغاً صحيحاً:"); return
    usd, sar = get_rates()
    if usd == 0 or sar == 0:
        ctx.reset(); ctx.send("لا يمكن تشغيل الحاسبة."); return
    res = convert(op, amount, usd, sar)
    _, src, dst = CALC_OPS[op]
    ctx.send("🧮 %s %s\n<b>النتيجة: %s %s</b>" % (fmt_num(amount), src, fmt_num(res), dst),
             kb([("🔁 عملية أخرى", "calc:menu")], [BACK_HOME]))


@on_cb("cust")
def cb_cust(ctx):
    if (ctx.args[0] if ctx.args else "") == "add":
        ctx.go("cust:name")
        ctx.reply("--- إضافة عميل جديد ---\nأدخل اسم العميل:", kb([CANCEL_BTN]))


@on_state("cust:name")
def st_cust_name(ctx):
    name = clean_text(ctx.text, 100, True)
    if not name: ctx.send("أدخل اسم العميل:"); return
    ctx.go("cust:phone", c_name=name); ctx.send("أدخل رقم العميل:")


@on_state("cust:phone")
def st_cust_phone(ctx):
    ph = parse_int(ctx.text, 1, cfg.MAX_PHONE)
    if ph is None: ctx.send("أدخل رقماً صحيحاً:"); return
    cn = ctx.client["num"]; name = ctx.data.get("c_name")
    old = db.one("SELECT customer_name, client_num FROM shop_customers WHERE customer_phone = :p_ph", p_ph=ph)
    if old:
        if int(old["client_num"]) == int(cn):
            ctx.send("❌ الرقم مسجل باسم: <b>%s</b>. أدخل رقماً آخر:" % esc(old["customer_name"]))
        else: ctx.send("❌ الرقم مسجل مسبقاً. أدخل رقماً آخر:")
        return
    try:
        db.run("INSERT INTO shop_customers (customer_phone, customer_name, client_num) "
               "VALUES (:p_ph, :p_n, :p_cn)", p_ph=ph, p_n=name, p_cn=cn)
    except Exception as e:
        if "UNIQUE" in str(e) or "ORA-00001" in str(e):
            ctx.send("❌ الرقم مسجل. أدخل رقماً آخر:"); return
        raise
    core.audit("CUSTOMER_ADD", ctx, details="%s %s" % (ph, name))
    ctx.reset()
    ctx.send("✅ تم إضافة العميل: %s — %s" % (esc(name), ph),
             kb([("👤 إضافة عميل آخر", "cust:add")], [BACK_HOME]))


PROD_EXTRA["imp"] = [[("🆕 إضافته كمنتج جديد", "imp:asnew")]]


@on_cb("imp")
def cb_imp(ctx):
    a = ctx.args; act = a[0] if a else "start"
    if act == "start":
        ctx.reset()
        ctx.reply("📦 <b>إضافة منتجات (استيراد)</b>\nهل المنتج موجود؟",
                  kb([("🆕 جديد", "imp:new"), ("📦 موجود", "imp:old")], [BACK_HOME]))
    elif act in ("new", "asnew"):
        ctx.go("imp:newname", i_mode="new", i_pid=None)
        ctx.reply("أدخل اسم المنتج الجديد:", kb([CANCEL_BTN]))
    elif act == "old":
        start_prod_search(ctx, "imp", prompt="ادخل اسم المنتج للبحث:")
    elif act == "p0" and ctx.state == "imp:profit": _after_profit(ctx, 0.0)
    elif act == "pay" and ctx.state == "imp:paid" and len(a) > 1:
        _after_paid(ctx, float(ctx.data.get("i_full") or 0) if a[1] == "full" else 0.0)
    elif act == "ok": save_import(ctx)


@prod_purpose("imp")
def imp_picked(ctx, p):
    ctx.go("imp:merchant", i_mode="old", i_pid=p["product_id"], i_name=p["product_name"])
    ctx.reply("📦 المنتج: <b>%s</b>\nالسعر: %s | المتوفر: %s\n\nأدخل اسم التاجر:"
              % (esc(p["product_name"]), fmt_num(p["price"]), fmt_num(p["quantity"])), kb([CANCEL_BTN]))


@on_state("imp:newname")
def st_imp_newname(ctx):
    name = clean_text(ctx.text, 100, True)
    if not name: ctx.send("أدخل اسم المنتج:"); return
    ex = db.one("SELECT product_id, product_name FROM products_table WHERE LOWER(product_name) = :p_n", p_n=name.lower())
    if ex:
        ctx.go("imp:merchant", i_mode="old", i_pid=ex["product_id"], i_name=ex["product_name"])
        ctx.send("ℹ️ المنتج موجود، سيتم تحديثه.\nأدخل اسم التاجر:", kb([CANCEL_BTN])); return
    ctx.go("imp:merchant", i_mode="new", i_pid=None, i_name=name)
    ctx.send("أدخل اسم التاجر:", kb([CANCEL_BTN]))


@on_state("imp:merchant")
def st_imp_merchant(ctx):
    m = clean_text(ctx.text, 100, True)
    if not m: ctx.send("أدخل اسم التاجر:"); return
    ctx.go("imp:cartons", i_merchant=m); ctx.send("أدخل عدد الكراتين:")


@on_state("imp:cartons")
def st_imp_cartons(ctx):
    v = parse_int(ctx.text, 1, 1_000_000)
    if v is None: ctx.send("أدخل عدداً صحيحاً:"); return
    ctx.go("imp:inside", i_cartons=v); ctx.send("أدخل العدد داخل الكرتون:")


@on_state("imp:inside")
def st_imp_inside(ctx):
    v = parse_int(ctx.text, 1, 100_000)
    if v is None: ctx.send("أدخل عدداً صحيحاً:"); return
    ctx.go("imp:price", i_inside=v); ctx.send("أدخل سعر الكرتون:")


@on_state("imp:price")
def st_imp_price(ctx):
    p = parse_float(ctx.text, 0.0)
    if p is None: ctx.send("أدخل سعراً صحيحاً:"); return
    d = ctx.data
    full = round(d["i_cartons"] * p, 2)
    if full > MAX_AMOUNT: ctx.send("الإجمالي كبير. أعد إدخال السعر:"); return
    cost = round(p / d["i_inside"], 2)
    ctx.go("imp:profit", i_price=p, i_full=full, i_cost=cost)
    u = _unit(ctx)
    ctx.send("[النظام]: إجمالي الفاتورة = <b>%s</b> %s\nتكلفة الحبة = <b>%s</b>\n\nأدخل ربح الحبة (أو 0):"
             % (fmt_num(full), u, fmt_num(cost)),
             kb([("0️⃣ بدون ربح", "imp:p0")], [CANCEL_BTN]))


def _after_profit(ctx, profit):
    d = ctx.data
    single = round(d["i_cost"] + profit, 2)
    if single > MAX_AMOUNT: ctx.send("السعر كبير. أدخل ربحاً أقل:"); return
    ctx.go("imp:paid", i_profit=profit, i_single=single)
    ctx.reply("[النظام]: سعر البيع = <b>%s</b>\n\nأدخل المبلغ المدفوع للتاجر:" % fmt_num(single),
              kb([("💵 دفعت كامل المبلغ", "imp:pay:full"), ("⏳ لم أدفع", "imp:pay:none")], [CANCEL_BTN]))


@on_state("imp:profit")
def st_imp_profit(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None: ctx.send("أدخل مبلغ الربح:"); return
    _after_profit(ctx, v)


def _after_paid(ctx, paid):
    d = ctx.data; full = float(d["i_full"])
    if paid > full + 0.001:
        ctx.send("المبلغ أكبر من الإجمالي (%s). أعد الإدخال:" % fmt_num(full)); return
    paid = round(paid, 2); resid = round(full - paid, 2)
    ctx.go("imp:confirm", i_paid=paid)
    u = _unit(ctx)
    total_qty = d["i_cartons"] * d["i_inside"]
    text = ("🧾 <b>ملخص فاتورة التوريد</b>\nالتاجر: %s\nالمنتج: %s\nالكراتين: %s × %s = %s حبة\n"
            "سعر الكرتون: %s\nالإجمالي: <b>%s</b> %s\nالمدفوع: %s | المتبقي: <b>%s</b>\n"
            "التكلفة: %s | الربح: %s | البيع: <b>%s</b>"
            % (esc(d["i_merchant"]), esc(d["i_name"]), fmt_num(d["i_cartons"]), fmt_num(d["i_inside"]),
               fmt_num(total_qty), fmt_num(d["i_price"]), fmt_num(full), u, fmt_num(paid), fmt_num(resid),
               fmt_num(d["i_cost"]), fmt_num(d["i_profit"]), fmt_num(d["i_single"])))
    ctx.reply(text, kb([("✅ حفظ", "imp:ok")], [CANCEL_BTN]))


@on_state("imp:paid")
def st_imp_paid(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None: ctx.send("أدخل المدفوع:"); return
    _after_paid(ctx, v)


def save_import(ctx):
    d = ctx.data
    need = ["i_mode", "i_name", "i_merchant", "i_cartons", "i_inside", "i_price", "i_full",
            "i_cost", "i_profit", "i_single", "i_paid"]
    if d.get("i_mode") == "old": need.append("i_pid")
    if ctx.state != "imp:confirm" or any(d.get(k) is None for k in need):
        ctx.reply("انتهت الصلاحية. ابدأ من جديد.", kb([("📦 توريد جديد", "imp:start")], [BACK_HOME])); return
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
                t.run("INSERT INTO products_table (product_name, price, selling_price, purchase_price, "
                      "quantity, units_per_carton) VALUES (:p_n, :p_sp, :p_sp, :p_pp, :p_q, :p_u)",
                      p_n=d["i_name"], p_sp=d["i_single"], p_pp=d["i_cost"], p_q=total_qty, p_u=d["i_inside"])
            else:
                n = t.run("UPDATE products_table SET price = :p_sp, selling_price = :p_sp, "
                          "purchase_price = :p_pp, quantity = NVL(quantity, 0) + :p_q, "
                          "units_per_carton = :p_u WHERE product_id = :p_id",
                          p_sp=d["i_single"], p_pp=d["i_cost"], p_q=total_qty, p_u=d["i_inside"], p_id=d["i_pid"])
                if n == 0: raise ValueError("المنتج لم يعد موجوداً")
            core.audit("IMPORT", ctx, details="%s x%s paid=%s" % (d["i_name"], total_qty, d["i_paid"]), t=t)
    except ValueError as e:
        ctx.reset(); ctx.reply("⚠️ %s" % esc(e), kb([("📦 توريد جديد", "imp:start")], [BACK_HOME])); return
    except Exception as e:
        if "UNIQUE" in str(e) or "ORA-00001" in str(e):
            ctx.reset()
            ctx.reply("❌ يوجد منتج بنفس الاسم. ابدأ من جديد.",
                      kb([("📦 توريد جديد", "imp:start")], [BACK_HOME])); return
        raise
    u = _unit(ctx); name, single, mode = d["i_name"], d["i_single"], d["i_mode"]
    ctx.reset()
    ctx.reply("✅ تم حفظ فاتورة التوريد!\n" +
              ("📦 تم إدراج [<b>%s</b>] بسعر %s للحبة." % (esc(name), fmt_num(single))
               if mode == "new" else
               "🔄 تم تحديث [<b>%s</b>] إلى %s %s وأُضيف %s حبة." % (esc(name), fmt_num(single), u, fmt_num(total_qty))),
              kb([("📦 توريد جديد", "imp:start")], [BACK_HOME]))


KIND_LABEL = {"d": "آجلة (دين)", "c": "كاش", "n": "شبكة"}
GENERAL = {"c": "عميل كاش عام", "n": "عميل شبكة عام"}
TABLE = {"c": "cash_sales", "n": "network_sales"}


def _cart(ctx): return ctx.data.setdefault("cart", [])
def _cart_total(cart): return round(sum(float(x.get("total", 0)) for x in cart), 2)


def _cart_summary(cart, u):
    lines = []
    for i, x in enumerate(cart, 1):
        lines.append("%d. %s × %s = %s %s" % (i, esc(x["pname"]), fmt_num(x["qty"]), fmt_num(x["total"]), u))
    return "\n".join(lines)


@on_cb("sale")
def cb_sale(ctx):
    a = ctx.args; act = a[0] if a else "menu"; st = ctx.state
    if act == "menu":
        ctx.reset()
        ctx.reply("--- 🛒 قسم المبيعات ---\nاختر النوع:",
                  kb([("📝 دين", "sale:type:d")], [("💰 كاش", "sale:type:c"), ("💳 شبكة", "sale:type:n")], [BACK_HOME]))
    elif act == "type" and len(a) > 1 and a[1] in KIND_LABEL:
        kind = a[1]
        ctx.reset(); ctx.put(s_type=kind, cart=[], s_cname=None, s_cphone=None)
        if kind == "d": start_cust_search(ctx, "sale", back="sale:menu")
        else:
            ctx.go("sale:cname", s_type=kind)
            ctx.reply("أدخل اسم الزبون (أو تخطي):",
                      kb([("⏭ تخطي", "sale:skip:name")], [("❌ إلغاء", "sale:menu")]))
    elif act == "skip" and len(a) > 1:
        kind = ctx.data.get("s_type")
        if a[1] == "name" and st == "sale:cname" and kind in GENERAL:
            ctx.go("sale:cphone", s_cname=GENERAL[kind])
            ctx.reply("أدخل هاتف الزبون (أو تخطي):",
                      kb([("⏭ تخطي", "sale:skip:phone")], [("❌ إلغاء", "sale:menu")]))
        elif a[1] == "phone" and st == "sale:cphone":
            ctx.put(s_cphone=0); start_prod_search(ctx, "sale", back="sale:menu")
    elif act == "add" and st == "sale:qty": _confirm_add_to_cart(ctx, ctx.data["s_qty"])
    elif act == "neg" and len(a) > 1 and st == "sale:negq":
        if a[1] == "y": _confirm_add_to_cart(ctx, ctx.data["s_qty"])
        else: _back_to_cart(ctx)
    elif act == "more": start_prod_search(ctx, "sale", back="sale:menu", prompt="أدخل اسم المنتج التالي:")
    elif act == "del" and len(a) > 1 and a[1].isdigit():
        idx = int(a[1]); cart = _cart(ctx)
        if 0 <= idx < len(cart): cart.pop(idx); ctx.put(cart=cart)
        _back_to_cart(ctx)
    elif act == "ok": _save_sale(ctx)


@on_state("sale:cname")
def st_sale_cname(ctx):
    name = clean_text(ctx.text, 100, True)
    if not name:
        ctx.send("أدخل اسم الزبون (أو تخطي):", kb([("⏭ تخطي", "sale:skip:name")])); return
    ctx.go("sale:cphone", s_cname=name)
    ctx.send("أدخل هاتف الزبون (أو تخطي):", kb([("⏭ تخطي", "sale:skip:phone")], [("❌ إلغاء", "sale:menu")]))


@on_state("sale:cphone")
def st_sale_cphone(ctx):
    ph = parse_int(ctx.text, 0, 999_999_999_999_999)
    if ph is None:
        ctx.send("أدخل رقماً صحيحاً (أو تخطي):", kb([("⏭ تخطي", "sale:skip:phone")])); return
    ctx.put(s_cphone=ph); start_prod_search(ctx, "sale", back="sale:menu")


@cust_purpose("sale")
def sale_cust_picked(ctx, c):
    ctx.put(s_cname=c["name"], s_cphone=c["phone"])
    start_prod_search(ctx, "sale", back="sale:menu",
                      prompt="👤 العميل: <b>%s</b>\n\nأدخل اسم المنتج للبحث:" % esc(c["name"]))


@prod_purpose("sale")
def sale_prod_picked(ctx, p):
    ctx.go("sale:qty", s_pid=p["product_id"], s_pname=p["product_name"], s_price=float(p["price"]),
           s_stock=int(p["quantity"]), s_cost=float(p["purchase_price"]),
           s_units=int(p["units_per_carton"] or 1))
    ctx.reply("📦 <b>%s</b>\nالسعر: %s %s | المتوفر: %s\n\nأدخل الكمية:"
              % (esc(p["product_name"]), fmt_num(p["price"]), _unit(ctx),
                 core.stock_text(p["quantity"], p["units_per_carton"])),
              kb([("❌ إلغاء", "sale:menu")]))


@on_state("sale:qty")
def st_sale_qty(ctx):
    q = parse_int(ctx.text, 1, 1_000_000)
    if q is None: ctx.send("أدخل كمية صحيحة:"); return
    stock = ctx.data.get("s_stock", 0)
    if q > stock:
        ctx.go("sale:negq", s_qty=q)
        ctx.send("⚠️ الكمية غير متوفرة! (المتبقي: %s)\nهل تريد المواصلة بالسالب؟" % fmt_num(stock),
                 kb([("✅ نعم", "sale:neg:y"), ("❌ لا", "sale:neg:n")])); return
    _confirm_add_to_cart(ctx, q)


def _confirm_add_to_cart(ctx, qty):
    d = ctx.data
    total = round(qty * d["s_price"], 2)
    if total > MAX_AMOUNT:
        ctx.go("sale:qty"); ctx.reply("الإجمالي كبير. أدخل كمية أقل:"); return
    cart = _cart(ctx)
    cart.append({"pid": d["s_pid"], "pname": d["s_pname"], "qty": qty,
                 "price": d["s_price"], "cost": d.get("s_cost", 0), "total": total})
    ctx.put(cart=cart); _back_to_cart(ctx)


def _back_to_cart(ctx):
    d = ctx.data; cart = _cart(ctx); u = _unit(ctx)
    if not cart:
        ctx.go(None); ctx.reply("🛒 السلة فارغة.", kb([("🛒 المبيعات", "sale:menu"), BACK_HOME])); return
    gt = _cart_total(cart)
    lines = ["🛒 <b>سلة المشتريات (%s)</b>" % KIND_LABEL[d["s_type"]],
             "العميل: %s" % esc(d.get("s_cname") or GENERAL.get(d["s_type"], "")), "",
             _cart_summary(cart, u), "", "الإجمالي: <b>%s</b> %s" % (fmt_num(gt), u)]
    btns = []
    for i, x in enumerate(cart):
        btns.append([("🗑 حذف %d) %s" % (i + 1, x["pname"][:20]), "sale:del:%d" % i)])
    btns.append([("➕ إضافة منتج آخر", "sale:more")])
    btns.append([("✅ تأكيد الفاتورة", "sale:ok")])
    btns.append([("❌ إلغاء", "sale:menu")])
    ctx.go(None)
    ctx.reply("\n".join(lines), kb(*btns))


def _new_invoice(t):
    for _ in range(8):
        n = int(time.time() * 1000) % 100000000 or 1
        used = t.val("SELECT COUNT(*) FROM (SELECT invoice_num FROM cash_sales WHERE invoice_num = :p_n "
                     "UNION ALL SELECT invoice_num FROM network_sales WHERE invoice_num = :p_n "
                     "UNION ALL SELECT invoice_num FROM shop_debts WHERE invoice_num = :p_n)", 0, p_n=n)
        if not used: return n
        time.sleep(0.003)
    raise RuntimeError("تعذر توليد رقم فاتورة")


def _save_sale(ctx):
    d = ctx.data; cart = _cart(ctx)
    if not cart or d.get("s_type") not in KIND_LABEL:
        ctx.reply("انتهت الصلاحية.", kb([("🛒 المبيعات", "sale:menu"), BACK_HOME])); return
    kind, cn = d["s_type"], ctx.client["num"]
    cname = core.fit_bytes(d.get("s_cname") or GENERAL.get(kind, ""), 100)
    cphone = int(d.get("s_cphone") or 0)
    try:
        with db.tx() as t:
            inv = _new_invoice(t)
            for item in cart:
                pname = core.fit_bytes(item["pname"], 100); qty = int(item["qty"])
                price = float(item["price"]); total = float(item["total"])
                profit = round((price - float(item.get("cost", 0))) * qty, 2)
                if kind == "d":
                    t.run("INSERT INTO shop_debts (client_num, customer_phone, customer_name, product_name, "
                          "quantity, single_price, debt_amount, invoice_num, debt_date) "
                          "VALUES (:p_cn, :p_ph, :p_cu, :p_pn, :p_q, :p_pr, :p_tot, :p_inv, SYSTIMESTAMP)",
                          p_cn=cn, p_ph=cphone, p_cu=cname, p_pn=pname, p_q=qty, p_pr=price, p_tot=total, p_inv=inv)
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
                          p_q=qty, p_id=item["pid"])
                if n == 0: raise ValueError("المنتج [%s] لم يعد موجوداً" % item["pname"])
            core.audit("SALE_" + kind.upper(), ctx,
                       details="inv=%s items=%s total=%s" % (inv, len(cart), _cart_total(cart)), t=t)
    except ValueError as e:
        ctx.reset(); ctx.reply("⚠️ %s" % esc(e), kb([("🛒 المبيعات", "sale:menu"), BACK_HOME])); return
    gt = _cart_total(cart); u = _unit(ctx); ctx.reset()
    head = ("✅ تم تسجيل الدين! رقم الفاتورة: <b>%s</b>" if kind == "d"
            else "✅ تم الحفظ! رقم الفاتورة: <b>%s</b>") % inv
    lines = ["====================================", "          فاتورة مبيعات             ",
             "====================================", "رقم الفاتورة: %s" % inv,
             "نوع الفاتورة: %s" % KIND_LABEL[kind], "اسم العميل: %s" % cname,
             "------------------------------------"]
    for item in cart:
        lines.append("%s | %s × %s = %s %s" % (core.fit_bytes(item["pname"], 30), fmt_num(item["qty"]),
                                                fmt_num(item["price"]), fmt_num(item["total"]), u))
    lines += ["------------------------------------", "الإجمالي: <b>%s</b> %s" % (fmt_num(gt), u),
              "====================================", "        شكراً لتسوقكم معنا!         "]
    ctx.reply(head + "\n\n" + "\n".join(esc(x) for x in lines),
              kb([("🖨️ ملف الفاتورة", "inv:%s:%s" % (kind, inv))],
                 [("🛒 عملية جديدة", "sale:menu"), BACK_HOME]))


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
    if len(a) < 2 or a[0] not in INV_SQL or not a[1].isdigit(): return
    kind, num = a[0], int(a[1])
    rows = db.rows(INV_SQL[kind], p_n=num, p_cn=ctx.client["num"])
    if not rows:
        ctx.send("⚠️ لم يتم العثور على الفاتورة."); return
    u = unit_of(ctx.client); shop = (ctx.client or {}).get("shop_name")
    L = ["====================================", "          فاتورة مبيعات             ",
         "===================================="]
    if shop: L.append("المحل: %s" % shop)
    r0 = rows[0]
    L += ["رقم الفاتورة: %s" % num, "نوع الفاتورة: %s" % KIND_LABEL[kind],
          "اسم العميل: %s" % r0["customer_name"], "التاريخ: %s" % fmt_dt(r0["dt"]),
          "------------------------------------"]
    total = 0.0
    for r in rows:
        L.append("%s | %s × %s = %s %s" % (core.fit_bytes(r["product_name"], 30),
                                            fmt_num(r["quantity"]), fmt_num(r["single_price"]),
                                            fmt_num(r["total"]), u))
        total += float(r["total"])
    L += ["------------------------------------", "الإجمالي: %s %s" % (fmt_num(total), u),
          "====================================", "        شكراً لتسوقكم معنا!         "]
    ctx.doc("Invoice_%s.txt" % num, "\n".join(L), caption="🖨️ فاتورة رقم %s" % num)


def archive_and_delete_debts(t, cn, phone, reason):
    t.run("INSERT INTO bot_debts_archive (debt_id, client_num, customer_phone, customer_name, product_name, "
          "quantity, single_price, debt_amount, paid_amount, debt_date, invoice_num, reason) "
          "SELECT debt_id, client_num, customer_phone, customer_name, product_name, quantity, single_price, "
          "debt_amount, paid_amount, debt_date, invoice_num, :p_r FROM shop_debts "
          "WHERE customer_phone = :p_ph AND client_num = :p_cn", p_r=reason, p_ph=phone, p_cn=cn)
    return t.run("DELETE FROM shop_debts WHERE customer_phone = :p_ph AND client_num = :p_cn",
                 p_ph=phone, p_cn=cn)


@on_cb("pay")
def cb_pay(ctx):
    a = ctx.args; act = a[0] if a else "menu"
    if act == "menu":
        ctx.reset()
        ctx.reply("===== 💸 قسم تسديد الديون =====",
                  kb([("💸 تسديد ديون", "pay:go")], [("📝 كشف الديون", "pay:bal")], [BACK_HOME]))
    elif act == "go": start_cust_search(ctx, "pay", back="pay:menu")
    elif act == "bal": start_cust_search(ctx, "bal", back="pay:menu")
    elif len(a) > 1 and a[1].isdigit():
        phone = int(a[1]); cn = ctx.client["num"]
        cust = get_customer(cn, phone)
        if not cust:
            ctx.reply("⚠️ العميل غير موجود.", kb([("↩️ رجوع", "pay:menu")])); return
        if act == "det": _debt_details(ctx, cust)
        elif act == "do":
            ctx.go("pay:amt", pay_phone=phone)
            ctx.reply("أدخل المبلغ الذي سيسدده:", kb([("❌ إلغاء", "pay:menu")]))
        elif act == "full": _settle_full(ctx, cust)


@cust_purpose("pay")
def pay_cust_picked(ctx, c):
    cn = ctx.client["num"]; td, tp, rem = debt_totals(c["phone"], cn); u = _unit(ctx)
    if rem <= 0:
        ctx.reset()
        ctx.reply("✅ العميل [<b>%s</b>] ليس عليه ديون." % esc(c["name"]), kb([("↩️ رجوع", "pay:menu"), BACK_HOME]))
        return
    ctx.reset()
    ctx.reply("👤 <b>%s</b>\n📞 %s\n💰 المتبقي: <b>%s</b> %s" % (esc(c["name"]), c["phone"], fmt_num(rem), u),
              kb([("📋 كشف التفاصيل", "pay:det:%s" % c["phone"])],
                 [("💸 تسديد", "pay:do:%s" % c["phone"])], [("↩️ رجوع", "pay:menu")]))


def _debt_details(ctx, cust):
    cn = ctx.client["num"]
    rows = db.rows("SELECT * FROM (SELECT product_name, quantity, debt_amount, NVL(paid_amount, 0) AS paid, "
                   "debt_date, invoice_num FROM shop_debts WHERE customer_phone = :p_ph AND client_num = :p_cn "
                   "ORDER BY debt_id) WHERE ROWNUM <= 40", p_ph=cust["phone"], p_cn=cn)
    u = _unit(ctx)
    lines = ["--- 📋 تفاصيل الديون: <b>%s</b> ---" % esc(cust["name"])]
    for r in rows:
        lines.append("- %s | %s | %s %s | %s%s"
                     % (esc(r["product_name"]), fmt_num(r["quantity"]), fmt_num(r["debt_amount"]), u,
                        fmt_dt(r["debt_date"]),
                        " | فاتورة: %s" % r["invoice_num"] if r.get("invoice_num") else ""))
    td, tp, rem = debt_totals(cust["phone"], cn)
    lines += ["", "الإجمالي: %s | المسدد: %s | المتبقي: <b>%s</b> %s"
              % (fmt_num(td), fmt_num(tp), fmt_num(rem), u)]
    ctx.reply("\n".join(lines), kb([("💸 تسديد", "pay:do:%s" % cust["phone"])], [("↩️ رجوع", "pay:menu")]))


@on_state("pay:amt")
def st_pay_amt(ctx):
    amt = parse_float(ctx.text, 0.0)
    if amt is None or amt <= 0: ctx.send("أدخل مبلغاً أكبر من صفر:"); return
    cn = ctx.client["num"]; phone = ctx.data.get("pay_phone")
    cust = get_customer(cn, phone) if phone is not None else None
    if not cust:
        ctx.reset(); ctx.send("⚠️ العميل غير موجود.", kb([("↩️ رجوع", "pay:menu")])); return
    td, tp, rem = debt_totals(phone, cn); u = _unit(ctx)
    if rem <= 0:
        ctx.reset(); ctx.send("✅ ليس عليه ديون.", kb([BACK_HOME])); return
    amt = round(amt, 2)
    if amt >= rem - 0.001:
        extra = "\nالمبلغ أكبر من المتبقي بـ %s %s." % (fmt_num(amt - rem), u) if amt > rem + 0.001 else ""
        ctx.go("pay:fullq", pay_phone=phone)
        ctx.send("سيتم تسديد كامل الدين (<b>%s</b> %s) وتصفير الحساب.%s\nتأكيد؟"
                 % (fmt_num(rem), u, extra),
                 kb([("✅ تأكيد", "pay:full:%s" % phone)], [("❌ إلغاء", "pay:menu")]))
        return
    with db.tx() as t:
        t.run("UPDATE shop_debts SET paid_amount = NVL(paid_amount, 0) + :p_a WHERE debt_id = "
              "(SELECT MAX(debt_id) FROM shop_debts WHERE customer_phone = :p_ph AND client_num = :p_cn)",
              p_a=amt, p_ph=phone, p_cn=cn)
        core.audit("DEBT_PAY", ctx, details="phone=%s amount=%s" % (phone, amt), t=t)
    ctx.reset()
    ctx.send("✅ تم تسجيل الدفعة! المتبقي: <b>%s</b> %s" % (fmt_num(rem - amt), u),
             kb([("💸 تسديد آخر", "pay:go")], [BACK_HOME]))


def _settle_full(ctx, cust):
    cn = ctx.client["num"]; td, tp, rem = debt_totals(cust["phone"], cn)
    if rem <= 0:
        ctx.reply("✅ ليس عليه ديون.", kb([BACK_HOME])); return
    with db.tx() as t:
        n = archive_and_delete_debts(t, cn, cust["phone"], "PAID_FULL")
        core.audit("DEBT_FULL", ctx, details="phone=%s paid=%s rows=%s" % (cust["phone"], rem, n), t=t)
    ctx.reset()
    ctx.reply("✅ تم تسديد الدين بالكامل!", kb([("💸 تسديد آخر", "pay:go")], [BACK_HOME]))


@cust_purpose("bal")
def bal_cust_picked(ctx, c):
    cn = ctx.client["num"]; td, tp, rem = debt_totals(c["phone"], cn); u = _unit(ctx)
    ctx.reset()
    lines = ["--- 📝 كشف رصيد: <b>%s</b> ---" % esc(c["name"])]
    if td == 0: lines.append("✅ سدد بالكامل.")
    else:
        lines += ["مجموع الدين: %s %s" % (fmt_num(td), u), "المسدد: %s %s" % (fmt_num(tp), u),
                  "المتبقي: <b>%s</b> %s" % (fmt_num(rem), u)]
    ctx.reply("\n".join(lines), kb([("📝 كشف آخر", "pay:bal")], [("↩️ رجوع", "pay:menu"), BACK_HOME]))
'''

# ════════════════════ personal.py (مُصلح) ════════════════════
SOURCES['personal'] = r'''"""القسم الفردي الشامل — نسخة مصححة (معالج واحد فقط لـ per)."""
from __future__ import annotations
import logging
from urllib.parse import quote
import core, db
from config import cfg
from core import (BACK_HOME, esc, fmt_dt, fmt_num, kb, on_cb, on_state, parse_float, parse_int)
log = logging.getLogger("personal")

EXPENSE_CATS = {
    "food": "🍔 أكل ومطاعم", "transport": "🚕 مواصلات", "grocery": "🛒 مقاضي البيت",
    "bills": "💡 فواتير واتصالات", "health": "💊 صحة وعلاج", "fun": "☕ كافيهات وترفيه",
    "gifts": "🎁 هدايا", "other": "📌 مصاريف أخرى",
}


def _cn(ctx): return ctx.client["num"]
def _u(ctx): return core.unit_of(ctx.client)
def _month_cond(): return "date(created_at) >= date('now', 'localtime', 'start of month')"
def _today_cond(): return "date(created_at) = date('now', 'localtime')"


# ═══════════════════ المعالج الوحيد لكل أزرار القسم الفردي ═══════════════════
@on_cb("per")
def cb_per(ctx):
    a = ctx.args
    section = a[0] if a else "menu"
    action = a[1] if len(a) > 1 else ""
    arg = a[2] if len(a) > 2 else ""

    # ── القائمة الرئيسية ──
    if section == "menu":
        ctx.reset()
        ctx.reply("👤 <b>القسم الفردي الشامل</b>\nاختر القسم:",
                  kb([("💸 المصاريف", "per:exp")], [("💰 الدخل", "per:inc")],
                     [("💼 المحفظة", "per:wallet")], [("🤝 الديون", "per:debt")],
                     [("📝 المذكرات", "per:note")], [("🎯 الأهداف", "per:goal")],
                     [("🔔 الالتزامات", "per:obl")], [("📊 التقرير الشامل", "per:report")],
                     [("📞 تواصل معنا", "support:home")], [BACK_HOME]))
        return

    # ── المصاريف ──
    if section == "exp":
        if not action: return _exp_menu(ctx)
        if action == "cat" and arg in EXPENSE_CATS:
            ctx.go("per:exp_amt", exp_cat=arg)
            return ctx.reply("اخترت: <b>%s</b>\nأدخل المبلغ:" % EXPENSE_CATS[arg],
                             kb([("❌ إلغاء", "per:exp")]))
        if action == "det":
            ctx.go("per:exp_det")
            return ctx.reply("أدخل تفاصيل (أو اضغط تخطي):",
                             kb([("⏭ تخطي", "per:exp:skipdet")], [("❌ إلغاء", "per:exp")]))
        if action == "skipdet": return _save_expense(ctx, None)
        if action == "today": return _exp_today(ctx)
        if action == "month": return _exp_month(ctx)
        if action == "list": return _exp_list(ctx, 0)
        if action == "listpage" and arg.isdigit(): return _exp_list(ctx, int(arg))

    # ── الدخل ──
    elif section == "inc":
        if not action: return _inc_menu(ctx)
        if action == "add":
            ctx.go("per:inc_src", inc_period=arg or "daily")
            return ctx.reply("أدخل مصدر الدخل (مثال: راتب، مبيعات):", kb([("❌ إلغاء", "per:inc")]))
        if action == "save": return _save_income(ctx)
        if action == "today": return _inc_today(ctx)
        if action == "month": return _inc_month(ctx)
        if action == "list": return _inc_list(ctx)

    # ── المحفظة ──
    elif section == "wallet":
        return _wallet(ctx)

    # ── الديون ──
    elif section == "debt":
        if not action: return _debt_menu(ctx)
        if action == "for":
            ctx.go("per:debt_for_name", debt_dir="for_me")
            return ctx.reply("🤝 <b>دين لي (عند الناس)</b>\nأدخل اسم الشخص:", kb([("❌ إلغاء", "per:debt")]))
        if action == "on":
            ctx.go("per:debt_on_name", debt_dir="on_me")
            return ctx.reply("🤝 <b>دين عليّ (للناس)</b>\nأدخل اسم الشخص:", kb([("❌ إلغاء", "per:debt")]))
        if action == "skipphone": return _debt_continue(ctx, "")
        if action == "skipreason": return _save_debt(ctx, None)
        if action == "list" and arg in ("for_me", "on_me"): return _debt_list(ctx, arg)
        if action == "view" and arg.isdigit(): return _debt_view(ctx, int(arg))
        if action == "pay" and arg.isdigit():
            ctx.go("per:debt_pay", debt_id=int(arg))
            return ctx.reply("أدخل المبلغ الذي سيُسدد الآن:", kb([("❌ إلغاء", "per:debt")]))
        if action == "wa" and arg.isdigit(): return _debt_whatsapp(ctx, int(arg))
        if action == "del" and arg.isdigit(): return _debt_delete(ctx, int(arg))

    # ── المذكرات ──
    elif section == "note":
        if not action: return _note_menu(ctx)
        if action == "add":
            ctx.go("per:note_title")
            return ctx.reply("📝 أدخل عنوان المذكرة:", kb([("❌ إلغاء", "per:note")]))
        if action == "content":
            ctx.go("per:note_content")
            return ctx.reply("اكتب محتوى المذكرة:", kb([("❌ إلغاء", "per:note")]))
        if action == "list": return _note_list(ctx, 0)
        if action == "listpage" and arg.isdigit(): return _note_list(ctx, int(arg))
        if action == "view" and arg.isdigit(): return _note_view(ctx, int(arg))
        if action == "del" and arg.isdigit(): return _note_delete(ctx, int(arg))

    # ── الأهداف ──
    elif section == "goal":
        if not action: return _goal_menu(ctx)
        if action == "add":
            ctx.go("per:goal_name")
            return ctx.reply("🎯 أدخل اسم الهدف:", kb([("❌ إلغاء", "per:goal")]))
        if action == "target":
            ctx.go("per:goal_target")
            return ctx.reply("أدخل المبلغ المستهدف:", kb([("❌ إلغاء", "per:goal")]))
        if action == "list": return _goal_list(ctx)
        if action == "view" and arg.isdigit(): return _goal_view(ctx, int(arg))
        if action == "dep" and arg.isdigit():
            ctx.go("per:goal_dep", goal_id=int(arg))
            return ctx.reply("أدخل مبلغ الإيداع:", kb([("❌ إلغاء", "per:goal")]))
        if action == "del" and arg.isdigit(): return _goal_delete(ctx, int(arg))

    # ── الالتزامات ──
    elif section == "obl":
        if not action: return _obl_menu(ctx)
        if action == "add":
            ctx.go("per:obl_name")
            return ctx.reply("🔔 أدخل اسم الالتزام:", kb([("❌ إلغاء", "per:obl")]))
        if action == "amt":
            ctx.go("per:obl_amt")
            return ctx.reply("أدخل المبلغ الشهري:", kb([("❌ إلغاء", "per:obl")]))
        if action == "day":
            ctx.go("per:obl_day")
            return ctx.reply("أدخل يوم السداد (1-31):", kb([("❌ إلغاء", "per:obl")]))
        if action == "list": return _obl_list(ctx)
        if action == "paid" and arg.isdigit(): return _obl_pay(ctx, int(arg))
        if action == "del" and arg.isdigit(): return _obl_delete(ctx, int(arg))

    elif section == "report":
        return _report(ctx)

    return _menu(ctx)


def _menu(ctx):
    ctx.reset()
    ctx.reply("👤 <b>القسم الفردي</b>\nاختر:",
              kb([("💸 المصاريف", "per:exp")], [("💰 الدخل", "per:inc")],
                 [("💼 المحفظة", "per:wallet")], [("🤝 الديون", "per:debt")],
                 [("📝 المذكرات", "per:note")], [("🎯 الأهداف", "per:goal")],
                 [("🔔 الالتزامات", "per:obl")], [("📊 التقرير", "per:report")],
                 [("📞 تواصل معنا", "support:home")], [BACK_HOME]))


# ═══════════════════ المصاريف ═══════════════════
def _exp_menu(ctx):
    ctx.reset()
    ctx.reply("💸 <b>المصاريف</b>\nاختر التصنيف:",
              kb(*[[(v, "per:exp:cat:%s" % k)] for k, v in EXPENSE_CATS.items()],
                 [("📊 اليوم", "per:exp:today"), ("📅 الشهر", "per:exp:month")],
                 [("📋 كشف تفصيلي", "per:exp:list")],
                 [("↩️ رجوع", "per:menu"), BACK_HOME]))


@on_state("per:exp_amt")
def st_exp_amt(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None or v <= 0: ctx.send("أدخل مبلغاً أكبر من صفر:"); return
    ctx.go("per:exp_det", exp_amt=v)
    ctx.reply("أدخل تفاصيل (أو تخطي):", kb([("⏭ تخطي", "per:exp:skipdet")], [("❌ إلغاء", "per:exp")]))


@on_state("per:exp_det")
def st_exp_det(ctx): _save_expense(ctx, core.clean_text(ctx.text, 300, True))


def _save_expense(ctx, details):
    d = ctx.data; amt = d.get("exp_amt"); cat = d.get("exp_cat")
    if not amt or not cat:
        ctx.reset(); ctx.send("انتهت الصلاحية.", kb([("💸 المصاريف", "per:exp"), BACK_HOME])); return
    db.run("INSERT INTO personal_expenses (client_num, category, amount, details) "
           "VALUES (:p_cn, :p_cat, :p_amt, :p_det)",
           p_cn=_cn(ctx), p_cat=cat, p_amt=amt, p_det=details)
    core.audit("EXPENSE_ADD", ctx, details="%s %s" % (cat, amt))
    ctx.reset()
    ctx.reply("✅ تم حفظ الصرف: <b>%s</b> — %s\nالتصنيف: %s" % (fmt_num(amt), _u(ctx), EXPENSE_CATS[cat]),
              kb([("➕ صرف آخر", "per:exp")], [("📊 اليوم", "per:exp:today")], [BACK_HOME]))


def _exp_today(ctx):
    r = db.one("SELECT NVL(SUM(amount), 0) AS total, COUNT(*) AS cnt FROM personal_expenses "
               "WHERE client_num = :p_cn AND " + _today_cond(), p_cn=_cn(ctx))
    ctx.reply("📊 صرف اليوم: <b>%s</b> %s\nالعمليات: %s" % (fmt_num(r["total"]), _u(ctx), r["cnt"]),
              kb([("📅 الشهر", "per:exp:month"), ("💸 صرف", "per:exp")], [BACK_HOME]))


def _exp_month(ctx):
    r = db.one("SELECT NVL(SUM(amount), 0) AS total, COUNT(*) AS cnt FROM personal_expenses "
               "WHERE client_num = :p_cn AND " + _month_cond(), p_cn=_cn(ctx))
    ctx.reply("📅 صرف الشهر: <b>%s</b> %s\nالعمليات: %s" % (fmt_num(r["total"]), _u(ctx), r["cnt"]),
              kb([("📊 اليوم", "per:exp:today"), ("💸 صرف", "per:exp")], [BACK_HOME]))


def _exp_list(ctx, page):
    rows = db.rows("SELECT * FROM (SELECT expense_id, category, amount, details, created_at "
                   "FROM personal_expenses WHERE client_num = :p_cn ORDER BY expense_id DESC "
                   "LIMIT 15 OFFSET :p_off)", p_cn=_cn(ctx), p_off=page * 15)
    lines = ["📋 <b>آخر المصاريف</b>", ""]
    for r in rows:
        cat = EXPENSE_CATS.get(r["category"], r["category"])
        lines.append("%s • %s %s\n    %s — %s" % (cat, fmt_num(r["amount"]), _u(ctx),
                                                  esc(r.get("details") or "-"), fmt_dt(r["created_at"])))
    if not rows: lines.append("لا توجد مصاريف.")
    nav = []
    if page > 0: nav.append(("◀️ السابق", "per:exp:listpage:%d" % (page - 1)))
    if len(rows) == 15: nav.append(("التالي ▶️", "per:exp:listpage:%d" % (page + 1)))
    rows_btns = ([nav] if nav else []) + [[("💸 صرف", "per:exp")], [("↩️ رجوع", "per:menu"), BACK_HOME]]
    ctx.reply("\n".join(lines), kb(*rows_btns))


# ═══════════════════ الدخل ═══════════════════
def _inc_menu(ctx):
    ctx.reset()
    ctx.reply("💰 <b>الدخل</b>",
              kb([("➕ دخل يومي", "per:inc:add:daily")], [("➕ دخل شهري", "per:inc:add:monthly")],
                 [("📊 اليوم", "per:inc:today"), ("📅 الشهر", "per:inc:month")],
                 [("📋 كشف", "per:inc:list")], [("💼 المحفظة", "per:wallet")],
                 [("↩️ رجوع", "per:menu"), BACK_HOME]))


@on_state("per:inc_src")
def st_inc_src(ctx):
    v = core.clean_text(ctx.text, 100, True)
    if not v: ctx.send("أدخل مصدر الدخل:"); return
    ctx.go("per:inc_amt", inc_src=v); ctx.reply("أدخل المبلغ:", kb([("❌ إلغاء", "per:inc")]))


@on_state("per:inc_amt")
def st_inc_amt(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None or v <= 0: ctx.send("أدخل مبلغاً:"); return
    ctx.go("per:inc_notes", inc_amt=v)
    ctx.reply("ملاحظات (أو تخطي):", kb([("⏭ تخطي", "per:inc:save")], [("❌ إلغاء", "per:inc")]))


@on_state("per:inc_notes")
def st_inc_notes(ctx):
    ctx.put(inc_notes=core.clean_text(ctx.text, 300, True)); _save_income(ctx)


def _save_income(ctx):
    d = ctx.data; src, amt, period = d.get("inc_src"), d.get("inc_amt"), d.get("inc_period") or "daily"
    if not src or not amt:
        ctx.reset(); ctx.send("انتهت الصلاحية.", kb([("💰 الدخل", "per:inc"), BACK_HOME])); return
    db.run("INSERT INTO personal_income (client_num, source, amount, period, notes) "
           "VALUES (:p_cn, :p_src, :p_amt, :p_p, :p_n)",
           p_cn=_cn(ctx), p_src=src, p_amt=amt, p_p=period, p_n=d.get("inc_notes"))
    core.audit("INCOME_ADD", ctx, details="%s %s %s" % (src, amt, period))
    ctx.reset()
    ctx.reply("✅ الدخل: <b>%s</b> %s\nالمصدر: %s\nالنوع: %s"
              % (fmt_num(amt), _u(ctx), esc(src), "يومي" if period == "daily" else "شهري"),
              kb([("➕ آخر", "per:inc")], [("💼 المحفظة", "per:wallet")], [BACK_HOME]))


def _inc_today(ctx):
    r = db.one("SELECT NVL(SUM(amount), 0) AS total FROM personal_income "
               "WHERE client_num = :p_cn AND " + _today_cond(), p_cn=_cn(ctx))
    ctx.reply("📊 دخل اليوم: <b>%s</b> %s" % (fmt_num(r["total"]), _u(ctx)),
              kb([("📅 الشهر", "per:inc:month")], [BACK_HOME]))


def _inc_month(ctx):
    r = db.one("SELECT NVL(SUM(amount), 0) AS total FROM personal_income "
               "WHERE client_num = :p_cn AND " + _month_cond(), p_cn=_cn(ctx))
    ctx.reply("📅 دخل الشهر: <b>%s</b> %s" % (fmt_num(r["total"]), _u(ctx)),
              kb([("📊 اليوم", "per:inc:today")], [BACK_HOME]))


def _inc_list(ctx):
    rows = db.rows("SELECT * FROM (SELECT source, amount, period, notes, created_at FROM personal_income "
                   "WHERE client_num = :p_cn ORDER BY income_id DESC) WHERE ROWNUM <= 15", p_cn=_cn(ctx))
    lines = ["📋 <b>كشف الدخل</b>", ""]
    for r in rows:
        lines.append("%s • %s %s (%s)\n    %s — %s" % (esc(r["source"]), fmt_num(r["amount"]), _u(ctx),
                                                       "يومي" if r["period"] == "daily" else "شهري",
                                                       esc(r.get("notes") or "-"), fmt_dt(r["created_at"])))
    if not rows: lines.append("لا سجلات.")
    ctx.reply("\n".join(lines), kb([("➕ دخل", "per:inc")], [("↩️ رجوع", "per:inc"), BACK_HOME]))


# ═══════════════════ المحفظة ═══════════════════
def _wallet(ctx):
    cn = _cn(ctx); u = _u(ctx)
    today = db.one("SELECT "
                   "(SELECT NVL(SUM(amount),0) FROM personal_income WHERE client_num=:c AND " + _today_cond() + ") AS inc, "
                   "(SELECT NVL(SUM(amount),0) FROM personal_expenses WHERE client_num=:c AND " + _today_cond() + ") AS exp",
                   c=cn)
    month = db.one("SELECT "
                   "(SELECT NVL(SUM(amount),0) FROM personal_income WHERE client_num=:c AND " + _month_cond() + ") AS inc, "
                   "(SELECT NVL(SUM(amount),0) FROM personal_expenses WHERE client_num=:c AND " + _month_cond() + ") AS exp",
                   c=cn)
    t_inc, t_exp = float(today["inc"]), float(today["exp"])
    m_inc, m_exp = float(month["inc"]), float(month["exp"])
    text = ("💼 <b>محفظتي الصافية</b>\n\n<b>اليوم:</b>\n💰 الدخل: %s %s\n💸 المصاريف: %s %s\n"
            "📊 الصافي: <b>%s</b> %s\n\n<b>هذا الشهر:</b>\n💰 الدخل: %s %s\n💸 المصاريف: %s %s\n"
            "📊 الصافي: <b>%s</b> %s"
            % (fmt_num(t_inc), u, fmt_num(t_exp), u, fmt_num(t_inc - t_exp), u,
               fmt_num(m_inc), u, fmt_num(m_exp), u, fmt_num(m_inc - m_exp), u))
    ctx.reply(text, kb([("💸 صرف", "per:exp"), ("💰 دخل", "per:inc")], [("↩️ رجوع", "per:menu"), BACK_HOME]))


# ═══════════════════ الديون الشخصية ═══════════════════
def _debt_menu(ctx):
    cn = _cn(ctx); u = _u(ctx)
    for_me = db.one("SELECT NVL(SUM(amount - paid_amount), 0) AS t, COUNT(*) AS c FROM personal_debts "
                    "WHERE client_num = :c AND direction = 'for_me'", c=cn)
    on_me = db.one("SELECT NVL(SUM(amount - paid_amount), 0) AS t, COUNT(*) AS c FROM personal_debts "
                   "WHERE client_num = :c AND direction = 'on_me'", c=cn)
    ctx.reset()
    ctx.reply("🤝 <b>الديون الشخصية</b>\n\n💚 ديون لي: <b>%s</b> %s (%s)\n🔴 ديون عليّ: <b>%s</b> %s (%s)"
              % (fmt_num(for_me["t"]), u, for_me["c"], fmt_num(on_me["t"]), u, on_me["c"]),
              kb([("➕ دين لي", "per:debt:for")], [("➕ دين عليّ", "per:debt:on")],
                 [("📋 كشف لي", "per:debt:list:for_me"), ("📋 كشف عليّ", "per:debt:list:on_me")],
                 [("↩️ رجوع", "per:menu"), BACK_HOME]))


@on_state("per:debt_for_name")
def st_debt_for_name(ctx):
    v = core.clean_text(ctx.text, 100, True)
    if not v: ctx.send("أدخل اسم الشخص:"); return
    ctx.go("per:debt_for_phone", debt_name=v)
    ctx.reply("أدخل رقم الهاتف (اختياري):", kb([("⏭ تخطي", "per:debt:skipphone")], [("❌ إلغاء", "per:debt")]))


@on_state("per:debt_on_name")
def st_debt_on_name(ctx):
    v = core.clean_text(ctx.text, 100, True)
    if not v: ctx.send("أدخل اسم الشخص:"); return
    ctx.go("per:debt_on_phone", debt_name=v)
    ctx.reply("أدخل رقم الهاتف (اختياري):", kb([("⏭ تخطي", "per:debt:skipphone")], [("❌ إلغاء", "per:debt")]))


def _debt_continue(ctx, phone):
    d = ctx.data; dname = d.get("debt_name") or ""; direction = d.get("debt_dir") or "for_me"
    ex = db.one("SELECT pdebt_id FROM personal_debts WHERE client_num = :c AND direction = :dir "
                "AND person_name = :n AND person_phone = :p",
                c=_cn(ctx), dir=direction, n=dname, p=phone)
    ctx.put(debt_phone=phone, debt_existing=ex["pdebt_id"] if ex else None)
    ctx.go("per:debt_amount")
    note = "\nℹ️ يوجد سجل سابق، سيتم الدمج." if ex else ""
    ctx.reply("أدخل المبلغ:" + note, kb([("❌ إلغاء", "per:debt")]))


@on_state("per:debt_for_phone")
def st_debt_for_phone(ctx): _debt_continue(ctx, core.clean_text(ctx.text, 30) or "")

@on_state("per:debt_on_phone")
def st_debt_on_phone(ctx): _debt_continue(ctx, core.clean_text(ctx.text, 30) or "")


@on_state("per:debt_amount")
def st_debt_amount(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None or v <= 0: ctx.send("أدخل مبلغاً:"); return
    ctx.go("per:debt_reason", debt_amt=v)
    ctx.reply("أدخل سبب الدين (اختياري):", kb([("⏭ تخطي", "per:debt:skipreason")], [("❌ إلغاء", "per:debt")]))


@on_state("per:debt_reason")
def st_debt_reason(ctx): _save_debt(ctx, core.clean_text(ctx.text, 300, True))


def _save_debt(ctx, reason):
    d = ctx.data; direction = d.get("debt_dir") or "for_me"; name = d.get("debt_name") or ""
    phone = d.get("debt_phone") or ""; amt = d.get("debt_amt")
    if not name or not amt:
        ctx.reset(); ctx.send("انتهت.", kb([("🤝 الديون", "per:debt"), BACK_HOME])); return
    existing = d.get("debt_existing")
    with db.tx() as t:
        if existing:
            t.run("UPDATE personal_debts SET amount = amount + :p_a, reason = :p_r, "
                  "last_update = SYSDATE WHERE pdebt_id = :p_id", p_a=amt, p_r=reason, p_id=existing)
            msg = "✅ تم الدمج التلقائي مع دين <b>%s</b>." % esc(name)
        else:
            t.run("INSERT INTO personal_debts (client_num, direction, person_name, person_phone, amount, reason) "
                  "VALUES (:p_cn, :p_dir, :p_n, :p_p, :p_a, :p_r)",
                  p_cn=_cn(ctx), p_dir=direction, p_n=name, p_p=phone, p_a=amt, p_r=reason)
            msg = "✅ دين %s <b>%s</b> %s" % ("لـ" if direction == "for_me" else "على", esc(name), fmt_num(amt))
        core.audit("PDEBT_ADD", ctx, details="%s %s %s" % (direction, name, amt), t=t)
    ctx.reset()
    ctx.reply(msg + "\nالمبلغ: %s %s" % (fmt_num(amt), _u(ctx)),
              kb([("➕ دين آخر", "per:debt")], [("📋 كشف", "per:debt:list:%s" % direction)], [("↩️ رجوع", "per:debt")]))


def _debt_list(ctx, direction):
    cn = _cn(ctx); u = _u(ctx)
    rows = db.rows("SELECT pdebt_id, person_name, person_phone, amount, paid_amount, "
                   "(amount - paid_amount) AS remain, reason, created_at "
                   "FROM personal_debts WHERE client_num = :c AND direction = :d "
                   "ORDER BY (amount - paid_amount) DESC", c=cn, d=direction)
    header = "💚 <b>ديون لي</b>" if direction == "for_me" else "🔴 <b>ديون عليّ</b>"
    if not rows:
        ctx.reply(header + "\n\nلا سجلات.", kb([("↩️ رجوع", "per:debt"), BACK_HOME])); return
    total = sum(float(r["remain"]) for r in rows)
    lines = [header, ""]; btns = []
    for r in rows:
        lines.append("<b>%s</b> — متبقي: %s %s\n    (أصل: %s | مسدد: %s)"
                     % (esc(r["person_name"]), fmt_num(r["remain"]), u,
                        fmt_num(r["amount"]), fmt_num(r["paid_amount"])))
        btns.append([("👤 %s" % (r["person_name"][:20]), "per:debt:view:%d" % r["pdebt_id"])])
    lines.append("\n💵 الإجمالي: <b>%s</b> %s" % (fmt_num(total), u))
    btns.append([("↩️ رجوع", "per:debt"), BACK_HOME])
    ctx.reply("\n".join(lines), kb(*btns))


def _debt_view(ctx, did):
    r = db.one("SELECT * FROM personal_debts WHERE pdebt_id = :id AND client_num = :c", id=did, c=_cn(ctx))
    if not r:
        ctx.reply("⚠️ غير موجود.", kb([("↩️ رجوع", "per:debt")])); return
    u = _u(ctx); direction = r["direction"]
    text = ("%s\n<b>%s</b>\n📞 %s\n💰 أصل: %s %s\n✅ مسدد: %s %s\n📊 متبقي: <b>%s</b> %s\n"
            "📝 السبب: %s\n📅 %s"
            % ("💚" if direction == "for_me" else "🔴", esc(r["person_name"]), esc(r["person_phone"] or "-"),
               fmt_num(r["amount"]), u, fmt_num(r["paid_amount"]), u,
               fmt_num(float(r["amount"]) - float(r["paid_amount"])), u,
               esc(r.get("reason") or "-"), fmt_dt(r["created_at"])))
    ctx.reply(text, kb([("💸 دفعة", "per:debt:pay:%d" % did)],
                       [("📤 واتساب", "per:debt:wa:%d" % did)],
                       [("🗑 حذف", "per:debt:del:%d" % did)],
                       [("↩️ رجوع", "per:debt"), BACK_HOME]))


@on_state("per:debt_pay")
def st_debt_pay(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None or v <= 0: ctx.send("أدخل مبلغاً:"); return
    did = ctx.data.get("debt_id")
    r = db.one("SELECT * FROM personal_debts WHERE pdebt_id = :id AND client_num = :c", id=did, c=_cn(ctx))
    if not r:
        ctx.reset(); ctx.send("⚠️ غير موجود.", kb([("🤝 الديون", "per:debt")])); return
    remain = float(r["amount"]) - float(r["paid_amount"]); pay = min(v, remain)
    with db.tx() as t:
        t.run("UPDATE personal_debts SET paid_amount = paid_amount + :p_a, last_update = SYSDATE "
              "WHERE pdebt_id = :id", p_a=pay, id=did)
        t.run("INSERT INTO personal_debt_payments (pdebt_id, client_num, amount, note) "
              "VALUES (:id, :c, :a, :n)", id=did, c=_cn(ctx), a=pay, n="دفعة")
        if v > remain: t.run("UPDATE personal_debts SET paid_amount = amount WHERE pdebt_id = :id", id=did)
        core.audit("PDEBT_PAY", ctx, details="id=%s amount=%s" % (did, pay), t=t)
    ctx.reset()
    extra = " (الزيادة تُرجع)" if v > remain else ""
    ctx.reply("✅ الدفعة: <b>%s</b> %s%s\nالمتبقي: <b>%s</b> %s"
              % (fmt_num(pay), _u(ctx), extra, fmt_num(max(remain - pay, 0)), _u(ctx)),
              kb([("👤 عرض", "per:debt:view:%d" % did)], [("↩️ رجوع", "per:debt")]))


def _debt_whatsapp(ctx, did):
    r = db.one("SELECT * FROM personal_debts WHERE pdebt_id = :id AND client_num = :c", id=did, c=_cn(ctx))
    if not r:
        ctx.reply("⚠️ غير موجود.", kb([("↩️ رجوع", "per:debt")])); return
    u = _u(ctx); remain = float(r["amount"]) - float(r["paid_amount"])
    if r["direction"] == "for_me":
        msg = "مرحباً %s،\nتذكير: المبلغ المتبقي %s %s\nشكراً 🌹" % (r["person_name"], fmt_num(remain), u)
    else:
        msg = "مرحباً %s،\nكشف حسابي:\nأصل: %s %s\nمسدد: %s %s\nمتبقي: %s %s\nشكراً 🌹" % (
            r["person_name"], fmt_num(r["amount"]), u, fmt_num(r["paid_amount"]), u, fmt_num(remain), u)
    phone = (r["person_phone"] or "").strip()
    if not phone:
        ctx.reply("⚠️ لا يوجد رقم.", kb([("↩️ رجوع", "per:debt:view:%d" % did)])); return
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("7") and len(digits) == 9: digits = "967" + digits
    elif not digits.startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9")): digits = "967" + digits
    url = "https://wa.me/%s?text=%s" % (digits, quote(msg))
    core.audit("PDEBT_WA", ctx, details="id=%s" % did)
    ctx.reply("📤 رابط واتساب:\n<a href='%s'>اضغط للفتح</a>\n\n<i>الرسالة:</i>\n<code>%s</code>"
              % (url, esc(msg)), kb([("↩️ رجوع", "per:debt:view:%d" % did)]))


def _debt_delete(ctx, did):
    n = db.run("DELETE FROM personal_debts WHERE pdebt_id = :id AND client_num = :c", id=did, c=_cn(ctx))
    db.run("DELETE FROM personal_debt_payments WHERE pdebt_id = :id AND client_num = :c", id=did, c=_cn(ctx))
    core.audit("PDEBT_DEL", ctx, details="id=%s" % did)
    ctx.reply("✅ تم الحذف." if n else "⚠️ غير موجود.", kb([("🤝 الديون", "per:debt"), BACK_HOME]))


# ═══════════════════ المذكرات ═══════════════════
def _note_menu(ctx):
    ctx.reset()
    ctx.reply("📝 <b>المذكرات</b>", kb([("➕ إضافة", "per:note:add")], [("📋 عرض", "per:note:list")],
                                      [("↩️ رجوع", "per:menu"), BACK_HOME]))


@on_state("per:note_title")
def st_note_title(ctx):
    v = core.clean_text(ctx.text, 200, True)
    if not v: ctx.send("أدخل العنوان:"); return
    ctx.go("per:note_content", note_title=v); ctx.reply("اكتب المحتوى:", kb([("❌ إلغاء", "per:note")]))


@on_state("per:note_content")
def st_note_content(ctx):
    content = (ctx.text or "").strip()[:2000]; title = ctx.data.get("note_title")
    if not title:
        ctx.reset(); ctx.send("انتهت.", kb([("📝 المذكرات", "per:note")])); return
    db.run("INSERT INTO personal_notes (client_num, title, content) VALUES (:c, :t, :ct)",
           c=_cn(ctx), t=title, ct=content)
    core.audit("NOTE_ADD", ctx, details=title)
    ctx.reset()
    ctx.reply("✅ تم حفظ المذكرة: <b>%s</b>" % esc(title),
              kb([("📋 عرض", "per:note:list")], [("➕ أخرى", "per:note:add")], [BACK_HOME]))


def _note_list(ctx, page):
    rows = db.rows("SELECT note_id, title, created_at FROM personal_notes "
                   "WHERE client_num = :c ORDER BY note_id DESC LIMIT 10 OFFSET :o", c=_cn(ctx), o=page * 10)
    if not rows:
        ctx.reply("📝 لا مذكرات.", kb([("➕ إضافة", "per:note:add")], [("↩️ رجوع", "per:note")])); return
    lines = ["📝 <b>مذكراتي</b>", ""]; btns = []
    for r in rows:
        lines.append("• <b>%s</b> — %s" % (esc(r["title"]), fmt_dt(r["created_at"])))
        btns.append([(r["title"][:30], "per:note:view:%d" % r["note_id"])])
    nav = []
    if page > 0: nav.append(("◀️ السابق", "per:note:listpage:%d" % (page - 1)))
    if len(rows) == 10: nav.append(("التالي ▶️", "per:note:listpage:%d" % (page + 1)))
    if nav: btns.append(nav)
    btns.append([("➕ مذكرة", "per:note:add")]); btns.append([("↩️ رجوع", "per:note"), BACK_HOME])
    ctx.reply("\n".join(lines), kb(*btns))


def _note_view(ctx, nid):
    r = db.one("SELECT * FROM personal_notes WHERE note_id = :id AND client_num = :c", id=nid, c=_cn(ctx))
    if not r:
        ctx.reply("⚠️ غير موجود.", kb([("↩️ رجوع", "per:note")])); return
    ctx.reply("📝 <b>%s</b>\n\n%s\n\n🕐 %s" % (esc(r["title"]), esc(r["content"] or ""), fmt_dt(r["created_at"])),
              kb([("🗑 حذف", "per:note:del:%d" % nid)], [("↩️ رجوع", "per:note")]))


def _note_delete(ctx, nid):
    db.run("DELETE FROM personal_notes WHERE note_id = :id AND client_num = :c", id=nid, c=_cn(ctx))
    ctx.reply("✅ تم الحذف.", kb([("📝 المذكرات", "per:note"), BACK_HOME]))


# ═══════════════════ الأهداف ═══════════════════
def _goal_menu(ctx):
    ctx.reset()
    ctx.reply("🎯 <b>الأهداف</b>", kb([("➕ إضافة", "per:goal:add")], [("📊 متابعة", "per:goal:list")],
                                      [("↩️ رجوع", "per:menu"), BACK_HOME]))


@on_state("per:goal_name")
def st_goal_name(ctx):
    v = core.clean_text(ctx.text, 100, True)
    if not v: ctx.send("أدخل اسم الهدف:"); return
    ctx.go("per:goal_target", goal_name=v); ctx.reply("أدخل المبلغ المستهدف:", kb([("❌ إلغاء", "per:goal")]))


@on_state("per:goal_target")
def st_goal_target(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None or v <= 0: ctx.send("أدخل مبلغاً:"); return
    db.run("INSERT INTO personal_goals (client_num, name, target_amount) VALUES (:c, :n, :t)",
           c=_cn(ctx), n=ctx.data.get("goal_name"), t=v)
    ctx.reset()
    ctx.reply("✅ الهدف: <b>%s</b>\nالمستهدف: %s %s"
              % (esc(ctx.data.get("goal_name", "")), fmt_num(v), _u(ctx)),
              kb([("📊 متابعة", "per:goal:list")], [("➕ هدف", "per:goal:add")], [BACK_HOME]))


def _goal_list(ctx):
    rows = db.rows("SELECT * FROM personal_goals WHERE client_num = :c ORDER BY goal_id DESC", c=_cn(ctx))
    if not rows:
        ctx.reply("🎯 لا أهداف.", kb([("➕ إضافة", "per:goal:add")], [("↩️ رجوع", "per:goal")])); return
    lines = ["🎯 <b>أهدافي</b>", ""]; btns = []
    for r in rows:
        pct = (float(r["saved_amount"]) / float(r["target_amount"]) * 100) if r["target_amount"] else 0
        lines.append("<b>%s</b>\n    جمعت: %s / %s %s (%.1f%%)"
                     % (esc(r["name"]), fmt_num(r["saved_amount"]), fmt_num(r["target_amount"]), _u(ctx), pct))
        btns.append([(r["name"][:28], "per:goal:view:%d" % r["goal_id"])])
    btns.append([("➕ هدف", "per:goal:add")]); btns.append([("↩️ رجوع", "per:goal"), BACK_HOME])
    ctx.reply("\n".join(lines), kb(*btns))


def _goal_view(ctx, gid):
    r = db.one("SELECT * FROM personal_goals WHERE goal_id = :id AND client_num = :c", id=gid, c=_cn(ctx))
    if not r:
        ctx.reply("⚠️ غير موجود.", kb([("↩️ رجوع", "per:goal")])); return
    remain = float(r["target_amount"]) - float(r["saved_amount"])
    pct = (float(r["saved_amount"]) / float(r["target_amount"]) * 100) if r["target_amount"] else 0
    ctx.reply("🎯 <b>%s</b>\n\nالمستهدف: %s %s\nجمعت: <b>%s</b> %s (%.1f%%)\nالمتبقي: %s %s"
              % (esc(r["name"]), fmt_num(r["target_amount"]), _u(ctx), fmt_num(r["saved_amount"]), _u(ctx),
                 pct, fmt_num(max(remain, 0)), _u(ctx)),
              kb([("💰 إيداع", "per:goal:dep:%d" % gid)], [("🗑 حذف", "per:goal:del:%d" % gid)],
                 [("↩️ رجوع", "per:goal"), BACK_HOME]))


@on_state("per:goal_dep")
def st_goal_dep(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None or v <= 0: ctx.send("أدخل مبلغاً:"); return
    gid = ctx.data.get("goal_id")
    db.run("UPDATE personal_goals SET saved_amount = saved_amount + :a WHERE goal_id = :id AND client_num = :c",
           a=v, id=gid, c=_cn(ctx))
    ctx.reply("✅ تم إيداع %s %s." % (fmt_num(v), _u(ctx)),
              kb([("👀 عرض", "per:goal:view:%d" % gid)], [("↩️ رجوع", "per:goal")]))
    ctx.reset()


def _goal_delete(ctx, gid):
    db.run("DELETE FROM personal_goals WHERE goal_id = :id AND client_num = :c", id=gid, c=_cn(ctx))
    ctx.reply("✅ تم الحذف.", kb([("🎯 الأهداف", "per:goal"), BACK_HOME]))


# ═══════════════════ الالتزامات ═══════════════════
def _obl_menu(ctx):
    ctx.reset()
    ctx.reply("🔔 <b>الالتزامات</b>", kb([("➕ إضافة", "per:obl:add")], [("📊 حالة", "per:obl:list")],
                                        [("↩️ رجوع", "per:menu"), BACK_HOME]))


@on_state("per:obl_name")
def st_obl_name(ctx):
    v = core.clean_text(ctx.text, 100, True)
    if not v: ctx.send("أدخل الاسم:"); return
    ctx.go("per:obl_amt", obl_name=v); ctx.reply("أدخل المبلغ الشهري:", kb([("❌ إلغاء", "per:obl")]))


@on_state("per:obl_amt")
def st_obl_amt(ctx):
    v = parse_float(ctx.text, 0.0)
    if v is None or v <= 0: ctx.send("أدخل مبلغاً:"); return
    ctx.go("per:obl_day", obl_amt=v); ctx.reply("أدخل يوم السداد (1-31):", kb([("❌ إلغاء", "per:obl")]))


@on_state("per:obl_day")
def st_obl_day(ctx):
    v = parse_int(ctx.text, 1, 31)
    if v is None: ctx.send("أدخل يوماً بين 1 و31:"); return
    db.run("INSERT INTO personal_obligations (client_num, name, amount, due_day) VALUES (:c, :n, :a, :d)",
           c=_cn(ctx), n=ctx.data.get("obl_name"), a=ctx.data.get("obl_amt"), d=v)
    ctx.reset()
    ctx.reply("✅ الالتزام: <b>%s</b>\nالمبلغ: %s %s\nيوم %s"
              % (esc(ctx.data.get("obl_name", "")), fmt_num(ctx.data.get("obl_amt")), _u(ctx), v),
              kb([("📊 حالة", "per:obl:list")], [("➕ آخر", "per:obl:add")], [BACK_HOME]))


def _obl_list(ctx):
    rows = db.rows("SELECT * FROM personal_obligations WHERE client_num = :c ORDER BY obligation_id", c=_cn(ctx))
    if not rows:
        ctx.reply("🔔 لا التزامات.", kb([("➕ إضافة", "per:obl:add")], [("↩️ رجوع", "per:obl")])); return
    u = _u(ctx)
    total_month = sum(float(r["amount"]) for r in rows)
    paid_month = sum(float(r["amount"]) for r in rows if r["is_paid_this_month"])
    lines = ["🔔 <b>الالتزامات</b>",
             "الإجمالي: %s %s | المسدد: %s %s | المتبقي: %s %s"
             % (fmt_num(total_month), u, fmt_num(paid_month), u, fmt_num(total_month - paid_month), u), ""]
    btns = []
    for r in rows:
        status = "✅" if r["is_paid_this_month"] else "⏳"
        lines.append("<b>%s</b> — %s %s | يوم %s | %s"
                     % (esc(r["name"]), fmt_num(r["amount"]), u, r["due_day"], status))
        if not r["is_paid_this_month"]:
            btns.append([("✅ سداد %s" % r["name"][:20], "per:obl:paid:%d" % r["obligation_id"])])
        else:
            btns.append([("🗑 حذف %s" % r["name"][:20], "per:obl:del:%d" % r["obligation_id"])])
    btns.append([("➕ إضافة", "per:obl:add")]); btns.append([("↩️ رجوع", "per:obl"), BACK_HOME])
    ctx.reply("\n".join(lines), kb(*btns))


def _obl_pay(ctx, oid):
    db.run("UPDATE personal_obligations SET is_paid_this_month = 1, last_paid_at = SYSDATE "
           "WHERE obligation_id = :id AND client_num = :c", id=oid, c=_cn(ctx))
    ctx.reply("✅ تم تسجيل السداد.", kb([("📊 الحالة", "per:obl:list")]))


def _obl_delete(ctx, oid):
    db.run("DELETE FROM personal_obligations WHERE obligation_id = :id AND client_num = :c", id=oid, c=_cn(ctx))
    ctx.reply("✅ تم الحذف.", kb([("🔔 الالتزامات", "per:obl"), BACK_HOME]))


# ═══════════════════ التقرير الشامل ═══════════════════
def _report(ctx):
    cn = _cn(ctx); u = _u(ctx)
    income = db.one("SELECT NVL(SUM(amount),0) AS m FROM personal_income WHERE client_num=:c AND " + _month_cond(), c=cn)
    expense = db.one("SELECT NVL(SUM(amount),0) AS m FROM personal_expenses WHERE client_num=:c AND " + _month_cond(), c=cn)
    top_exp = db.one("SELECT category, NVL(SUM(amount),0) AS t FROM personal_expenses "
                     "WHERE client_num=:c AND " + _month_cond() +
                     " GROUP BY category ORDER BY t DESC LIMIT 1", c=cn)
    for_me = db.one("SELECT NVL(SUM(amount - paid_amount),0) AS t FROM personal_debts "
                    "WHERE client_num=:c AND direction='for_me'", c=cn)
    on_me = db.one("SELECT NVL(SUM(amount - paid_amount),0) AS t FROM personal_debts "
                   "WHERE client_num=:c AND direction='on_me'", c=cn)
    goals = db.one("SELECT COUNT(*) AS c, NVL(SUM(saved_amount),0) AS s, NVL(SUM(target_amount),0) AS t "
                   "FROM personal_goals WHERE client_num=:c", c=cn)
    obl = db.one("SELECT COUNT(*) AS c, NVL(SUM(amount),0) AS total, "
                 "NVL(SUM(CASE WHEN is_paid_this_month=1 THEN amount ELSE 0 END),0) AS paid "
                 "FROM personal_obligations WHERE client_num=:c", c=cn)
    m_inc, m_exp = float(income["m"]), float(expense["m"]); net = m_inc - m_exp
    status = "🟢 ربح" if net >= 0 else "🔴 خسارة"
    text = ("📊 <b>التقرير الشخصي الشامل</b>\n\n<b>💼 الشهر:</b>\n💰 الدخل: %s %s\n💸 المصاريف: %s %s\n"
            "📊 الصافي: <b>%s</b> %s (%s)\n" % (fmt_num(m_inc), u, fmt_num(m_exp), u, fmt_num(net), u, status))
    if top_exp:
        text += "🏷 أكثر تصنيف: <b>%s</b> (%s %s)\n" % (EXPENSE_CATS.get(top_exp["category"], top_exp["category"]),
                                                     fmt_num(top_exp["t"]), u)
    text += ("\n<b>🤝 الديون:</b>\n💚 لي: %s %s\n🔴 عليّ: %s %s\n📊 صافي: <b>%s</b> %s\n"
             % (fmt_num(for_me["t"]), u, fmt_num(on_me["t"]), u,
                fmt_num(float(for_me["t"]) - float(on_me["t"])), u))
    text += ("\n<b>🎯 الأهداف:</b>\nعدد: %s | جمعت: %s / %s %s\n"
             % (goals["c"], fmt_num(goals["s"]), fmt_num(goals["t"]), u))
    text += ("\n<b>🔔 الالتزامات:</b>\nعدد: %s | الإجمالي: %s | المسدد: %s | المتبقي: <b>%s</b> %s"
             % (obl["c"], fmt_num(obl["total"]), fmt_num(obl["paid"]),
                fmt_num(float(obl["total"]) - float(obl["paid"])), u))
    ctx.reply(text, kb([("💸 المصاريف", "per:exp"), ("💰 الدخل", "per:inc")],
                       [("📞 تواصل معنا", "support:home")], [BACK_HOME]))
'''




# ════════════════════ admin.py (الشامل مع إضافة مستخدمين) ════════════════════
SOURCES['admin'] = r'''"""لوحة الإدارة الشاملة — تحكم كامل بالبوت (للمدراء فقط: ADMIN_IDS)."""
from __future__ import annotations
import logging
import core, db, subs, tg
from config import cfg
from core import (BACK_HOME, duration_label, esc, fmt_date, fmt_dt, fmt_num, kb, on_cb, on_state,
                  parse_float, parse_int, store_password)
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
    if not _guard(ctx): return
    a = ctx.args
    act = a[0] if a else "home"
    arg = a[1] if len(a) > 1 else ""
    arg2 = a[2] if len(a) > 2 else ""

    if act == "home": home(ctx)
    elif act == "pend": pending(ctx)
    elif act == "ok" and arg.isdigit(): decide(ctx, int(arg), True)
    elif act == "no" and arg.isdigit(): decide(ctx, int(arg), False)
    elif act == "subs": subscribers(ctx, int(arg) if arg.isdigit() else 0)
    elif act == "c" and arg.isdigit(): client_detail(ctx, int(arg))
    elif act == "act":
        ctx.go("adm:num", adm_action="extend")
        ctx.reply("أدخل <b>رقم العميل</b>:", kb([HOME_BTN]))
    elif act == "ext" and arg.isdigit(): ask_extend_type(ctx, int(arg))
    elif act == "extm" and arg.isdigit():
        ctx.go("adm:ext_amount", adm_num=int(arg), adm_unit=arg2)
        unit_label = {"minutes": "دقيقة", "hours": "ساعة", "days": "يوم", "months": "شهر"}.get(arg2, "وحدة")
        ctx.reply("أدخل عدد <b>%s</b>:" % unit_label, kb([HOME_BTN]))
    elif act == "edit" and arg.isdigit(): client_edit_menu(ctx, int(arg))
    elif act == "editf" and arg.isdigit(): _edit_field(ctx, int(arg), arg2)
    elif act == "toggle" and arg.isdigit(): toggle(ctx, int(arg))
    elif act == "del" and arg.isdigit(): _confirm_delete(ctx, int(arg))
    elif act == "delyes" and arg.isdigit(): _do_delete(ctx, int(arg))
    elif act == "reset" and arg.isdigit(): _confirm_reset(ctx, int(arg))
    elif act == "resetyes" and arg.isdigit(): _do_reset(ctx, int(arg))
    elif act == "broadcast":
        ctx.go("adm:broadcast")
        ctx.reply("أدخل رسالة لإرسالها لكل المشتركين:", kb([HOME_BTN]))
    elif act == "price":
        ctx.go("adm:price")
        ctx.reply("💰 سعر الشهر: <b>%s</b> %s\nأدخل السعر الجديد:"
                  % (fmt_num(subs.month_price()), cfg.SUB_PRICE_UNIT), kb([HOME_BTN]))
    elif act == "rates":
        usd, sar = _rates()
        ctx.go("adm:usd")
        ctx.reply("💱 الدولار = %s | السعودي = %s\n\nأدخل سعر <b>الدولار</b>:"
                  % (fmt_num(usd), fmt_num(sar)), kb([HOME_BTN]))
    elif act == "stats": _stats(ctx)
    elif act == "newuser":
        ctx.go("adm:newuser_tgid")
        ctx.reply("➕ <b>إنشاء حساب لمستخدم</b>\n\n"
                  "أدخل <b>رقم تلجرام</b> للمستخدم (من زر «🆔 رقم حسابي»):\n"
                  "<i>أو أرسل 0 لإنشاء حساب بدون ربط.</i>", kb([HOME_BTN]))
    elif act == "addacct" and arg.isdigit(): _add_account_to_user(ctx, int(arg))
    elif act == "usraccts" and arg.isdigit(): _show_tg_accounts(ctx, int(arg))
    else: home(ctx)


def _rates():
    r = db.one("SELECT usd_price, sar_price FROM exchange_rates WHERE id = 1")
    return (float(r["usd_price"] or 0), float(r["sar_price"] or 0)) if r else (0.0, 0.0)


def home(ctx):
    ctx.reset()
    pend = db.val("SELECT COUNT(*) FROM bot_sub_requests WHERE status = 'PENDING'", 0)
    total = db.val("SELECT COUNT(*) FROM clients_table", 0)
    soon = db.val("SELECT COUNT(*) FROM clients_table WHERE expiry_date BETWEEN datetime('now','localtime') "
                  "AND datetime('now','localtime','+7 days')", 0)
    expired = db.val("SELECT COUNT(*) FROM clients_table WHERE expiry_date < datetime('now','localtime')", 0)
    blocked = db.val("SELECT COUNT(*) FROM clients_table WHERE is_active = 0", 0)
    tg_users = db.val("SELECT COUNT(*) FROM bot_user_accounts", 0)
    ctx.reply("🛡 <b>لوحة الإدارة الشاملة</b>\n\n"
              "📥 طلبات معلّقة: <b>%s</b>\n👥 المشتركون: %s\n📱 ارتباطات تلجرام: %s\n"
              "⏰ خلال 7 أيام: %s\n⛔ منتهي: %s | موقوف: %s\n💰 سعر الشهر: %s %s"
              % (pend, total, tg_users, soon, expired, blocked,
                 fmt_num(subs.month_price()), cfg.SUB_PRICE_UNIT),
              kb([("📥 الطلبات (%s)" % pend, "adm:pend")],
                 [("👥 المشتركون", "adm:subs:0"), ("➕ تمديد يدوي", "adm:act")],
                 [("🆕 إنشاء حساب جديد", "adm:newuser")],
                 [("💰 سعر الشهر", "adm:price"), ("💱 أسعار الصرف", "adm:rates")],
                 [("📊 إحصائيات", "adm:stats")],
                 [("📢 رسالة جماعية", "adm:broadcast")],
                 [BACK_HOME]))


def pending(ctx):
    rows = db.rows("SELECT * FROM (SELECT r.req_id, r.months, r.amount, r.created_at, c.name, c.num "
                   "FROM bot_sub_requests r JOIN clients_table c ON c.num = r.client_num "
                   "WHERE r.status = 'PENDING' ORDER BY r.req_id) WHERE ROWNUM <= 10")
    if not rows:
        ctx.reply("لا طلبات معلّقة ✅", kb([HOME_BTN])); return
    lines = ["📥 <b>الطلبات المعلّقة</b>", ""]; btns = []
    for r in rows:
        lines.append("#%s • %s (رقم %s) • %s • %s %s\n    %s"
                     % (r["req_id"], esc(r["name"]), r["num"], duration_label(r["months"]),
                        fmt_num(r["amount"]), cfg.SUB_PRICE_UNIT, core.fmt_dt(r["created_at"])))
        btns.append([("✅ #%s" % r["req_id"], "adm:ok:%s" % r["req_id"]),
                     ("❌ #%s" % r["req_id"], "adm:no:%s" % r["req_id"])])
    btns.append([HOME_BTN])
    ctx.reply("\n".join(lines), kb(*btns))


def decide(ctx, rid, ok):
    try:
        req, res = (subs.approve_request if ok else subs.reject_request)(ctx, rid)
    except ValueError as e:
        ctx.reply("⚠️ %s" % esc(e), kb([HOME_BTN])); return
    if not req:
        ctx.reply("⚠️ %s" % esc(res), kb([("📥 الطلبات", "adm:pend"), HOME_BTN])); return
    if ok:
        ctx.reply("✅ تم تفعيل #%s (العميل %s).\nينتهي: <b>%s</b>"
                  % (rid, req["client_num"], fmt_date(res)), kb([("📥 الطلبات", "adm:pend"), HOME_BTN]))
    else:
        ctx.reply("❌ رُفض #%s." % rid, kb([("📥 الطلبات", "adm:pend"), HOME_BTN]))


def subscribers(ctx, page):
    rows = db.rows(page_sql("SELECT num, name, shop_name, expiry_date, "
                            "(julianday(expiry_date) - julianday('now', 'localtime')) AS days_left, "
                            "is_active FROM clients_table ORDER BY expiry_date", page, 8))
    has_next = len(rows) > 8
    lines = ["👥 <b>المشتركون</b>", ""]; btns = []
    for r in rows[:8]:
        dl = r["days_left"]
        if r["is_active"] is not None and int(r["is_active"]) == 0: st = "⛔ موقوف"
        elif dl is not None and dl < 0: st = "❌ منتهي"
        else: st = "✅ %s يوم" % ("∞" if dl is None else int(dl))
        lines.append("<b>%s</b> (رقم %s) — %s — ينتهي %s" % (esc(r["name"]), r["num"], st, fmt_date(r["expiry_date"])))
        btns.append([("👤 %s (%s)" % ((r["name"] or "")[:22], r["num"]), "adm:c:%s" % r["num"])])
    if not rows: lines.append("لا مشتركون.")
    nav = []
    if page > 0: nav.append(("◀️ السابق", "adm:subs:%d" % (page - 1)))
    if has_next: nav.append(("التالي ▶️", "adm:subs:%d" % (page + 1)))
    if nav: btns.append(nav)
    btns.append([("🆕 إنشاء حساب", "adm:newuser")])
    btns.append([HOME_BTN])
    ctx.reply("\n".join(lines), kb(*btns))


def client_detail(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ غير موجود.", kb([("👥 المشتركون", "adm:subs:0"), HOME_BTN])); return
    st = subs.status(c)
    state = "⛔ موقوف" if st["blocked"] else ("❌ منتهي" if st["expired"] else "✅ ساري")
    links = db.rows("SELECT telegram_id, added_at FROM bot_user_accounts WHERE client_num = :n", n=num)
    tg_line = "\n📱 مرتبط بـ %d حساب تلجرام" % len(links) if links else "\n📱 غير مرتبط بأي حساب تلجرام"
    ctx.reply("👤 <b>%s</b> (رقم %s)\nالايميل: %s\nالمحل: %s\nنوع الحساب: %s\n"
              "بدأ: %s\nينتهي: <b>%s</b> (%s)\nالمدة: %s شهر | مدفوع: %s %s%s"
              % (esc(c["name"]), c["num"], esc(c["email"]), esc(c.get("shop_name") or "-"),
                 esc(c.get("account_type") or "غير محدد"), fmt_date(c.get("start_date")),
                 fmt_date(c.get("expiry_date")), state, c.get("subscription_months") or 0,
                 fmt_num(c.get("money") or 0), cfg.SUB_PRICE_UNIT, tg_line),
              kb([("➕ تمديد / تجديد", "adm:ext:%s" % num)],
                 [("✏️ تعديل البيانات", "adm:edit:%s" % num)],
                 [("➕ إضافة حساب إضافي", "adm:addacct:%s" % num)],
                 [("✅ تفعيل" if st["blocked"] else "⛔ إيقاف", "adm:toggle:%s" % num)],
                 [("🔄 تصفير", "adm:reset:%s" % num)],
                 [("🗑 حذف", "adm:del:%s" % num)],
                 [("👥 المشتركون", "adm:subs:0"), HOME_BTN]))


def toggle(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ غير موجود.", kb([HOME_BTN])); return
    blocked = subs.status(c)["blocked"]
    db.run("UPDATE clients_table SET is_active = :p_v WHERE num = :p_n", p_v=1 if blocked else 0, p_n=num)
    core.audit("ACCOUNT_TOGGLE", ctx, client_num=num, details="active=%s" % (1 if blocked else 0))
    if blocked:
        subs.notify_client(num, "✅ تم تفعيل حسابك.", kb([BACK_HOME]))
    else:
        subs.notify_client(num, "⛔ تم إيقاف حسابك. للاستفسار تواصل مع الإدارة.",
                           kb([("📞 تواصل معنا", "support:home"), BACK_HOME]))
    client_detail(ctx, num)


def ask_extend_type(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ غير موجود.", kb([HOME_BTN])); return
    ctx.go(None)
    ctx.reply("➕ <b>تمديد</b>\nالعميل: %s (رقم %s)\nينتهي: %s\n\nاختر:"
              % (esc(c["name"]), num, fmt_date(c.get("expiry_date"))),
              kb([("📅 شهر", "adm:extm:%s:months" % num), ("📆 يوم", "adm:extm:%s:days" % num)],
                 [("⏰ ساعة", "adm:extm:%s:hours" % num), ("⏱ دقيقة", "adm:extm:%s:minutes" % num)],
                 [("↩️ رجوع", "adm:c:%s" % num), HOME_BTN]))


@on_state("adm:num")
def st_adm_num(ctx):
    n = parse_int(ctx.text, 1, 2147483647)
    if n is None: ctx.send("أدخل رقم العميل:"); return
    if not core.fetch_client(n):
        ctx.send("⚠️ غير موجود. أعد المحاولة:", kb([HOME_BTN])); return
    ask_extend_type(ctx, n)


@on_state("adm:ext_amount")
def st_adm_ext_amount(ctx):
    d = ctx.data; num, unit = d.get("adm_num"), d.get("adm_unit")
    if not num or unit not in ("minutes", "hours", "days", "months"):
        ctx.reset(); ctx.send("انتهت.", kb([HOME_BTN])); return
    v = parse_int(ctx.text, 1, 100000)
    if v is None: ctx.send("أدخل عدداً:"); return
    try:
        with db.tx() as t:
            exp = subs.grant_precise(t, num, amount=0, **{unit: v})
            core.audit("SUB_MANUAL_PRECISE", ctx, client_num=num, details="+%s %s" % (v, unit), t=t)
    except ValueError as e:
        ctx.reset(); ctx.send("⚠️ %s" % esc(e), kb([HOME_BTN])); return
    ctx.reset()
    unit_ar = {"minutes": "دقيقة", "hours": "ساعة", "days": "يوم", "months": "شهر"}[unit]
    subs.notify_client(num, "✅ تمديد اشتراكك بـ <b>%s %s</b>.\nينتهي: <b>%s</b>"
                       % (v, unit_ar, fmt_date(exp)), kb([BACK_HOME]))
    ctx.send("✅ تمديد %s بـ %s %s.\nينتهي: <b>%s</b>" % (num, v, unit_ar, fmt_date(exp)),
             kb([("👤 تفاصيل", "adm:c:%s" % num), HOME_BTN]))


def client_edit_menu(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ غير موجود.", kb([HOME_BTN])); return
    ctx.go(None)
    ctx.reply("✏️ <b>تعديل البيانات</b>\nالعميل: %s (رقم %s)\n\nاختر الحقل:" % (esc(c["name"]), num),
              kb([("👤 الاسم", "adm:editf:%s:name" % num), ("🔢 رقم الدخول", "adm:editf:%s:num" % num)],
                 [("📧 الإيميل", "adm:editf:%s:email" % num), ("🏪 اسم المتجر", "adm:editf:%s:shop_name" % num)],
                 [("🏷 النشاط", "adm:editf:%s:activity_type" % num), ("🌍 الدولة", "adm:editf:%s:shop_location" % num)],
                 [("📍 الموقع", "adm:editf:%s:location" % num), ("💵 العملة", "adm:editf:%s:currency" % num)],
                 [("🔐 كلمة المرور", "adm:editf:%s:password_hash" % num)],
                 [("↩️ رجوع", "adm:c:%s" % num), HOME_BTN]))


_EDIT_LABELS = {"name": "الاسم", "num": "رقم الدخول", "email": "الإيميل",
                "shop_name": "اسم المتجر", "activity_type": "النشاط",
                "shop_location": "الدولة", "location": "الموقع", "currency": "العملة",
                "password_hash": "كلمة المرور"}


def _edit_field(ctx, num, field):
    if field not in _EDIT_LABELS:
        ctx.reply("حقل غير معروف.", kb([HOME_BTN])); return
    ctx.go("adm:editval", adm_num=num, adm_field=field)
    ctx.reply("أدخل <b>%s</b> الجديد:" % _EDIT_LABELS[field], kb([HOME_BTN]))


@on_state("adm:editval")
def st_adm_editval(ctx):
    num, field = ctx.data.get("adm_num"), ctx.data.get("adm_field")
    if not num or field not in _EDIT_LABELS:
        ctx.reset(); ctx.send("انتهت.", kb([HOME_BTN])); return
    raw = ctx.text or ""
    if field == "num":
        v = parse_int(raw, 1, 2147483647)
        if v is None: ctx.send("أدخل رقماً:"); return
        if v != num and db.one("SELECT num FROM clients_table WHERE num = :p_n", p_n=v):
            ctx.send("⚠️ مستخدم. أدخل رقماً آخر:"); return
        db.run("UPDATE clients_table SET num = :p_v WHERE num = :p_n", p_v=v, p_n=num)
        db.run("UPDATE bot_users SET client_num = :p_v WHERE client_num = :p_n", p_v=v, p_n=num)
        db.run("UPDATE bot_user_accounts SET client_num = :p_v WHERE client_num = :p_n", p_v=v, p_n=num)
        core.audit("ADMIN_EDIT_NUM", ctx, client_num=v, details="old=%s new=%s" % (num, v))
        ctx.reset()
        ctx.send("✅ تم تحديث رقم الدخول: %s → %s" % (num, v),
                 kb([("👤 تفاصيل", "adm:c:%s" % v), HOME_BTN])); return
    if field == "password_hash":
        if len(raw) < 8: ctx.send("8 أحرف على الأقل:"); return
        v = store_password(raw)
    elif field == "email":
        v = core.clean_text(raw, 150)
        if not v or "@" not in v: ctx.send("إيميل غير صحيح:"); return
    else: v = core.clean_text(raw, 100, True)
    db.run("UPDATE clients_table SET %s = :p_v WHERE num = :p_n" % field, p_v=v, p_n=num)
    core.audit("ADMIN_EDIT", ctx, client_num=num, details="%s=%s" % (field, "***" if field == "password_hash" else v))
    ctx.reset()
    ctx.send("✅ تم تحديث <b>%s</b> للعميل %s" % (_EDIT_LABELS[field], num),
             kb([("✏️ تعديل آخر", "adm:edit:%s" % num)], [("👤 تفاصيل", "adm:c:%s" % num), HOME_BTN]))


def _confirm_delete(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ غير موجود.", kb([HOME_BTN])); return
    ctx.reply("⚠️ <b>حذف نهائي</b>\nحذف <b>%s</b> (رقم %s)؟\nكل بياناته ستُحذف نهائياً."
              % (esc(c["name"]), num),
              kb([("🗑 نعم، احذف", "adm:delyes:%s" % num)], [("❌ إلغاء", "adm:c:%s" % num), HOME_BTN]))


def _do_delete(ctx, num):
    with db.tx() as t:
        for tbl in ("bot_user_accounts", "personal_expenses", "personal_income", "personal_debt_payments",
                    "personal_debts", "personal_notes", "personal_goals", "personal_obligations",
                    "shop_customers", "shop_debts", "cash_sales", "network_sales", "imports_table",
                    "bot_sub_requests"):
            t.run("DELETE FROM %s WHERE client_num = :n" % tbl, n=num)
        t.run("UPDATE bot_users SET client_num = NULL, state = NULL, state_data = NULL WHERE client_num = :c", c=num)
        t.run("DELETE FROM clients_table WHERE num = :n", n=num)
        core.audit("ADMIN_DELETE_USER", ctx, client_num=num, t=t)
    ctx.reset()
    ctx.reply("✅ تم حذف المستخدم %s وكل بياناته." % num, kb([("👥 المشتركون", "adm:subs:0"), HOME_BTN]))


def _confirm_reset(ctx, num):
    c = core.fetch_client(num)
    if not c:
        ctx.reply("⚠️ غير موجود.", kb([HOME_BTN])); return
    ctx.reply("🔄 <b>تصفير البيانات</b>\nحذف بيانات المتجر والديون والشخصية لـ <b>%s</b> مع بقاء الحساب والاشتراك.\nتأكيد؟"
              % esc(c["name"]),
              kb([("🔄 نعم، صفّر", "adm:resetyes:%s" % num)], [("❌ إلغاء", "adm:c:%s" % num), HOME_BTN]))


def _do_reset(ctx, num):
    with db.tx() as t:
        for tbl in ("personal_expenses", "personal_income", "personal_debt_payments", "personal_debts",
                    "personal_notes", "personal_goals", "personal_obligations", "shop_customers",
                    "shop_debts", "cash_sales", "network_sales", "imports_table"):
            t.run("DELETE FROM %s WHERE client_num = :n" % tbl, n=num)
        core.audit("ADMIN_RESET_USER", ctx, client_num=num, t=t)
    ctx.reset()
    ctx.reply("✅ تم تصفير بيانات المستخدم %s." % num, kb([("👤 تفاصيل", "adm:c:%s" % num), HOME_BTN]))


# ─────────── إنشاء مستخدم جديد ───────────
@on_state("adm:newuser_tgid")
def st_newuser_tgid(ctx):
    raw = (ctx.text or "").strip()
    if raw == "0":
        ctx.go("adm:newuser_name", adm_tgid=None); ctx.send("أدخل اسم المستخدم:"); return
    tgid = parse_int(raw, 1, 10 ** 15)
    if tgid is None:
        ctx.send("أدخل رقم تلجرام أو 0 للتخطي:"); return
    exists = db.one("SELECT telegram_id FROM bot_users WHERE telegram_id = :t", t=tgid)
    if not exists:
        ctx.send("⚠️ لا يوجد مستخدم تلجرام بهذا الرقم (يجب أن يرسل /start أولاً).\n"
                 "أو أرسل 0 لإنشاء حساب بدون ربط:", kb([HOME_BTN])); return
    ctx.go("adm:newuser_name", adm_tgid=tgid)
    ctx.send("✅ تلجرام: %s\nأدخل اسم المستخدم:" % tgid)


@on_state("adm:newuser_name")
def st_newuser_name(ctx):
    v = core.clean_text(ctx.text, 100, True)
    if not v: ctx.send("أدخل الاسم:"); return
    ctx.go("adm:newuser_num", adm_name=v); ctx.send("أدخل رقم العميل (رقم الدخول):")


@on_state("adm:newuser_num")
def st_newuser_num(ctx):
    n = parse_int(ctx.text, 1, 2147483647)
    if n is None: ctx.send("أدخل رقماً:"); return
    if db.one("SELECT num FROM clients_table WHERE num = :n", n=n):
        ctx.send("⚠️ مستخدم. اختر آخر:"); return
    ctx.go("adm:newuser_email", adm_num=n); ctx.send("أدخل الإيميل:")


@on_state("adm:newuser_email")
def st_newuser_email(ctx):
    e = core.clean_text(ctx.text, 150)
    if not e or "@" not in e: ctx.send("إيميل غير صحيح:"); return
    if db.one("SELECT num FROM clients_table WHERE LOWER(email) = :e", e=e.lower()):
        ctx.send("⚠️ مستخدم. أدخل آخر:"); return
    ctx.go("adm:newuser_pass", adm_email=e); ctx.send("أدخل كلمة المرور (8+):")


@on_state("adm:newuser_pass")
def st_newuser_pass(ctx):
    pw = ctx.text or ""
    ctx.delete_user_message()
    if len(pw) < 8: ctx.send("8 أحرف على الأقل:"); return
    ctx.go("adm:newuser_months", adm_pw=pw); ctx.send("أدخل عدد الأشهر (1-999):")


@on_state("adm:newuser_months")
def st_newuser_months(ctx):
    m = parse_int(ctx.text, 1, 999)
    if m is None: ctx.send("أدخل عدداً:"); return
    d = ctx.data
    try:
        with db.tx() as t:
            t.run("INSERT INTO clients_table (num, name, email, password_hash, subscription_months, "
                  "subscription_duration, money) VALUES (:n, :nm, :e, :p, :m, :dur, 0)",
                  n=d["adm_num"], nm=d["adm_name"], e=d["adm_email"],
                  p=store_password(d["adm_pw"]), m=m, dur=duration_label(m))
            if d.get("adm_tgid"):
                t.run("INSERT INTO bot_user_accounts (telegram_id, client_num, added_by) "
                      "VALUES (:t, :c, :a)", t=d["adm_tgid"], c=d["adm_num"], a=ctx.user_id)
                t.run("UPDATE bot_users SET client_num = :c WHERE telegram_id = :t",
                      c=d["adm_num"], t=d["adm_tgid"])
            core.audit("ADMIN_NEW_USER", ctx, client_num=d["adm_num"],
                       details="tgid=%s months=%s" % (d.get("adm_tgid"), m), t=t)
    except Exception as e:
        if "UNIQUE" in str(e) or "ORA-00001" in str(e):
            ctx.reset()
            ctx.send("⚠️ الرقم أو الإيميل مستخدم.", kb([("🆕 جديد", "adm:newuser"), HOME_BTN])); return
        raise
    num = d["adm_num"]
    ctx.reset()
    msg = "✅ تم إنشاء الحساب!\nرقم: %s\nاسم: %s\nمدة: %s" % (num, d["adm_name"], duration_label(m))
    if d.get("adm_tgid"):
        msg += "\n📱 تلجرام: %s" % d["adm_tgid"]
        tg.send(int(d["adm_tgid"]),
                "🎉 تم إنشاء حساب جديد لك!\n📌 رقم الدخول: <b>%s</b>\n👤 %s\n📅 المدة: %s\n\n"
                "لتسجيل الدخول: /start ثم «تسجيل الدخول»." % (num, esc(d["adm_name"]), duration_label(m)),
                kb([("🏠 القائمة", "m:home")]))
    ctx.send(msg, kb([("👤 تفاصيل", "adm:c:%s" % num), ("🆕 آخر", "adm:newuser"), HOME_BTN]))


# ─────────── إضافة حساب إضافي لمستخدم موجود ───────────
def _add_account_to_user(ctx, client_num):
    links = db.rows("SELECT DISTINCT telegram_id FROM bot_user_accounts WHERE client_num = :n", n=client_num)
    if not links:
        ctx.reply("⚠️ الحساب غير مرتبط بأي مستخدم تلجرام.", kb([("👤 تفاصيل", "adm:c:%s" % client_num), HOME_BTN]))
        return
    tgid = int(links[0]["telegram_id"])
    ctx.go("adm:addacct_name", adm_tgid=tgid)
    ctx.reply("➕ <b>إضافة حساب إضافي</b>\nالمستخدم تلجرام: <code>%s</code>\n\nأدخل اسم الحساب الجديد:" % tgid,
              kb([HOME_BTN]))


@on_state("adm:addacct_name")
def st_addacct_name(ctx):
    v = core.clean_text(ctx.text, 100, True)
    if not v: ctx.send("أدخل الاسم:"); return
    ctx.go("adm:addacct_num", adm_name=v); ctx.send("أدخل رقم العميل الجديد:")


@on_state("adm:addacct_num")
def st_addacct_num(ctx):
    n = parse_int(ctx.text, 1, 2147483647)
    if n is None: ctx.send("أدخل رقماً:"); return
    if db.one("SELECT num FROM clients_table WHERE num = :n", n=n):
        ctx.send("⚠️ مستخدم. اختر آخر:"); return
    ctx.go("adm:addacct_email", adm_num=n); ctx.send("أدخل الإيميل:")


@on_state("adm:addacct_email")
def st_addacct_email(ctx):
    e = core.clean_text(ctx.text, 150)
    if not e or "@" not in e: ctx.send("إيميل غير صحيح:"); return
    if db.one("SELECT num FROM clients_table WHERE LOWER(email) = :e", e=e.lower()):
        ctx.send("⚠️ مستخدم. أدخل آخر:"); return
    ctx.go("adm:addacct_pass", adm_email=e); ctx.send("أدخل كلمة المرور:")


@on_state("adm:addacct_pass")
def st_addacct_pass(ctx):
    pw = ctx.text or ""
    ctx.delete_user_message()
    if len(pw) < 8: ctx.send("8 أحرف على الأقل:"); return
    ctx.go("adm:addacct_months", adm_pw=pw); ctx.send("أدخل عدد الأشهر:")


@on_state("adm:addacct_months")
def st_addacct_months(ctx):
    m = parse_int(ctx.text, 1, 999)
    if m is None: ctx.send("أدخل عدداً:"); return
    d = ctx.data; tgid = d["adm_tgid"]
    try:
        with db.tx() as t:
            t.run("INSERT INTO clients_table (num, name, email, password_hash, subscription_months, "
                  "subscription_duration, money) VALUES (:n, :nm, :e, :p, :m, :dur, 0)",
                  n=d["adm_num"], nm=d["adm_name"], e=d["adm_email"],
                  p=store_password(d["adm_pw"]), m=m, dur=duration_label(m))
            t.run("INSERT INTO bot_user_accounts (telegram_id, client_num, added_by) "
                  "VALUES (:t, :c, :a)", t=tgid, c=d["adm_num"], a=ctx.user_id)
            core.audit("ADMIN_ADD_ACCOUNT", ctx, client_num=d["adm_num"],
                       details="tgid=%s months=%s" % (tgid, m), t=t)
    except Exception as e:
        if "UNIQUE" in str(e) or "ORA-00001" in str(e):
            ctx.reset()
            ctx.send("⚠️ الرقم أو الإيميل مستخدم.", kb([("👤 تفاصيل", "adm:c:%s" % d.get("adm_num")), HOME_BTN]))
            return
        raise
    num = d["adm_num"]; ctx.reset()
    tg.send(tgid, "🎉 تم إضافة حساب جديد لك!\n📌 رقم: <b>%s</b>\n👤 %s\n📅 %s\n\n"
                  "استخدم زر «🔄 تبديل الحساب» في القائمة الرئيسية."
           % (num, esc(d["adm_name"]), duration_label(m)), kb([("🏠 القائمة", "m:home")]))
    ctx.send("✅ تم إضافة الحساب %s وربطه بـ %s." % (num, tgid),
             kb([("👤 تفاصيل", "adm:c:%s" % num), ("📱 حسابات المستخدم", "adm:usraccts:%s" % tgid), HOME_BTN]))


def _show_tg_accounts(ctx, tgid):
    rows = core.user_accounts(tgid)
    if not rows:
        ctx.reply("⚠️ لا حسابات مرتبطة.", kb([HOME_BTN])); return
    lines = ["📱 <b>حسابات المستخدم</b> <code>%s</code>\n" % tgid]; btns = []
    for r in rows:
        dl = r.get("days_left")
        st = "⛔" if (r.get("is_active") is not None and int(r["is_active"]) == 0) else (
            "❌" if (dl is not None and dl < 0) else "✅")
        lines.append("%s <b>%s</b> (رقم %s) — %s" % (st, esc(r["name"]), r["client_num"], fmt_date(r.get("expiry_date"))))
        btns.append([("👤 %s (%s)" % ((r["name"] or "")[:20], r["client_num"]), "adm:c:%s" % r["client_num"])])
    btns.append([HOME_BTN])
    ctx.reply("\n".join(lines), kb(*btns))


@on_state("adm:broadcast")
def st_broadcast(ctx):
    msg = (ctx.text or "").strip()
    if not msg: ctx.send("أدخل نص الرسالة:"); return
    users = db.rows("SELECT DISTINCT telegram_id FROM bot_users WHERE client_num IS NOT NULL")
    sent = 0
    for u in users:
        if tg.send(int(u["telegram_id"]), "📢 <b>رسالة من الإدارة</b>\n\n" + esc(msg)): sent += 1
    core.audit("ADMIN_BROADCAST", ctx, details="%s users" % sent)
    ctx.reset()
    ctx.send("✅ أُرسلت إلى %s مستخدم." % sent, kb([HOME_BTN]))


def _stats(ctx):
    stats = db.one(
        "SELECT "
        "(SELECT COUNT(*) FROM clients_table) AS total_users, "
        "(SELECT COUNT(*) FROM clients_table WHERE is_active = 1) AS active_users, "
        "(SELECT COUNT(*) FROM clients_table WHERE expiry_date < datetime('now','localtime')) AS expired_users, "
        "(SELECT COUNT(*) FROM clients_table WHERE account_type = 'تجاري') AS shops, "
        "(SELECT COUNT(*) FROM clients_table WHERE account_type = 'فردي') AS individuals, "
        "(SELECT COUNT(*) FROM bot_sub_requests WHERE status='PENDING') AS pending, "
        "(SELECT COUNT(*) FROM bot_user_accounts) AS total_links, "
        "(SELECT COUNT(DISTINCT telegram_id) FROM bot_user_accounts) AS total_tg_users, "
        "(SELECT COUNT(*) FROM personal_expenses) AS total_expenses, "
        "(SELECT NVL(SUM(amount), 0) FROM personal_expenses) AS sum_expenses, "
        "(SELECT COUNT(*) FROM personal_income) AS total_income_rows, "
        "(SELECT NVL(SUM(amount), 0) FROM personal_income) AS sum_income, "
        "(SELECT COUNT(*) FROM personal_debts) AS total_pdebts, "
        "(SELECT COUNT(*) FROM personal_notes) AS total_notes, "
        "(SELECT COUNT(*) FROM personal_goals) AS total_goals, "
        "(SELECT COUNT(*) FROM products_table) AS total_products, "
        "(SELECT COUNT(*) FROM shop_customers) AS total_customers, "
        "(SELECT COUNT(*) FROM shop_debts) AS total_debts "
        "FROM dual")
    text = ("📊 <b>إحصائيات البوت</b>\n\n<b>👥 المستخدمون:</b>\n"
            "الحسابات: %s | نشط: %s | منتهي: %s\n"
            "حسابات تلجرام: %s | ارتباطات: %s\n"
            "تجاري: %s | فردي: %s | طلبات: %s\n\n"
            "<b>🛒 المتجر:</b>\nالمنتجات: %s | العملاء: %s | سجلات الديون: %s\n\n"
            "<b>👤 القسم الفردي:</b>\nالمصاريف: %s بقيمة %s\nالدخل: %s بقيمة %s\n"
            "الديون الشخصية: %s | المذكرات: %s | الأهداف: %s"
            % (stats["total_users"], stats["active_users"], stats["expired_users"],
               stats["total_tg_users"], stats["total_links"],
               stats["shops"], stats["individuals"], stats["pending"],
               stats["total_products"], stats["total_customers"], stats["total_debts"],
               stats["total_expenses"], fmt_num(stats["sum_expenses"]),
               stats["total_income_rows"], fmt_num(stats["sum_income"]),
               stats["total_pdebts"], stats["total_notes"], stats["total_goals"]))
    ctx.reply(text, kb([HOME_BTN]))


@on_state("adm:price")
def st_price(ctx):
    v = parse_int(ctx.text, 0, 999_999_999_999)
    if v is None: ctx.send("أدخل سعراً:"); return
    n = db.run("UPDATE system_settings SET month_price = :p_v WHERE id = 1", p_v=v)
    if not n: db.run("INSERT INTO system_settings (id, month_price) VALUES (1, :p_v)", p_v=v)
    core.audit("SET_MONTH_PRICE", ctx, details=str(v))
    ctx.reset()
    ctx.send("✅ سعر الشهر: <b>%s</b> %s" % (fmt_num(v), cfg.SUB_PRICE_UNIT), kb([HOME_BTN]))


@on_state("adm:usd")
def st_usd(ctx):
    v = parse_float(ctx.text, 0.0001, 10_000_000.0)
    if v is None: ctx.send("أدخل سعر الدولار:"); return
    ctx.go("adm:sar", adm_usd=v); ctx.send("أدخل سعر <b>الريال السعودي</b>:")


@on_state("adm:sar")
def st_sar(ctx):
    v = parse_float(ctx.text, 0.0001, 10_000_000.0)
    usd = ctx.data.get("adm_usd")
    if v is None or usd is None: ctx.send("أدخل السعر:"); return
    n = db.run("UPDATE exchange_rates SET usd_price = :p_u, sar_price = :p_s WHERE id = 1", p_u=usd, p_s=v)
    if not n: db.run("INSERT INTO exchange_rates (id, usd_price, sar_price) VALUES (1, :p_u, :p_s)", p_u=usd, p_s=v)
    core.audit("SET_RATES", ctx, details="usd=%s sar=%s" % (usd, v))
    ctx.reset()
    ctx.send("✅ الأسعار:\n💵 الدولار = %s\n🇸🇦 السعودي = %s" % (fmt_num(usd), fmt_num(v)), kb([HOME_BTN]))
'''

# ════════════════════ router.py ════════════════════
SOURCES['router'] = r'''"""توجيه التحديثات القادمة من تلجرام."""
from __future__ import annotations
import collections, logging
import accounts, admin, core, menus, personal, pickers, reports, shop, subs, support, tg
from config import cfg
from core import CB_H, LOCK, MEDIA_STATES, STATE_H, Ctx, esc
log = logging.getLogger("router")

FREE_CB_WHEN_EXPIRED = {"sub", "acct", "adm", "auth", "support"}
BUTTON_STATES = {"sale:negq", "sale:confirm", "imp:confirm", "pay:fullq", "setup:country", "setup:currency"}

HELP = ("ℹ️ <b>المساعدة</b>\n\n/start — البدء\n/menu — القائمة\n/subscription — اشتراكي\n"
        "/cancel — إلغاء\n/logout — خروج\n/id — رقم حسابي\n/contact — التواصل\n\n"
        "💡 يمكنك كتابة الأرقام بالعربية أو الإنجليزية.")

_seen = collections.deque(); _seen_set = set(); _SEEN_MAX = 3000


def _dup(update_id):
    if update_id is None: return False
    if update_id in _seen_set: return True
    if len(_seen) >= _SEEN_MAX: _seen_set.discard(_seen.popleft())
    _seen.append(update_id); _seen_set.add(update_id)
    return False


def handle_update(update):
    ctx = Ctx(update)
    if ctx.chat_id is None or ctx.user_id is None or ctx.chat_type != "private": return
    with LOCK:
        if _dup(ctx.update_id): return
        try: _process(ctx)
        except Exception as e:
            log.exception("update %s failed", ctx.update_id); _fail(ctx, e)


def _fail(ctx, e):
    try:
        ctx.answer()
        msg = "⚠️ خطأ غير متوقع. أرسل /menu."
        if ctx.is_admin: msg += "\n<code>%s</code>" % esc(str(e)[:350])
        tg.send(ctx.chat_id, msg)
    except Exception: log.exception("failed to report error")


def _process(ctx):
    if ctx.is_cb: ctx.answer()
    ctx.load_session()
    num = ctx.sess.get("client_num")
    if num:
        ctx.client = core.fetch_client(num)
        if ctx.client is None: ctx.unlink()
        else: ctx.sub = subs.status(ctx.client)
    if ctx.is_cb: return _cb(ctx)
    text = (ctx.text or "").strip()
    if text.startswith("/"): return _cmd(ctx, text)
    return _state(ctx)


def _home_or_expired(ctx):
    if ctx.sub and not ctx.sub["ok"]: return subs.show_expired(ctx)
    return menus.home(ctx)


def _cmd(ctx, text):
    cmd = text.split()[0].split("@")[0].lower()
    if cmd == "/id":
        ctx.send("🆔 رقم حسابك: <code>%s</code>" % ctx.user_id); return
    if cmd == "/help":
        ctx.send(HELP); return
    if cmd == "/contact":
        ctx.args = ["home"]; return CB_H["support"](ctx)
    ctx.reset()
    if cmd in ("/start", "/menu", "/cancel"):
        if ctx.client: return _home_or_expired(ctx)
        return accounts.start(ctx, fresh=True)
    if cmd in ("/subscription", "/sub"):
        if ctx.client: return subs.home(ctx) if ctx.sub["ok"] else subs.show_expired(ctx)
        return accounts.start(ctx, fresh=True)
    if cmd == "/logout":
        if ctx.client: return accounts.logout(ctx)
        return accounts.start(ctx, fresh=True)
    if cmd == "/admin":
        if not ctx.is_admin:
            ctx.send("⛔ للمدير فقط."); return
        ctx.args = ["home"]; return CB_H["adm"](ctx)
    ctx.send("أمر غير معروف. /help للمساعدة.")


def _cb(ctx):
    parts = ctx.cb.split(":")
    prefix, ctx.args = parts[0], parts[1:]
    h = CB_H.get(prefix)
    if h is None:
        ctx.answer("زر غير معروف"); return
    if prefix in ("adm", "auth", "support"): return h(ctx)
    if not ctx.client:
        ctx.send("سجّل الدخول أولاً: /start"); return
    if not ctx.sub["ok"] and prefix not in FREE_CB_WHEN_EXPIRED:
        return subs.show_expired(ctx)
    return h(ctx)


def _state(ctx):
    st = ctx.state
    if not st:
        if ctx.client:
            if ctx.sub["ok"]: return menus.home(ctx, note="👇 اختر من القائمة")
            return subs.show_expired(ctx)
        return accounts.start(ctx, fresh=True)
    if st in BUTTON_STATES:
        ctx.send("👆 اضغط زراً من الرسالة، أو /cancel."); return
    h = STATE_H.get(st)
    if h is None:
        ctx.reset()
        return _home_or_expired(ctx) if ctx.client else accounts.start(ctx, fresh=True)
    if st.startswith(("reg:", "login:")):
        if ctx.client:
            ctx.reset(); return _home_or_expired(ctx)
    elif st.startswith("adm:"):
        if not ctx.is_admin:
            ctx.reset(); ctx.send("⛔ غير مسموح."); return
    else:
        if not ctx.client:
            ctx.reset(); return accounts.start(ctx, fresh=True)
        if not ctx.sub["ok"] and st != "sub:proof":
            ctx.reset(); return subs.show_expired(ctx)
    if ctx.text is None and st not in MEDIA_STATES:
        ctx.send("أرسل نصاً (أو /cancel)."); return
    return h(ctx)
'''

# ════════════════════ server.py ════════════════════
SOURCES['server'] = r'''"""خادم الويب (Webhook)."""
from __future__ import annotations
import hmac, json, logging, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import db, router, subs, tg
from config import cfg
log = logging.getLogger("server")
STATE = {"schema": None, "webhook": None, "db_error": None}
_started = False; _start_lock = threading.Lock()
STATUS_LINES = {200: "200 OK", 400: "400 Bad Request", 401: "401 Unauthorized", 403: "403 Forbidden",
                404: "404 Not Found", 413: "413 Payload Too Large", 500: "500 Internal Server Error"}


def startup():
    if not cfg.BOT_TOKEN:
        log.error("BOT_TOKEN غير موجود"); return
    try:
        STATE["schema"] = db.ensure_schema(); STATE["db_error"] = None
        log.info("schema: %s", STATE["schema"])
    except Exception as e:
        STATE["db_error"] = str(e)[:300]; log.error("DB init failed: %s", e)
    tg.set_commands()
    if cfg.PUBLIC_URL:
        url = cfg.PUBLIC_URL + "/webhook"
        ok = tg.set_webhook(url, cfg.WEBHOOK_SECRET)
        STATE["webhook"] = url if ok else "FAILED: " + tg.last_error()
        log.info("webhook %s", STATE["webhook"])
    else:
        STATE["webhook"] = "PUBLIC_URL غير محدد"; log.warning("PUBLIC_URL غير محدد")


def ensure_started():
    global _started
    if _started: return
    with _start_lock:
        if not _started:
            _started = True
            threading.Thread(target=startup, daemon=True).start()


def _json(status, obj):
    return status, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _text(status, s): return status, "text/plain; charset=utf-8", s.encode("utf-8")


def _key_ok(query, headers):
    if not cfg.CRON_SECRET: return False
    k = (query.get("key") or [""])[0] or headers.get("x-cron-key", "")
    return hmac.compare_digest(k, cfg.CRON_SECRET)


def process_http(method, path, query, headers, body):
    ensure_started()
    path = path.rstrip("/") or "/"
    if path == "/" and method in ("GET", "HEAD"): return _text(200, "OK")
    if path == "/webhook":
        if method != "POST": return _text(404, "not found")
        if not hmac.compare_digest(headers.get("x-telegram-bot-api-secret-token", ""), cfg.WEBHOOK_SECRET):
            return _text(403, "forbidden")
        try: update = json.loads(body.decode("utf-8"))
        except Exception: return _text(400, "bad request")
        try: router.handle_update(update)
        except Exception: log.exception("handle_update error")
        return _text(200, "ok")
    if path == "/health" and method in ("GET", "HEAD"):
        try: db.ping(); db_state = "ok"
        except Exception as e:
            db_state = "error"; STATE["db_error"] = str(e)[:300]
        out = {"status": "ok", "db": db_state}
        if _key_ok(query, headers):
            out.update(webhook=STATE["webhook"], schema=STATE["schema"], db_error=STATE["db_error"],
                       registration=cfg.REGISTRATION_MODE, admins=len(cfg.ADMIN_IDS))
        return _json(200, out)
    if path == "/cron/reminders" and method in ("GET", "POST"):
        if not _key_ok(query, headers): return _text(403, "forbidden")
        try: return _json(200, {"sent": subs.run_reminders()})
        except Exception as e:
            log.exception("reminders failed"); return _json(500, {"error": str(e)[:200]})
    return _text(404, "not found")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"; server_version = "ShopBot"

    def _do(self, method):
        u = urlparse(self.path)
        try: length = int(self.headers.get("Content-Length") or 0)
        except ValueError: length = 0
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
        if method != "HEAD": self.wfile.write(data)

    def do_GET(self): self._do("GET")
    def do_HEAD(self): self._do("HEAD")
    def do_POST(self): self._do("POST")
    def log_message(self, fmt, *args): log.debug("http: " + fmt, *args)


def run():
    ensure_started()
    srv = ThreadingHTTPServer(("0.0.0.0", cfg.PORT), Handler)
    srv.daemon_threads = True
    log.info("listening on 0.0.0.0:%s", cfg.PORT)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


def application(environ, start_response):
    try: length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError: length = 0
    body = environ["wsgi.input"].read(length) if 0 < length <= 1_000_000 else b""
    headers = {}
    for k, v in environ.items():
        if k.startswith("HTTP_"): headers[k[5:].replace("_", "-").lower()] = v
    status, ctype, data = process_http(environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO", "/"),
                                       parse_qs(environ.get("QUERY_STRING", "")), headers, body)
    start_response(STATUS_LINES.get(status, "%d" % status),
                   [("Content-Type", ctype), ("Content-Length", str(len(data)))])
    return [data]
'''

# ════════════════════ app.py ════════════════════
SOURCES['app'] = r'''"""نقطة التشغيل."""
import logging
from config import cfg
logging.basicConfig(level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
from server import application, run  # noqa: E402,F401
if __name__ == "__main__": run()
'''


class _Loader(importlib.abc.Loader):
    def __init__(self, name): self.name = name
    def create_module(self, spec): return None
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


def __getattr__(name):
    if name == "application":
        import server
        return server.application
    raise AttributeError(name)


if __name__ == "__main__":
    main()





