import asyncio
import os
import re
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from telebot.async_telebot import AsyncTeleBot

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaWebPage

# ---------------------------------------------------------------------------
# Existing configuration (unchanged)
# ---------------------------------------------------------------------------

# Read token directly from Railway variables
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

ADMIN_ID = 7578145913
KEYWORDS = ['You received']

FORWARD_RULES = {
    # MH X LARRY GROUP 2 (channel) -> CHIME PICCASO
    -1003894781195: [-5350880041],
    # Chime Rev & out no-7 -> CHIME GAFFER
    -1002335630148: [-5580596463],
    # MH x LARRY VENMO -> GAFFER VENMO, PICCASO VENMO
    -5339749243: [-5100231154, -5306739731],
}

# Sources where ONLY bot messages may be forwarded, never humans. Messages from
# people in these chats are ignored even if they match a keyword.
BOT_ONLY_SOURCES = {
    -1002335630148,
}

# ---------------------------------------------------------------------------
# Telethon configuration (new)
#
# Telethon is used for READING ONLY. It logs in as your user account so it can
# see messages posted by other bots, which the Bot API never delivers. Nothing
# is ever sent from the user account - every outgoing message still goes out
# through `bot` (your bot token) below.
# ---------------------------------------------------------------------------

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')

# Preferred for deployment: a StringSession produced by telethon_login.py.
# Falls back to a local .session file for running on your Mac.
TELETHON_SESSION = os.getenv('TELETHON_SESSION')
TELETHON_SESSION_NAME = os.getenv('TELETHON_SESSION_NAME', 'user_session')

# Which bot's messages to relay. Usernames or numeric ids, comma separated.
# Matching is case insensitive and a leading @ is optional.
# Empty (the default) accepts ANY bot in the source chats, which is what you
# want while more than one notification bot is in play. Humans are never
# accepted on this path. Set it to pin a specific bot, e.g.
# SOURCE_BOTS=Hasan_Transection_Bot
SOURCE_BOTS = os.getenv('SOURCE_BOTS', '')

# Which chats Telethon watches. Defaults to the source chats of FORWARD_RULES.
TELETHON_SOURCE_CHATS = os.getenv('TELETHON_SOURCE_CHATS', '')

TELETHON_ENABLED = bool(API_ID and API_HASH)

# ---------------------------------------------------------------------------
# Runtime state (unchanged)
# ---------------------------------------------------------------------------

forwarded_count = 0
today_count = 0
start_time = datetime.now()
last_messages = []

userbot_status = 'disabled'

bot = AsyncTeleBot(BOT_TOKEN)


async def notify_admin(msg):
    try:
        await bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        print(f"Notify Admin Error: {e}", flush=True)


