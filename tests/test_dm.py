"""Escalation DMs must reach everyone, including whoever owns the userbot session."""
import asyncio, os, sys

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forwarder as f

bot_dms, user_dms, admin_alerts, failures = [], [], [], []
bot_can_reach = set()          # ids the bot is allowed to message
user_can_reach = set()         # handles the account is allowed to message


class FakeMsg:
    def __init__(self, mid): self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        # No ADMIN_ID special case: Ethan is a DM recipient now as well as the
        # admin, so the two have to be told apart by route, not by chat id.
        if chat_id not in bot_can_reach:
            raise RuntimeError("bot can't initiate conversation with a user")
        bot_dms.append(chat_id); return FakeMsg(1)


async def fake_notify_admin(text):
    admin_alerts.append(text)


f.notify_admin = fake_notify_admin


class FakeClient:
    async def send_message(self, handle, text):
        if handle.lower() not in user_can_reach:
            raise RuntimeError('Cannot find any entity corresponding to "%s"' % handle)
        user_dms.append(handle.lower())


f.bot = FakeBot()


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond: failures.append(label)


def reset(userbot='ethannxxxx', send=True, client=True):
    bot_dms.clear(); user_dms.clear(); admin_alerts.clear()
    bot_can_reach.clear(); user_can_reach.clear()
    f._userbot_username = userbot
    f.USERBOT_SEND = send
    f._active_client = FakeClient() if client else None
    f._user_ids.clear()
    f._user_ids.update({'larryyxx': 7418675217, 'ethannxxxx': f.ADMIN_ID})


LARRY, ETHAN = 7418675217, f.ADMIN_ID
CREW = ['maynuddin23', 'mhsupportzone', 'maynuddin233']
ALL = ['ethannxxxx', 'larryyxx'] + CREW


async def dm_crew(text):
    """Both audiences with the same body, for the delivery-path checks below."""
    missed = await f.dm_handles(f.CASHOUT_ADMIN_HANDLES, text)
    missed += await f.dm_handles(f.CASHOUT_CREW_HANDLES, text)
    await f.warn_unreachable(missed)


f.dm_crew = dm_crew


