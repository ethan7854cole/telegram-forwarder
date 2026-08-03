"""An @ in a muted group has to arrive as a DM, or it arrives nowhere.

The four cashout groups are muted as a matter of course, so a mention sits
there unread until somebody scrolls back. Telegram does not tell a bot whether
a chat is muted - that is a per-user setting the API does not expose - so this
never tries to detect it; the groups are simply watched.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
VENMO = -5100231154
ETHAN, LARRY = f.ADMIN_ID, 7418675217
BOTID = 111222

sent, dms, failures = [], [], []


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(1)

    async def set_message_reaction(self, *a, **k):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
f._user_ids.update({'larryyxx': LARRY, 'ethannxxxx': ETHAN})

NOW = datetime(2026, 8, 3, 3, 47, tzinfo=timezone.utc)


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); f._seen_messages.clear()


async def mention(chat_id, text, mid=100, uid=77, username='someguy',
                  full_name='Some Guy', when=NOW):
    await f.observe_mentions(chat_id, text, mid, when, uid, username, full_name)


def alerts():
    return [(uid, t) for uid, t in dms if 'YOU WERE MENTIONED' in t]


def first_body():
    """The first alert's text, or '' if none was sent.

    Indexing alerts()[0] directly makes the suite CRASH when the feature is
    switched off, which reports one failure instead of the dozen that are
    actually broken. A missing alert is a failed check, not an exception."""
    got = alerts()
    return got[0][1] if got else ''


async def main():
    # -- 1. the ordinary case ------------------------------------------------
    reset()
    await mention(MHLARRY, 'hey @Larryyxx can you check this one')
    check('both Ethan and Larry are told', len(alerts()) == 2, str(dms))
    check('it goes to their DMs, not the group', sent == [], str(sent))

    body = first_body()
    check('it names the group', 'MH X LARRY GROUP 2' in body, body)
    check('it names who sent it', '@someguy' in body and 'Some Guy' in body, body)
    check('it carries their id', 'Their id: 77' in body, body)
    check('it carries the time', 'At: ' in body and '03 Aug 2026' in body, body)
    check('it quotes the message', 'can you check this one' in body, body)

    # -- 2. every one of the four groups is watched --------------------------
    for chat in (PICCASO, GAFFER, MHLARRY, CHIMEREV):
        reset()
        await mention(chat, 'ping @ethannxxxx', mid=200 + abs(chat) % 97)
        check(f'{f.chat_name(chat)} is watched', len(alerts()) == 2, str(dms))

    # -- 3. ...and nowhere else ----------------------------------------------
    reset()
    await mention(VENMO, 'ping @ethannxxxx', mid=300)
    check('a VENMO target is not watched', alerts() == [], str(dms))

    reset()
    await mention(9999, 'ping @ethannxxxx', mid=301)      # a private chat
    check('a chat that is not on the list is ignored', alerts() == [], str(dms))

    # -- 4. who is NOT told --------------------------------------------------
    reset()
    await mention(MHLARRY, 'tagging @Maynuddin23 @MHSUPPORTZONE', mid=400)
    check('mentioning the crew alerts nobody', alerts() == [], str(dms))

    reset()
    await mention(MHLARRY, 'reminder for @Larryyxx', mid=401, uid=BOTID,
                  username='larrysbot')
    check("Larry's own bot never triggers it", alerts() == [], str(dms))

    reset()
    await mention(MHLARRY, '@ethannxxxx look at this', mid=402, uid=LARRY,
                  username='Larryyxx', full_name='Larry')
    told = [uid for uid, _ in alerts()]
    check('the sender is not told about their own message', LARRY not in told, str(told))
    check('but the person they tagged is', ETHAN in told, str(told))

    # -- 5. what counts as a mention -----------------------------------------
    for text, expect, why in (
            ('@larryyxx lowercase', True, 'case does not matter'),
            ('@LARRYYXX shouting', True, 'nor does shouting'),
            ('ping @larryyxx.', True, 'punctuation right after it still counts'),
            ('ping @ethannxxxx and @larryyxx', True, 'two at once is still one alert'),
            ('mail me at bob@larryyxx', False, 'an email tail is not a mention'),
            ('@larryyxxx is somebody else', False, 'a longer handle is a different person'),
            ('larryyxx with no at sign', False, 'the @ is required'),
            ('nothing to see here', False, 'no mention at all')):
        reset()
        await mention(MHLARRY, text, mid=500 + hash(text) % 400)
        got = len(alerts()) > 0
        check(f'{why}: {text!r}', got == expect, f'alerts={len(alerts())}')

    # -- 6. two mentions in one message is still one alert each --------------
    reset()
    await mention(MHLARRY, '@ethannxxxx @larryyxx both of you', mid=600)
    check('one message, one DM each', len(alerts()) == 2, str(len(alerts())))

    # -- 7. the same message down both input paths -------------------------
    reset()
    await mention(MHLARRY, 'ping @larryyxx', mid=700)
    await mention(MHLARRY, 'ping @larryyxx', mid=700)
    check('the two input paths do not double up', len(alerts()) == 2, str(len(alerts())))

    # -- 8. a long message is trimmed, not dumped ----------------------------
    reset()
    await mention(MHLARRY, '@larryyxx ' + ('x' * 900), mid=800)
    check('a very long message is trimmed', 0 < len(first_body()) < 700,
          str(len(first_body())))
    check('and says so', first_body().rstrip().endswith('…'), first_body()[-40:])

    # -- 9. a missing timestamp does not break it ----------------------------
    reset()
    await mention(MHLARRY, 'ping @larryyxx', mid=900, when=None)
    check('no timestamp is handled', len(alerts()) == 2, str(dms))
    check('and says the time is unknown', 'time unknown' in first_body(),
          first_body())

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
