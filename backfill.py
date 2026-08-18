"""One-time backfill: forward past messages from one group into another.

History is READ with your Telethon user session. Every message is SENT with
your bot token, exactly like forwarder.py, so forwards appear as coming from
your bot and never from your personal account.

Text messages only - photos, videos, documents, stickers and their captions are
skipped, matching what forwarder.py handles. A text message with a link preview
still counts as text.

Dry run by default - it prints what it would send and sends nothing. Add --send
to actually deliver.

Examples:

    # See what would be forwarded (safe, sends nothing)
    python3 backfill.py

    # Only messages containing a keyword
    python3 backfill.py --keyword "You received"

    # Actually send
    python3 backfill.py --send
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_helper import ApiTelegramException

from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaWebPage

DEFAULT_SOURCE = '-1002335630148'       # chime rev and out no-7
DEFAULT_TARGET = '-5580596463'          # Chime gaffer
DEFAULT_KEYWORDS = ['You received']     # matched case insensitively


LOCAL_TZ = timezone(timedelta(hours=5, minutes=45))     # Nepal, no DST
_STAMP_RE = re.compile(
    r'\b\d{1,2}:\d{2}\s*[AaPp][Mm]\s*-\s*\d{1,2}\s+[A-Za-z]{3}\s+\d{4}')


def correct_timestamp(text, sent_at, enabled=True):
    """Same rewrite as forwarder.correct_timestamp: the notification bot's clock
    runs ~14 min fast, so swap its embedded timestamp for the real send time."""
    if not enabled or sent_at is None:
        return text
    return _STAMP_RE.sub(sent_at.astimezone(LOCAL_TZ).strftime('%I:%M %p - %d %b %Y'),
                         text, count=1)


def is_plain_text(msg):
    """Text messages only - no photos, videos, documents, stickers or their
    captions. A link preview still counts as plain text."""
    if msg.media is None:
        return True
    return isinstance(msg.media, MessageMediaWebPage)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', default=DEFAULT_SOURCE,
                   help='source group: title (substring ok) or numeric id')
    p.add_argument('--target', default=DEFAULT_TARGET,
                   help='destination group: title (substring ok) or numeric id')
    p.add_argument('--since', default='01:00',
                   help='"HH:MM" today in local time, or a full ISO timestamp')
    p.add_argument('--keyword', action='append', default=None,
                   help=f'only forward messages containing this (repeatable). '
                        f'Default: {DEFAULT_KEYWORDS}')
    p.add_argument('--no-keyword', action='store_true',
                   help='disable the keyword filter and forward every message')
    p.add_argument('--all-senders', action='store_true',
                   help='include humans. By default only bot senders forward')
    p.add_argument('--limit', type=int, default=500,
                   help='safety cap on messages scanned (default 500)')
    p.add_argument('--delay', type=float, default=1.5,
                   help='seconds between sends, to stay under flood limits')
    p.add_argument('--send', action='store_true',
                   help='actually send. Without this it is a dry run')
    p.add_argument('--keep-original-time', action='store_true',
                   help="forward the bot's own timestamp instead of correcting it")
    p.add_argument('--use-deploy-session', action='store_true',
                   help='allow TELETHON_SESSION from the environment. Unsafe: it '
                        'can revoke the deployment key and stop forwarding')
    args = p.parse_args()
    if args.no_keyword:
        args.keyword = []
    elif args.keyword is None:
        args.keyword = list(DEFAULT_KEYWORDS)
    args.from_bot_only = not args.all_senders
    return args


def parse_since(value):
    """Return a timezone-aware cutoff in the machine's local timezone."""
    local_tz = datetime.now().astimezone().tzinfo
    try:
        if ':' in value and len(value) <= 5:
            hh, mm = (int(x) for x in value.split(':'))
            base = datetime.now(local_tz).replace(hour=hh, minute=mm, second=0, microsecond=0)
            # A time later than "now" must mean yesterday.
            if base > datetime.now(local_tz):
                base -= timedelta(days=1)
            return base
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=local_tz)
    except Exception:
        raise SystemExit(f"Could not understand --since {value!r}")


