import asyncio
import os
import re
import signal
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone

from telebot.async_telebot import AsyncTeleBot
from telebot.types import ReactionTypeEmoji

from telethon import TelegramClient, events, utils
from telethon.errors import (AuthKeyDuplicatedError, AuthKeyUnregisteredError,
                             SessionRevokedError, UserDeactivatedBanError)
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import MessageMediaWebPage, ReactionEmoji

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

# The one exception to "reading only" above, and it is a narrow one: the cashout
# escalation has to reach people PRIVATELY, and a bot cannot do that. A bot may
# only message someone who has already pressed Start on it, and it can never
# address a person by @username at all - only by numeric id. The user account
# has neither limit. So when the bot cannot deliver an escalation DM, the user
# account sends it instead (and reacts, where a channel denies the bot).
# Set USERBOT_SEND=0 to keep the account strictly read-only, accepting that only
# people who have started the bot will get the private warning.
USERBOT_SEND = os.getenv('USERBOT_SEND', '1') != '0'

# Railway overlaps deploys: the replacement container boots while the outgoing
# one is still alive. For the Bot API that is a harmless getUpdates 409, but for
# Telethon it is fatal - two IPs on one auth key and Telegram destroys the key
# permanently, which silently stops every forward until someone logs in again.
# Holding the new container back past the changeover keeps the two from ever
# being connected at the same moment. Costs one quiet minute after a deploy.
ON_RAILWAY = bool(os.getenv('RAILWAY_ENVIRONMENT') or os.getenv('RAILWAY_SERVICE_ID')
                  or os.getenv('RAILWAY_PROJECT_ID'))
TELETHON_START_DELAY = int(os.getenv('TELETHON_START_DELAY', '45' if ON_RAILWAY else '0'))

# On connect, look back over this window and forward anything that was missed
# while the listener was down. 0 disables the sweep. The cap is a guard against
# a misconfiguration dumping hours of history into a group.
CATCHUP_LOOKBACK_MINUTES = int(os.getenv('CATCHUP_LOOKBACK_MINUTES', '180'))
CATCHUP_MAX = int(os.getenv('CATCHUP_MAX', '25'))
CATCHUP_SCAN_LIMIT = int(os.getenv('CATCHUP_SCAN_LIMIT', '300'))

# The target is read back further than the source. A target group carries more
# traffic than its source - every forward, plus /add and /out confirmations,
# milestones and idle prompts - so an equal limit can run out of room before it
# has covered the same window, and anything past that point would look
# undelivered when it is sitting right there.
CATCHUP_TARGET_SCAN_LIMIT = int(os.getenv('CATCHUP_TARGET_SCAN_LIMIT',
                                          str(CATCHUP_SCAN_LIMIT * 3)))

# ---------------------------------------------------------------------------
# Runtime state (unchanged)
# ---------------------------------------------------------------------------

forwarded_count = 0
today_count = 0
start_time = datetime.now()
last_messages = []

userbot_status = 'disabled'

# Set once run_userbot() has a client, so the shutdown handler can release it.
_active_client = None

bot = AsyncTeleBot(BOT_TOKEN)


async def notify_admin(msg):
    try:
        await bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        print(f"Notify Admin Error: {e}", flush=True)


class _ConflictWatcher:
    """Notices when a second process is polling this same bot token.

    It has to hook telebot's exception_handler rather than wrap bot.polling():
    with none_stop=True, polling() catches the 409 internally, logs it and
    carries on, so nothing ever propagates out for a try/except to see.

    A 409 is worth shouting about because it is never only a polling problem.
    Every process polling this token is also running run_userbot() with the
    same TELETHON_SESSION from a different IP, and that is what makes Telegram
    destroy the auth key and stop all forwarding."""

    def __init__(self):
        self.conflicts = 0
        self.warned = False

    async def handle(self, exception):
        text = str(exception)
        if '409' not in text and 'terminated by other getUpdates' not in text:
            return False        # not ours: let telebot log it as usual

        self.conflicts += 1
        print(f"⚠️ [CONFLICT x{self.conflicts}] Another process is polling this "
              f"token.", flush=True)

        # A Railway deploy changeover overlaps the old and new container for a
        # few seconds, which is normal and self-clears. Sustained conflict is a
        # genuine second instance.
        if self.conflicts >= 15 and not self.warned:
            self.warned = True
            await notify_admin(
                "🚨 TWO BOT INSTANCES ARE RUNNING on the same token.\n\n"
                "Telegram keeps cutting one of them off (getUpdates 409). Both are "
                "also using the same TELETHON_SESSION from different IPs, which "
                "destroys the session key and stops ALL forwarding.\n\n"
                "Check for a duplicate Railway service on this repo. Replacing "
                "TELETHON_SESSION while this is true will just burn the new one too.")
        return True             # handled: suppress the repeated stack-trace log


_conflict_watcher = _ConflictWatcher()
bot.exception_handler = _conflict_watcher


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
# Amount for /add and /out, with an optional minus written either way round:
# "/add -100" and "/add-100" both take 100 back off Total In. The joined form
# needs its own handler as well - Telegram reads the command as the word after
# the slash, so "/add-100" is the command "add-100" and never reaches a
# commands=['add'] handler at all. This only parses it.
_CMD_AMOUNT_RE = re.compile(r'^/\w+(?:@\w+)?\s*(-?)\s*\$?\s*([\d,]+(?:\.\d+)?)')

# The command word itself, tolerating the joined form: "/add-100" -> "add".
_CMD_NAME_RE = re.compile(r'^/(\w+)')

# Which spellings need routing past telebot's command matcher.
_JOINED_LEDGER_RE = re.compile(r'^/(?:add|out)(?:@\w+)?-', re.I)
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
    text = _TOTAL_IN_SUB.sub(lambda m: f"{m.group(1)}{total_in:,.2f}", text, count=1)
    text = _TOTAL_OUT_SUB.sub(lambda m: f"{m.group(1)}{total_out:,.2f}", text, count=1)
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
          f"in={after[0]:,.2f} out={after[1]:,.2f}{note}", flush=True)


# ---------------------------------------------------------------------------
# Idle payment watchdog
#
# When a target group stops receiving payments, ask the group whether there is a
# problem. Repeats every interval while it stays quiet, with different wording
# each time, and resets the moment a payment arrives.
# ---------------------------------------------------------------------------

IDLE_ALERT_MINUTES = int(os.getenv('IDLE_ALERT_MINUTES', '90'))
IDLE_ALERT_CHATS = {-5580596463, -5350880041}      # CHIME GAFFER, CHIME PICCASO

IDLE_NAMES = {-5580596463: 'CHIME GAFFER', -5350880041: 'CHIME PICCASO'}
# Short names so the groups can be targeted from a private chat.
IDLE_ALIASES = {'gaffer': -5580596463, 'piccaso': -5350880041}

