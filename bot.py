import json
import os
import re
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters,
    ConversationHandler, CallbackQueryHandler,
)

TOKEN = os.environ["BOT_TOKEN"]

ADMIN_USERNAMES = {"IgAccJohn", "Dragonball77", "MrK6776", "react249", "jiang9546"}

PAGE_SIZE = 10

_data_dir = os.path.realpath(os.environ.get("BOT_DATA_DIR", "/app"))
if ".." in os.path.basename(_data_dir):
    raise ValueError("BOT_DATA_DIR 不能包含 .. 路径穿越成分")
os.makedirs(_data_dir, exist_ok=True)
LEDGER_SETTINGS_FILE = os.path.join(_data_dir, "ledger_settings.json")
LEDGER_ENTRIES_FILE = os.path.join(_data_dir, "ledger_entries.json")
LEDGER_CARRYOVER_FILE = os.path.join(_data_dir, "ledger_carryover.json")
LEDGER_CLEAR_SNAPSHOT_FILE = os.path.join(_data_dir, "ledger_clear_snapshot.json")
OPERATORS_FILE = os.path.join(_data_dir, "operators.json")

DEFAULT_LEDGER_SETTINGS = {
    "currency": "MYR",
    "period_start": None,
    "period_label": None,
    "tz_offset": 8,
    "in_fee": 0,
    "out_fee": 0,
}

(
    ADDOP_WAIT,
) = range(100, 101)

RE_SET_CURRENCY = re.compile(r"^设[置疑定](?:币种|货币)\s*([A-Za-z]+)$")
RE_CHANGE_CURRENCY = re.compile(r"^修改(?:货币|币种)\s*([A-Za-z]+)\s*到\s*([A-Za-z]+)$")
RE_SET_TIMEZONE = re.compile(r"^设[置疑定]时区\s*([+-]?\d+(?:\.\d+)?)$")
RE_SET_IN_FEE = re.compile(r"^设置IN费率\s*(-?\d+(?:\.\d+)?)$", re.IGNORECASE)
RE_SET_OUT_FEE = re.compile(r"^设置OUT费率\s*(-?\d+(?:\.\d+)?)$", re.IGNORECASE)
RE_SET_PERIOD_LABEL = re.compile(r"^设[置疑定]日期\s*(\d{4}-\d{2}-\d{2})$")
RE_VIEW_LEDGER_BILL = re.compile(r"^账单$")
RE_CLOSE_LEDGER = re.compile(r"^(?:结束账单|日切)$")
RE_LEDGER_ENTRY = re.compile(r"^([+-])\s*(\d+(?:\.\d+)?)\s*(.*)$", re.DOTALL)
RE_LEDGER_DISBURSE = re.compile(r"^下发\s*([+-])?\s*(\d+(?:\.\d+)?)\s*(?:手续\s*(\d+(?:\.\d+)?)\s*)?(.*)$", re.DOTALL)
RE_REVOKE = re.compile(r"^撤销$")
RE_REVOKE_RESTORE = re.compile(r"^撤销恢复$")
RE_RETRACT = re.compile(r"^回撤$")
RE_CLEAR_LEDGER = re.compile(r"^清空账单$")
RE_UNDO_CLEAR_LEDGER = re.compile(r"^撤销清空账单$")

CHAR_MAP = {
    "（": "(", "）": ")", "＋": "+", "－": "-",
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
}


def normalize(text):
    for cn, en in CHAR_MAP.items():
        text = text.replace(cn, en)
    return text


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_admin(user) -> bool:
    if not user.username:
        return False
    return user.username.lower() in {u.lower() for u in ADMIN_USERNAMES}


def load_operators():
    return load_json(OPERATORS_FILE, {"ids": [], "usernames": []})


def save_operators(data):
    save_json(OPERATORS_FILE, data)


def is_operator(user) -> bool:
    """Admin 天然可用；其他用户需在操作员名单内。"""
    if is_admin(user):
        return True
    data = load_operators()
    if user.id in data["ids"]:
        return True
    if user.username and user.username.lower() in [u.lower() for u in data["usernames"]]:
        return True
    return False


