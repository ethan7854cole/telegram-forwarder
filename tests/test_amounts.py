"""What happens around the /out itself: paying a figure that is not the one
asked for, and taking back the chase once the money has actually moved - the
crew's private DM and the reminders in the handling group alike.

Stubbed bot and Telethon client - nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
os.environ.setdefault('CASHOUT_TIMEOUT_MINUTES', '5')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
LARRY, ETHAN, CREW = f.LARRY_ID, f.ETHAN_ID, 555
ADMIN = f.ADMIN_ID          # notify_admin(): the bot-owner account

sent, dms, reactions, deleted = [], [], [], []
_next_id = [6000]
failures = []


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        if chat_id > 0:
            dms.append((chat_id, text, _next_id[0]))
        else:
            sent.append((chat_id, text, _next_id[0]))
        return FakeMsg(_next_id[0])

    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id))
        return True

    async def delete_message(self, chat_id, message_id):
        deleted.append((chat_id, message_id))
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); reactions.clear(); deleted.clear()
    f._pending_cashouts.clear(); f._seen_messages.clear(); f._ledger.clear()
    f._user_ids['larryyxx'] = LARRY
    f._user_ids['ethannxxxx'] = ETHAN
    f._user_ids['maynuddin23'] = CREW


real_sleep = asyncio.sleep


async def run_watchdog(seconds=0.2):
    async def fast(_): await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


async def open_request(text='!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200', msg_id=901):
    await f.observe_cashout(PICCASO, text, msg_id, datetime.now(timezone.utc),
                            user_id=42)
    return f._pending_cashouts[MHLARRY][-1]


def larry_dms(marker):
    return [t for uid, t, _ in dms if uid == LARRY and marker in t]


async def main():
    # -- paying less than was asked for -------------------------------------
    reset()
    await open_request()
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 150', 902, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')

    short = larry_dms('CASHOUT PAID SHORT BY')
    check('Larry is told when the /out pays less than was asked',
          len(short) == 1, str(dms))
    check('the alert carries both figures',
          short and 'Asked for: 200.00$' in short[0] and 'Paid: 150.00$' in short[0],
          str(short))
    check('and says how big the gap is',
          short and '50.00$' in short[0], str(short))
    check('it carries the routing, as every admin DM does',
          short and 'From:' in short[0] and 'Paid in:' in short[0], str(short))
    check('the crew are NOT told about it',
          [t for uid, t, _ in dms if uid == CREW] == [], str(dms))

    # The money moved, so the request is finished exactly as any other.
    check('the /out is still relayed to the group that asked',
          any(c == PICCASO and t == '/out 150' for c, t, _ in sent), str(sent))
    check('the request is still settled', MHLARRY not in f._pending_cashouts)
    check('the original request is still hearted',
          (PICCASO, 901) in reactions, str(reactions))
    check('the books follow what was actually paid',
          f.ledger_snapshot(PICCASO)[1] == 150.0, str(f.ledger_snapshot(PICCASO)))

    # -- paying more than was asked for -------------------------------------
    reset()
    await open_request()
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 250', 903, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    over = larry_dms('CASHOUT PAID OVER BY')
    check('an overpayment is flagged too', len(over) == 1, str(dms))
    check('and names the right gap', over and '50.00$' in over[0], str(over))

    # -- the exact figure raises nothing ------------------------------------
    reset()
    await open_request()
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 904, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('an exact /out raises no alert',
          larry_dms('CASHOUT PAID') == [], str(dms))
    check('the completed notice still goes out',
          larry_dms('COMPLETED SUCCESSFULLY') != [], str(dms))

    # -- a figure that cannot be read is not guessed at ---------------------
    reset()
    # Every valid request now carries a readable Amount line, so 'unreadable'
    # is no longer reachable - what is tested here is the matching case.
    await open_request('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 150')
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 150', 905, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('a /out matching the figure asked raises nothing',
          larry_dms('CASHOUT PAID') == [], str(dms))

    reset()
    await open_request()
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out done', 906, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('an unreadable /out figure raises nothing',
          larry_dms('CASHOUT PAID') == [], str(dms))

    # -- the caption on a screenshot is compared the same way ---------------
    reset()
    await open_request()
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 150', 907, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23', has_media=True)
    check('a /out written as a screenshot caption is compared too',
          larry_dms('CASHOUT PAID SHORT BY') != [], str(dms))

    # -- the 17-minute chase is taken back once the /out lands --------------
    reset()
    req = await open_request()
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=18)
    await run_watchdog()
    check('the crew were chased privately at 17 minutes',
          [t for uid, t, _ in dms if uid == CREW] != [], str(dms))
    check('and where it landed was recorded',
          len(req['crew_notice']) == 1, str(req['crew_notice']))
    notice_id = req['crew_notice'][0][2]

    deleted.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 908, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('the crew chase DM is deleted once the /out arrives',
          [d for d in deleted if d[0] > 0] == [(CREW, notice_id)], str(deleted))
    check('the request is settled as normal', MHLARRY not in f._pending_cashouts)

    # -- nothing else is ever deleted ---------------------------------------
    check('Larry and Ethan keep their copies',
          not any(chat in (LARRY, ETHAN) for chat, _ in deleted), str(deleted))

    reset()
    await open_request()
    deleted.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 909, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('a cashout that was never chased deletes nothing',
          deleted == [], str(deleted))

    # -- the copy sent by the USER ACCOUNT is taken back too -----------------
    # A bot cannot open a chat with somebody who has never pressed Start, so in
    # practice the crew are reached from the user account. That copy has to be
    # retractable as well, and an id only means anything alongside the client
    # that sent it.
    reset()
    f._user_ids.pop('maynuddin23', None)      # bot cannot reach them
    sent_via_user, deleted_via_user = [], []

    class FakeSent:
        def __init__(self, mid): self.id = mid

    class FakeClient:
        async def send_message(self, handle, text):
            sent_via_user.append((handle, text))
            return FakeSent(4200 + len(sent_via_user))

        async def delete_messages(self, where, ids):
            deleted_via_user.append((where, tuple(ids)))
            return True

    f.USERBOT_SEND, f._active_client = True, FakeClient()
    try:
        req = await open_request()
        req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=18)
        await run_watchdog()
        check('the crew were reached from the user account',
              sent_via_user != [], str(sent_via_user))
        check('the receipt records which client sent it',
              req['crew_notice'] and req['crew_notice'][0][0] == 'user',
              str(req['crew_notice']))

        await f.observe_cashout(MHLARRY, '/out 200', 930,
                                datetime.now(timezone.utc), user_id=77,
                                username='Maynuddin23')
        check('the user-account copy is deleted through that same client',
              deleted_via_user != [], str(deleted_via_user))
        check('and it deletes the right message',
              deleted_via_user and deleted_via_user[0][1] == (4201,),
              str(deleted_via_user))
        check('nothing was left on the request', req['crew_notice'] == [],
              str(req['crew_notice']))
    finally:
        f.USERBOT_SEND, f._active_client = False, None

    # -- a delete that fails is not silent ----------------------------------
    reset()
    req = await open_request()
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=18)
    await run_watchdog()

    async def refuse(chat_id, message_id):
        raise RuntimeError('message to delete not found')
    f.bot.delete_message = refuse
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 910, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    f.bot.delete_message = FakeBot.delete_message.__get__(f.bot)

    warned = [t for uid, t, _ in dms
              if uid == ADMIN and 'chase DM to the crew could not be deleted' in t]
    check('the admin account is told when the chase DM cannot be taken back',
          len(warned) == 1, str(dms))
    check('and told the money side is already done',
          warned and 'already done' in warned[0], str(warned))
    check('the crew are not told about the failure',
          [t for uid, t, _ in dms if uid == CREW] == [], str(dms))

    # -- the GROUP reminders are taken back the same way ---------------------
    # They read "still waiting on a /out" and end in the crew tag, so one left
    # behind is a live chase for a cashout that has already been paid.
    reset()
    req = await open_request()
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=6)
    await run_watchdog()
    posted = [(c, mid) for c, t, mid in sent if c == MHLARRY and 'TIMEFRAME' in t]
    check('a reminder went into the handling group', len(posted) == 1, str(sent))
    check('and where it landed was recorded on the request',
          req['group_notice'] == [posted[0][1]], str(req['group_notice']))

    forwarded_copy = req['message_id']
    deleted.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 911, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('the group reminder is deleted once the /out arrives',
          deleted == [(MHLARRY, posted[0][1])], str(deleted))
    check('the forwarded request itself is left alone',
          (MHLARRY, forwarded_copy) not in deleted, str(deleted))
    check('nothing was left on the request', req['group_notice'] == [],
          str(req['group_notice']))
    check('the request is settled as normal', MHLARRY not in f._pending_cashouts)

    # Every round the ladder posted goes, not just the last one.
    reset()
    req = await open_request()
    for minutes in (6, 9, 13):
        req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        await run_watchdog()
    check('all three rungs were recorded', len(req['group_notice']) == 3,
          str(req['group_notice']))
    rungs = list(req['group_notice'])
    deleted.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 912, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('every reminder is taken back, not only the last',
          [d for d in deleted if d[0] == MHLARRY] == [(MHLARRY, mid) for mid in rungs],
          str(deleted))

    # -- one cashout's reminders, not the group's ---------------------------
    # Two requests open in one handling group: paying one must not clear the
    # reminders still chasing the other.
    reset()
    first = await open_request('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200', msg_id=920)
    second = await open_request('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 75', msg_id=921)
    check('both requests are open', len(f._pending_cashouts[MHLARRY]) == 2)
    for request in (first, second):
        request['opened'] = datetime.now(timezone.utc) - timedelta(minutes=6)
    await run_watchdog()
    check('each request got its own reminder',
          len(first['group_notice']) == 1 and len(second['group_notice']) == 1,
          f"{first['group_notice']} {second['group_notice']}")
    first_reminder, second_reminder = first['group_notice'][0], second['group_notice'][0]

    deleted.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 913, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('only the paid request had its reminder deleted',
          deleted == [(MHLARRY, first_reminder)], str(deleted))
    check("the other request's reminder is left standing",
          second['group_notice'] == [second_reminder], str(second['group_notice']))
    check('and that request is still open',
          f._pending_cashouts.get(MHLARRY) == [second], str(f._pending_cashouts))

    # -- a request nobody chased deletes nothing ----------------------------
    reset()
    await open_request()
    deleted.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 914, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    check('a cashout that was never chased deletes nothing in the group',
          deleted == [], str(deleted))

    # -- a reminder somebody already deleted by hand is not a failure -------
    reset()
    req = await open_request()
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=6)
    await run_watchdog()

    async def already_gone(chat_id, message_id):
        raise RuntimeError('Bad Request: message to delete not found')
    f.bot.delete_message = already_gone
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 915, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    f.bot.delete_message = FakeBot.delete_message.__get__(f.bot)
    check('a reminder already deleted by hand raises nothing',
          [t for uid, t, _ in dms if uid == ADMIN and 'reminder' in t] == [],
          str(dms))

    # -- a delete that really fails is not silent ---------------------------
    reset()
    req = await open_request()
    req['opened'] = datetime.now(timezone.utc) - timedelta(minutes=6)
    await run_watchdog()

    async def refuse_group(chat_id, message_id):
        raise RuntimeError("message can't be deleted")
    f.bot.delete_message = refuse_group
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 200', 916, datetime.now(timezone.utc),
                            user_id=77, username='Maynuddin23')
    f.bot.delete_message = FakeBot.delete_message.__get__(f.bot)

    stuck = [t for uid, t, _ in dms
             if uid == ADMIN and 'could not be deleted from the group' in t]
    check('the admin account is told when a reminder cannot be taken back',
          len(stuck) == 1, str(dms))
    check('and told the money side is already done',
          stuck and 'already done' in stuck[0], str(stuck))
    check('the crew are not told about it',
          [t for uid, t, _ in dms if uid == CREW] == [], str(dms))
    check('nothing about the failure is posted in the group',
          [t for c, t, _ in sent if c == MHLARRY and 'could not' in t] == [],
          str(sent))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print(f"all amount/retraction checks passed")


asyncio.run(main())