async def main():
    # -- who is on which list ------------------------------------------------
    check('Ethan is on the admin list',
          'ethannxxxx' in [h.lower() for h in f.CASHOUT_ADMIN_HANDLES],
          str(f.CASHOUT_ADMIN_HANDLES))
    check('Larry is on the admin list',
          'larryyxx' in [h.lower() for h in f.CASHOUT_ADMIN_HANDLES],
          str(f.CASHOUT_ADMIN_HANDLES))
    check('the crew are on their own list',
          sorted(h.lower() for h in f.CASHOUT_CREW_HANDLES) == sorted(CREW),
          str(f.CASHOUT_CREW_HANDLES))
    check('no handle is on both lists',
          not (set(h.lower() for h in f.CASHOUT_ADMIN_HANDLES)
               & set(h.lower() for h in f.CASHOUT_CREW_HANDLES)))
    check('their ids are known, so the bot itself can reach them',
          f._user_ids.get('ethannxxxx') == ETHAN and f._user_ids.get('larryyxx') == LARRY,
          str(f._user_ids))

    # -- the two messages differ in exactly the intended way ----------------
    req = {'text': 'CASHOUT REQUEST $500 for Gabriel W.', 'origin': -5350880041}
    admin_text = f.cashout_admin_dm_text(req, -1003894781195, 5)
    crew_text = f.cashout_crew_dm_text(req, 5)

    check('admin DM names the group it came from', 'From: CHIME PICCASO' in admin_text,
          admin_text)
    check('admin DM names where it is waiting',
          'Waiting in: MH X LARRY GROUP 2' in admin_text, admin_text)
    check('crew DM has no From line', 'From:' not in crew_text, crew_text)
    check('crew DM has no Waiting in line', 'Waiting in:' not in crew_text, crew_text)
    check('crew DM names no group at all',
          not any(n in crew_text for n in ('CHIME PICCASO', 'CHIME GAFFER',
                                           'MH X LARRY', 'Chime Rev')), crew_text)
    check('both carry the required headline',
          'OUT REQUEST HAS CROSSED' in admin_text and 'OUT REQUEST HAS CROSSED' in crew_text)
    check('both carry the request itself',
          'CASHOUT REQUEST $500' in admin_text and 'CASHOUT REQUEST $500' in crew_text)
    check('crew DM says what to do', 'Please action it' in crew_text, crew_text)
    check('admin DM says who is being chased',
          'Tagged in the group' in admin_text, admin_text)

    # -- the normal case: Ethan and Larry get it FROM THE BOT ----------------
    reset()
    bot_can_reach.update([ETHAN, LARRY])
    user_can_reach.update(CREW)
    await f.dm_crew('alert')
    check('Ethan and Larry warned by the bot itself',
          sorted(bot_dms) == sorted([ETHAN, LARRY]), str(bot_dms))
    check('neither goes via the user account',
          'ethannxxxx' not in user_dms and 'larryyxx' not in user_dms, str(user_dms))
    check('the crew still fall back to the account', sorted(user_dms) == sorted(CREW),
          str(user_dms))
    check('nobody unreachable', admin_alerts == [], str(admin_alerts))

    # -- nobody started the bot: the account carries everyone ----------------
    reset()
    user_can_reach.update(ALL)
    await f.dm_crew('alert')
    check('all five reached via the user account', sorted(user_dms) == sorted(ALL),
          str(user_dms))
    check('no admin alert when everyone was reached', admin_alerts == [], str(admin_alerts))

    # -- Larry started the bot, crew did not ---------------------------------
    reset()
    bot_can_reach.add(LARRY)
    user_can_reach.update(['ethannxxxx'] + CREW)
    await f.dm_crew('alert')
    check('Larry gets the bot DM', bot_dms == [LARRY], str(bot_dms))
    check('crew fall back to the account', all(h in user_dms for h in CREW), str(user_dms))
    check('the account is not used for Larry', 'larryyxx' not in user_dms)

    # -- THE FIX: the session belongs to Larry, who has not started the bot --
    reset(userbot='larryyxx')
    user_can_reach.update(['larryyxx'] + CREW)
    await f.dm_crew('alert')
    check('Larry still warned when the session is his own',
          'larryyxx' in user_dms, str(user_dms))
    check('crew still reached alongside him',
          all(h in user_dms for h in CREW), str(user_dms))

    # -- the session belongs to a crew member --------------------------------
    reset(userbot='maynuddin23')
    user_can_reach.update(['larryyxx'] + CREW)
    await f.dm_crew('alert')
    check('a crew member owning the session is still warned',
          'maynuddin23' in user_dms, str(user_dms))

    # -- nobody reachable at all: admin must be told who ---------------------
    reset()
    await f.dm_crew('alert')
    check('nothing delivered', bot_dms == [] and user_dms == [])
    check('admin alerted', len(admin_alerts) == 1, str(admin_alerts))
    check('the alert names every unreachable handle',
          all(h in admin_alerts[0].lower() for h in ['larryyxx'] + CREW), str(admin_alerts))

    # -- partial failure names only the ones that failed ---------------------
    reset()
    user_can_reach.update(['maynuddin23', 'mhsupportzone'])
    await f.dm_crew('alert')
    check('partial failure still alerts', len(admin_alerts) == 1)
    check('only the unreached are named',
          'larryyxx' in admin_alerts[0].lower() and 'maynuddin233' in admin_alerts[0].lower()
          and 'mhsupportzone' not in admin_alerts[0].lower(), str(admin_alerts))

    # -- USERBOT_SEND=0 keeps the account strictly read-only -----------------
    reset(send=False)
    bot_can_reach.add(LARRY)
    user_can_reach.update(CREW)
    await f.dm_crew('alert')
    check('USERBOT_SEND=0 sends nothing from the account', user_dms == [], str(user_dms))
    check('USERBOT_SEND=0 still uses the bot', bot_dms == [LARRY])
    check('USERBOT_SEND=0 reports the rest', len(admin_alerts) == 1)

    # -- no client yet (userbot still connecting) ----------------------------
    reset(client=False)
    bot_can_reach.add(LARRY)
    await f.dm_crew('alert')
    check('no client: bot still delivers', bot_dms == [LARRY])
    check('no client: the rest are reported', len(admin_alerts) == 1)

    # -- a learned id lets the bot take over from the account ---------------
    reset()
    f._user_ids['maynuddin23'] = 555
    bot_can_reach.update([555, ETHAN, LARRY])
    user_can_reach.update(['mhsupportzone', 'maynuddin233'])
    await f.dm_crew('alert')
    check('a learned id routes through the bot', 555 in bot_dms, str(bot_dms))
    check('that handle no longer needs the account', 'maynuddin23' not in user_dms)
    check('everyone still reached', admin_alerts == [], str(admin_alerts))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures)); sys.exit(1)
    print("all DM checks passed")


asyncio.run(main())
