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
# Milestone alerts
#
# Every notification carries the group's running totals:
#     ➕ Total In : 675.01$
#     ➖ Total Out: 557.00$
# so both figures are read straight off the message. No extra message types are
# watched and nothing new is forwarded - the /add and /out commands stay in the
# source group where they belong.
# ---------------------------------------------------------------------------

MILESTONE_IN_STEP = int(os.getenv('MILESTONE_IN_STEP', '5000'))
MILESTONE_OUT_STEP = int(os.getenv('MILESTONE_OUT_STEP', '1000'))
MILESTONE_MENTIONS = os.getenv('MILESTONE_MENTIONS', '@ethannxxxx @Larryyxx')

_TOTAL_IN_RE = re.compile(r'Total\s*In\s*:?\s*([\d,]+(?:\.\d+)?)', re.I)
_TOTAL_OUT_RE = re.compile(r'Total\s*Out\s*:?\s*([\d,]+(?:\.\d+)?)', re.I)

# rule_key -> (last_total_in, last_total_out)
_totals_seen = {}


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


async def check_milestones(rule_key, targets, text, from_bot):
    """Post an alert to the rule's targets when a threshold is crossed.

    Only bot-sent messages count, so a human re-pasting an old notification
    cannot make the totals jump and fire a false alert."""
    if not from_bot:
        return

    total_in, total_out = parse_totals(text)
    if total_in is None and total_out is None:
        return

    previous = _totals_seen.get(rule_key)
    _totals_seen[rule_key] = (total_in, total_out)
    if previous is None:
        # First notification after a restart only establishes a baseline.
        print(f"📊 [TOTALS] Baseline for {rule_key}: "
              f"in={total_in} out={total_out}", flush=True)
        return

    alerts = []
    level = crossed_milestone(previous[0], total_in, MILESTONE_IN_STEP)
    if level:
        alerts.append(('IN', level, in_milestone_text(level, total_in, total_out)))
    level = crossed_milestone(previous[1], total_out, MILESTONE_OUT_STEP)
    if level:
        alerts.append(('OUT', level, out_milestone_text(level, total_in, total_out)))

    for kind, level, body in alerts:
        print(f"🏁 [MILESTONE {kind}] ${level:,} crossed in {rule_key}", flush=True)
        for target in targets:
            try:
                await bot.send_message(target, body)
                print(f"   🎯 {kind} milestone sent to {target}", flush=True)
            except Exception as e:
                print(f"   ❌ milestone send failed for {target}: {e}", flush=True)


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
        try:
            # Always sent with the bot token, never from the user account.
            await bot.send_message(target, fixed)
            print(f"🚀 [FORWARD SUCCESS] Sent to {target}", flush=True)
            forwarded_count += 1
            today_count += 1
            last_messages.append(fixed[:50])
            if len(last_messages) > 10:
                last_messages.pop(0)
        except Exception as e:
            print(f"❌ [FORWARD ERROR] Target {target}: {e}", flush=True)

    # After the payment confirmation, so the alert lands beneath it.
    await check_milestones(rule_key, FORWARD_RULES[rule_key], text, from_bot)


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