# Rotated so a repeat never reads identically. The duration line differs every
# time in any case, so even a full cycle cannot produce a duplicate message.
_IDLE_BODIES = [
    ("⏳ No payments here for {duration}.",
     "Is everything okay on the payment side, or are you\n"
     "facing any issues? Let us know if there is any!"),
    ("⏳ Still quiet — {duration} without a payment.",
     "Checking in again. Is everything running fine on\n"
     "your side, or is something holding payments up?\n"
     "Let us know if there is any issue!"),
    ("⏳ {duration} with no payments.",
     "Any update on the payments? If something is stuck\n"
     "or not working, tell us and we will sort it out.\n"
     "Let us know if there is any issue!"),
    ("⏳ {duration} quiet now.",
     "Nothing has come through in a while. Is there a\n"
     "problem at your end? A quick word either way would\n"
     "help — let us know if there is any issue!"),
]

# target -> {'last': datetime|None, 'since': datetime, 'sent': int}
_idle_state = {}


def _idle_slot(target):
    return _idle_state.setdefault(target, {'last': None,
                                           'since': datetime.now(timezone.utc),
                                           'sent': 0,
                                           'paused': False})


def _humanise(minutes):
    hours, mins = divmod(int(minutes), 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if mins:
        parts.append(f"{mins} minute" + ("s" if mins != 1 else ""))
    return " ".join(parts) or "0 minutes"


async def note_payment(target):
    """A payment landed: restart the clock and the wording rotation.

    A payment also lifts a pause - if money is moving again, whatever was wrong
    has cleared, and a pause nobody remembers would silently kill the watchdog."""
    if target not in IDLE_ALERT_CHATS:
        return
    slot = _idle_slot(target)
    now = datetime.now(timezone.utc)
    slot['last'] = now
    slot['since'] = now
    slot['sent'] = 0

    if slot['paused']:
        # Silently re-armed. Nothing is posted: the group never sees chatter
        # about the watchdog's own state.
        slot['paused'] = False
        print(f"🔔 [IDLE] {target} auto-resumed on payment", flush=True)


def set_idle_paused(target, paused):
    slot = _idle_slot(target)
    slot['paused'] = paused
    if not paused:
        # Fresh clock, so resuming after a long pause cannot fire instantly.
        slot['since'] = datetime.now(timezone.utc)
        slot['sent'] = 0


def idle_alert_text(target, quiet_minutes, index):
    """Just the elapsed time and the question - no figures. The ledger belongs
    in payment messages, not in a prompt asking whether something is wrong."""
    header, question = _IDLE_BODIES[index % len(_IDLE_BODIES)]
    return (f"{header.format(duration=_humanise(quiet_minutes))}\n\n"
            f"{question}\n\n"
            "-ETHAN")


async def idle_watchdog():
    if IDLE_ALERT_MINUTES <= 0:
        print("ℹ️ [IDLE] watchdog disabled (IDLE_ALERT_MINUTES=0)", flush=True)
        return

    for target in IDLE_ALERT_CHATS:
        _idle_slot(target)          # clock starts now, not at epoch
    print(f"⏳ [IDLE] watching {len(IDLE_ALERT_CHATS)} groups, "
          f"prompt every {_humanise(IDLE_ALERT_MINUTES)} of silence", flush=True)

    while True:
        await asyncio.sleep(60)
        now = datetime.now(timezone.utc)
        for target in sorted(IDLE_ALERT_CHATS):
            slot = _idle_slot(target)
            if slot['paused']:
                continue
            quiet = (now - slot['since']).total_seconds() / 60.0
            due = IDLE_ALERT_MINUTES * (slot['sent'] + 1)
            if quiet < due:
                continue
            try:
                await bot.send_message(target, idle_alert_text(target, due, slot['sent']))
                slot['sent'] += 1
                print(f"⏳ [IDLE] {target} quiet {_humanise(due)}, "
                      f"prompt #{slot['sent']} sent", flush=True)
            except Exception as e:
                print(f"❌ [IDLE] prompt failed for {target}: {e}", flush=True)


# ---------------------------------------------------------------------------
# Cashout requests
#
# Payments travel outward, source -> target. Cashout requests travel the other
# way: the chime groups ask for money to go OUT, and that request has to be seen
# and actioned by the crew on the other side.
#
#   CHIME PICCASO --"CASHOUT REQUEST"--> MH X LARRY GROUP 2
#   CHIME GAFFER  --"CASHOUT REQUEST"--> Chime Rev & out no-7
#
# The request is posted with the crew tagged. If nobody answers it inside the
# timeout it is re-tagged in the group AND each of them is warned privately.
# When somebody finally replies with /out, that reply is sent back to the chime
# group the request came from and the forwarded request is hearted.
#
# This is a SEPARATE table from FORWARD_RULES on purpose. Putting these pairs in
# there would drag the chime groups into TARGET_CHATS and make the ledger, the
# milestones and the idle watchdog all fire on the wrong side of the flow.
# ---------------------------------------------------------------------------

CASHOUT_KEYWORD = os.getenv('CASHOUT_KEYWORD', 'CASHOUT REQUEST')

CASHOUT_ROUTES = {
    -5350880041: -1003894781195,        # CHIME PICCASO -> MH X LARRY GROUP 2
    -5580596463: -1002335630148,        # CHIME GAFFER  -> Chime Rev & out no-7
}

# Reverse lookup, for recognising a message posted in a handling group.
_CASHOUT_HANDLERS = {handling: source for source, handling in CASHOUT_ROUTES.items()}

CHAT_NAMES = {
    -5350880041: 'CHIME PICCASO',
    -5580596463: 'CHIME GAFFER',
    -1003894781195: 'MH X LARRY GROUP 2',
    -1002335630148: 'Chime Rev & out no-7',
}

# Tagged on the forwarded request and again on every reminder.
CASHOUT_MENTIONS = os.getenv('CASHOUT_MENTIONS',
                             '@Maynuddin23 @MHSUPPORTZONE @maynuddin233')

# Anyone here speaking in the handling group counts as "they responded" and puts
# the reminder clock back to zero. The request itself stays OPEN until a real
# /out lands - an acknowledgement is not a cashout.
CASHOUT_RESPONDERS = {h.strip().lower().lstrip('@') for h in
                      os.getenv('CASHOUT_RESPONDERS',
                                'Maynuddin23,MHSUPPORTZONE,maynuddin233').split(',')
                      if h.strip()}

# Warned privately once a request goes unanswered. Larry leads, he is the one
# who chases it.
CASHOUT_DM_HANDLES = [h.strip().lstrip('@') for h in
                      os.getenv('CASHOUT_DM_HANDLES',
                                'larryyxx,Maynuddin23,MHSUPPORTZONE,maynuddin233').split(',')
                      if h.strip()]

CASHOUT_TIMEOUT_MINUTES = int(os.getenv('CASHOUT_TIMEOUT_MINUTES', '5'))

# Stop reminding after this many rounds, so a request that was settled off-chat
# cannot nag the group forever. The request stays open either way - a late /out
# is still forwarded and still hearted.
CASHOUT_MAX_NUDGES = int(os.getenv('CASHOUT_MAX_NUDGES', '6'))

CASHOUT_HEART = os.getenv('CASHOUT_HEART', '❤')

# @username -> numeric id. A bot can only DM an id, so the ones we know are
# seeded here and the rest are learned the first time that person speaks in a
# watched chat. @Larryyxx and @ethannxxxx, matching LEDGER_ADMINS.
_user_ids = {'larryyxx': 7418675217, 'ethannxxxx': ADMIN_ID}

# Set once the userbot knows who it is, so it never DMs its own account.
_userbot_username = ''

# /out anywhere in the message, as a word. "/out", "/out 500", "ok /out done".
_OUT_CMD_RE = re.compile(r'(?:^|\s)/out\b', re.I)

# The figure inside that reply, wherever it sits. The ledger's own _CMD_AMOUNT_RE
# is anchored to the start of the message, which is right for a typed command but
# would miss "ok /out 500" - and this text was typed by someone else, in another
# group, with no reason to keep to that shape.
_OUT_AMOUNT_RE = re.compile(r'/out(?:@\w+)?\s+\$?\s*([\d,]+(?:\.\d+)?)', re.I)

# handling chat id -> [request, ...], oldest first
_pending_cashouts = {}


def chat_name(chat_id):
    return CHAT_NAMES.get(chat_id, str(chat_id))


def _canonical(chat_id, table):
    """Match a chat id against a config table under either id spelling."""
    if chat_id in table:
        return chat_id
    for variant in _id_variants(chat_id):
        if variant in table:
            return variant
    return None


def remember_user(sender):
    """Learn @username -> id from anyone who speaks in a watched chat.

    This is what makes the escalation DM reachable by the bot: the crew are
    configured by username, but the Bot API can only send to an id."""
    username = (getattr(sender, 'username', '') or '').lower()
    user_id = getattr(sender, 'id', None)
    if username and user_id and _user_ids.get(username) != user_id:
        _user_ids[username] = user_id
        print(f"👤 [CASHOUT] learned @{username} = {user_id}", flush=True)


def _is_responder(user_id, username):
    if (username or '').lower() in CASHOUT_RESPONDERS:
        return True
    return user_id in LEDGER_ADMINS        # Ethan and Larry always count


async def dm_crew(text):
    """Private warning to each configured handle.

    Bot first, because a message from the bot is the one that fits the rest of
    the system. The user account is the fallback for anyone the bot cannot reach
    - see USERBOT_SEND. Reports who could not be reached at all."""
    unreachable = []
    for handle in CASHOUT_DM_HANDLES:
        key = handle.lower()
        sent = False

        user_id = _user_ids.get(key)
        if user_id:
            try:
                await bot.send_message(user_id, text)
                sent = True
                print(f"✉️ [CASHOUT] DM sent to @{handle} via bot", flush=True)
            except Exception as e:
                # Almost always "bot can't initiate conversation with a user".
                print(f"⚠️ [CASHOUT] bot DM to @{handle} failed: {e}", flush=True)

        if not sent and USERBOT_SEND and _active_client is not None:
            try:
                await _active_client.send_message(handle, text)
                sent = True
                # Messaging the logged-in account itself is allowed on purpose.
                # Telegram files it under Saved Messages, which that person does
                # see - and if the session belongs to someone ON this list, the
                # alternative is the person most likely to act on it being the
                # only one who never hears about it.
                where = ' (Saved Messages)' if key == _userbot_username else ''
                print(f"✉️ [CASHOUT] DM sent to @{handle} via user account{where}",
                      flush=True)
            except Exception as e:
                print(f"⚠️ [CASHOUT] user-account DM to @{handle} failed: {e}", flush=True)

        if not sent:
            unreachable.append(handle)

    if unreachable:
        names = ', '.join('@' + h for h in unreachable)
        print(f"❌ [CASHOUT] nobody could be DMed at: {names}", flush=True)
        await notify_admin(
            f"⚠️ Could not privately warn {names} about an overdue cashout.\n\n"
            "Ask them to open the bot and press Start, which lets the bot DM "
            "them directly. Until then only the group mention reaches them.")


async def heart_request(handling, message_id):
    """❤ the forwarded request, marking it done.

    Falls back to the user account because a broadcast channel refuses
    reactions from a bot that is not an admin there, and the account already
    has the rights."""
    try:
        await bot.set_message_reaction(handling, message_id,
                                       [ReactionTypeEmoji(CASHOUT_HEART)])
        print(f"❤️ [CASHOUT] hearted {message_id} in {chat_name(handling)}", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ [CASHOUT] bot could not react in {chat_name(handling)}: {e}",
              flush=True)

    if USERBOT_SEND and _active_client is not None:
        try:
            entity = await _resolve_one(_active_client, handling)
            if entity is not None:
                await _active_client(SendReactionRequest(
                    peer=entity, msg_id=message_id,
                    reaction=[ReactionEmoji(emoticon=CASHOUT_HEART)]))
                print(f"❤️ [CASHOUT] hearted {message_id} in {chat_name(handling)} "
                      "via user account", flush=True)
                return True
        except Exception as e:
            print(f"❌ [CASHOUT] user-account reaction failed in "
                  f"{chat_name(handling)}: {e}", flush=True)
    return False


async def open_cashout_request(source, text, sent_at):
    """Post a cashout request into its handling group and start the clock."""
    handling = CASHOUT_ROUTES[source]
    body = f"{correct_timestamp(text, sent_at)}\n\n{CASHOUT_MENTIONS}"
    try:
        sent = await bot.send_message(handling, body)
    except Exception as e:
        print(f"❌ [CASHOUT] could not post {chat_name(source)} request to "
              f"{chat_name(handling)}: {e}", flush=True)
        await notify_admin(
            f"🚨 A CASHOUT REQUEST from {chat_name(source)} could not be posted to "
            f"{chat_name(handling)}:\n{e}\n\n"
            "Nobody has been told about it. Check the bot is still a member there "
            "and allowed to post.")
        return

    now = datetime.now(timezone.utc)
    _pending_cashouts.setdefault(handling, []).append({
        'origin': source,
        'text': text,
        'message_id': sent.message_id,     # what gets hearted
        'opened': now,
        'last_seen': now,                  # reset by any reply from the crew
        'nudges': 0,
        'exhausted': False,
    })
    print(f"📤 [CASHOUT] {chat_name(source)} -> {chat_name(handling)} "
          f"(msg {sent.message_id}), waiting {CASHOUT_TIMEOUT_MINUTES}m for /out",
          flush=True)


async def book_cashout_out(origin, text):
    """Move the chime group's Total Out by the figure in the /out reply.

    The forwarded /out is posted BY the bot, so the ordinary /out handler never
    sees it - that one is reachable only by Ethan and Larry, and stays that way.
    The money still has to leave the books, so it is booked here instead, in
    exactly the shape /out itself posts.

    That shape is not cosmetic. recover_ledgers() rebuilds the books after a
    deploy by reading back the newest bot message carrying BOTH totals, so
    booking silently - without posting the figures - would let the next redeploy
    roll this cashout straight back off the books."""
    match = _OUT_AMOUNT_RE.search(text)
    amount = _to_float(match.group(1)) if match else None
    if amount is None or amount <= 0:
        # A bare "/out" with no figure. The instruction still gets forwarded and
        # hearted; there is simply nothing to book.
        print(f"📒 [CASHOUT] no amount in the /out - {chat_name(origin)} totals "
              "left alone", flush=True)
        return

    before = ledger_snapshot(origin)
    after = (before[0], before[1] + amount)
    try:
        await bot.send_message(origin,
                               f"📤 Out = -{amount:,.2f}$\n\n"
                               f"📊 Group Total:\n"
                               f"➕ Total In : {after[0]:,.2f}$\n"
                               f"➖ Total Out: {after[1]:,.2f}$")
    except Exception as e:
        # Nothing committed - the same rule the rest of the ledger keeps: the
        # books never move ahead of what the group can actually see.
        print(f"❌ [CASHOUT] Total Out NOT moved in {chat_name(origin)}, "
              f"send failed: {e}", flush=True)
        return

    ledger_commit(origin, after, f" (cashout /out {amount:,.2f})")
    await check_milestones(origin, before, after)


def _match_request(queue, reply_to):
    """Which open request a /out is answering.

    An explicit reply is unambiguous, so it wins. Otherwise the oldest open
    request is taken, which is the order they are worked in."""
    if reply_to:
        for request in queue:
            if request['message_id'] == reply_to:
                return request
    return queue[0]


async def handle_cashout_reply(handling, text, user_id, username, reply_to):
    """A message in a handling group, while at least one request is open there.

    Nothing here runs unless a request we forwarded is genuinely outstanding, so
    ordinary traffic - including an ordinary /out - is never touched."""
    queue = _pending_cashouts.get(handling)
    if not queue:
        return

    if _is_responder(user_id, username):
        # Somebody is on it. Put the reminder clock back for this group's open
        # requests; they stay open until a /out actually arrives.
        now = datetime.now(timezone.utc)
        for request in queue:
            request['last_seen'] = now
        print(f"💬 [CASHOUT] @{username or user_id} replied in "
              f"{chat_name(handling)} - reminder clock reset", flush=True)

    if not _OUT_CMD_RE.search(text):
        return

    request = _match_request(queue, reply_to)
    origin = request['origin']
    try:
        await bot.send_message(origin, text)
    except Exception as e:
        # Left open deliberately: the request is not settled until the chime
        # group has actually seen the /out.
        print(f"❌ [CASHOUT] /out could not be sent back to {chat_name(origin)}: {e}",
              flush=True)
        return

    queue.remove(request)
    if not queue:
        _pending_cashouts.pop(handling, None)

    await book_cashout_out(origin, text)

    waited = (datetime.now(timezone.utc) - request['opened']).total_seconds() / 60.0
    print(f"✅ [CASHOUT] /out returned to {chat_name(origin)} after "
          f"{_humanise(waited)} ({request['nudges']} reminder(s))", flush=True)
    await heart_request(handling, request['message_id'])


async def observe_cashout(chat_id, text, message_id, sent_at,
                          user_id=None, username=None, reply_to=None):
    """Single entry point for both input paths.

    Called for every text message in a watched chat. Decides whether it opens a
    cashout request, answers one, or is none of our business."""
    if not text:
        return
    if BOT_ID is not None and user_id == BOT_ID:
        return                              # never act on our own posts

    source = _canonical(chat_id, CASHOUT_ROUTES)
    if source is not None:
        if CASHOUT_KEYWORD.lower() not in text.lower():
            return
        if _is_duplicate(('cashout', source, message_id)):
            return
        await open_cashout_request(source, text, sent_at)
        return

    handling = _canonical(chat_id, _CASHOUT_HANDLERS)
    if handling is not None:
        if _is_duplicate(('cashout-reply', handling, message_id)):
            return
        await handle_cashout_reply(handling, text, user_id, username, reply_to)


def cashout_nudge_text(waited_minutes):
    return (f"⏰ OUT REQUEST HAS CROSSED {_humanise(waited_minutes)} TIMEFRAME\n\n"
            "This cashout request is still waiting on a /out.\n\n"
            f"{CASHOUT_MENTIONS}\n\n"
            "-ETHAN")


def cashout_dm_text(request, handling, waited_minutes):
    preview = ' '.join((request['text'] or '').split())[:200]
    return (f"⏰ OUT REQUEST HAS CROSSED {_humanise(waited_minutes)} TIMEFRAME\n\n"
            f"From: {chat_name(request['origin'])}\n"
            f"Waiting in: {chat_name(handling)}\n\n"
            f"{preview}\n\n"
            "Nobody has sent a /out for it yet. Please action it.")


async def cashout_watchdog():
    """Chase every request that has gone quiet past the timeout."""
    if CASHOUT_TIMEOUT_MINUTES <= 0:
        print("ℹ️ [CASHOUT] escalation disabled (CASHOUT_TIMEOUT_MINUTES=0)", flush=True)
        return

    print(f"📤 [CASHOUT] {len(CASHOUT_ROUTES)} route(s), chasing after "
          f"{_humanise(CASHOUT_TIMEOUT_MINUTES)} of silence", flush=True)

    while True:
        await asyncio.sleep(20)
        now = datetime.now(timezone.utc)
        for handling, queue in list(_pending_cashouts.items()):
            for request in list(queue):
                if request['exhausted']:
                    continue
                quiet = (now - request['last_seen']).total_seconds() / 60.0
                if quiet < CASHOUT_TIMEOUT_MINUTES:
                    continue

                if request['nudges'] >= CASHOUT_MAX_NUDGES:
                    request['exhausted'] = True
                    total = (now - request['opened']).total_seconds() / 60.0
                    print(f"🔕 [CASHOUT] giving up reminders in "
                          f"{chat_name(handling)} after {request['nudges']}", flush=True)
                    await notify_admin(
                        f"🚨 A cashout request from {chat_name(request['origin'])} has "
                        f"gone {_humanise(total)} with no /out, after "
                        f"{request['nudges']} reminders.\n\n"
                        "Reminders have stopped so the group is not spammed. The "
                        "request is still open - a late /out will still be forwarded "
                        "and hearted.")
                    continue

                request['nudges'] += 1
                request['last_seen'] = now
                waited = (now - request['opened']).total_seconds() / 60.0

                try:
                    await bot.send_message(handling, cashout_nudge_text(waited),
                                           reply_to_message_id=request['message_id'])
                    print(f"⏰ [CASHOUT] reminder #{request['nudges']} in "
                          f"{chat_name(handling)} after {_humanise(waited)}", flush=True)
                except Exception as e:
                    print(f"❌ [CASHOUT] reminder failed in {chat_name(handling)}: {e}",
                          flush=True)

                await dm_crew(cashout_dm_text(request, handling, waited))


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
        await deliver_to_target(target, fixed, text, from_bot)


async def deliver_to_target(target, fixed, text, from_bot):
    """Send one notification to one group and move that group's books.

    Split out of process_incoming so the start-up catch-up can deliver to a
    single target: a message can be missing from one group while another
    already has it, and re-sending to the group that has it would duplicate."""
    global forwarded_count, today_count

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
        return False

    if movement:
        ledger_commit(target, movement[1])
        await note_payment(target)  # a real payment landed: reset the clock
    print(f"🚀 [FORWARD SUCCESS] Sent to {target}", flush=True)
    forwarded_count += 1
    today_count += 1
    last_messages.append(body[:50])
    if len(last_messages) > 10:
        last_messages.pop(0)

    # After the payment confirmation, so the alert lands beneath it.
    if movement:
        await check_milestones(target, movement[0], movement[1])
    return True


# ---------------------------------------------------------------------------
# Bot API handlers (unchanged behaviour, async syntax)
# ---------------------------------------------------------------------------

@bot.message_handler(commands=['start'])
async def start(message):
    if message.chat.id in LEDGER_ADMINS:
        await bot.reply_to(message, 'Bot is running. Use /help to see all commands.')


@bot.message_handler(commands=['status'])
async def status(message):
    if message.chat.id in LEDGER_ADMINS:
        paused = sorted(t for t in IDLE_ALERT_CHATS if _idle_slot(t)['paused'])
        prompts = ('off in ' + ', '.join(str(t) for t in paused)) if paused else 'on'
        open_requests = sum(len(q) for q in _pending_cashouts.values())
        txt = (f"Bot Online\nGroups: {len(FORWARD_RULES)}\n"
               f"Forwarded: {forwarded_count}\nUptime: {get_uptime()}\n"
               f"Userbot: {userbot_status}\n"
               f"Payment prompts: {prompts}\n"
               f"Cashouts awaiting /out: {open_requests}")
        await bot.reply_to(message, txt)


@bot.message_handler(commands=['help'])
async def help_command(message):
    """Private-chat command reference. Values come from the live config so this
    cannot drift out of date when an env var changes."""
    if message.chat.id not in LEDGER_ADMINS:
        return

    groups = ' or '.join(IDLE_NAMES[t] for t in sorted(IDLE_ALERT_CHATS))
    await bot.send_message(message.chat.id,
        "📖 COMMANDS\n"
        "\n"
        f"LEDGER — type these inside {groups}\n"
        "\n"
        "/add 500 — adds 500.00$ to Total In\n"
        "/out 100 — adds 100.00$ to Total Out\n"
        "/add -100 — takes 100.00$ back off Total In\n"
        "/out -50 — takes 50.00$ back off Total Out\n"
        "(the space is optional: /add-100 works too)\n"
        "/set in 800 — sets Total In to 800.00$\n"
        "/set out 300 — sets Total Out to 300.00$\n"
        "\n"
        "PAYMENT PROMPTS — here in private, or silently in a group\n"
        "\n"
        "/pause — stops prompts in both groups\n"
        "/pause gaffer — stops them in CHIME GAFFER only\n"
        "/pause piccaso — stops them in CHIME PICCASO only\n"
        "/resume — starts them again, same three forms\n"
        "\n"
        "CASHOUTS — automatic, nothing to type\n"
        "\n"
        f"A \"{CASHOUT_KEYWORD}\" in CHIME PICCASO or CHIME GAFFER is\n"
        "posted to its group with the crew tagged.\n"
        f"No answer in {_humanise(CASHOUT_TIMEOUT_MINUTES)} — tagged again, and\n"
        "everyone gets a private warning.\n"
        "Their /out reply goes back to the chime group, its\n"
        "amount is added to that group's Total Out, and the\n"
        "request gets a ❤.\n"
        "A /out with nothing pending is ignored.\n"
        "\n"
        "INFO\n"
        "\n"
        "/status — bot state, userbot, which groups are paused\n"
        "/ping — quick alive check\n"
        "/help — this list\n"
        "\n"
        "GOOD TO KNOW\n"
        "\n"
        "Only Ethan and Larry can use any of these.\n"
        "Payments add to Total In on their own.\n"
        "A payment also lifts a pause by itself.\n"
        f"Milestones fire every {MILESTONE_IN_STEP:,}$ in "
        f"and every {MILESTONE_OUT_STEP:,}$ out.\n"
        f"Prompts ask the group after {_humanise(IDLE_ALERT_MINUTES)} "
        "without a payment.\n"
        "\n"
        "In a group, /pause and /resume post nothing at all — check /status.")


@bot.message_handler(commands=['ping'])
async def ping(message):
    if message.chat.id in LEDGER_ADMINS:
        await bot.reply_to(message, 'Pong! Bot is alive.')


@bot.message_handler(commands=['add', 'out'])
async def ledger_command(message):
    """/add <amount> and /out <amount>, target groups only, Ethan and Larry only."""
    chat_id = message.chat.id
    user_id = getattr(message.from_user, 'id', None)

    # A /out typed in a handling group may be answering a cashout request, and
    # telebot routes commands here rather than to forward_text. This has to run
    # before the guard below, which would otherwise drop it. It does nothing
    # unless a request we forwarded is actually open in that chat.
    await cashout_from_bot_api(message)

    # Silent in source groups and DMs, so the source side cannot reach the books.
    if chat_id not in TARGET_CHATS:
        return

    if user_id not in LEDGER_ADMINS:
        print(f"⛔ [LEDGER] {user_id} denied in {chat_id}", flush=True)
        await bot.reply_to(message, "⛔ Not permitted. Only Ethan and Larry can "
                                    "change the totals.")
        return

    name = _CMD_NAME_RE.match(message.text)
    command = name.group(1).lower() if name else ''
    match = _CMD_AMOUNT_RE.match(message.text)
    amount = _to_float(match.group(2)) if match else None
    if amount is None or amount == 0:
        await bot.reply_to(message, f"Usage: /{command} <amount>\n"
                                    f"Example: /{command} 100\n"
                                    f"         /{command} -100  (takes it back off)")
        return
    if match.group(1) == '-':
        amount = -amount

    before = ledger_snapshot(chat_id)
    column = 'Total In' if command == 'add' else 'Total Out'
    if command == 'add':
        after = (before[0] + amount, before[1])
    else:
        after = (before[0], before[1] + amount)

    # A correction that overshoots is a typo, not an instruction. Refuse it
    # rather than publish a negative total, which would then be carried into
    # every forwarded notification by rewrite_totals().
    if after[0] < 0 or after[1] < 0:
        print(f"⛔ [LEDGER] /{command} {amount:,.2f} by {user_id} would take "
              f"{column} below zero in {chat_id}", flush=True)
        await bot.reply_to(message,
                           f"⛔ That would take {column} below zero.\n\n"
                           f"➕ Total In : {before[0]:,.2f}$\n"
                           f"➖ Total Out: {before[1]:,.2f}$\n\n"
                           f"Use /set {'in' if command == 'add' else 'out'} "
                           "<amount> to set it outright.")
        return

    if amount < 0:
        heading = f"✏️ {column} adjusted by {amount:,.2f}$"
    elif command == 'add':
        heading = f"💰 Deposit = +{amount:,.2f}$"
    else:
        heading = f"📤 Out = -{amount:,.2f}$"

    try:
        await bot.send_message(chat_id,
                               f"{heading}\n\n"
                               f"📊 Group Total:\n"
                               f"➕ Total In : {after[0]:,.2f}$\n"
                               f"➖ Total Out: {after[1]:,.2f}$")
    except Exception as e:
        print(f"❌ [LEDGER] /{command} NOT applied, send failed: {e}", flush=True)
        return

    ledger_commit(chat_id, after, f" (/{command} {amount:,.2f} by {user_id})")
    await check_milestones(chat_id, before, after)


@bot.message_handler(func=lambda m: bool(getattr(m, 'text', None))
                     and bool(_JOINED_LEDGER_RE.match(m.text)))
async def ledger_joined_command(message):
    """"/add-100" and "/out-50", written without the space.

    Telegram reads the command as the word right after the slash, so these
    arrive as the commands "add-100" and "out-50" and never reach the handler
    above. Same code, just reached a different way. Registered ahead of the
    catch-all text handler, which telebot would otherwise hand them to."""
    await ledger_command(message)


@bot.message_handler(commands=['pause', 'resume'])
async def idle_pause_command(message):
    """/pause and /resume the payment prompts, per group.

    For when the hold-up is on your side and asking the group whether they have
    a problem would be the wrong message."""
    chat_id = message.chat.id
    user_id = getattr(message.from_user, 'id', None)
    command = message.text.lstrip('/').split('@')[0].split()[0].lower()
    pausing = command == 'pause'

    # ---- private chat: name a group or hit both, and get a reply ----
    if chat_id in LEDGER_ADMINS:
        if user_id not in LEDGER_ADMINS:
            return
        parts = message.text.split()
        argument = parts[1].lower() if len(parts) > 1 else ''
        if not argument:
            targets = sorted(IDLE_ALERT_CHATS)
        elif argument in IDLE_ALIASES:
            targets = [IDLE_ALIASES[argument]]
        else:
            await bot.reply_to(message,
                               f"Usage: /{command}          (both groups)\n"
                               f"       /{command} gaffer   (CHIME GAFFER only)\n"
                               f"       /{command} piccaso  (CHIME PICCASO only)")
            return

        for target in targets:
            set_idle_paused(target, pausing)
        names = ', '.join(IDLE_NAMES.get(t, str(t)) for t in targets)
        print(f"{'🔇' if pausing else '🔔'} [IDLE] {names} "
              f"{'paused' if pausing else 'resumed'} by {user_id} via DM", flush=True)

        if pausing:
            await bot.reply_to(message,
                               f"🔇 Paused: {names}\n\n"
                               "Nothing will be posted in those groups.\n"
                               "Send /resume when you want them back.")
        else:
            await bot.reply_to(message,
                               f"🔔 Resumed: {names}\n\n"
                               f"Next prompt after {_humanise(IDLE_ALERT_MINUTES)} "
                               "of silence.")
        return

    # ---- inside a target group: deliberately SILENT ----
    # Pausing usually means the hold-up is on our side, and announcing it would
    # be exactly the wrong message. Check the state with /status.
    if chat_id not in IDLE_ALERT_CHATS:
        return

    if user_id not in LEDGER_ADMINS:
        print(f"⛔ [IDLE] pause/resume by {user_id} denied in {chat_id}", flush=True)
        await bot.reply_to(message, "⛔ Not permitted. Only Ethan and Larry can "
                                    "change this.")
        return

    set_idle_paused(chat_id, pausing)
    print(f"{'🔇' if pausing else '🔔'} [IDLE] {chat_id} "
          f"{'paused' if pausing else 'resumed'} by {user_id}", flush=True)


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
                               f"set to {amount:,.2f}$\n\n"
                               f"📊 Group Total:\n"
                               f"➕ Total In : {after[0]:,.2f}$\n"
                               f"➖ Total Out: {after[1]:,.2f}$")
    except Exception as e:
        print(f"❌ [LEDGER] /set NOT applied, send failed: {e}", flush=True)
        return

    ledger_commit(chat_id, after, f" (/set {column} {amount:,.2f} by {user_id})")
    await check_milestones(chat_id, before, after)