# ---------- 操作员名单 ----------

def total_pages(count):
    return max(1, -(-count // PAGE_SIZE))


def get_operators_list():
    data = load_operators()
    items = [("id", str(i), f"🆔 {i}") for i in data["ids"]]
    items += [("un", u, f"👤 @{u}") for u in data["usernames"]]
    return items


def build_operators_page(page, items=None):
    if items is None:
        items = get_operators_list()
    total = len(items)
    pages = total_pages(total)
    page = max(1, min(page, pages))
    start = (page - 1) * PAGE_SIZE
    page_items = items[start:start + PAGE_SIZE]

    if page_items:
        lines = [f"📋 操作员（共 {total} 位）— 第 {page}/{pages} 页", "", "点击操作员可移除："]
    else:
        lines = ["📋 操作员（共 0 位）", "", "（暂无操作员，点下方添加）"]
    text = "\n".join(lines)

    buttons = [[InlineKeyboardButton(label, callback_data=f"op:rm:{kind}:{val}")] for kind, val, label in page_items]

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀ 上一页", callback_data=f"op:page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="op:noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("下一页 ▶", callback_data=f"op:page:{page + 1}"))
    buttons.append(nav)

    buttons.append([InlineKeyboardButton("➕ 添加操作员", callback_data="op:add")])
    buttons.append([InlineKeyboardButton("❌ 关闭", callback_data="op:close")])

    return text, InlineKeyboardMarkup(buttons), page


async def listoperators_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        await update.message.reply_text("只有管理员能执行此操作")
        return
    text, kb, _ = build_operators_page(1)
    await update.message.reply_text(text, reply_markup=kb)


async def listoperators_page_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[2])
    text, kb, _ = build_operators_page(page)
    await query.edit_message_text(text, reply_markup=kb)


async def listoperators_noop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def listoperators_rm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, kind, val = query.data.split(":", 3)
    items = get_operators_list()
    idx = next((i for i, (k, v, _) in enumerate(items) if k == kind and v == val), 0)
    page = idx // PAGE_SIZE + 1
    label = next((l for k, v, l in items if k == kind and v == val), val)

    text = f"确定要移除操作员 {label} 吗？"
    buttons = [
        [InlineKeyboardButton("✅ 确认移除", callback_data=f"op:rmconfirm:{kind}:{val}:{page}")],
        [InlineKeyboardButton("❌ 取消", callback_data=f"op:cancel:{page}")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def listoperators_rmconfirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, kind, val, page = query.data.split(":", 4)
    data = load_operators()
    if kind == "id":
        data["ids"] = [i for i in data["ids"] if str(i) != val]
    else:
        data["usernames"] = [u for u in data["usernames"] if u.lower() != val.lower()]
    save_operators(data)
    text, kb, _ = build_operators_page(int(page))
    await query.edit_message_text(f"✅ 已移除\n\n{text}", reply_markup=kb)


async def listoperators_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[2])
    text, kb, _ = build_operators_page(page)
    await query.edit_message_text(text, reply_markup=kb)


async def listoperators_close_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("已关闭")


async def addoperator_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        if update.callback_query:
            await update.callback_query.answer("只有管理员能执行此操作", show_alert=True)
        else:
            await update.message.reply_text("只有管理员能执行此操作")
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text("请输入要授权的操作员用户名（@开头）或用户ID（纯数字）：\n发 /cancel 取消")
    return ADDOP_WAIT


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("已取消")
    return ConversationHandler.END


async def addoperator_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.text.strip()
    data = load_operators()
    if target.startswith("@"):
        uname = target[1:]
        if uname not in data["usernames"]:
            data["usernames"].append(uname)
    else:
        try:
            uid = int(target)
        except ValueError:
            await update.message.reply_text("格式不对，用户ID必须是纯数字，或者用 @username，请重新输入：")
            return ADDOP_WAIT
        if uid not in data["ids"]:
            data["ids"].append(uid)
    save_operators(data)
    text, kb, _ = build_operators_page(1)
    await update.message.reply_text(f"✅ 已授权操作员：{target}\n\n{text}", reply_markup=kb)
    return ConversationHandler.END


addoperator_conv = ConversationHandler(
    entry_points=[
        CommandHandler("addoperator", addoperator_start),
        CallbackQueryHandler(addoperator_start, pattern="^op:add$"),
    ],
    states={ADDOP_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, addoperator_receive)]},
    fallbacks=[CommandHandler("cancel", cancel_conversation)],
)


