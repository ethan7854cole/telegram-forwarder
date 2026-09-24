"""The start-up check names what would make a feature fail silently.

Telegram only delivers reactions to a bot that is an ADMINISTRATOR in the chat,
so without it a crew acknowledgement and a payment retraction both vanish with
no error anywhere. And a RETRACT_SOURCES set in Railway replaces the default in
the code outright. Neither is visible from the code, so the bot checks at boot
and DMs the admin - only when something is wrong.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
os.environ.pop('RETRACT_SOURCES', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

MHLARRY, CHIMEREV = -1003894781195, -1002335630148
GVENMO, LVENMO = -5100231154, -1004298140797
GAFFER = -5580596463

dms = []


class Member:
    def __init__(self, status):
        self.status = status


class FakeBot:
    statuses = {}
    broken = set()

    async def get_chat_member(self, chat_id, user_id):
        if chat_id in self.broken:
            raise RuntimeError('chat not found')
        return Member(self.statuses.get(chat_id, 'administrator'))

    async def send_message(self, chat_id, text, **kw):
        dms.append((chat_id, text))


f.bot = FakeBot()
failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset(statuses=None, broken=()):
    dms.clear()
    f._health_checked = False
    f.bot.statuses = statuses or {}
    f.bot.broken = set(broken)


async def main():
    default_sources = set(f.RETRACT_SOURCES)

    # -- 1. everything in order: silent --------------------------------------
    reset()
    problems = await f.health_check()
    check('no problems when the bot is admin everywhere', problems == [], str(problems))
    check('and nobody is DMed', dms == [], str(dms))
    check('the default undoes payments on both live routes',
          CHIMEREV in f.RETRACT_SOURCES and LVENMO in f.RETRACT_SOURCES)

    # -- 2. once per process --------------------------------------------------
    f.bot.statuses = {LVENMO: 'member'}
    check('a reconnect does not check again', await f.health_check() == [])

    # -- 3. not an admin where reactions have to arrive ----------------------
    reset({LVENMO: 'member'})
    problems = await f.health_check()
    check('a non-admin handling group is reported',
          any('MH x LARRY VENMO' in p and 'not an admin' in p for p in problems),
          str(problems))
    check('saying what stops working',
          any('undo a payment' in p and 'crew reactions' in p for p in problems),
          str(problems))
    check('the admin is DMed once', len(dms) == 1 and dms[0][0] == f.ADMIN_ID, str(dms))

    # A forward target only needs membership - the bot deletes its own posts.
    reset({GVENMO: 'member'})
    check('a plain member is fine in a forward target', await f.health_check() == [])

    reset({GVENMO: 'left'})
    problems = await f.health_check()
    check('but not being in it at all is reported',
          any('GAFFER VENMO' in p and 'NOT a member' in p for p in problems), str(problems))

    reset(broken={CHIMEREV})
    problems = await f.health_check()
    check('a chat that cannot be checked is reported, not skipped',
          any('Chime Rev' in p and 'could not check' in p for p in problems), str(problems))

    # -- 4. Railway overriding RETRACT_SOURCES -------------------------------
    reset()
    f.RETRACT_SOURCES = f._with_variants([CHIMEREV])
    os.environ['RETRACT_SOURCES'] = str(CHIMEREV)
    problems = await f.health_check()
    check('a live source that cannot undo a payment is named',
          any('MH x LARRY VENMO' in p and str(LVENMO) in p for p in problems),
          str(problems))
    check('and Railway is named as the place to fix it',
          any('Railway' in p for p in problems), str(problems))
    del os.environ['RETRACT_SOURCES']
    f.RETRACT_SOURCES = default_sources

    # -- 5. a group out of service is not reported ---------------------------
    reset({MHLARRY: 'member'})
    f.PAUSED_CHATS = f._with_variants([MHLARRY, -5350880041])
    problems = await f.health_check()
    check('a paused group is left out of the check',
          not any('MH X LARRY GROUP 2' in p for p in problems), str(problems))
    f.PAUSED_CHATS = f._with_variants([])

    # -- 6. a failing check never takes boot down ---------------------------
    reset()
    real = f.bot.get_chat_member
    async def boom(*a, **k):
        raise RuntimeError('network down')
    f.bot.get_chat_member = boom
    problems = await f.health_check()
    check('every chat failing is reported, and nothing raises', len(problems) >= 3,
          str(problems))
    f.bot.get_chat_member = real

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