async def cashout_from_bot_api(message):
    """Bot API side of observe_cashout.

    Telethon normally sees these first and the dedup key discards this copy, but
    it keeps the cashout flow alive if the userbot is down."""
    reply = getattr(message, 'reply_to_message', None)
    sent_at = (datetime.fromtimestamp(message.date, tz=timezone.utc)
               if getattr(message, 'date', None) else None)
    await observe_cashout(message.chat.id, message.text, message.message_id, sent_at,
                          getattr(message.from_user, 'id', None),
                          getattr(message.from_user, 'username', None),
                          getattr(reply, 'message_id', None))


@bot.message_handler(content_types=['text'])
async def forward_text(message):
    sender_is_bot = bool(getattr(message.from_user, 'is_bot', False))
    sent_at = (datetime.fromtimestamp(message.date, tz=timezone.utc)
               if getattr(message, 'date', None) else None)
    await cashout_from_bot_api(message)
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
    # Both ends of a cashout route are watched too: the chime groups because the
    # requests start there, and the handling groups because the /out answering
    # one is a human message the Bot API may never deliver.
    chats = list(FORWARD_RULES.keys())
    for chat_id in list(CASHOUT_ROUTES) + list(CASHOUT_ROUTES.values()):
        if chat_id not in chats:
            chats.append(chat_id)
    return chats


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