async def removeoperator_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await listoperators_cmd(update, context)


# ---------- 记账数据存取 ----------

def load_ledger_settings():
    return load_json(LEDGER_SETTINGS_FILE, {})

def save_ledger_settings(data):
    save_json(LEDGER_SETTINGS_FILE, data)

def get_group_ledger_settings(chat_id) -> dict:
    data = load_ledger_settings()
    merged = dict(DEFAULT_LEDGER_SETTINGS)
    merged.update(data.get(str(chat_id), {}))
    return merged

def set_group_ledger_setting(chat_id, key, value):
    data = load_ledger_settings()
    data.setdefault(str(chat_id), dict(DEFAULT_LEDGER_SETTINGS))[key] = value
    save_ledger_settings(data)

def load_ledger_entries():
    return load_json(LEDGER_ENTRIES_FILE, {})

def save_ledger_entries(data):
    save_json(LEDGER_ENTRIES_FILE, data)

def append_ledger_entry(chat_id, entry: dict):
    data = load_ledger_entries()
    data.setdefault(str(chat_id), []).append(entry)
    save_ledger_entries(data)

def get_ledger_tz(chat_id=None):
    offset = get_group_ledger_settings(chat_id).get("tz_offset", 8) if chat_id is not None else 8
    return timezone(timedelta(hours=offset))

def load_ledger_carryover():
    return load_json(LEDGER_CARRYOVER_FILE, {})

def save_ledger_carryover(data):
    save_json(LEDGER_CARRYOVER_FILE, data)

def get_group_carryover(chat_id):
    raw = load_ledger_carryover().get(str(chat_id), {})
    if isinstance(raw, (int, float)):
        return {DEFAULT_LEDGER_SETTINGS["currency"]: float(raw)}
    return raw

def set_group_carryover(chat_id, currency_totals: dict):
    data = load_ledger_carryover()
    data[str(chat_id)] = {k: round(v, 4) for k, v in currency_totals.items()}
    save_ledger_carryover(data)

def change_ledger_currency(chat_id, src: str, dst: str) -> int:
    """把该群账本里所有币种为 src 的未撤销记录批量改为 dst（已撤销的记录跳过、不动它），
    并合并结转余额；若当前设置的币种是 src，一并改为 dst。返回被改动的记录数。"""
    data = load_ledger_entries()
    entries = data.get(str(chat_id), [])
    count = 0
    for e in entries:
        if e.get("voided"):
            continue
        if e.get("currency", "").upper() == src:
            e["currency"] = dst
            count += 1
    if count:
        save_ledger_entries(data)

    carryover = dict(get_group_carryover(chat_id))
    if src in carryover:
        carryover[dst] = round(carryover.get(dst, 0.0) + carryover.pop(src), 4)
        set_group_carryover(chat_id, carryover)

    settings = get_group_ledger_settings(chat_id)
    if settings.get("currency") == src:
        set_group_ledger_setting(chat_id, "currency", dst)

    return count

def load_clear_snapshots():
    return load_json(LEDGER_CLEAR_SNAPSHOT_FILE, {})

def save_clear_snapshots(data):
    save_json(LEDGER_CLEAR_SNAPSHOT_FILE, data)


