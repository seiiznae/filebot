import os
import sqlite3
import secrets
import json
import asyncio
import re
from datetime import datetime

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommand,
    BotCommandScopeDefault, BotCommandScopeChat, MessageEntity
)
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters
)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN belum diset di environment variable")

# Keamanan: daftar admin default. Owner pertama tidak boleh dihapus lewat panel.
DEFAULT_ADMIN_IDS = {1137740036, 1779151962, 1943239073, 7186342193}
OWNER_ID = 1137740036
CHANNEL_ID = -1001967813918
FREE_GROUP_ID = -1002228292417
MEMBERSHIP_GROUP_ID = -1002115664800

DEFAULT_CHANNEL_LINK = "https://t.me/Nakahoshi"
DEFAULT_FREE_GROUP_LINK = "https://t.me/+lYiuGXIVy1JkYWE9"
DEFAULT_PAYMENT_LINK = "https://t.me/nakanosqbot?start=NakaFileBOT"
DEFAULT_OWNER_LINK = "https://t.me/seiizn"
DB_NAME = "files.db"

DEFAULT_START_TEXT = """╭━━━━━━━━━━━━━━━━━━━━╮
       ✦ NAKAHOSHI ✦
      FILE SHARE BOT
╰━━━━━━━━━━━━━━━━━━━━╯

🤖 BOT KHUSUS FILE SHARE
   NON-MEMBERSHIP USER

Jika Anda sudah bergabung ke Membership Nakahoshi, silakan langsung menikmati konten Membership.

🎬 @Nakahoshi

━━━━━━━━━━━━━━━━━━━━

Belum menjadi member?

⭐ Membership Nakahoshi
💰 Rp15.000 / 30 Hari

Dapatkan akses Membership dan nikmati konten lengkap.

👇 Pilih akses Anda:"""

DEFAULT_FSUB_TEXT = "UNTUK FREE USER, SILAHKAN BERGABUNG TERLEBIH DAHULU KE GRUP DAN CHANNEL UTAMA KAMI UNTUK MENDAPATKAN FILE!!\n\nSETELAH BERGABUNG KE CHANNEL DAN GRUP, SILAHKAN TEKAN TOMBOL 🔄 CEK AKSES DI BAWAH UNTUK MENDAPATKAN FILE.\n\n━━━━━━━━━━━━━━━━━━━━\n\n💎 MEMBERSHIP NAKAHOSHI\n\nBosan menggunakan bot file?\nNggak perlu ribet cari file atau join sana-sini.\nLangsung saja tekan tombol ⭐ JOIN MEMBERSHIP di bawah!"

DEFAULT_BANNED_TEXT = "🚫 AKUN KAMU TELAH DI-BANNED.\n\nJika merasa ini kesalahan, silakan hubungi Customer Service."
DEFAULT_DENIED_TEXT = "🚫 COMMAND KHUSUS ADMIN.\n\nKamu tidak memiliki izin untuk menggunakan command ini."
DEFAULT_NOT_FOUND_TEXT = "❌ File tidak ditemukan atau sudah tidak tersedia."
DEFAULT_INVALID_LINK_TEXT = "❌ Link file tidak valid."
DEFAULT_ACCESS_OK_TEXT = "✅ AKSES OK\n\n📤 File sedang dikirim..."
DEFAULT_DELETE_NOTICE = "⚠️ FILE INI AKAN DIHAPUS OTOMATIS DALAM {minutes} MENIT."
DEFAULT_CS_TEXT = "🛠️ CUSTOMER SERVICE NAKAHOSHI\n\nJika terdapat masalah pada file, akses, atau akun, silakan hubungi admin kami."
DEFAULT_UNBAN_TEXT = "🚫 Akun kamu sedang dibanned.\n\nSilakan ajukan permintaan unban kepada admin melalui tombol di bawah."
DEFAULT_MAINTENANCE_TEXT = "🔧 NAKAHOSHI SEDANG DALAM PEMELIHARAAN.\n\nSilakan coba kembali nanti."

pending_batches = {}
admin_sessions = {}