async def _resolve_one(client, chat_id):
    """Try both spellings of a chat id and return whichever resolves."""
    for candidate in [chat_id] + _id_variants(chat_id):
        try:
            return await client.get_entity(candidate)
        except Exception:
            continue
    return None


async def _resolve_source_chats(client, wanted):
    """Resolve each configured chat separately so one bad id cannot stop the
    listener from starting on the good ones."""
    resolved = []
    for chat_id in wanted:
        entity = await _resolve_one(client, chat_id)
        if entity is None:
            print(f"⚠️ [TELETHON] Could not resolve source chat {chat_id} - skipping it.", flush=True)
            continue
        title = getattr(entity, 'title', None) or getattr(entity, 'username', '')
        print(f"👁️ [TELETHON] Watching {chat_id} ({title})", flush=True)
        resolved.append(entity)
    return resolved


def _catchup_signature(text):
    """Content key for one notification that survives forwarding.

    TWO things are rewritten on the way out, and neither can be part of the key.
    The timestamp becomes the real send time. The totals become this target's
    own ledger figures, which is the whole point of the ledger - so they match
    the source only until the books first diverge, and from then on every
    delivered copy looks like a different message. That made the sweep re-send
    the entire window on each connect, and it re-runs on every reconnect, not
    just on boot.

    What is left - the name and the amount - is identical in the source and in
    the copy sitting in the target group."""
    stripped = _STAMP_RE.sub('', text or '')
    stripped = _TOTAL_IN_SUB.sub(r'\1', stripped)
    stripped = _TOTAL_OUT_SUB.sub(r'\1', stripped)
    return ' '.join(stripped.split())


