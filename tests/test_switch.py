"""The emergency stop: /cashout off takes the whole flow out of service.

For when something is going wrong and the right move is to stop the bot
touching real money until a person has looked. Nothing forwarded, nothing
chased, no totals moved.

Two things make this harder than a boolean.

It has to survive a redeploy - Railway wipes the disk on every push, and the
incident that made somebody stop the flow is very often the reason a push is
coming - so the state lives in a message and is read back on boot. That message
is PRIVATE: nothing about the switch is ever posted in a group. Which is why
recovery reads the bot's own DM, something only the userbot can do, and only
because the userbot is Ethan's or Larry's account.

And it must not become a silent hole. Silent in the groups is the requirement;
silent to a person is the bug. Anything real that arrives while the stop is on
is reported to Ethan and Larry rather than dropped.

Nothing here touches Telegram or the network.
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
ETHAN, LARRY, CREW = 7578145913, 7418675217, 77
BOTID = 111222

sent, dms, replies, copies = [], [], [], []
_next_id = [8000]
real_sleep = asyncio.sleep


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(_next_id[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        copies.append((chat_id, caption))
        return FakeMsg(8500)

    async def reply_to(self, message, text):
        replies.append(text)
        return FakeMsg(8600)

    async def set_message_reaction(self, *a, **k):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY})

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); replies.clear(); copies.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f._cashout_stopped = False
    f._cashout_stopped_by = None


# ---- a message shaped the way telebot delivers one -----------------------

class Cmd:
    def __init__(self, text, chat_id=ETHAN, uid=ETHAN, username='ethannxxxx'):
        self.chat = type('Chat', (), {'id': chat_id, 'type': 'private'})()
        self.from_user = type('U', (), {'id': uid, 'username': username})()
        self.text = text
        self.message_id = 8100


# ---- a Telethon client for the boot-recovery path ------------------------

class TeleMessage:
    def __init__(self, text, when, sender_id=BOTID):
        self.raw_text = text
        self.date = when
        self._sender_id = sender_id

    async def get_sender(self):
        return type('S', (), {'id': self._sender_id})()


class FakeClient:
    """history: {chat_id: [TeleMessage, ...]} newest first."""
    def __init__(self, history=None, explode=False):
        self.history = history or {}
        self.explode = explode

    async def get_entity(self, cid):
        if self.explode == 'entity':
            raise RuntimeError('CHANNEL_PRIVATE')
        return type('E', (), {'id': cid})()

    def iter_messages(self, entity, limit=100):
        if self.explode == 'iter':
            raise AttributeError('no iter_messages here')
        msgs = self.history.get(entity.id, [])

        async def gen():
            for m in msgs[:limit]:
                yield m
        return gen()


async def run_watchdog(seconds=0.15):
    async def fast(_):
        await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


def admin_dms():
    return [t for c, t in dms if c in (ETHAN, LARRY)]


async def main():
    now = datetime.now(timezone.utc)

    # -- 1. /cashout off stops a request being forwarded --------------------
    reset()
    await f.cashout_switch_command(Cmd('/cashout off'))
    check('the switch reports stopped', f.cashout_stopped() is True)
    check('NOTHING is posted in any group', sent == [], str(sent))
    check('Ethan and Larry both get the marker privately',
          sorted(c for c, _ in dms) == sorted([ETHAN, LARRY]), str(dms))
    check('the marker says what it is',
          all(f.CASHOUT_STOP_MARK in t for _, t in dms), str(dms))

    sent.clear(); dms.clear()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $25 $jenny-buhr', 901, now,
                            user_id=42)
    check('the request is NOT forwarded', sent == [], str(sent))
    check('and nothing is opened', f._pending_cashouts == {}, str(f._pending_cashouts))

    # -- 2. but it is NOT swallowed silently --------------------------------
    told = admin_dms()
    check('Ethan and Larry are told it arrived', len(told) == 2, str(dms))
    if told:
        check('the alert carries the request text', 'jenny-buhr' in told[0], told[0])
        check('and says it was not actioned',
              'NOT been forwarded' in told[0] or 'not been forwarded' in told[0].lower(),
              told[0])

    # -- 3. ordinary chatter while stopped is not reported ------------------
    dms.clear()
    await f.observe_cashout(MHLARRY, 'morning all', 902, now, user_id=CREW,
                            username='Maynuddin23')
    check('ordinary talk raises nothing', admin_dms() == [], str(dms))

    # -- 4. a /out while stopped moves no money, and is reported ------------
    dms.clear()
    await f.observe_cashout(MHLARRY, '/out 25', 903, now, user_id=CREW,
                            username='Maynuddin23')
    check('no totals are moved', f.ledger_snapshot(PICCASO) == (0.0, 0.0),
          str(f.ledger_snapshot(PICCASO)))
    check('nothing is relayed to the chime group', sent == [], str(sent))
    check('but Ethan and Larry hear about the /out', len(admin_dms()) == 2, str(dms))

    # -- 5. open requests are KEPT, not cancelled ---------------------------
    # Stopping is a pause. Dropping them would strand real cashouts that were
    # already in flight when the switch was thrown.
    reset()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $500 for Gabriel', 910, now,
                            user_id=42)
    check('a request is open before stopping',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1)
    await f.cashout_switch_command(Cmd('/cashout off'))
    check('it is still open after stopping',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1,
          str(f._pending_cashouts))

    # -- 6. nothing is chased while stopped ---------------------------------
    f._pending_cashouts[MHLARRY][0]['last_seen'] = now - timedelta(minutes=30)
    sent.clear(); dms.clear()
    await run_watchdog()
    check('no reminder is posted while stopped', sent == [], str(sent))
    check('no escalation DM either', dms == [], str(dms))

    # -- 7. /cashout on brings it back --------------------------------------
    sent.clear()
    await f.cashout_switch_command(Cmd('/cashout on'))
    check('the switch reports running', f.cashout_stopped() is False)
    check('resuming posts nothing in any group either', sent == [], str(sent))
    resume_marks = [c for c, t in dms if f.CASHOUT_RESUME_MARK in t]
    check('and the resume marker goes privately to Ethan and Larry',
          sorted(resume_marks) == sorted([ETHAN, LARRY]), str(dms))
    check('the request survived the whole thing',
          len(f._pending_cashouts.get(MHLARRY, [])) == 1)

    sent.clear()
    await f.observe_cashout(PICCASO, 'CASHOUT REQUEST $75 for Dana', 911, now,
                            user_id=42)
    check('requests are forwarded again',
          any(c == MHLARRY for c, _ in sent), str(sent))

    # -- 8. only Ethan and Larry may throw it -------------------------------
    reset()
    await f.cashout_switch_command(Cmd('/cashout off', chat_id=MHLARRY, uid=CREW,
                                       username='Maynuddin23'))
    check('the crew cannot stop the flow', f.cashout_stopped() is False)

    # -- 8b. and the refusal itself is silent -------------------------------
    # Answering "not permitted" in the group would announce that a kill switch
    # exists, to exactly the people it is being kept from. It is logged instead.
    check('nothing is said in the group', replies == [] and sent == [],
          f"replies={replies} sent={sent}")
    check('and nobody is DMed about it', dms == [], str(dms))

    # -- 9. it works from a cashout group, not just a DM --------------------
    # Typed in a group, every answer still comes back privately. Replying in the
    # group would put the switch in front of the crew.
    reset()
    await f.cashout_switch_command(Cmd('/cashout off', chat_id=CHIMEREV, uid=LARRY,
                                       username='Larryyxx'))
    check('Larry can stop it from a handling group', f.cashout_stopped() is True)
    check('nothing at all is posted in that group', sent == [], str(sent))
    check('no in-group reply either', replies == [], str(replies))
    check('the confirmation comes back privately to Larry',
          any(c == LARRY and 'STOPPED' in t for c, t in dms), str(dms))

    reset()
    f._cashout_stopped = True
    await f.cashout_switch_command(Cmd('/cashout', chat_id=CHIMEREV, uid=LARRY,
                                       username='Larryyxx'))
    check('even a status check in a group answers privately',
          sent == [] and replies == []
          and any(c == LARRY for c, _ in dms), f"sent={sent} replies={replies} dms={dms}")

    # -- 10. bare /cashout reports the state --------------------------------
    replies.clear()
    await f.cashout_switch_command(Cmd('/cashout'))
    check('status says stopped', any('STOPPED' in r for r in replies), str(replies))
    reset()
    replies.clear()
    await f.cashout_switch_command(Cmd('/cashout'))
    check('status says running', any('running' in r for r in replies), str(replies))

    # -- 10b. /help and /status carry it ------------------------------------
    # A command nobody can find is a command nobody uses, and this is the one
    # that gets reached for under pressure. Both are rendered from the live
    # code, so this fails the moment the entry is dropped or renamed.
    reset()
    dm = Cmd('/help')
    await f.help_command(dm)
    helptext = '\n'.join(t for c, t in dms if c == ETHAN)
    check('/help lists /cashout off', '/cashout off' in helptext, helptext[:400])
    check('/help lists /cashout on', '/cashout on' in helptext, helptext[:400])
    check('/help says open requests are kept',
          'kept, not cancelled' in helptext, helptext[:400])
    check('/help says it survives a redeploy',
          'survives a redeploy' in helptext, helptext[:400])

    replies.clear()
    await f.status(Cmd('/status'))
    check('/status says running when it is',
          any('running' in r for r in replies), str(replies))
    check('/status does not shout when nothing is wrong',
          not any('STOPPED' in r for r in replies), str(replies))

    await f.cashout_switch_command(Cmd('/cashout off'))
    replies.clear()
    await f.status(Cmd('/status'))
    check('/status leads with the stop when it is on',
          replies and replies[0].startswith('⏸️'), str(replies))
    check('/status tells you how to undo it',
          any('/cashout on' in r for r in replies), str(replies))

    # -- 11. it survives a redeploy -----------------------------------------
    # The whole reason the state is written into the groups at all.
    reset()
    client = FakeClient({BOTID: [TeleMessage(f.CASHOUT_STOP_MARK, now)]})
    await f.recover_cashout_switch(client)
    check('a stop marker in the groups restores the stop',
          f.cashout_stopped() is True)
    check('and Ethan and Larry are reminded on boot',
          any('still' in t and 'STOPPED' in t for t in admin_dms()), str(dms))

    reset()
    client = FakeClient({BOTID: [TeleMessage(f.CASHOUT_RESUME_MARK, now)]})
    await f.recover_cashout_switch(client)
    check('a resume marker leaves it running', f.cashout_stopped() is False)

    # The NEWEST marker wins, across both groups.
    reset()
    # Newest first, which is the order Telegram returns history in.
    client = FakeClient({BOTID: [
        TeleMessage(f.CASHOUT_STOP_MARK, now),
        TeleMessage(f.CASHOUT_RESUME_MARK, now - timedelta(hours=2)),
    ]})
    await f.recover_cashout_switch(client)
    check('the newest marker wins', f.cashout_stopped() is True)

    reset()
    client = FakeClient({BOTID: [
        TeleMessage(f.CASHOUT_RESUME_MARK, now),
        TeleMessage(f.CASHOUT_STOP_MARK, now - timedelta(hours=2)),
    ]})
    await f.recover_cashout_switch(client)
    check('and the other way round', f.cashout_stopped() is False)

    # Somebody else's message carrying the same words must not count.
    reset()
    client = FakeClient({BOTID: [TeleMessage(f.CASHOUT_STOP_MARK, now, sender_id=CREW)]})
    await f.recover_cashout_switch(client)
    check('only the bot\'s own marker counts', f.cashout_stopped() is False)

    # -- 12. reading the switch back can NEVER take the userbot down --------
    # This ran inside run_userbot()'s reconnect loop and an exception escaping
    # it was retried forever, so the userbot never finished starting. Found by
    # test_caption hanging - the boot equivalent of a handler causing the exact
    # failure it was written to prevent.
    reset()
    for mode, label in (('iter', 'iter_messages raising'),
                        ('entity', 'get_entity raising')):
        reset()
        try:
            await asyncio.wait_for(
                f.recover_cashout_switch(FakeClient({}, explode=mode)), timeout=5)
            check(f'{label} does not propagate', True)
        except asyncio.TimeoutError:
            check(f'{label} does not propagate', False, 'it hung')
        except Exception as e:
            check(f'{label} does not propagate', False, f'{type(e).__name__}: {e}')

    check('an unreadable switch is left alone, not guessed',
          f.cashout_stopped() is False)
    check('and a person is told it could not be verified',
          any('could not read back' in t for t in admin_dms()), str(dms))

    # A stop already in force must not be silently lifted by a failed read.
    reset()
    f._cashout_stopped = True
    await f.recover_cashout_switch(FakeClient({}, explode='iter'))
    check('a failed read does not lift an existing stop',
          f.cashout_stopped() is True)

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