def get_uptime():
    uptime = datetime.now() - start_time
    hours = int(uptime.total_seconds() // 3600)
    minutes = int((uptime.total_seconds() % 3600) // 60)
    return f"{hours}h {minutes}m"


# ---------------------------------------------------------------------------
# Shared forwarding pipeline
#
# Both input paths (Bot API for humans, Telethon for bots) funnel into
# process_incoming() so the keyword filter, routing, counters, logging and
# error handling exist in exactly one place.
# ---------------------------------------------------------------------------

def _id_variants(chat_id):
    """Telegram writes supergroup ids as -100<internal> in some places and
    -<internal> in others. Return the alternate spelling of a chat id so a rule
    matches regardless of which form the config uses."""
    text = str(chat_id)
    if text.startswith('-100'):
        return [int('-' + text[4:])]
    if text.startswith('-'):
        return [int('-100' + text[1:])]
    return []


def resolve_rule_key(chat_id):
    """Exact match first so existing behaviour is untouched, then fall back to
    the alternate id spelling."""
    if chat_id in FORWARD_RULES:
        return chat_id
    for variant in _id_variants(chat_id):
        if variant in FORWARD_RULES:
            return variant
    return None


# Nepal time. A fixed offset rather than a zoneinfo lookup: Nepal has no DST,
# and Railway's container has no tzdata installed.
LOCAL_TZ = timezone(timedelta(hours=5, minutes=45))

# Matches the timestamp the notification bot embeds, e.g. "03:35 AM - 30 Jul 2026"
_STAMP_RE = re.compile(
    r'\b\d{1,2}:\d{2}\s*[AaPp][Mm]\s*-\s*\d{1,2}\s+[A-Za-z]{3}\s+\d{4}')

# The notification bot's own clock runs roughly 14 minutes fast, so the time it
# writes into the message is wrong. Rewrite it to when the message was actually
# sent, in Nepal time. Set FIX_TIMESTAMPS=0 to forward the text untouched.
FIX_TIMESTAMPS = os.getenv('FIX_TIMESTAMPS', '1') != '0'


def correct_timestamp(text, sent_at):
    """Replace the bot's embedded timestamp with the real send time. Text with
    no recognisable timestamp is returned unchanged."""
    if not FIX_TIMESTAMPS or sent_at is None:
        return text
    stamp = sent_at.astimezone(LOCAL_TZ).strftime('%I:%M %p - %d %b %Y')
    return _STAMP_RE.sub(stamp, text, count=1)


_seen_messages = OrderedDict()


def _is_duplicate(key):
    """Telethon replays recent messages after a reconnect. Drop anything we
    have already forwarded."""
    if key in _seen_messages:
        return True
    _seen_messages[key] = True
    while len(_seen_messages) > 500:
        _seen_messages.popitem(last=False)
    return False


# ---------------------------------------------------------------------------
# Target group ledger
#
# Each target group keeps its OWN running totals, controlled only by Ethan and
# Larry. A forwarded payment adds to Total In; /add and /out adjust either side.
# The two total lines of a forwarded notification are rewritten to show this
# ledger, so the target group shows your books rather than the source group's.
#
# The bot never does arithmetic on the source group's figures - it reads them
# once to open the ledger, and from then on the ledger is its own.
# ---------------------------------------------------------------------------

MILESTONE_IN_STEP = int(os.getenv('MILESTONE_IN_STEP', '5000'))
MILESTONE_OUT_STEP = int(os.getenv('MILESTONE_OUT_STEP', '1000'))
MILESTONE_MENTIONS = os.getenv('MILESTONE_MENTIONS', '@ethannxxxx @Larryyxx')

# Only these accounts may move the numbers. Numeric ids, so a username change
# can neither break nor hijack it. @ethannxxxx and @Larryyxx.
LEDGER_ADMINS = {7418675217, 7578145913}

# Every chat that receives forwards.
TARGET_CHATS = {t for targets in FORWARD_RULES.values() for t in targets}

BOT_ID = int(BOT_TOKEN.split(':')[0]) if BOT_TOKEN and ':' in BOT_TOKEN else None

_TOTAL_IN_RE = re.compile(r'Total\s*In\s*:?\s*([\d,]+(?:\.\d+)?)', re.I)
_TOTAL_OUT_RE = re.compile(r'Total\s*Out\s*:?\s*([\d,]+(?:\.\d+)?)', re.I)

# Same patterns, split so the number can be substituted in place.
_TOTAL_IN_SUB = re.compile(r'(Total\s*In\s*:?\s*)([\d,]+(?:\.\d+)?)', re.I)
_TOTAL_OUT_SUB = re.compile(r'(Total\s*Out\s*:?\s*)([\d,]+(?:\.\d+)?)', re.I)

_RECEIVED_RE = re.compile(r'You\s+received\s+\$?\s*([\d,]+(?:\.\d+)?)', re.I)
_CMD_AMOUNT_RE = re.compile(r'^/\w+(?:@\w+)?\s+\$?\s*([\d,]+(?:\.\d+)?)')
_SET_RE = re.compile(r'^/set(?:@\w+)?\s+(in|out)\s+\$?\s*([\d,]+(?:\.\d+)?)', re.I)

# target chat id -> {'in': float, 'out': float}
_ledger = {}


def _to_float(raw):
    try:
        return float(raw.replace(',', ''))
    except (AttributeError, ValueError):
        return None


def parse_received_amount(text):
    """The dollar figure out of 'You received $15.0 from Gabriel W.'"""
    m = _RECEIVED_RE.search(text)
    return _to_float(m.group(1)) if m else None


def rewrite_totals(text, total_in, total_out):
    """Swap the two total lines for the ledger's figures, preserving the rest of
    the line exactly. Text without a totals block is returned untouched."""
    if not _TOTAL_IN_SUB.search(text):
        return text
    text = _TOTAL_IN_SUB.sub(lambda m: f"{m.group(1)}{total_in:.2f}", text, count=1)
    text = _TOTAL_OUT_SUB.sub(lambda m: f"{m.group(1)}{total_out:.2f}", text, count=1)
    return text


def parse_totals(text):
    """Pull (total_in, total_out) out of a notification. Either may be None."""
    def num(pattern):
        m = pattern.search(text)
        if not m:
            return None
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            return None
    return num(_TOTAL_IN_RE), num(_TOTAL_OUT_RE)


def crossed_milestone(previous, current, step):
    """Highest step boundary newly crossed, or None.

    A decrease returns None: the bot's totals reset at the start of a new cycle,
    and a reset must not replay alerts for ground already covered."""
    if step <= 0 or previous is None or current is None or current <= previous:
        return None
    if int(current // step) > int(previous // step):
        return int(current // step) * step
    return None


def _money(value):
    return f"{value:,.2f}$" if value is not None else "n/a"


def _step_label(step):
    return f"{step // 1000}K" if step >= 1000 and step % 1000 == 0 else f"{step:,}"


def in_milestone_text(level, total_in, total_out):
    return (f"🎉 MILESTONE HIT — ${level:,} IN! 🎉\n\n"
            f"➕ Total In : {_money(total_in)}\n"
            f"➖ Total Out: {_money(total_out)}\n\n"
            "Outstanding work, team! 🔥\n\n"
            "Every single deposit stacked up to this — that is\n"
            "consistency, not luck. The engine is running and\n"
            "the numbers speak for themselves.\n\n"
            f"Onward to the next {_step_label(MILESTONE_IN_STEP)}! 💪\n\n"
            f"{MILESTONE_MENTIONS}\n\n"
            "-ETHAN")


def out_milestone_text(level, total_in, total_out):
    return (f"⚠️ OUT ALERT — ${level:,} CROSSED ⚠️\n\n"
            f"➕ Total In : {_money(total_in)}\n"
            f"➖ Total Out: {_money(total_out)}\n\n"
            "The out is climbing and needs a look before it\n"
            "runs further ahead. Worth a quick review of what\n"
            "is going out and why.\n\n"
            f"Please check in: {MILESTONE_MENTIONS}\n\n"
            "-ETHAN")


async def check_milestones(target, before, after):
    """Post an alert to one target group when its ledger crosses a threshold.

    `before` and `after` are (total_in, total_out) for that group's ledger."""
    alerts = []
    level = crossed_milestone(before[0], after[0], MILESTONE_IN_STEP)
    if level:
        alerts.append(('IN', level, in_milestone_text(level, after[0], after[1])))
    level = crossed_milestone(before[1], after[1], MILESTONE_OUT_STEP)
    if level:
        alerts.append(('OUT', level, out_milestone_text(level, after[0], after[1])))

    for kind, level, body in alerts:
        print(f"🏁 [MILESTONE {kind}] ${level:,} crossed in {target}", flush=True)
        try:
            await bot.send_message(target, body)
            print(f"   🎯 {kind} milestone sent to {target}", flush=True)
        except Exception as e:
            print(f"   ❌ milestone send failed for {target}: {e}", flush=True)


def ledger_snapshot(target):
    """Current figures for a target, or zeroes if it has no ledger yet."""
    led = _ledger.get(target)
    return (led['in'], led['out']) if led else (0.0, 0.0)


def ledger_preview_payment(target, text):
    """What a forwarded payment WOULD do, without committing anything.

    Returns (before, after) as (in, out) tuples, or None when there is nothing
    to show - a message with no totals block and no ledger yet."""
    if target not in _ledger:
        # Opening balance is the source group's current figures. The payment in
        # this very message is already inside that figure, so it is not added
        # again - otherwise the first message would be counted twice.
        src_in, src_out = parse_totals(text)
        if src_in is None and src_out is None:
            return None
        opening = (src_in or 0.0, src_out or 0.0)
        return opening, opening

    before = ledger_snapshot(target)
    amount = parse_received_amount(text) or 0.0
    return before, (before[0] + amount, before[1])


def ledger_commit(target, after, note=''):
    """Store new figures.

    Called ONLY once the message carrying them is on the wire. The ledger is
    always exactly what the newest message in the group shows, so a failed send
    can never leave the books ahead of what anyone can see."""
    opening = target not in _ledger
    _ledger[target] = {'in': after[0], 'out': after[1]}
    print(f"📒 [LEDGER] {target} {'opened at' if opening else 'now'} "
          f"in={after[0]:.2f} out={after[1]:.2f}{note}", flush=True)


async def process_incoming(chat_id, text, origin, from_bot=False, sent_at=None):
    global forwarded_count, today_count

    print(f"📩 [MSG RECEIVED] ({origin}) Chat ID: {chat_id} | Text: '{text}'", flush=True)

    fixed = correct_timestamp(text, sent_at)
    if fixed != text:
        print(f"🕒 [TIME FIXED] -> {_STAMP_RE.search(fixed).group(0)}", flush=True)

    rule_key = resolve_rule_key(chat_id)
    if rule_key is None:
        print(f"⚠️ [SKIP] Chat ID {chat_id} is not in FORWARD_RULES.", flush=True)
        return

    if rule_key in BOT_ONLY_SOURCES and not from_bot:
        print(f"⚠️ [SKIP] Chat {chat_id} forwards bot messages only.", flush=True)
        return

    lowered = text.lower()
    if not any(kw.lower() in lowered for kw in KEYWORDS):
        print("⚠️ [SKIP] Message does not contain keyword 'You received'.", flush=True)
        return

    print("✅ [KEYWORD MATCH] Forwarding message...", flush=True)
    for target in FORWARD_RULES[rule_key]:
        # Each target keeps its own books, so the totals shown are per target.
        movement = ledger_preview_payment(target, text) if from_bot else None
        body = fixed
        if movement:
            body = rewrite_totals(fixed, movement[1][0], movement[1][1])
        elif target in _ledger:
            # Human-pasted text. Show the ledger so the group never displays two
            # different sets of numbers, but do not book an amount we cannot
            # trust - only the notification bot moves the books.
            body = rewrite_totals(fixed, *ledger_snapshot(target))
        try:
            # Always sent with the bot token, never from the user account.
            await bot.send_message(target, body)
        except Exception as e:
            # Nothing committed: the ledger stays level with the last message
            # the group can actually see.
            print(f"❌ [FORWARD ERROR] Target {target}: {e}", flush=True)
            continue

        if movement:
            ledger_commit(target, movement[1])
        print(f"🚀 [FORWARD SUCCESS] Sent to {target}", flush=True)
        forwarded_count += 1
        today_count += 1
        last_messages.append(body[:50])
        if len(last_messages) > 10:
            last_messages.pop(0)

        # After the payment confirmation, so the alert lands beneath it.
        if movement:
            await check_milestones(target, movement[0], movement[1])


# ---------------------------------------------------------------------------
# Bot API handlers (unchanged behaviour, async syntax)
# ---------------------------------------------------------------------------

@bot.message_handler(commands=['start'])
async def start(message):
    if message.chat.id == ADMIN_ID:
        await bot.reply_to(message, 'Bot is running. Use /help to see all commands.')


@bot.message_handler(commands=['status'])
async def status(message):
    if message.chat.id == ADMIN_ID:
        txt = (f"Bot Online\nGroups: {len(FORWARD_RULES)}\n"
               f"Forwarded: {forwarded_count}\nUptime: {get_uptime()}\n"
               f"Userbot: {userbot_status}")
        await bot.reply_to(message, txt)


@bot.message_handler(commands=['ping'])
async def ping(message):
    if message.chat.id == ADMIN_ID:
        await bot.reply_to(message, 'Pong! Bot is alive.')


@bot.message_handler(commands=['add', 'out'])
async def ledger_command(message):
    """/add <amount> and /out <amount>, target groups only, Ethan and Larry only."""
    chat_id = message.chat.id
    user_id = getattr(message.from_user, 'id', None)

    # Silent in source groups and DMs, so the source side cannot reach the books.
    if chat_id not in TARGET_CHATS:
        return

    if user_id not in LEDGER_ADMINS:
        print(f"⛔ [LEDGER] {user_id} denied in {chat_id}", flush=True)
        await bot.reply_to(message, "⛔ Not permitted. Only Ethan and Larry can "
                                    "change the totals.")
        return

    command = message.text.lstrip('/').split('@')[0].split()[0].lower()
    match = _CMD_AMOUNT_RE.match(message.text)
    amount = _to_float(match.group(1)) if match else None
    if amount is None or amount <= 0:
        await bot.reply_to(message, f"Usage: /{command} <amount>\nExample: /{command} 100")
        return

    before = ledger_snapshot(chat_id)
    if command == 'add':
        after = (before[0] + amount, before[1])
        heading = f"💰 Deposit = +{amount:.2f}$"
    else:
        after = (before[0], before[1] + amount)
        heading = f"📤 Out = -{amount:.2f}$"

    try:
        await bot.send_message(chat_id,
                               f"{heading}\n\n"
                               f"📊 Group Total:\n"
                               f"➕ Total In : {after[0]:.2f}$\n"
                               f"➖ Total Out: {after[1]:.2f}$")
    except Exception as e:
        print(f"❌ [LEDGER] /{command} NOT applied, send failed: {e}", flush=True)
        return

    ledger_commit(chat_id, after, f" (/{command} {amount:.2f} by {user_id})")
    await check_milestones(chat_id, before, after)


@bot.message_handler(commands=['set'])
async def ledger_set_command(message):
    """/set in <amount> or /set out <amount> - overwrite a column outright.

    This is the correction route: /add and /out can only increase a column, so a
    figure that has gone wrong needs to be set directly."""
    chat_id = message.chat.id
    user_id = getattr(message.from_user, 'id', None)

    if chat_id not in TARGET_CHATS:
        return

    if user_id not in LEDGER_ADMINS:
        print(f"⛔ [LEDGER] /set by {user_id} denied in {chat_id}", flush=True)
        await bot.reply_to(message, "⛔ Not permitted. Only Ethan and Larry can "
                                    "change the totals.")
        return

    match = _SET_RE.match(message.text)
    amount = _to_float(match.group(2)) if match else None
    if amount is None or amount < 0:
        await bot.reply_to(message, "Usage: /set in <amount>   or   /set out <amount>\n"
                                    "Example: /set in 800")
        return

    column = match.group(1).lower()
    before = ledger_snapshot(chat_id)
    after = (amount, before[1]) if column == 'in' else (before[0], amount)

    try:
        await bot.send_message(chat_id,
                               f"✏️ Corrected: Total {'In' if column == 'in' else 'Out'} "
                               f"set to {amount:.2f}$\n\n"
                               f"📊 Group Total:\n"
                               f"➕ Total In : {after[0]:.2f}$\n"
                               f"➖ Total Out: {after[1]:.2f}$")
    except Exception as e:
        print(f"❌ [LEDGER] /set NOT applied, send failed: {e}", flush=True)
        return

    ledger_commit(chat_id, after, f" (/set {column} {amount:.2f} by {user_id})")
    await check_milestones(chat_id, before, after)


@bot.message_handler(content_types=['text'])
async def forward_text(message):
    sender_is_bot = bool(getattr(message.from_user, 'is_bot', False))
    sent_at = (datetime.fromtimestamp(message.date, tz=timezone.utc)
               if getattr(message, 'date', None) else None)
    await process_incoming(message.chat.id, message.text, 'bot-api',
                           from_bot=sender_is_bot, sent_at=sent_at)


# ---------------------------------------------------------------------------
# Telethon listener
# ---------------------------------------------------------------------------

def _parse_source_bots():
    ids, usernames = set(), set()
    for item in SOURCE_BOTS.split(','):
        item = item.strip().lstrip('@')
        if not item:
            continue
        if item.lstrip('-').isdigit():
            ids.add(int(item))
        else:
            usernames.add(item.lower())
    return ids, usernames


def _configured_source_chats():
    if TELETHON_SOURCE_CHATS.strip():
        return [int(c.strip()) for c in TELETHON_SOURCE_CHATS.split(',') if c.strip()]
    return list(FORWARD_RULES.keys())


def _is_plain_text(message):
    """Mirrors the Bot API handler's content_types=['text']: text only, no
    photos, videos, documents, stickers or their captions. A message carrying
    only a link preview is still plain text."""
    if message.media is None:
        return True
    return isinstance(message.media, MessageMediaWebPage)


def _is_target_sender(sender, bot_ids, bot_usernames):
    if sender is None:
        return False
    if bot_ids or bot_usernames:
        username = (getattr(sender, 'username', '') or '').lower()
        return sender.id in bot_ids or username in bot_usernames
    # Nothing configured: accept any bot. Humans already arrive via the Bot API.
    return bool(getattr(sender, 'bot', False))


async def _resolve_source_chats(client, wanted):
    """Resolve each configured chat separately so one bad id cannot stop the
    listener from starting on the good ones."""
    resolved = []
    for chat_id in wanted:
        entity = None
        for candidate in [chat_id] + _id_variants(chat_id):
            try:
                entity = await client.get_entity(candidate)
                break
            except Exception:
                continue
        if entity is None:
            print(f"⚠️ [TELETHON] Could not resolve source chat {chat_id} - skipping it.", flush=True)
            continue
        title = getattr(entity, 'title', None) or getattr(entity, 'username', '')
        print(f"👁️ [TELETHON] Watching {chat_id} ({title})", flush=True)
        resolved.append(entity)
    return resolved


async def recover_ledgers(client):
    """Rebuild each target's ledger from the last totals this bot published there.

    Railway wipes the filesystem on every deploy, so the books cannot live on
    disk. They live in the messages themselves: the bot's own posts carry the
    figures, so reading the newest one back restores the running totals."""
    for target in sorted(TARGET_CHATS):
        try:
            entity = await client.get_entity(target)
        except Exception as e:
            print(f"⚠️ [LEDGER] {target} unreachable, will open on first message: {e}",
                  flush=True)
            continue

        found = False
        async for message in client.iter_messages(entity, limit=200):
            sender = await message.get_sender()
            if BOT_ID is None or getattr(sender, 'id', None) != BOT_ID:
                continue
            total_in, total_out = parse_totals(message.raw_text or '')
            if total_in is None or total_out is None:
                continue
            _ledger[target] = {'in': total_in, 'out': total_out}
            print(f"📒 [LEDGER] {target} recovered: in={total_in:.2f} "
                  f"out={total_out:.2f} (from {message.date:%m-%d %H:%M})", flush=True)
            found = True
            break
        if not found:
            print(f"📒 [LEDGER] {target} has no prior totals - opens on first message",
                  flush=True)


async def run_userbot():
    global userbot_status

    if not TELETHON_ENABLED:
        userbot_status = 'disabled (no TELEGRAM_API_ID / TELEGRAM_API_HASH)'
        print("ℹ️ [TELETHON] Disabled - set TELEGRAM_API_ID and TELEGRAM_API_HASH to "
              "receive messages from other bots.", flush=True)
        return

    bot_ids, bot_usernames = _parse_source_bots()
    session = StringSession(TELETHON_SESSION) if TELETHON_SESSION else TELETHON_SESSION_NAME
    warned_unauthorised = False

    while True:
        client = TelegramClient(session, int(API_ID), API_HASH)
        try:
            # connect() instead of start() so a missing session fails loudly
            # rather than blocking on an interactive login prompt in production.
            await client.connect()
            if not await client.is_user_authorized():
                userbot_status = 'not authorised'
                print("❌ [TELETHON] Session is not authorised. Regenerate it with: "
                      "python3 telethon_login.py --deploy", flush=True)
                if not warned_unauthorised:
                    warned_unauthorised = True
                    await notify_admin(
                        "⚠️ Telethon session is NOT authorised - messages from bots are "
                        "not being forwarded. Regenerate TELETHON_SESSION with:\n"
                        "python3 telethon_login.py --deploy\n\n"
                        "Note: the deployment needs its own session. Sharing one auth key "
                        "between Railway and your Mac makes Telegram revoke it.")
                await asyncio.sleep(300)
                continue

            me = await client.get_me()
            print(f"🔐 [TELETHON] Logged in as {me.first_name} (@{me.username})", flush=True)

            # Warms the entity cache so numeric chat ids resolve reliably.
            await client.get_dialogs()

            await recover_ledgers(client)

            chats = await _resolve_source_chats(client, _configured_source_chats())
            if not chats:
                userbot_status = 'no source chats resolved'
                print("❌ [TELETHON] No source chats could be resolved - listener idle.", flush=True)
                return

            @client.on(events.NewMessage(chats=chats))
            async def on_source_message(event):
                sender = await event.get_sender()
                if not _is_target_sender(sender, bot_ids, bot_usernames):
                    return
                if not _is_plain_text(event.message):
                    return
                text = event.raw_text
                if not text:
                    return
                if _is_duplicate((event.chat_id, event.id)):
                    return
                # _is_target_sender above already guaranteed a bot sender.
                await process_incoming(event.chat_id, text, 'telethon',
                                       from_bot=True, sent_at=event.message.date)

            target = SOURCE_BOTS if SOURCE_BOTS.strip() else 'any bot'
            userbot_status = f'listening ({len(chats)} chats, from: {target})'
            print(f"✅ [TELETHON] Listening for messages from: {target}", flush=True)

            await client.run_until_disconnected()
            print("⚠️ [TELETHON] Disconnected - reconnecting in 15s.", flush=True)
        except Exception as e:
            userbot_status = f'error: {e}'
            print(f"❌ [TELETHON ERROR] {e} - retrying in 15s.", flush=True)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        await asyncio.sleep(15)


# ---------------------------------------------------------------------------
# Entry point - one event loop, both listeners
# ---------------------------------------------------------------------------

async def run_bot():
    while True:
        try:
            await bot.polling(none_stop=True, allowed_updates=['message'])
        except Exception as e:
            print(f"Polling Error: {e}", flush=True)
            await asyncio.sleep(5)


async def main():
    print('Bot running...', flush=True)
    await notify_admin('Bot is ONLINE. Use /help to see all commands.')
    await asyncio.gather(run_bot(), run_userbot(), return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