def get_period_start_str(chat_id, tz):
    """当前账期起点；第一次调用时确定起点，之后只靠结束账单推进。"""
    ps = get_group_ledger_settings(chat_id).get("period_start")
    if ps:
        return ps
    entries = load_ledger_entries().get(str(chat_id), [])
    if entries:
        ps = min(e["time"] for e in entries)
    else:
        ps = datetime.now(tz).strftime("%Y-%m-%d 00:00:00")
    set_group_ledger_setting(chat_id, "period_start", ps)
    return ps


def get_period_label(chat_id, tz):
    label = get_group_ledger_settings(chat_id).get("period_label")
    if label:
        return label
    return datetime.now(tz).strftime("%Y-%m-%d")


def _period_entries(chat_id):
    entries = load_ledger_entries().get(str(chat_id), [])
    period_start_str = get_period_start_str(chat_id, get_ledger_tz(chat_id))
    return [e for e in entries if e.get("time", "") >= period_start_str and not e.get("voided")]


def get_today_entries_split(chat_id, tz):
    """返回当前账期的 (入账列表, 出账列表)，按时间正序排列。"""
    today_entries = _period_entries(chat_id)
    ins = sorted((e for e in today_entries if e["type"] == "in"), key=lambda e: e["time"])
    outs = sorted((e for e in today_entries if e["type"] == "out"), key=lambda e: e["time"])
    return ins, outs


def get_today_totals(chat_id, tz):
    """返回 Deposit 合计，按币种分类（+ 记一笔算 +amount，- 记一笔算 -amount，都计入 Deposit，不再区分费率）。"""
    deposit_totals = {}
    for e in _period_entries(chat_id):
        if e["type"] not in ("in", "out"):
            continue
        cur = e.get("currency", "USDT")
        signed_amount = e["amount"] if e["type"] == "in" else -e["amount"]
        deposit_totals[cur] = deposit_totals.get(cur, 0.0) + signed_amount
    return deposit_totals


def get_today_disburse(chat_id, tz):
    """返回当前账期的下发记录列表，和按币种分类的净额合计字典。"""
    items = [e for e in _period_entries(chat_id) if e["type"] == "disburse"]
    net_totals = {}
    for e in items:
        cur = e.get("currency", "USDT")
        net_totals[cur] = net_totals.get(cur, 0.0) + e["net_amount"]
    return items, net_totals


# ---------- 清空 / 结算 ----------

def clear_ledger_today(chat_id):
    """把当前账期所有未作废的记录标记作废，结转余额不动。"""
    tz = get_ledger_tz(chat_id)
    period_start_str = get_period_start_str(chat_id, tz)

    data = load_ledger_entries()
    entries = data.get(str(chat_id), [])
    cleared_ids = []
    for e in entries:
        if e.get("time", "") >= period_start_str and not e.get("voided"):
            e["voided"] = True
            cleared_ids.append(e["id"])
    save_ledger_entries(data)

    snapshots = load_clear_snapshots()
    snapshots[str(chat_id)] = cleared_ids
    save_clear_snapshots(snapshots)
    return len(cleared_ids)


def undo_clear_ledger_today(chat_id):
    """撤销最近一次「清空账单」。"""
    snapshots = load_clear_snapshots()
    cleared_ids = snapshots.pop(str(chat_id), None)
    if cleared_ids is None:
        return None
    save_clear_snapshots(snapshots)

    data = load_ledger_entries()
    restored = 0
    for e in data.get(str(chat_id), []):
        if e.get("id") in cleared_ids and e.get("voided"):
            e["voided"] = False
            restored += 1
    save_ledger_entries(data)
    return restored


