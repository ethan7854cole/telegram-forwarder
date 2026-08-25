"""Crew who work one handling group rather than both.

@NPR_CA (prutok sha) is crew on Chime Rev & out no-7 and nowhere else. The
three standing crew are on every route, and adding somebody to one side must
not quietly add them to the other: tagging them in the wrong group asks them to
pay a cashout that was never theirs, and counting a reaction of theirs there
would stop the chase for the people who actually have to do it.

Every other way the bot treats crew has to reach them identically - tagged on
the request and on every reminder, their reaction acknowledges it, their /out
is relayed, booked and hearted, they get the last-resort DM - and their name
must never reach a chime group.

The other route has to read byte for byte as it always did.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ['PAUSED_CHATS'] = ''          # both routes live: this is about crew
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
ETHAN, LARRY = f.ETHAN_ID, f.LARRY_ID
MAY, NPR = 77, 88
BOTID = 111222

sent, dms, copies, reactions = [], [], [], []
_next_id = [7000]
real_sleep = asyncio.sleep
failures = []


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
        return FakeMsg(7500)

    async def reply_to(self, message, text):
        return FakeMsg(7600)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id))
        return True

    async def delete_message(self, chat_id, message_id):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None
f.BOT_ID = BOTID


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label
          + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); copies.clear(); reactions.clear()
    f._ledger.clear(); f._seen_messages.clear(); f._pending_cashouts.clear()
    f._cashout_stopped = False
    # Learned ids, so a DM to any of them would really be delivered here.
    # Without one, "they were not DMed" passes for the wrong reason.
    f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY,
                        'maynuddin23': MAY, 'npr_ca': NPR})


def to(chat_id):
    return [t for c, t in sent if c == chat_id]


def dm_to(user_id):
    return [t for c, t in dms if c == user_id]


async def run_watchdog(seconds=0.25):
    async def fast(_):
        await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


async def open_request(origin, mid=601, minutes_ago=0):
    handling = f.CASHOUT_ROUTES[origin]['handling']
    await f.observe_cashout(origin, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 500', mid,
                            datetime.now(timezone.utc), user_id=42)
    for request in f._pending_cashouts.get(handling, []):
        request['opened'] = (datetime.now(timezone.utc)
                             - timedelta(minutes=minutes_ago))
    return f._pending_cashouts[handling][0]


# --------------------------------------------------------------------------
def test_config():
    check('@NPR_CA is crew on Chime Rev & out no-7',
          [h.lower() for h in f.group_crew(CHIMEREV)] == ['npr_ca'],
          str(f.group_crew(CHIMEREV)))
    check('and on nothing else', f.group_crew(MHLARRY) == []
          and f.group_crew(None) == [], str(f.group_crew(MHLARRY)))
    check('the tag line for Chime Rev carries all four',
          all(h in f.crew_mentions(CHIMEREV) for h in
              ('@Maynuddin23', '@MHSUPPORTZONE', '@maynuddin233', '@NPR_CA')),
          f.crew_mentions(CHIMEREV))
    check('MH X LARRY GROUP 2 reads exactly as it always did',
          f.crew_mentions(MHLARRY) == f.CASHOUT_MENTIONS, f.crew_mentions(MHLARRY))
    check('the Chime Rev crew DM list has all four',
          [h.lower() for h in f.crew_handles(CHIMEREV)]
          == ['maynuddin23', 'mhsupportzone', 'maynuddin233', 'npr_ca'],
          str(f.crew_handles(CHIMEREV)))
    check('and the other list is unchanged',
          f.crew_handles(MHLARRY) == list(f.CASHOUT_CREW_HANDLES),
          str(f.crew_handles(MHLARRY)))
    check('they answer for their own group',
          f._is_responder(NPR, 'NPR_CA', CHIMEREV) is True)
    check('and count for nothing in the other one',
          f._is_responder(NPR, 'NPR_CA', MHLARRY) is False)
    check('case does not matter', f._is_responder(NPR, 'npr_ca', CHIMEREV) is True)
    check('the standing crew still answer everywhere',
          f._is_responder(MAY, 'Maynuddin23', MHLARRY)
          and f._is_responder(MAY, 'Maynuddin23', CHIMEREV)
          and f._is_responder(MAY, 'Maynuddin23'))
    check('a stranger is nobody, in either group',
          not f._is_responder(999, 'someone', CHIMEREV)
          and not f._is_responder(999, 'someone', MHLARRY))


async def test_tagging():
    reset()
    await open_request(GAFFER, mid=602)
    posted = to(CHIMEREV)
    check('a request into Chime Rev tags @NPR_CA',
          len(posted) == 1 and '@NPR_CA' in posted[0], str(posted))
    check('and still tags the standing three',
          posted and all(h in posted[0] for h in
                         ('@Maynuddin23', '@MHSUPPORTZONE', '@maynuddin233')),
          str(posted))

    reset()
    await open_request(PICCASO, mid=603)
    posted = to(MHLARRY)
    check('a request into MH X LARRY GROUP 2 does not',
          len(posted) == 1 and '@NPR_CA' not in posted[0], str(posted))
    check('and ends exactly as it did before',
          posted and posted[0].endswith(f.CASHOUT_MENTIONS), str(posted))


async def test_reminders():
    reset()
    await open_request(GAFFER, mid=604, minutes_ago=45)
    await run_watchdog()
    nudges = [t for t in to(CHIMEREV) if 'CROSSED' in t]
    check('every reminder in Chime Rev tags them too',
          nudges and all('@NPR_CA' in t for t in nudges), str(nudges))
    check('their group gets the last-resort DM', dm_to(NPR) != [], str(dms))
    check('and it names no group, like everyone else\'s',
          all('Chime Rev' not in t and 'GAFFER' not in t for t in dm_to(NPR)),
          str(dm_to(NPR)))
    admin = [t for t in dm_to(LARRY) if 'Tagged in the group' in t]
    check('the admin notice says who was tagged, including them',
          admin and '@NPR_CA' in admin[0], str(admin))

    reset()
    await open_request(PICCASO, mid=605, minutes_ago=45)
    await run_watchdog()
    nudges = [t for t in to(MHLARRY) if 'CROSSED' in t]
    check('the other group\'s reminders are untouched',
          nudges and not any('@NPR_CA' in t for t in nudges), str(nudges))
    check('and they are not DMed about a group that is not theirs',
          dm_to(NPR) == [], str(dm_to(NPR)))
    admin = [t for t in dm_to(LARRY) if 'Tagged in the group' in t]
    check('nor named in the admin notice for it',
          admin and '@NPR_CA' not in admin[0], str(admin))


async def test_acknowledging():
    reset()
    request = await open_request(GAFFER, mid=606, minutes_ago=45)
    await f.note_cashout_seen(CHIMEREV, request['message_id'], NPR, 'NPR_CA')
    check('their reaction in Chime Rev acknowledges the request',
          request['seen'] is True)
    check('and Larry is told it was picked up',
          any('picked' in t.lower() or 'handled' in t.lower() for t in dm_to(LARRY)),
          str(dm_to(LARRY)))
    before = len(to(CHIMEREV))
    await run_watchdog()
    check('which stops the group being chased',
          len([t for t in to(CHIMEREV) if 'CROSSED' in t]) == 0,
          str(to(CHIMEREV)[before:]))

    reset()
    request = await open_request(PICCASO, mid=607)
    seen = await f.note_cashout_seen(MHLARRY, request['message_id'], NPR, 'NPR_CA')
    check('the same reaction in the other group means nothing',
          seen is False and request['seen'] is False)


async def test_paying():
    reset()
    f._ledger[GAFFER] = {'in': 6000.0, 'out': 1000.0}
    request = await open_request(GAFFER, mid=608)
    await f.observe_cashout(CHIMEREV, '/out 500', 609,
                            datetime.now(timezone.utc), user_id=NPR,
                            username='NPR_CA', reply_to=request['message_id'])
    check('their /out reaches the group that asked',
          any('/out 500' in t for t in to(GAFFER)), str(to(GAFFER)))
    check('and is booked there', f._ledger[GAFFER]['out'] == 1500.0, str(f._ledger))
    check('the original request is hearted',
          (GAFFER, 608) in reactions, str(reactions))
    check('and the request is settled',
          not f._pending_cashouts.get(CHIMEREV), str(f._pending_cashouts))


async def test_redaction():
    reset()
    check('an @NPR_CA is stripped out of anything bound for a chime group',
          '@NPR_CA' not in f.strip_identities('/out 500 sent by @NPR_CA'),
          f.strip_identities('/out 500 sent by @NPR_CA'))
    check('and so is the bare name',
          'NPR_CA' not in f.strip_identities('paid by NPR_CA just now'),
          f.strip_identities('paid by NPR_CA just now'))

    f._ledger[GAFFER] = {'in': 6000.0, 'out': 1000.0}
    request = await open_request(GAFFER, mid=610)
    await f.observe_cashout(CHIMEREV, '/out 500 sent by @NPR_CA $jenny-buhr', 611,
                            datetime.now(timezone.utc), user_id=NPR,
                            username='NPR_CA', reply_to=request['message_id'])
    landed = to(GAFFER)
    check('a /out naming them carries no name into the chime group',
          landed and not any('NPR_CA' in t for t in landed), str(landed))
    check('but the figure and the cashtag still travel',
          any('/out 500' in t and '$jenny-buhr' in t for t in landed), str(landed))
    check('and the books still moved by what was asked',
          f._ledger[GAFFER]['out'] == 1500.0, str(f._ledger))
    check('the handling group still sees the handles',
          '@NPR_CA' in f.crew_mentions(CHIMEREV))


async def main():
    print('one-group crew')
    test_config()
    await test_tagging()
    await test_reminders()
    await test_acknowledging()
    await test_paying()
    await test_redaction()

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