async def _delivered_signatures(client, target):
    """What is already sitting in a target group, and how far back that is known.

    Returns (counts, reached). `reached` is the oldest moment the scan actually
    accounted for; anything older than it cannot be judged and must not be
    guessed at.

    Sender attribution is deliberately NOT used. Telegram credits a post in a
    channel to the channel itself rather than to the bot that sent it, and a
    post by an anonymous admin to the group - so filtering on the bot's own id
    can match nothing at all and make a fully delivered window look entirely
    missing. Content is the honest test: if the text is already in the group it
    has been delivered, whoever Telegram says put it there. A human pasting the
    same text would count too, which errs towards staying quiet - the right
    direction, because a missed payment can still be backfilled by hand and a
    duplicate cannot be taken back."""
    counts = Counter()
    entity = await _resolve_one(client, target)
    if entity is None:
        return None, None               # unreadable: caller must not guess
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CATCHUP_LOOKBACK_MINUTES)

    scanned = 0
    last_date = None
    covered_window = False
    async for msg in client.iter_messages(entity, limit=CATCHUP_TARGET_SCAN_LIMIT):
        scanned += 1
        last_date = msg.date
        if msg.date < cutoff:
            covered_window = True       # read right past the far edge
            break
        if msg.raw_text:
            counts[_catchup_signature(msg.raw_text)] += 1

    if covered_window or scanned < CATCHUP_TARGET_SCAN_LIMIT:
        # Either we read past the window, or the group simply has no more
        # history - either way the whole window is accounted for.
        reached = cutoff
    else:
        # The scan hit its limit first. Everything older than the last message
        # we saw is unknown, not absent.
        reached = last_date
        print(f"⚠️ [CATCHUP] {target} history is deeper than {CATCHUP_TARGET_SCAN_LIMIT} "
              f"messages; only judging back to {last_date:%m-%d %H:%M}.", flush=True)
    return counts, reached