def close_ledger_day(chat_id):
    """结算当前账期的 GrandTotal，结转到下一账期（单一币种，以当前设置币种为准），账期日期+1。"""
    settings = get_group_ledger_settings(chat_id)
    tz = get_ledger_tz(chat_id)
    deposit_totals = get_today_totals(chat_id, tz)
    _, disburse_totals = get_today_disburse(chat_id, tz)

    label = get_period_label(chat_id, tz)

    total_grand = round(sum(deposit_totals.values()) + sum(disburse_totals.values()), 4)
    cur = settings["currency"]
    grand_totals = {cur: total_grand}

    set_group_carryover(chat_id, grand_totals)

    try:
        next_label = (datetime.strptime(label, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        next_label = label

    settings["period_label"] = next_label
    all_s = load_ledger_settings()
    all_s[str(chat_id)] = settings
    save_ledger_settings(all_s)

    all_entries = load_ledger_entries()
    all_entries[str(chat_id)] = []
    save_ledger_entries(all_entries)

    return grand_totals, next_label


# ---------- 格式化 ----------

def _fmt_num(n):
    n = round(n, 4)
    if n == int(n):
        return str(int(n))
    return f"{n:g}"


def format_ledger_line(entry, is_multi=False):
    """23:32 200 = +100（原始金额不带符号，净额带正负号，不显示币种）"""
    time_str = entry["time"][11:16]
    sign = 1 if entry["type"] == "in" else -1
    display_amount = _fmt_num(entry["amount"])
    display_net = _fmt_num(sign * entry["net_amount"])
    if sign == 1:
        display_net = f"+{display_net}"

    line = f"<b>{time_str}</b> {display_amount} = {display_net}"
    if entry.get("note"):
        line += f" · {entry['note']}"
    return line


def format_disburse_line(entry):
    time_str = entry["time"][11:16]
    display_amount = _fmt_num(entry["amount"])
    display_net = _fmt_num(entry["net_amount"])
    if entry["net_amount"] > 0:
        display_net = f"+{display_net}"
    line = f"<b>{time_str}</b> {display_amount} = {display_net}"
    if entry.get("note"):
        line += f" · {entry['note']}"
    return line


# ---------- 账单视图 ----------

def build_ledger_summary(chat_id):
    """账单视图（图1格式）：账期 → 交易流水 → 已下发 → Deposit/Withdraw/Grand Total。"""
    settings = get_group_ledger_settings(chat_id)
    tz = get_ledger_tz(chat_id)
    ins, outs = get_today_entries_split(chat_id, tz)
    deposit_totals = get_today_totals(chat_id, tz)
    disburse_items, disburse_totals = get_today_disburse(chat_id, tz)

    lines = [f"📅 账期：{get_period_label(chat_id, tz)}", ""]

    combined = sorted(ins + outs, key=lambda e: e["time"])
    lines.append(f"交易流水 ({len(combined)}笔)")
    if combined:
        lines += [format_ledger_line(e) for e in combined[-5:]]
    else:
        lines.append("（暂无）")
    lines.append("")

    lines.append(f"已下发 ({len(disburse_items)}笔)")
    if disburse_items:
        lines += [format_disburse_line(e) for e in disburse_items[-5:]]
    else:
        lines.append("（暂无）")
    lines.append("")

    total_deposit = sum(deposit_totals.values())
    total_withdraw = sum(disburse_totals.values())
    total_grand = round(total_deposit + total_withdraw, 4)
    cur = settings["currency"]
    lines.append(f"Deposit: {_fmt_num(total_deposit)} {cur}")
    lines.append(f"Withdraw: {_fmt_num(total_withdraw)} {cur}")
    lines.append(f"Settlement: {_fmt_num(total_grand)} {cur}")

    return "\n".join(lines)


# ---------- 记账消息处理 ----------

async def try_handle_ledger_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """匹配 +金额 / -金额 记一笔，可带备注。"""
    m = RE_LEDGER_ENTRY.match(text)
    if not m:
        return False

    sign, amount_str, note = m.groups()
    amount = float(amount_str)
    note = note.strip()

    chat_id = update.effective_chat.id
    user = update.effective_user
    settings = get_group_ledger_settings(chat_id)
    tz = get_ledger_tz(chat_id)

    entry_type = "in" if sign == "+" else "out"

    entry = {
        "type": entry_type,
        "amount": amount,
        "net_amount": amount,
        "currency": settings["currency"],
        "note": note,
        "operator_id": user.id,
        "operator_name": f"@{user.username}" if user.username else (user.full_name or str(user.id)),
        "time": datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S"),
    }

    data_now = load_ledger_entries()
    entry["id"] = len(data_now.get(str(chat_id), [])) + 1
    entry["voided"] = False
    entry["user_message_id"] = update.message.message_id
    append_ledger_entry(chat_id, entry)

    summary_text = build_ledger_summary(chat_id)
    sent = await update.message.reply_text(summary_text, parse_mode="HTML")

    data_after = load_ledger_entries()
    for e in data_after.get(str(chat_id), []):
        if e.get("id") == entry["id"]:
            e["confirm_message_id"] = sent.message_id
            break
    save_ledger_entries(data_after)
    return True


async def try_handle_ledger_disburse(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """匹配「下发」指令：下发 2000 / 下发 -2000 手续20 备注。"""
    m = RE_LEDGER_DISBURSE.match(text)
    if not m:
        return False
    sign, amount_str, fee_override_str, note = m.groups()
    amount = float(amount_str)
    note = note.strip()
    chat_id = update.effective_chat.id
    user = update.effective_user
    tz = get_ledger_tz(chat_id)

    fee = float(fee_override_str) if fee_override_str is not None else 0
    net_amount = round(amount - fee, 4)
    # 无符号或带 "-" 号：正常下发，让 Withdraw -amount；显式带 "+" 号：冲正/撤回一笔下发，让 Withdraw +amount
    is_reversal = (sign == "+")
    effect = net_amount if is_reversal else -net_amount

    entry = {
        "type": "disburse",
        "amount": amount,
        "sign": sign or "-",
        "fee_flat": fee,
        "net_amount": round(effect, 4),
        "currency": get_group_ledger_settings(chat_id)["currency"],
        "note": note,
        "operator_id": user.id,
        "operator_name": f"@{user.username}" if user.username else (user.full_name or str(user.id)),
        "time": datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S"),
    }

    data_now = load_ledger_entries()
    entry["id"] = len(data_now.get(str(chat_id), [])) + 1
    entry["voided"] = False
    entry["user_message_id"] = update.message.message_id
    append_ledger_entry(chat_id, entry)

    summary_text = build_ledger_summary(chat_id)
    sent = await update.message.reply_text(summary_text, parse_mode="HTML")

    data_after = load_ledger_entries()
    for e in data_after.get(str(chat_id), []):
        if e.get("id") == entry["id"]:
            e["confirm_message_id"] = sent.message_id
            break
    save_ledger_entries(data_after)
    return True


async def try_handle_ledger_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """回复某笔记账消息，发「撤销」/「撤销恢复」来作废/恢复该笔记录；
    发「回撤」= 作废该笔 + 删除操作员发的原始记账消息（+200/-200/下发）。"""
    is_revoke = RE_REVOKE.match(text)
    is_restore = RE_REVOKE_RESTORE.match(text)
    is_retract = RE_RETRACT.match(text)
    if not (is_revoke or is_restore or is_retract):
        return False

    if not update.message.reply_to_message:
        await update.message.reply_text("请回复要撤销的那条记账消息，再发「撤销」")
        return True

    chat_id = update.effective_chat.id
    target_message_id = update.message.reply_to_message.message_id

    data = load_ledger_entries()
    entries = data.get(str(chat_id), [])
    target = next(
        (e for e in entries
         if e.get("confirm_message_id") == target_message_id
         or e.get("user_message_id") == target_message_id),
        None,
    )

    if not target:
        await update.message.reply_text("没找到这条消息对应的记账记录（可能不是记账相关消息）")
        return True

    if is_revoke or is_retract:
        if target.get("voided"):
            await update.message.reply_text("这笔已经是撤销状态了")
            return True
        target["voided"] = True
        save_ledger_entries(data)

        if is_retract and target.get("user_message_id"):
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=target["user_message_id"],
                )
            except Exception:
                await update.message.reply_text("⚠️ 原始记账消息删除失败（可能已被删或Bot无删除权限），该笔已作废")

        summary_text = build_ledger_summary(chat_id)
        await update.message.reply_text(
            f"✅ 已撤销记录（#{target['id']}），以下为最新账单：\n\n{summary_text}",
            parse_mode="HTML",
        )
        return True

    if not target.get("voided"):
        await update.message.reply_text("这笔本来就没被撤销，不需要恢复")
        return True
    target["voided"] = False
    save_ledger_entries(data)
    summary_text = build_ledger_summary(chat_id)
    await update.message.reply_text(
        f"✅ 已恢复记录（#{target['id']}），以下为最新账单：\n\n{summary_text}",
        parse_mode="HTML",
    )
    return True


# ---------- 设置 / 结算类指令 ----------

async def try_handle_ledger_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    chat_id = update.effective_chat.id

    if RE_CLEAR_LEDGER.match(text):
        if not is_admin(update.effective_user):
            await update.message.reply_text("只有管理员能清空账单")
            return True
        count = clear_ledger_today(chat_id)
        summary_text = build_ledger_summary(chat_id)
        await update.message.reply_text(
            f"✅ 已清空本期账单，共 {count} 笔记录作废（结转余额不受影响）\n"
            f"如果操作有误，可发「撤销清空账单」撤回。\n\n{summary_text}",
            parse_mode="HTML",
        )
        return True

    if RE_UNDO_CLEAR_LEDGER.match(text):
        restored = undo_clear_ledger_today(chat_id)
        if restored is None:
            await update.message.reply_text("没有可撤销的「清空账单」记录（可能已经撤销过，或还没清空过）")
        else:
            await update.message.reply_text(f"✅ 已撤销清空，恢复了 {restored} 笔记录，重新计入统计")
        return True

    m = RE_SET_CURRENCY.match(text)
    if m:
        currency = m.group(1).upper()
        set_group_ledger_setting(chat_id, "currency", currency)
        await update.message.reply_text(f"✅ 本群币种已设置为 {currency}")
        return True

    m = RE_SET_TIMEZONE.match(text)
    if m:
        offset = float(m.group(1))
        if not (-12 <= offset <= 14):
            await update.message.reply_text("时区偏移超出范围（-12 到 +14）")
            return True
        set_group_ledger_setting(chat_id, "tz_offset", offset)
        offset_str = f"+{offset:g}" if offset >= 0 else f"{offset:g}"
        await update.message.reply_text(
            f"✅ 本群时区已设置为 UTC{offset_str}\n（只影响之后的记账时间和账期切换，已有记录的时间戳不会改变）"
        )
        return True

    m = RE_SET_IN_FEE.match(text)
    if m:
        fee = float(m.group(1))
        set_group_ledger_setting(chat_id, "in_fee", fee)
        await update.message.reply_text(f"✅ 本群 IN 费率已设置为 {_fmt_num(fee)}%")
        return True

    m = RE_SET_OUT_FEE.match(text)
    if m:
        fee = float(m.group(1))
        set_group_ledger_setting(chat_id, "out_fee", fee)
        await update.message.reply_text(f"✅ 本群 OUT 费率已设置为 {_fmt_num(fee)}%")
        return True

    m = RE_CHANGE_CURRENCY.match(text)
    if m:
        if not is_admin(update.effective_user):
            await update.message.reply_text("只有管理员能修改币种")
            return True
        src, dst = m.group(1).upper(), m.group(2).upper()
        if src == dst:
            await update.message.reply_text("两个币种相同，无需修改")
            return True
        changed = change_ledger_currency(chat_id, src, dst)
        if changed == 0:
            await update.message.reply_text(f"没有找到币种为 {src} 的记录")
        else:
            summary_text = build_ledger_summary(chat_id)
            await update.message.reply_text(
                f"✅ 已将 {changed} 笔记录的币种从 {src} 改为 {dst}\n\n{summary_text}",
                parse_mode="HTML",
            )
        return True

    if RE_VIEW_LEDGER_BILL.match(text):
        text_out = build_ledger_summary(chat_id)
        await update.message.reply_text(text_out, parse_mode="HTML")
        return True

    if RE_CLOSE_LEDGER.match(text):
        grand_totals, next_label = close_ledger_day(chat_id)
        gt_str = " | ".join([f"{cur}: {_fmt_num(val)}" for cur, val in grand_totals.items()])
        await update.message.reply_text(
            f"✅ 账单已结束！\n\n"
            f"📊 <b>结转总额</b>：<code>{gt_str}</code>\n"
            f"📅 <b>新账期</b>：{next_label}",
            parse_mode="HTML"
        )
        return True

    m = RE_SET_PERIOD_LABEL.match(text)
    if m:
        set_group_ledger_setting(chat_id, "period_label", m.group(1))
        await update.message.reply_text(f"✅ 账期日期已校准为：{m.group(1)}")
        return True

    return False


# ---------- 回调 ----------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    if not is_operator(user):
        return

    text = update.message.text.strip()
    bot_username = context.bot.username
    if bot_username:
        text = text.replace(f"@{bot_username}", "").strip()

    text = normalize(text)

    if await try_handle_ledger_settings(update, context, text):
        return

    if await try_handle_ledger_revoke(update, context, text):
        return

    if await try_handle_ledger_entry(update, context, text):
        return

    if await try_handle_ledger_disburse(update, context, text):
        return


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "开始聊天"),
        BotCommand("ledger", "查看本群账单"),
        BotCommand("addoperator", "添加操作员（管理员）"),
        BotCommand("removeoperator", "移除操作员（管理员，点选列表）"),
        BotCommand("listoperators", "查看/管理操作员"),
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "你好！我是记账助手机器人 🧾\n\n"
        "记一笔：发 +金额 表示入账，-金额 表示出账，后面可加备注\n"
        "例如：+100 lim / -50 提现\n"
        "下发：发「下发 金额 [手续X] [备注]」\n"
        "查看账单：发「账单」或 /ledger\n"
        "改币种：发「设置币种 AUD」\n"
        "批量改币种：发「修改币种 USD到MYR」（管理员，全局生效）\n"
        "改时区：发「设定时区 +10」（支持负数和半点，如 -5、5.5）\n"
        "设IN/OUT费率：发「设置IN费率 5」/「设置OUT费率 3」（百分比，影响记账净额）\n"
        "校准账期：发「设定日期 2026-09-10」\n"
        "结束账单 / 日切 / 清空账单 / 撤销清空账单\n"
        "撤销某笔：回复那条记账消息发「撤销」，恢复发「撤销恢复」\n\n"
        "（管理员专属：/addoperator /removeoperator /listoperators）"
    )


async def ledger_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = build_ledger_summary(update.effective_chat.id)
    await update.message.reply_text(text, parse_mode="HTML")


app = ApplicationBuilder().token(TOKEN).post_init(post_init).concurrent_updates(True).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("ledger", ledger_cmd))
app.add_handler(CommandHandler("removeoperator", removeoperator_alias))
app.add_handler(CommandHandler("listoperators", listoperators_cmd))
app.add_handler(addoperator_conv)
app.add_handler(CallbackQueryHandler(listoperators_page_cb, pattern=r"^op:page:\d+$"))
app.add_handler(CallbackQueryHandler(listoperators_rmconfirm_cb, pattern=r"^op:rmconfirm:"))
app.add_handler(CallbackQueryHandler(listoperators_rm_cb, pattern=r"^op:rm:(id|un):"))
app.add_handler(CallbackQueryHandler(listoperators_cancel_cb, pattern=r"^op:cancel:\d+$"))
app.add_handler(CallbackQueryHandler(listoperators_close_cb, pattern=r"^op:close$"))
app.add_handler(CallbackQueryHandler(listoperators_noop_cb, pattern=r"^op:noop$"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("记账机器人已启动，正在监听消息...")
app.run_polling(drop_pending_updates=True)