def db():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table, column, definition):
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = db(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS files (code TEXT PRIMARY KEY, file_id TEXT NOT NULL, file_type TEXT NOT NULL, caption TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS batches (code TEXT PRIMARY KEY, created_by INTEGER, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS batch_items (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_code TEXT NOT NULL, file_id TEXT NOT NULL, file_type TEXT NOT NULL, caption TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, first_seen TEXT, last_seen TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_at TEXT, added_by INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, reason TEXT, banned_at TEXT, banned_by INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_commands (command TEXT PRIMARY KEY, description TEXT, config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)")
    ensure_column(conn, "files", "caption_entities", "TEXT")
    ensure_column(conn, "batch_items", "caption_entities", "TEXT")
    defaults = {
        "start_text": DEFAULT_START_TEXT,
        "start_media": "",
        "start_media_type": "",
        "start_entities": "[]",
        "start_config": json.dumps({"text": DEFAULT_START_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": [["⭐ JOIN MEMBERSHIP", "url", DEFAULT_PAYMENT_LINK], ["📢 JOIN CHANNEL", "url", DEFAULT_CHANNEL_LINK], ["👥 JOIN GROUP", "url", DEFAULT_FREE_GROUP_LINK], ["👤 OWNER BOT", "url", DEFAULT_OWNER_LINK]]}, ensure_ascii=False),
        "fsub_config": json.dumps({"text": DEFAULT_FSUB_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": [["📢 JOIN CHANNEL", "url", DEFAULT_CHANNEL_LINK], ["👥 JOIN GROUP", "url", DEFAULT_FREE_GROUP_LINK], ["🔄 CEK AKSES", "check", ""], ["⭐ JOIN MEMBERSHIP", "url", DEFAULT_PAYMENT_LINK]]}, ensure_ascii=False),
        "membership_price": "Rp15.000 / 30 Hari",
        "channel_link": DEFAULT_CHANNEL_LINK,
        "free_group_link": DEFAULT_FREE_GROUP_LINK,
        "payment_link": DEFAULT_PAYMENT_LINK,
        "owner_link": DEFAULT_OWNER_LINK,
        "cs_link": DEFAULT_OWNER_LINK,
        "protect_content": "1",
        "auto_delete_enabled": "0",
        "auto_delete_minutes": "10",
        "auto_delete_notice": json.dumps({"text": DEFAULT_DELETE_NOTICE, "entities": [], "media_id": "", "media_type": "", "buttons": []}, ensure_ascii=False),
        "banned_message": json.dumps({"text": DEFAULT_BANNED_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": []}, ensure_ascii=False),
        "denied_message": json.dumps({"text": DEFAULT_DENIED_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": []}, ensure_ascii=False),
        "not_found_message": json.dumps({"text": DEFAULT_NOT_FOUND_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": []}, ensure_ascii=False),
        "invalid_link_message": json.dumps({"text": DEFAULT_INVALID_LINK_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": []}, ensure_ascii=False),
        "access_ok_message": json.dumps({"text": DEFAULT_ACCESS_OK_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": []}, ensure_ascii=False),
        "cs_config": json.dumps({"text": DEFAULT_CS_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": [["👤 HUBUNGI ADMIN", "url", DEFAULT_OWNER_LINK]]}, ensure_ascii=False),
        "unban_config": json.dumps({"text": DEFAULT_UNBAN_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": [["📝 AJUKAN UNBAN", "url", DEFAULT_OWNER_LINK]]}, ensure_ascii=False),
        "maintenance_config": json.dumps({"text": DEFAULT_MAINTENANCE_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": []}, ensure_ascii=False),
        "maintenance": "0",
    }
    for key, value in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))
    for uid in DEFAULT_ADMIN_IDS:
        cur.execute("INSERT OR IGNORE INTO admins(user_id,added_at,added_by) VALUES(?,?,?)", (uid, datetime.now().isoformat(timespec="seconds"), OWNER_ID))
    default_commands = {
        "peraturan": ("Peraturan Nakahoshi", {"text": "📜 PERATURAN NAKAHOSHI\n\nSilakan isi peraturan Nakahoshi melalui Admin Panel.", "entities": [], "media_id": "", "media_type": "", "buttons": []}),
        "unbanned": ("Pengajuan unban akun", {"text": DEFAULT_UNBAN_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": [["📝 AJUKAN UNBAN", "url", DEFAULT_OWNER_LINK]]}),
        "joinvip": ("Membership Nakahoshi", {"text": "⭐ JOIN VIP\n\nCuma Rp15.000 / 30 Hari. Murah banget 😝", "entities": [], "media_id": "", "media_type": "", "buttons": [["⭐ JOIN MEMBERSHIP", "url", DEFAULT_PAYMENT_LINK]]}),
        "listchannel": ("List channel Nakahoshi", {"text": "📚 LIST CHANNEL NAKAHOSHI\n\nSilakan pilih channel/folder yang ingin kamu buka 👇", "entities": [], "media_id": "", "media_type": "", "buttons": []}),
        "customerservice": ("Hubungi Customer Service", {"text": DEFAULT_CS_TEXT, "entities": [], "media_id": "", "media_type": "", "buttons": [["👤 HUBUNGI ADMIN", "url", DEFAULT_OWNER_LINK]]}),
    }
    for command, (desc, config) in default_commands.items():
        cur.execute("INSERT OR IGNORE INTO user_commands(command,description,config,enabled) VALUES(?,?,?,1)", (command, desc, json.dumps(config, ensure_ascii=False)))
    conn.commit(); conn.close()


def get_setting(key):
    conn = db(); row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone(); conn.close()
    return row["value"] if row else ""


def set_setting(key, value):
    conn = db(); conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value)); conn.commit(); conn.close()


def get_admin_ids():
    conn = db(); rows = conn.execute("SELECT user_id FROM admins").fetchall(); conn.close()
    ids = {int(r["user_id"]) for r in rows}; ids.add(OWNER_ID); return ids


def is_admin(user_id): return user_id in get_admin_ids()


def is_banned(user_id):
    conn = db(); row = conn.execute("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,)).fetchone(); conn.close()
    return row is not None and user_id not in get_admin_ids()


def save_user(user):
    if not user: return
    now = datetime.now().isoformat(timespec="seconds")
    conn = db(); conn.execute("""INSERT INTO users(user_id,username,first_name,first_seen,last_seen) VALUES(?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen""",
        (user.id, user.username or "", user.first_name or "", now, now)); conn.commit(); conn.close()


def serialize_entities(entities):
    result=[]
    for e in entities or []:
        d={"type":e.type,"offset":e.offset,"length":e.length}
        for name in ("url","language","custom_emoji_id"):
            value=getattr(e,name,None)
            if value is not None: d[name]=value
        user=getattr(e,"user",None)
        if user is not None:
            d["user"]={"id":user.id,"is_bot":user.is_bot,"first_name":user.first_name or "","username":user.username}
        result.append(d)
    return result


def deserialize_entities(raw):
    try: data=json.loads(raw or "[]")
    except Exception: return []
    out=[]
    for d in data:
        try:
            kwargs={k:d[k] for k in ("type","offset","length") if k in d}
            for k in ("url","language","custom_emoji_id"):
                if k in d: kwargs[k]=d[k]
            out.append(MessageEntity(**kwargs))
        except Exception: pass
    return out


def cfg_json(text="", entities=None, media_id="", media_type="", buttons=None):
    return {"text": text or "", "entities": serialize_entities(entities) if entities is not None else [], "media_id": media_id or "", "media_type": media_type or "", "buttons": buttons or []}


def get_config(key):
    try: return json.loads(get_setting(key) or "{}")
    except Exception: return cfg_json()


def set_config(key, config): set_setting(key, json.dumps(config, ensure_ascii=False))


def user_command(command):
    conn=db(); row=conn.execute("SELECT * FROM user_commands WHERE command=?",(command,)).fetchone(); conn.close(); return row


def make_code(prefix): return f"{prefix}_{secrets.token_urlsafe(10)}"


def create_file_record(file_id, file_type, caption, entities):
    code=make_code("F"); conn=db(); conn.execute("INSERT INTO files(code,file_id,file_type,caption,caption_entities) VALUES(?,?,?,?,?)",(code,file_id,file_type,caption or "",json.dumps(serialize_entities(entities),ensure_ascii=False))); conn.commit(); conn.close(); return code


def create_batch(user_id, items):
    code=make_code("B"); conn=db(); conn.execute("INSERT INTO batches(code,created_by,created_at) VALUES(?,?,?)",(code,user_id,datetime.now().isoformat(timespec="seconds")))
    conn.executemany("INSERT INTO batch_items(batch_code,file_id,file_type,caption,caption_entities) VALUES(?,?,?,?,?)",[(code,x[0],x[1],x[2] or "",json.dumps(serialize_entities(x[3]),ensure_ascii=False)) for x in items]); conn.commit(); conn.close(); return code


def get_file(code):
    conn=db(); row=conn.execute("SELECT * FROM files WHERE code=?",(code,)).fetchone(); conn.close(); return row


def get_batch(code):
    conn=db(); rows=conn.execute("SELECT * FROM batch_items WHERE batch_code=? ORDER BY id",(code,)).fetchall(); conn.close(); return rows


def build_keyboard(buttons, code=None):
    rows=[]
    for b in buttons or []:
        if len(b)<2: continue
        label=b[0]; kind=b[1]; value=b[2] if len(b)>2 else ""
        if kind=="check" and code: btn=InlineKeyboardButton(label,callback_data=f"check:{code}")
        elif kind=="url" and value: btn=InlineKeyboardButton(label,url=value)
        else: continue
        if not rows or len(rows[-1])>=2: rows.append([])
        rows[-1].append(btn)
    return InlineKeyboardMarkup(rows) if rows else None


def access_keyboard(code):
    cfg=get_config("fsub_config")
    return build_keyboard(cfg.get("buttons"),code) or InlineKeyboardMarkup([[InlineKeyboardButton("📢 JOIN CHANNEL",url=get_setting("channel_link")),InlineKeyboardButton("👥 JOIN GROUP",url=get_setting("free_group_link"))],[InlineKeyboardButton("🔄 CEK AKSES",callback_data=f"check:{code}")],[InlineKeyboardButton("⭐ JOIN MEMBERSHIP",url=get_setting("payment_link"))]])


def start_keyboard(): return build_keyboard(get_config("start_config").get("buttons"))


async def member_is_inside(bot, chat_id, user_id):
    try:
        member=await bot.get_chat_member(chat_id,user_id)
        return member.status in {"member","administrator","creator","restricted"}
    except Exception: return False


async def check_access(bot,user_id):
    if is_admin(user_id): return True
    if is_banned(user_id): return False
    if await member_is_inside(bot,MEMBERSHIP_GROUP_ID,user_id): return True
    return await member_is_inside(bot,CHANNEL_ID,user_id) and await member_is_inside(bot,FREE_GROUP_ID,user_id)


def protect(): return get_setting("protect_content") == "1"


async def send_cfg(chat_id, cfg, bot, code=None, reply_markup=None, protect_content=None):
    markup=reply_markup or build_keyboard(cfg.get("buttons"),code)
    entities=deserialize_entities(json.dumps(cfg.get("entities",[]),ensure_ascii=False))
    text=cfg.get("text") or ""
    kwargs={"chat_id":chat_id,"protect_content":protect() if protect_content is None else protect_content}
    if markup: kwargs["reply_markup"]=markup
    media_id=cfg.get("media_id"); media_type=cfg.get("media_type")
    if media_id:
        if text: kwargs["caption"]=text; kwargs["caption_entities"]=entities
        if media_type=="photo": return await bot.send_photo(photo=media_id,**kwargs)
        if media_type=="video": return await bot.send_video(video=media_id,**kwargs)
        if media_type=="animation": return await bot.send_animation(animation=media_id,**kwargs)
        if media_type=="document": return await bot.send_document(document=media_id,**kwargs)
        if media_type=="audio": return await bot.send_audio(audio=media_id,**kwargs)
    if text: return await bot.send_message(text=text,entities=entities,**kwargs)
    return None


async def send_file(chat_id,item,bot):
    entities=deserialize_entities(item["caption_entities"] if "caption_entities" in item.keys() else "[]")
    kwargs={"chat_id":chat_id,"protect_content":protect()}
    if item["caption"]: kwargs["caption"]=item["caption"]; kwargs["caption_entities"]=entities
    t=item["file_type"]; fid=item["file_id"]
    if t=="video": return await bot.send_video(video=fid,**kwargs)
    if t=="photo": return await bot.send_photo(photo=fid,**kwargs)
    if t=="animation": return await bot.send_animation(animation=fid,**kwargs)
    if t=="document": return await bot.send_document(document=fid,**kwargs)
    if t=="audio": return await bot.send_audio(audio=fid,**kwargs)
    return None


async def schedule_delete(context, chat_id, message_ids, minutes):
    async def task():
        await asyncio.sleep(minutes*60)
        for mid in message_ids:
            try: await context.bot.delete_message(chat_id,mid)
            except Exception: pass
    asyncio.create_task(task())


async def deliver(update,context,code):
    chat_id=update.effective_chat.id; sent=[]
    if code.startswith("B_"):
        rows=get_batch(code)
        if not rows: await send_cfg(chat_id,get_config("not_found_message"),context.bot); return
        for row in rows:
            msg=await send_file(chat_id,row,context.bot)
            if msg: sent.append(msg.message_id)
    else:
        row=get_file(code)
        if not row: await send_cfg(chat_id,get_config("not_found_message"),context.bot); return
        msg=await send_file(chat_id,row,context.bot)
        if msg: sent.append(msg.message_id)
    if sent and get_setting("auto_delete_enabled")=="1":
        minutes=max(1,int(get_setting("auto_delete_minutes") or "10"))
        notice=get_config("auto_delete_notice"); notice["text"]=(notice.get("text") or DEFAULT_DELETE_NOTICE).replace("{minutes}",str(minutes))
        nmsg=await send_cfg(chat_id,notice,context.bot)
        if nmsg: sent.append(nmsg.message_id)
        await schedule_delete(context,chat_id,sent,minutes)


async def show_page(update,context,command):
    row=user_command(command)
    if not row or not row["enabled"]: await update.message.reply_text("❌ Command tidak tersedia.",protect_content=protect()); return
    await send_cfg(update.effective_chat.id,json.loads(row["config"]),context.bot)


async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user); uid=update.effective_user.id
    if is_banned(uid): await send_cfg(update.effective_chat.id,get_config("banned_message"),context.bot); return
    if get_setting("maintenance")=="1" and not is_admin(uid): await send_cfg(update.effective_chat.id,get_config("maintenance_config"),context.bot); return
    if context.args:
        code=context.args[0]
        if not (code.startswith("F_") or code.startswith("B_")): await send_cfg(update.effective_chat.id,get_config("invalid_link_message"),context.bot); return
        if not await check_access(context.bot,uid): await send_cfg(update.effective_chat.id,get_config("fsub_config"),context.bot,code=code,reply_markup=access_keyboard(code)); return
        await send_cfg(update.effective_chat.id,get_config("access_ok_message"),context.bot); await deliver(update,context,code); return
    await send_cfg(update.effective_chat.id,load_target("start"),context.bot)


async def check_button(update,context):
    q=update.callback_query
    if is_banned(q.from_user.id): await q.answer("🚫 Kamu sedang dibanned.",show_alert=True); return
    if not await check_access(context.bot,q.from_user.id): await q.answer("❌ Kamu belum memenuhi syarat akses.",show_alert=True); return
    await q.answer()
    try: await q.edit_message_text(get_config("access_ok_message").get("text") or DEFAULT_ACCESS_OK_TEXT)
    except Exception: pass
    await deliver(update,context,q.data.split(":",1)[1])


# ---------- Admin editor ----------
def admin_home_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📊 Statistik",callback_data="adm:stats"),InlineKeyboardButton("📁 File",callback_data="adm:files")],[InlineKeyboardButton("🎨 Start",callback_data="adm:page:start"),InlineKeyboardButton("📢 FSUB",callback_data="adm:page:fsub")],[InlineKeyboardButton("👤 User Command",callback_data="adm:commands"),InlineKeyboardButton("📝 System Message",callback_data="adm:system")],[InlineKeyboardButton("👑 Admin",callback_data="adm:admins"),InlineKeyboardButton("🚫 Ban User",callback_data="adm:bans")],[InlineKeyboardButton("🗑️ Auto Delete",callback_data="adm:autodel"),InlineKeyboardButton("📢 Broadcast",callback_data="adm:broadcast")],[InlineKeyboardButton("💾 Backup",callback_data="adm:backup"),InlineKeyboardButton("🔧 Maintenance",callback_data="adm:maintenance")]])


def back_home(): return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali",callback_data="adm:home")]])
def cancel_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("❌ BATAL",callback_data="adm:cancel")]])


def editor_menu(uid,target):
    return InlineKeyboardMarkup([[InlineKeyboardButton("📝 Text",callback_data=f"edit:text:{target}"),InlineKeyboardButton("🖼️ Media",callback_data=f"edit:media:{target}")],[InlineKeyboardButton("🔘 Buttons",callback_data=f"edit:buttons:{target}"),InlineKeyboardButton("👁️ Preview",callback_data=f"edit:preview:{target}")],[InlineKeyboardButton("💾 Simpan",callback_data=f"edit:save:{target}"),InlineKeyboardButton("🗑️ Hapus Media",callback_data=f"edit:delmedia:{target}")],[InlineKeyboardButton("❌ Batal",callback_data="adm:cancel")]])


def load_target(target):
    if target=="start":
        cfg=get_config("start_config")
        if not cfg.get("text") and (get_setting("start_text") or get_setting("start_media")):
            cfg=cfg_json(get_setting("start_text"),deserialize_entities(get_setting("start_entities")),get_setting("start_media"),get_setting("start_media_type"),[["⭐ JOIN MEMBERSHIP","url",get_setting("payment_link")],["📢 JOIN CHANNEL","url",get_setting("channel_link")],["👥 JOIN GROUP","url",get_setting("free_group_link")],["👤 OWNER BOT","url",get_setting("owner_link")]])
        return cfg
    if target=="fsub": return get_config("fsub_config")
    if target.startswith("cmd/"):
        row=user_command(target[4:]); return json.loads(row["config"]) if row else None
    return get_config(target)


def save_target(target,cfg):
    if target=="start":
        set_config("start_config",cfg); set_setting("start_text",cfg.get("text", "")); set_setting("start_entities",json.dumps(cfg.get("entities",[]),ensure_ascii=False)); set_setting("start_media",cfg.get("media_id", "")); set_setting("start_media_type",cfg.get("media_type", ""))
    elif target=="fsub": set_config("fsub_config",cfg)
    elif target.startswith("cmd/"):
        conn=db(); conn.execute("UPDATE user_commands SET config=? WHERE command=?",(json.dumps(cfg,ensure_ascii=False),target[4:])); conn.commit(); conn.close()
    else: set_config(target,cfg)


def session(uid,target):
    s=admin_sessions.setdefault(uid,{}); s["target"]=target; s["draft"]=json.loads(json.dumps(load_target(target),ensure_ascii=False)); return s


async def admin_command(update,context):
    if not is_admin(update.effective_user.id):
        await send_cfg(update.effective_chat.id,get_config("denied_message"),context.bot); return
    await update.message.reply_text("👑 NAKAHOSHI ADMIN PANEL\n\nPilih menu:",reply_markup=admin_home_markup(),protect_content=protect())


async def admin_callback(update,context):
    q=update.callback_query; uid=q.from_user.id
    if not is_admin(uid): await q.answer("Tidak punya akses.",show_alert=True); return
    await q.answer(); data=q.data
    if data in ("adm:home","adm:cancel"): admin_sessions.pop(uid,None); await q.edit_message_text("👑 NAKAHOSHI ADMIN PANEL\n\nPilih menu:",reply_markup=admin_home_markup()); return
    if data=="adm:stats":
        conn=db(); vals=[conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0],conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],conn.execute("SELECT COUNT(*) FROM banned_users").fetchone()[0]]; conn.close(); await q.edit_message_text(f"📊 STATISTIK\n\n📁 File: {vals[0]}\n📦 Batch: {vals[1]}\n👥 User: {vals[2]}\n🚫 Banned: {vals[3]}",reply_markup=back_home()); return
    if data=="adm:files":
        conn=db(); rows=conn.execute("SELECT code,file_type FROM files ORDER BY rowid DESC LIMIT 20").fetchall(); conn.close(); await q.edit_message_text("📁 FILE TERBARU\n\n"+(("\n".join(f"{r['code']} — {r['file_type']}" for r in rows)) if rows else "Belum ada file."),reply_markup=back_home()); return
    if data in ("adm:page:start","adm:page:fsub"):
        target="start" if data.endswith("start") else "fsub"; session(uid,target); await q.edit_message_text(f"⚙️ EDIT {target.upper()}\n\nMedia + Text + Buttons + Preview.\nSemua perubahan masih draft sampai disimpan.",reply_markup=editor_menu(uid,target)); return
    if data=="adm:commands":
        conn=db(); rows=conn.execute("SELECT command,description,enabled FROM user_commands ORDER BY command").fetchall(); conn.close(); kb=[]
        for r in rows: kb.append([InlineKeyboardButton(("🟢 " if r["enabled"] else "🔴 ")+"/"+r["command"],callback_data=f"adm:cmd:{r['command']}")])
        kb.append([InlineKeyboardButton("➕ Tambah Command",callback_data="adm:addcmd")]); kb.append([InlineKeyboardButton("⬅️ Kembali",callback_data="adm:home")]); await q.edit_message_text("👤 USER COMMAND\n\nPilih command:",reply_markup=InlineKeyboardMarkup(kb)); return
    if data.startswith("adm:cmd:"):
        command=data.split(":",2)[2]; session(uid,"cmd/"+command); row=user_command(command); status="🟢 AKTIF" if row and row["enabled"] else "🔴 NONAKTIF"; base=editor_menu(uid,"cmd/"+command).inline_keyboard; base.append([InlineKeyboardButton("🔄 Aktif/Nonaktif",callback_data=f"adm:toggle:{command}"),InlineKeyboardButton("🗑️ Hapus",callback_data=f"adm:deletecmd:{command}")]); await q.edit_message_text(f"⚙️ EDIT /{command}\nStatus: {status}\n\nMedia + Text + Buttons + Preview",reply_markup=InlineKeyboardMarkup(base)); return
    if data=="adm:addcmd": admin_sessions[uid]={"action":"add_command"}; await q.edit_message_text("➕ TAMBAH COMMAND\n\nKirim format:\n/nama | Deskripsi",reply_markup=cancel_kb()); return
    if data.startswith("adm:toggle:"):
        command=data.split(":",2)[2]; conn=db(); row=conn.execute("SELECT enabled FROM user_commands WHERE command=?",(command,)).fetchone();
        if row: conn.execute("UPDATE user_commands SET enabled=? WHERE command=?",(0 if row["enabled"] else 1,command)); conn.commit()
        conn.close(); await refresh_command_menus(context.bot); await q.edit_message_text(f"🔄 /{command} diubah statusnya.",reply_markup=back_home()); return
    if data.startswith("adm:deletecmd:"):
        command=data.split(":",2)[2]; conn=db(); conn.execute("DELETE FROM user_commands WHERE command=?",(command,)); conn.commit(); conn.close(); admin_sessions.pop(uid,None); await refresh_command_menus(context.bot); await q.edit_message_text(f"🗑️ /{command} dihapus.",reply_markup=back_home()); return
    if data=="adm:system":
        keys=[("banned_message","🚫 Pesan Banned"),("denied_message","⛔ Command Admin Ditolak"),("not_found_message","❌ File Tidak Ditemukan"),("invalid_link_message","🔗 Link Tidak Valid"),("access_ok_message","✅ Akses OK"),("cs_config","🛠️ Customer Service"),("unban_config","♻️ Unban"),("auto_delete_notice","🗑️ Notifikasi Auto Delete")]; kb=[[InlineKeyboardButton(label,callback_data=f"adm:sys:{key}")] for key,label in keys]; kb.append([InlineKeyboardButton("⬅️ Kembali",callback_data="adm:home")]); await q.edit_message_text("📝 SYSTEM MESSAGE\n\nPilih pesan:",reply_markup=InlineKeyboardMarkup(kb)); return
    if data.startswith("adm:sys:"):
        target=data.split(":",2)[2]; session(uid,target); await q.edit_message_text("📝 EDIT SYSTEM MESSAGE\n\nBisa Text + Media + Buttons + Preview.",reply_markup=editor_menu(uid,target)); return
    if data=="adm:admins":
        conn=db(); rows=conn.execute("SELECT user_id FROM admins ORDER BY user_id").fetchall(); conn.close(); text="👑 ADMIN\n\n"+"\n".join(f"{r['user_id']}"+((" — OWNER") if r['user_id']==OWNER_ID else "") for r in rows); kb=[[InlineKeyboardButton("➕ Tambah Admin",callback_data="adm:addadmin")],[InlineKeyboardButton("🗑️ Hapus Admin",callback_data="adm:deladmin")],[InlineKeyboardButton("⬅️ Kembali",callback_data="adm:home")]]; await q.edit_message_text(text,reply_markup=InlineKeyboardMarkup(kb)); return
    if data=="adm:addadmin": admin_sessions[uid]={"action":"add_admin"}; await q.edit_message_text("➕ TAMBAH ADMIN\n\nKirim Telegram User ID.",reply_markup=cancel_kb()); return
    if data=="adm:deladmin": admin_sessions[uid]={"action":"del_admin"}; await q.edit_message_text("🗑️ HAPUS ADMIN\n\nKirim Telegram User ID. Owner tidak dapat dihapus.",reply_markup=cancel_kb()); return
    if data=="adm:bans":
        conn=db(); rows=conn.execute("SELECT user_id,reason FROM banned_users ORDER BY banned_at DESC LIMIT 50").fetchall(); conn.close(); text="🚫 BANNED USERS\n\n"+(("\n".join(f"{r['user_id']} — {r['reason'] or '-'}" for r in rows)) if rows else "Belum ada user banned."); kb=[[InlineKeyboardButton("🔨 Ban User",callback_data="adm:ban")],[InlineKeyboardButton("♻️ Unban User",callback_data="adm:unban")],[InlineKeyboardButton("⬅️ Kembali",callback_data="adm:home")]]; await q.edit_message_text(text,reply_markup=InlineKeyboardMarkup(kb)); return
    if data=="adm:ban": admin_sessions[uid]={"action":"ban"}; await q.edit_message_text("🔨 BAN USER\n\nKirim User ID.\nOpsional alasan: 123456789 | alasan",reply_markup=cancel_kb()); return
    if data=="adm:unban": admin_sessions[uid]={"action":"unban"}; await q.edit_message_text("♻️ UNBAN USER\n\nKirim User ID.",reply_markup=cancel_kb()); return
    if data=="adm:autodel":
        status="🟢 AKTIF" if get_setting("auto_delete_enabled")=="1" else "🔴 NONAKTIF"; await q.edit_message_text(f"🗑️ AUTO DELETE FILE\n\nStatus: {status}\nWaktu: {get_setting('auto_delete_minutes')} menit",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Aktifkan",callback_data="adm:ad:on"),InlineKeyboardButton("🔴 Matikan",callback_data="adm:ad:off")],[InlineKeyboardButton("⏱️ Atur Waktu",callback_data="adm:ad:time"),InlineKeyboardButton("📝 Notifikasi",callback_data="adm:ad:msg")],[InlineKeyboardButton("⬅️ Kembali",callback_data="adm:home")]])); return
    if data=="adm:ad:on": set_setting("auto_delete_enabled","1"); await q.edit_message_text("🟢 Auto Delete aktif.",reply_markup=back_home()); return
    if data=="adm:ad:off": set_setting("auto_delete_enabled","0"); await q.edit_message_text("🔴 Auto Delete dimatikan.",reply_markup=back_home()); return
    if data=="adm:ad:time": admin_sessions[uid]={"action":"ad_time"}; await q.edit_message_text("⏱️ Kirim jumlah menit. Contoh: 10",reply_markup=cancel_kb()); return
    if data=="adm:ad:msg": session(uid,"auto_delete_notice"); await q.edit_message_text("📝 EDIT NOTIFIKASI AUTO DELETE",reply_markup=editor_menu(uid,"auto_delete_notice")); return
    if data=="adm:broadcast": admin_sessions[uid]={"action":"broadcast"}; await q.edit_message_text("📢 BROADCAST\n\nKirim satu pesan/media yang ingin dibroadcast.\nSetelah itu gunakan /broadcast_confirm untuk mengirim.",reply_markup=cancel_kb()); return
    if data=="adm:backup":
        try:
            with open(DB_NAME,"rb") as f: await context.bot.send_document(uid,f,caption="💾 Backup database NakaFileBOT",protect_content=True)
        except Exception as e: await q.answer("Backup gagal: "+str(e)[:150],show_alert=True)
        return
    if data=="adm:maintenance":
        status="🟢 AKTIF" if get_setting("maintenance")=="1" else "🔴 NONAKTIF"; await q.edit_message_text(f"🔧 MAINTENANCE\n\nStatus: {status}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Aktifkan",callback_data="adm:maint:on"),InlineKeyboardButton("🔴 Matikan",callback_data="adm:maint:off")],[InlineKeyboardButton("📝 Edit Pesan",callback_data="adm:maint:msg")],[InlineKeyboardButton("⬅️ Kembali",callback_data="adm:home")]])); return
    if data=="adm:maint:on": set_setting("maintenance","1"); await q.edit_message_text("🟢 Maintenance aktif.",reply_markup=back_home()); return
    if data=="adm:maint:off": set_setting("maintenance","0"); await q.edit_message_text("🔴 Maintenance dimatikan.",reply_markup=back_home()); return
    if data=="adm:maint:msg": session(uid,"maintenance_config"); await q.edit_message_text("📝 EDIT PESAN MAINTENANCE",reply_markup=editor_menu(uid,"maintenance_config")); return
    if data.startswith("edit:"):
        _,action,target=data.split(":",2); s=admin_sessions.get(uid)
        if not s or s.get("target")!=target: session(uid,target); s=admin_sessions[uid]
        cfg=s["draft"]
        if action=="text": s["action"]="edit_text"; await q.edit_message_text("📝 KIRIM TEKS BARU\n\nKirim pesan langsung dari Telegram. Formatting Telegram akan ikut tersimpan.",reply_markup=cancel_kb()); return
        if action=="media": s["action"]="edit_media"; await q.edit_message_text("🖼️ KIRIM MEDIA\n\nBisa Foto, GIF/Animation, Video, Dokumen, atau Audio.",reply_markup=cancel_kb()); return
        if action=="delmedia": cfg["media_id"]=""; cfg["media_type"]=""; await q.edit_message_text("🗑️ Media di draft sudah dihapus. Belum tersimpan.",reply_markup=editor_menu(uid,target)); return
        if action=="buttons": await show_buttons(q,uid,target); return
        if action=="preview": await preview_cfg(q,context,uid,target,cfg); return
        if action=="save": save_target(target,cfg); admin_sessions.pop(uid,None); await q.edit_message_text("💾 PERUBAHAN TERSIMPAN.\n\nSetting lama sudah diganti dengan draft ini.",reply_markup=back_home()); return


async def show_buttons(q,uid,target):
    cfg=admin_sessions[uid]["draft"]; buttons=cfg.get("buttons",[]); kb=[]
    for i,b in enumerate(buttons): kb.append([InlineKeyboardButton(f"✏️ {b[0]}",callback_data=f"btn:edit:{target}:{i}"),InlineKeyboardButton("🗑️",callback_data=f"btn:del:{target}:{i}")])
    kb.append([InlineKeyboardButton("➕ Tambah Button",callback_data=f"btn:add:{target}")]); kb.append([InlineKeyboardButton("⬅️ Editor",callback_data=f"btn:back:{target}")]); await q.edit_message_text("🔘 BUTTON MANAGER\n\nSemua perubahan masih di draft.",reply_markup=InlineKeyboardMarkup(kb))


async def preview_cfg(q,context,uid,target,cfg):
    await q.edit_message_text("👁️ PREVIEW\n\nPreview lengkap sedang dikirim di bawah...",reply_markup=back_home()); await send_cfg(q.message.chat_id,cfg,context.bot,protect_content=False)


async def button_callback(update,context):
    q=update.callback_query; uid=q.from_user.id
    if not is_admin(uid): await q.answer("Tidak punya akses.",show_alert=True); return
    data=q.data.split(":"); action,target=data[1],data[2]; s=admin_sessions.get(uid)
    if not s or s.get("target")!=target: await q.answer("Draft sudah tidak aktif.",show_alert=True); return
    cfg=s["draft"]
    if action=="back": await q.answer(); await q.edit_message_text("⚙️ EDITOR\n\nPilih bagian:",reply_markup=editor_menu(uid,target)); return
    if action=="add": s["action"]="add_button"; await q.answer(); await q.edit_message_text("➕ TAMBAH BUTTON\n\nKirim format:\nNama Tombol | URL",reply_markup=cancel_kb()); return
    idx=int(data[3])
    if action=="del": cfg["buttons"].pop(idx); await q.answer("Button dihapus dari draft."); await show_buttons(q,uid,target); return
    if action=="edit": s["action"]="edit_button"; s["button_index"]=idx; await q.answer(); await q.edit_message_text(f"✏️ EDIT BUTTON\n\nSaat ini: {cfg['buttons'][idx][0]}\nURL: {cfg['buttons'][idx][2] if len(cfg['buttons'][idx])>2 else ''}\n\nKirim format baru:\nNama Tombol | URL",reply_markup=cancel_kb()); return


async def receive_admin_media(update,context):
    uid=update.effective_user.id
    if not is_admin(uid): return
    save_user(update.effective_user); s=admin_sessions.get(uid); msg=update.message; action=s.get("action") if s else None
    if action=="broadcast":
        s["broadcast_message_id"]=msg.message_id; s["broadcast_chat_id"]=uid; s["action"]="broadcast_confirm"; await msg.reply_text("📢 Pesan siap dibroadcast.\n\nKetik /broadcast_confirm untuk KIRIM ke semua user, atau /cancel untuk batal."); return
    if action=="edit_media":
        cfg=s["draft"]
        if msg.photo: cfg["media_id"]=msg.photo[-1].file_id; cfg["media_type"]="photo"
        elif msg.video: cfg["media_id"]=msg.video.file_id; cfg["media_type"]="video"
        elif msg.animation: cfg["media_id"]=msg.animation.file_id; cfg["media_type"]="animation"
        elif msg.document: cfg["media_id"]=msg.document.file_id; cfg["media_type"]="document"
        elif msg.audio: cfg["media_id"]=msg.audio.file_id; cfg["media_type"]="audio"
        else: return
        if msg.caption is not None: cfg["text"]=msg.caption; cfg["entities"]=serialize_entities(msg.caption_entities)
        s["action"]="editor"; await msg.reply_text("🖼️ Media masuk ke draft. Belum disimpan.",reply_markup=editor_menu(uid,s["target"])); return
    if action in (None,"editor") and (msg.photo or msg.video or msg.animation or msg.document or msg.audio):
        file_id=msg.photo[-1].file_id if msg.photo else (msg.video.file_id if msg.video else (msg.animation.file_id if msg.animation else (msg.document.file_id if msg.document else msg.audio.file_id)))
        ftype="photo" if msg.photo else ("video" if msg.video else ("animation" if msg.animation else ("document" if msg.document else "audio")))
        item=(file_id,ftype,msg.caption or "",msg.caption_entities or [])
        pending=pending_batches.get(uid)
        if pending is not None: pending.append(item); await msg.reply_text(f"✅ Ditambahkan ke batch. Total: {len(pending)} file."); return
        code=create_file_record(*item); await msg.reply_text(f"✅ File tersimpan!\n\n🔗 Link:\nhttps://t.me/{context.bot.username}?start={code}\n\nCode: {code}"); return


async def admin_text_input(update,context):
    uid=update.effective_user.id
    if not is_admin(uid): return
    msg=update.message; s=admin_sessions.get(uid); action=s.get("action") if s else None
    if action=="broadcast":
        s["broadcast_message_id"]=msg.message_id; s["broadcast_chat_id"]=uid; s["action"]="broadcast_confirm"; await msg.reply_text("📢 Pesan siap dibroadcast.\n\nKetik /broadcast_confirm untuk KIRIM ke semua user, atau /cancel untuk batal."); return
    if action=="add_command":
        m=re.match(r"^/?([a-zA-Z0-9_]+)\s*\|\s*(.+)$",msg.text.strip())
        if not m: await msg.reply_text("Format salah. Contoh: /help | Bantuan Nakahoshi"); return
        cmd,desc=m.group(1).lower(),m.group(2); reserved={"start","admin","batch","done","cancelbatch","cancel","broadcast","broadcast_confirm","setpayment","setchannel","setgroup","setowner"}
        if cmd in reserved: await msg.reply_text("❌ Nama command dipakai sistem/admin."); return
        conn=db(); exists=conn.execute("SELECT 1 FROM user_commands WHERE command=?",(cmd,)).fetchone()
        if exists: conn.close(); await msg.reply_text("❌ Command sudah ada."); return
        cfg=cfg_json("Tulis isi command ini..."); conn.execute("INSERT INTO user_commands(command,description,config,enabled) VALUES(?,?,?,1)",(cmd,desc,json.dumps(cfg,ensure_ascii=False))); conn.commit(); conn.close(); admin_sessions.pop(uid,None); await refresh_command_menus(context.bot); await msg.reply_text(f"✅ /{cmd} dibuat. Buka /admin → User Command untuk mengaturnya."); return
    if action=="add_admin":
        try: new=int(msg.text.strip())
        except: await msg.reply_text("❌ User ID harus angka."); return
        conn=db(); conn.execute("INSERT OR IGNORE INTO admins(user_id,added_at,added_by) VALUES(?,?,?)",(new,datetime.now().isoformat(timespec="seconds"),uid)); conn.commit(); conn.close(); admin_sessions.pop(uid,None); await msg.reply_text(f"✅ {new} sekarang admin."); return
    if action=="del_admin":
        try: new=int(msg.text.strip())
        except: await msg.reply_text("❌ User ID harus angka."); return
        if new==OWNER_ID: await msg.reply_text("🚫 Owner utama tidak dapat dihapus."); return
        conn=db(); conn.execute("DELETE FROM admins WHERE user_id=?",(new,)); conn.commit(); conn.close(); admin_sessions.pop(uid,None); await msg.reply_text(f"🗑️ Admin {new} dihapus."); return
    if action in ("ban","unban"):
        raw=msg.text.strip(); parts=raw.split("|",1)
        try: target=int(parts[0].strip())
        except: await msg.reply_text("❌ User ID harus angka."); return
        if action=="ban":
            if target in get_admin_ids(): await msg.reply_text("🚫 Admin tidak dapat dibanned."); return
            reason=parts[1].strip() if len(parts)>1 else ""; conn=db(); conn.execute("INSERT OR REPLACE INTO banned_users(user_id,reason,banned_at,banned_by) VALUES(?,?,?,?)",(target,reason,datetime.now().isoformat(timespec="seconds"),uid)); conn.commit(); conn.close(); admin_sessions.pop(uid,None); await msg.reply_text(f"🔨 User {target} berhasil dibanned.")
        else:
            conn=db(); conn.execute("DELETE FROM banned_users WHERE user_id=?",(target,)); conn.commit(); conn.close(); admin_sessions.pop(uid,None); await msg.reply_text(f"♻️ User {target} berhasil di-unban.")
        return
    if action=="ad_time":
        try: minutes=int(msg.text.strip()); assert minutes>=1
        except: await msg.reply_text("❌ Masukkan angka menit minimal 1."); return
        set_setting("auto_delete_minutes",str(minutes)); admin_sessions.pop(uid,None); await msg.reply_text(f"⏱️ Auto Delete diatur {minutes} menit."); return
    if action=="edit_text":
        s["draft"]["text"]=msg.text; s["draft"]["entities"]=serialize_entities(msg.entities); s["action"]="editor"; await msg.reply_text("📝 Text masuk draft. Formatting Telegram ikut disimpan. Belum disimpan.",reply_markup=editor_menu(uid,s["target"])); return
    if action=="add_button":
        m=re.match(r"^(.+?)\s*\|\s*(https?://\S+)$",msg.text.strip())
        if not m: await msg.reply_text("Format salah: Nama Tombol | URL"); return
        s["draft"].setdefault("buttons",[]).append([m.group(1).strip(),"url",m.group(2).strip()]); s["action"]="editor"; await msg.reply_text("🔘 Button ditambahkan ke draft.",reply_markup=editor_menu(uid,s["target"])); return
    if action=="edit_button":
        m=re.match(r"^(.+?)\s*\|\s*(https?://\S+)$",msg.text.strip()); idx=s.get("button_index")
        if not m or idx is None: await msg.reply_text("Format salah: Nama Tombol | URL"); return
        s["draft"]["buttons"][idx]=[m.group(1).strip(),"url",m.group(2).strip()]; s["action"]="editor"; await msg.reply_text("✏️ Button diperbarui di draft.",reply_markup=editor_menu(uid,s["target"])); return


async def cancel_command(update,context):
    if is_admin(update.effective_user.id): admin_sessions.pop(update.effective_user.id,None); pending_batches.pop(update.effective_user.id,None); await update.message.reply_text("❌ Dibatalkan.")


async def batch_command(update,context):
    if not is_admin(update.effective_user.id): return
    pending_batches[update.effective_user.id]=[]; await update.message.reply_text("📦 MODE BATCH AKTIF\n\nKirim file. Setelah selesai ketik /done.\nBatal: /cancelbatch")

async def done_command(update,context):
    uid=update.effective_user.id
    if not is_admin(uid): return
    items=pending_batches.pop(uid,None)
    if items is None: await update.message.reply_text("Tidak ada batch aktif."); return
    if not items: await update.message.reply_text("❌ Batch kosong."); return
    code=create_batch(uid,items); await update.message.reply_text(f"✅ BATCH SELESAI\n\n📦 Total: {len(items)}\n🔗 https://t.me/{context.bot.username}?start={code}\n\nCode: {code}")


async def start_broadcast(update,context):
    uid=update.effective_user.id
    if not is_admin(uid): return
    admin_sessions[uid]={"action":"broadcast"}
    await update.message.reply_text("📢 BROADCAST\n\nKirim satu pesan/media yang ingin dibroadcast.\nSetelah itu ketik /broadcast_confirm untuk KIRIM ke semua user, atau /cancel untuk batal.",protect_content=protect())


async def broadcast_confirm(update,context):
    uid=update.effective_user.id
    if not is_admin(uid): return
    s=admin_sessions.get(uid)
    if not s or s.get("action")!="broadcast_confirm" or not s.get("broadcast_message_id"): await update.message.reply_text("Tidak ada broadcast yang menunggu. Jalankan /broadcast dulu."); return
    conn=db(); users=[r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]; conn.close(); ok=bad=0
    for target in users:
        try: await context.bot.copy_message(chat_id=target,from_chat_id=uid,message_id=s["broadcast_message_id"],protect_content=protect()); ok+=1
        except Exception: bad+=1
        await asyncio.sleep(0.04)
    admin_sessions.pop(uid,None); await update.message.reply_text(f"📢 BROADCAST SELESAI\n\n✅ Terkirim: {ok}\n❌ Gagal: {bad}")


async def generic_command(update,context):
    cmd=update.message.text.split()[0].lstrip("/").split("@")[0].lower()
    if cmd in {"start","admin","batch","done","cancelbatch","cancel","broadcast","broadcast_confirm","setpayment","setchannel","setgroup","setowner"}: return
    save_user(update.effective_user)
    if is_banned(update.effective_user.id): await send_cfg(update.effective_chat.id,get_config("banned_message"),context.bot); return
    row=user_command(cmd)
    if row and row["enabled"]: await show_page(update,context,cmd)


async def set_link(update,context,key,label):
    if not is_admin(update.effective_user.id): return
    if not context.args: await update.message.reply_text("Gunakan command dengan URL."); return
    set_setting(key," ".join(context.args).strip()); await update.message.reply_text(f"✅ {label} berhasil diubah.")

async def setpayment(update,context): await set_link(update,context,"payment_link","Payment link")
async def setchannel(update,context): await set_link(update,context,"channel_link","Channel link")
async def setgroup(update,context): await set_link(update,context,"free_group_link","Group link")
async def setowner(update,context): await set_link(update,context,"owner_link","Owner link")


async def refresh_command_menus(bot):
    conn=db(); rows=conn.execute("SELECT command,description FROM user_commands WHERE enabled=1 ORDER BY rowid").fetchall(); conn.close()
    user_cmds=[BotCommand("start","Buka bot / akses file")]+[BotCommand(r["command"],r["description"][:256]) for r in rows]
    await bot.set_my_commands(user_cmds,scope=BotCommandScopeDefault())
    admin_cmds=user_cmds+[BotCommand("admin","Admin panel"),BotCommand("batch","Mulai batch file"),BotCommand("done","Selesaikan batch"),BotCommand("cancelbatch","Batalkan batch"),BotCommand("cancel","Batalkan proses"),BotCommand("broadcast","Broadcast"),BotCommand("broadcast_confirm","Konfirmasi broadcast")]
    for uid in get_admin_ids():
        try: await bot.set_my_commands(admin_cmds,scope=BotCommandScopeChat(chat_id=uid))
        except Exception as e: print("set admin commands error",uid,e)


async def post_init(application): await refresh_command_menus(application.bot)

async def error_handler(update,context): print("ERROR:",context.error)


def main():
    init_db()
    app=Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("admin",admin_command))
    app.add_handler(CommandHandler("batch",batch_command))
    app.add_handler(CommandHandler("done",done_command))
    app.add_handler(CommandHandler("cancelbatch",cancel_command))
    app.add_handler(CommandHandler("cancel",cancel_command))
    app.add_handler(CommandHandler("broadcast",start_broadcast))
    app.add_handler(CommandHandler("broadcast_confirm",broadcast_confirm))
    app.add_handler(CommandHandler("setpayment",setpayment)); app.add_handler(CommandHandler("setchannel",setchannel)); app.add_handler(CommandHandler("setgroup",setgroup)); app.add_handler(CommandHandler("setowner",setowner))
    app.add_handler(CallbackQueryHandler(check_button,pattern=r"^check:"))
    app.add_handler(CallbackQueryHandler(admin_callback,pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(button_callback,pattern=r"^btn:"))
    app.add_handler(MessageHandler(filters.PHOTO|filters.VIDEO|filters.ANIMATION|filters.Document.ALL|filters.AUDIO,receive_admin_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,admin_text_input))
    app.add_handler(MessageHandler(filters.COMMAND,generic_command))
    app.add_error_handler(error_handler)
    print("Bot sedang berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__": main()