async def catch_up(client):
    """Forward notifications that arrived while this listener was not running.

    There is a deaf window on every deploy - the start-up hold alone is ~45s -
    and after an outage it can be hours. A payment landing in it would
    otherwise be lost in silence, which is the failure mode that started all
    this.

    Railway wipes the disk on deploy, so there is no local record of what was
    forwarded. The target group's own history is the record: a notification
    whose text is not already sitting in the target was never delivered.

    Copies are counted rather than tested for membership. Timestamps are
    stripped before comparing, so two identical payments minutes apart look
    alike - counting means it forwards the difference instead of deciding one
    of each was enough."""
    if not CATCHUP_LOOKBACK_MINUTES:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CATCHUP_LOOKBACK_MINUTES)
    total = 0

    for rule_key, targets in FORWARD_RULES.items():
        source = await _resolve_one(client, rule_key)
        if source is None:
            continue
        # The live handler keys dedup off event.chat_id, so use the same
        # canonical form here or the two would not recognise each other.
        source_id = utils.get_peer_id(source)

        pending = []
        async for msg in client.iter_messages(source, limit=CATCHUP_SCAN_LIMIT):
            if msg.date < cutoff:
                break
            if not _is_plain_text(msg) or not msg.raw_text:
                continue
            if not any(k.lower() in msg.raw_text.lower() for k in KEYWORDS):
                continue
            sender = await msg.get_sender()
            if not bool(getattr(sender, 'bot', False)):
                continue        # the live path forwards bot notifications only
            pending.append(msg)
        if not pending:
            continue
        pending.reverse()                       # oldest first, so groups read in order

        for target in targets:
            delivered, reached = await _delivered_signatures(client, target)
            if delivered is None:
                print(f"⚠️ [CATCHUP] {target} unreadable - skipping, will not guess.",
                      flush=True)
                continue

            missing = []
            unjudged = 0
            for msg in pending:
                if reached is not None and msg.date < reached:
                    # Older than the target scan could see. Unknown, not absent.
                    unjudged += 1
                    continue
                sig = _catchup_signature(msg.raw_text)
                if delivered[sig] > 0:
                    delivered[sig] -= 1         # this copy is already in the group
                else:
                    missing.append(msg)
            if unjudged:
                print(f"⚠️ [CATCHUP] {target}: {unjudged} message(s) older than the "
                      "readable history - left alone rather than risk a duplicate.",
                      flush=True)
            if not missing:
                continue

            if len(missing) > CATCHUP_MAX:
                # Something is off - a wrong id, a cleared group. Deliver the
                # newest and say so rather than flooding the group with hours
                # of history.
                print(f"⚠️ [CATCHUP] {target} looks {len(missing)} behind; sending the "
                      f"newest {CATCHUP_MAX}.", flush=True)
                await notify_admin(
                    f"⚠️ Catch-up found {len(missing)} unforwarded notifications for "
                    f"{target}, more than the {CATCHUP_MAX} cap. Sent the newest "
                    f"{CATCHUP_MAX}. Use backfill.py if the rest are wanted.")
                missing = missing[-CATCHUP_MAX:]

            print(f"⏪ [CATCHUP] {target}: {len(missing)} missed notification(s).",
                  flush=True)
            for msg in missing:
                # Mark before sending: the live handler is already queued behind
                # this and must not send the same message a second time.
                _is_duplicate((source_id, msg.id))
                fixed = correct_timestamp(msg.raw_text, msg.date)
                if await deliver_to_target(target, fixed, msg.raw_text, True):
                    total += 1
                await asyncio.sleep(1.5)        # stay under the send rate limit

    if total:
        print(f"⏪ [CATCHUP] delivered {total} missed notification(s).", flush=True)
        await notify_admin(f"⏪ Caught up {total} notification(s) that arrived while "
                           f"the forwarder was not listening.")
    else:
        print("⏪ [CATCHUP] nothing missed.", flush=True)


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
            print(f"📒 [LEDGER] {target} recovered: in={total_in:,.2f} "
                  f"out={total_out:,.2f} (from {message.date:%m-%d %H:%M})", flush=True)
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

    if TELETHON_START_DELAY:
        # Only before the first connect. Reconnects inside the loop below are
        # replacing a dropped connection of our own, not racing another
        # container, so they must not be delayed.
        userbot_status = f'waiting {TELETHON_START_DELAY}s for the previous deploy to exit'
        print(f"⏸️ [TELETHON] Holding {TELETHON_START_DELAY}s so the outgoing container "
              "releases the session first (set TELETHON_START_DELAY=0 to disable).",
              flush=True)
        await asyncio.sleep(TELETHON_START_DELAY)

    global _active_client

    while True:
        client = TelegramClient(session, int(API_ID), API_HASH)
        _active_client = client
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
            global _userbot_username
            _userbot_username = (me.username or '').lower()

            # Warms the entity cache so numeric chat ids resolve reliably.
            await client.get_dialogs()

            chats = await _resolve_source_chats(client, _configured_source_chats())
            if not chats:
                # Retry rather than return: a transient resolve failure must not
                # silently retire the listener for the life of the process.
                userbot_status = 'no source chats resolved'
                print("❌ [TELETHON] No source chats could be resolved - retrying in 60s.", flush=True)
                await asyncio.sleep(60)
                continue

            # Register the handler BEFORE the ledger rebuild and the catch-up
            # sweep, so a payment arriving during them is queued rather than
            # missed. Each event waits on this gate, which opens once the books
            # are straight and the sweep has run - that ordering keeps the
            # groups reading chronologically and lets dedup do its job.
            ready = asyncio.Event()

            @client.on(events.NewMessage(chats=chats))
            async def on_source_message(event):
                await ready.wait()
                sender = await event.get_sender()
                text = event.raw_text
                if not text or not _is_plain_text(event.message):
                    return
                remember_user(sender)

                sender_id = getattr(sender, 'id', None)
                if BOT_ID is not None and sender_id == BOT_ID:
                    # Our own forwards now land in watched chats - the handling
                    # groups are also payment sources. Acting on them would loop.
                    return

                # Cashout first, and it accepts humans as well as bots: a request
                # or the /out answering one is as likely to be typed by a person.
                # It never consumes the message - the two keyword filters cannot
                # both match, so the payment path still gets its turn below.
                await observe_cashout(event.chat_id, text, event.id,
                                      event.message.date, sender_id,
                                      getattr(sender, 'username', None),
                                      getattr(event.message, 'reply_to_msg_id', None))

                if not _is_target_sender(sender, bot_ids, bot_usernames):
                    return
                if _is_duplicate((event.chat_id, event.id)):
                    return
                # _is_target_sender above already guaranteed a bot sender.
                await process_incoming(event.chat_id, text, 'telethon',
                                       from_bot=True, sent_at=event.message.date)

            await recover_ledgers(client)
            try:
                await catch_up(client)
            except Exception as e:
                # A failed sweep must not cost us the live listener - being late
                # on a few messages beats being deaf to all of them.
                print(f"⚠️ [CATCHUP] sweep failed: {e} - continuing to listen.",
                      flush=True)
            ready.set()

            target = SOURCE_BOTS if SOURCE_BOTS.strip() else 'any bot'
            userbot_status = f'listening ({len(chats)} chats, from: {target})'
            print(f"✅ [TELETHON] Listening for messages from: {target}", flush=True)

            await client.run_until_disconnected()
            print("⚠️ [TELETHON] Disconnected - reconnecting in 15s.", flush=True)
        except (AuthKeyDuplicatedError, AuthKeyUnregisteredError,
                SessionRevokedError, UserDeactivatedBanError) as e:
            # Telegram has destroyed the auth key - almost always because the
            # same session ran from two IPs at once (deployment + laptop, or two
            # overlapping Railway containers). Reconnecting can NEVER fix this:
            # only a fresh login can. Retrying silently every 15s is how this
            # went unnoticed for hours, so shout once and stop.
            userbot_status = f'session dead: {type(e).__name__}'
            print(f"💀 [TELETHON DEAD] {type(e).__name__}: {e}\n"
                  "   Forwarding of bot messages is STOPPED until TELETHON_SESSION "
                  "is replaced. Run: python3 telethon_login.py --deploy", flush=True)
            await notify_admin(
                f"🚨 FORWARDING IS DOWN - Telethon session destroyed "
                f"({type(e).__name__}).\n\n"
                "Messages posted by the notification bot are NOT being forwarded "
                "to any group, and this cannot self-heal.\n\n"
                "Fix:\n"
                "1. python3 telethon_login.py --deploy\n"
                "2. Paste the new string into Railway's TELETHON_SESSION\n"
                "3. Redeploy\n\n"
                "Cause: that session key was used from two IPs at once. Never run "
                "local scripts with the deployment's session, and keep Railway at "
                "a single replica.")
            return
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