async def resolve_chat(client, ref, label):
    if ref.lstrip('-').isdigit():
        return await client.get_entity(int(ref))

    needle = ref.strip().lower()
    partial = []
    async for dialog in client.iter_dialogs():
        if dialog.is_user:
            continue
        name = (dialog.name or '').lower()
        if name == needle:
            return dialog.entity
        if needle in name:
            partial.append(dialog)

    if len(partial) == 1:
        print(f"   {label}: matched {partial[0].name!r} ({partial[0].id})")
        return partial[0].entity
    if not partial:
        raise SystemExit(f"❌ No group found matching {label} {ref!r}. "
                         f"Run: python3 telethon_login.py --list-chats")
    listing = '\n'.join(f"     {d.name!r} ({d.id})" for d in partial)
    raise SystemExit(f"❌ {label} {ref!r} is ambiguous:\n{listing}\n"
                     f"   Re-run with --{label.lower()} and an exact numeric id.")


def load_guards():
    """Borrow forwarder.py's own redaction rather than keeping a second copy.

    A backfill posts into the same groups the live path does, so it has to obey
    the same rule: no crew handle, and no @username of any kind, reaches a
    chime or VENMO group. Writing that logic out again here would be the second
    list somebody forgets to update - so the real one is imported.

    forwarder.py cannot be imported without a bot token, which a dry run does
    not need. That is fine: a dry run posts nothing, and the only mode that
    does need this is --send, which requires the token anyway. The fallback
    still strips every @handle, so the worst case is losing the bare-name half
    of the rule on a run that sends nothing."""
    try:
        from forwarder import strip_identities, chat_paused
        return strip_identities, chat_paused
    except Exception as e:
        print(f"   ⚠️  using the simple redactor ({type(e).__name__}) - "
              "@handles only")
        return (lambda text: _HANDLE_RE.sub('', text or '').strip() or text,
                lambda chat_id: False)


# Same shape as forwarder's, for the fallback above only.
_HANDLE_RE = re.compile(r'(?<![\w@])@[A-Za-z][A-Za-z0-9_]{3,31}')


async def send_with_retry(bot, chat_id, text, attempts=4):
    for attempt in range(attempts):
        try:
            await bot.send_message(chat_id, text)
            return True
        except ApiTelegramException as e:
            wait = 0
            if isinstance(getattr(e, 'result_json', None), dict):
                wait = e.result_json.get('parameters', {}).get('retry_after', 0)
            if wait and attempt < attempts - 1:
                print(f"      rate limited, waiting {wait}s")
                await asyncio.sleep(wait + 1)
                continue
            print(f"      ❌ {e}")
            return False
        except Exception as e:
            print(f"      ❌ {e}")
            return False
    return False