def _install_shutdown_handler(loop):
    """Leave promptly and quietly when Railway says we are going away.

    This matters more than it looks. In a container this process is PID 1, and
    PID 1 does not get the kernel's default signal dispositions: an unhandled
    SIGTERM is simply IGNORED. So the outgoing container sat there holding the
    Telethon connection until Railway lost patience and sent SIGKILL, which is
    the overlap that destroyed the session. Handling SIGTERM explicitly is what
    makes the old container actually leave.

    Exit via os._exit rather than loop.stop(): stopping the loop out from under
    asyncio.run() raises RuntimeError and exits non-zero, which Railway reads as
    a crash and restarts - turning a clean shutdown into another instance."""
    def _on_term():
        print("🛑 [SHUTDOWN] SIGTERM - releasing the Telethon session before exit.",
              flush=True)
        if _active_client is not None:
            loop.create_task(_active_client.disconnect())
        # Enough for the disconnect to reach Telegram, then go without fuss.
        loop.call_later(2, lambda: os._exit(0))

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_term)
        except (NotImplementedError, RuntimeError):
            pass        # not supported on this platform; default behaviour applies


async def main():
    print('Bot running...', flush=True)
    _install_shutdown_handler(asyncio.get_running_loop())
    await notify_admin('Bot is ONLINE. Use /help to see all commands.')
    await asyncio.gather(run_bot(), run_userbot(), idle_watchdog(),
                         cashout_watchdog(), return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