async def main():
    args = parse_args()
    cutoff = parse_since(args.since)

    api_id, api_hash = os.getenv('TELEGRAM_API_ID'), os.getenv('TELEGRAM_API_HASH')
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not (api_id and api_hash):
        raise SystemExit("❌ Set TELEGRAM_API_ID and TELEGRAM_API_HASH.")
    if args.send and not bot_token:
        raise SystemExit("❌ Set TELEGRAM_BOT_TOKEN to send.")

    # This script runs on your machine, so it must use YOUR session. If
    # TELETHON_SESSION is exported here it is almost certainly the deployment's
    # string, and connecting with it from a second IP makes Telegram destroy
    # that key - which silently kills forwarding until someone logs in again.
    if os.getenv('TELETHON_SESSION') and not args.use_deploy_session:
        raise SystemExit(
            "❌ TELETHON_SESSION is set in this shell.\n"
            "   That is the DEPLOYMENT's session. Using it from this machine "
            "makes Telegram\n   revoke the key and stops all forwarding.\n\n"
            "   Run this instead:  unset TELETHON_SESSION && python3 backfill.py ...\n"
            "   (or pass --use-deploy-session if you really mean it)")

    session = StringSession(os.getenv('TELETHON_SESSION')) if args.use_deploy_session \
        and os.getenv('TELETHON_SESSION') else os.getenv('TELETHON_SESSION_NAME', 'user_session')

    print(f"Cutoff  : {cutoff.isoformat()}")
    print(f"Keyword : {args.keyword or 'none - every message'}")
    print(f"Senders : {'bots only' if args.from_bot_only else 'everyone'}")
    print(f"Content : text only")
    print(f"Time    : {'kept as the bot wrote it' if args.keep_original_time else 'corrected to real send time (Nepal)'}")
    print(f"Mode    : {'SEND' if args.send else 'DRY RUN - nothing will be sent'}\n")

    client = TelegramClient(session, int(api_id), api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("❌ Telethon session not authorised. Run: python3 telethon_login.py")

    print("Resolving groups...")
    await client.get_dialogs()          # warm the entity cache
    src = await resolve_chat(client, args.source, 'Source')
    dst = await resolve_chat(client, args.target, 'Target')
    src_id = utils.get_peer_id(src)     # sync helper; the client method is async
    dst_id = utils.get_peer_id(dst)
    print(f"   Source: {getattr(src, 'title', src_id)} ({src_id})")
    print(f"   Target: {getattr(dst, 'title', dst_id)} ({dst_id})\n")

    print(f"Scanning up to {args.limit} messages...")
    picked, scanned = [], 0
    async for msg in client.iter_messages(src, limit=args.limit):
        scanned += 1
        if msg.date.astimezone(cutoff.tzinfo) < cutoff:
            break
        if not is_plain_text(msg):
            continue
        text = msg.raw_text
        if not text:
            continue
        if args.keyword and not any(k.lower() in text.lower() for k in args.keyword):
            continue
        sender = await msg.get_sender()
        if args.from_bot_only and not bool(getattr(sender, 'bot', False)):
            continue
        who = getattr(sender, 'username', None) or getattr(sender, 'first_name', '?')
        out = correct_timestamp(text, msg.date, not args.keep_original_time)
        picked.append((msg, who, out))

    picked.reverse()        # oldest first, so the target reads chronologically
    print(f"   Scanned {scanned}, selected {len(picked)}\n")

    if not picked:
        print("Nothing matched. Check --since, --keyword, or the source group.")
        await client.disconnect()
        return

    for i, (msg, who, out) in enumerate(picked, 1):
        stamp = msg.date.astimezone(cutoff.tzinfo).strftime('%H:%M:%S')
        print(f"{i:>3}. [{stamp}] @{who}: {out.replace(chr(10), ' ⏎ ')[:90]}")

    if not args.send:
        print(f"\nDRY RUN. {len(picked)} message(s) would go to "
              f"{getattr(dst, 'title', dst_id)}.")
        print("Re-run with --send to deliver them.")
        await client.disconnect()
        return

    print(f"\nSending {len(picked)} message(s) via bot token...")
    redact, paused = load_guards()

    # A group taken out of service is silent, and a backfill is not an
    # exception to that - it is exactly the kind of thing somebody would run
    # without remembering the group is paused.
    if paused(dst_id):
        raise SystemExit(f"❌ {getattr(dst, 'title', dst_id)} is OUT OF SERVICE. "
                         "Put it back with /group on before backfilling into it.")

    bot = AsyncTeleBot(bot_token)
    ok = 0
    for i, (_, _, out) in enumerate(picked, 1):
        clean = redact(out)
        if clean != out:
            print(f"   {i}/{len(picked)}  (a name was taken out)")
        else:
            print(f"   {i}/{len(picked)}")
        if await send_with_retry(bot, dst_id, clean):
            ok += 1
        await asyncio.sleep(args.delay)

    await bot.close_session()
    await client.disconnect()
    print(f"\nDone. {ok}/{len(picked)} delivered.")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
