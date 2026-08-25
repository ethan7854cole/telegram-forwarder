"""A cashout request edited after it was forwarded.

The copy in the handling group is rewritten, and the crew are tagged again to
say so. A silent rewrite is the dangerous version: they read a request once, and
if the figure changes underneath them the copy they pay is the one they
remember.

What must NOT change: the ladder still runs from `opened`, an acknowledgement is
not taken back, and a request that has already been paid is left completely
alone — re-tagging the crew over that could only ask them to pay it twice.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ['PAUSED_CHATS'] = ''
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
GVENMO, LVENMO = -5100231154, -1004298140797
ETHAN, LARRY = f.ETHAN_ID, f.LARRY_ID
MAY, STRANGER = 77, 999
BOTID = 111222

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
ROUTES = [(PICCASO, MHLARRY), (GAFFER, CHIMEREV), (GVENMO, LVENMO)]

sent, dms, edits, deleted = [], [], [], []
failures = []
_next_id = [9000]
real_sleep = asyncio.sleep


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    fail_edit = False

    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _next_id[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text, reply_to_message_id))
        return FakeMsg(_next_id[0])

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        if FakeBot.fail_edit:
            raise Exception('message to edit not found')
        edits.append((chat_id, message_id, text))
        return FakeMsg(message_id)

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        return FakeMsg(9500)

    async def set_message_reaction(self, chat_id, message_id, reaction):
        return True

    async def delete_message(self, chat_id, message_id):
        deleted.append((chat_id, message_id))
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
    sent.clear(); dms.clear(); edits.clear(); deleted.clear()
    f._ledger.clear(); f._seen_messages.clear(); f._pending_cashouts.clear()
    f._cashout_stopped = False
    FakeBot.fail_edit = False
    f._user_ids.update({'ethannxxxx': ETHAN, 'larryyxx': LARRY,
                        'maynuddin23': MAY})


def to(chat_id):
    return [t for c, t, _ in sent if c == chat_id]


def dm_to(user_id):
    return [t for c, t, _ in dms if c == user_id]


async def open_request(origin, mid=801, text='!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200'):
    await f.observe_cashout(origin, text, mid, NOW, user_id=STRANGER,
                            username='someone')
    handling = f.CASHOUT_ROUTES[origin]['handling']
    return f._pending_cashouts[handling][0]


async def edit_request(origin, mid, text, sent_at=NOW):
    await f.observe_cashout(origin, text, mid, sent_at, user_id=STRANGER,
                            username='someone', is_edit=True)


async def run_watchdog(seconds=0.25):
    async def fast(_):
        await real_sleep(0.01)
    f.asyncio.sleep = fast
    task = asyncio.create_task(f.cashout_watchdog())
    await real_sleep(seconds)
    task.cancel()
    f.asyncio.sleep = real_sleep


# --------------------------------------------------------------------------
async def test_the_copy_is_rewritten():
    for origin, handling in ROUTES:
        reset()
        request = await open_request(origin, mid=801)
        copy_id = request['message_id']
        sent.clear()

        await edit_request(origin, 801, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
        label = f.chat_name(handling)
        mine = [e for e in edits if e[0] == handling and e[1] == copy_id]
        check(f'{label}: the forwarded copy is rewritten', len(mine) == 1, str(edits))
        check(f'{label}: it carries the new figure',
              mine and 'Amount : 350' in mine[0][2] and 'Amount : 200' not in mine[0][2],
              str(mine))
        check(f'{label}: and still tags the crew',
              mine and mine[0][2].rstrip().endswith(f.crew_mentions(handling)),
              str(mine))


async def test_the_crew_are_told():
    for origin, handling in ROUTES:
        reset()
        request = await open_request(origin, mid=802)
        copy_id = request['message_id']
        sent.clear()

        await edit_request(origin, 802, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
        posted = [(t, r) for c, t, r in sent if c == handling]
        label = f.chat_name(handling)
        check(f'{label}: one notice is posted', len(posted) == 1, str(posted))
        check(f'{label}: it says the request was edited',
              posted and 'HAS BEEN EDITED' in posted[0][0], str(posted))
        check(f'{label}: it tags the crew',
              posted and posted[0][0].rstrip().endswith(f.crew_mentions(handling)),
              str(posted))
        check(f'{label}: it replies to the request it points at',
              posted and posted[0][1] == copy_id, str(posted))
        check(f'{label}: it shows the figure that changed',
              posted and '200.00$ -> 350.00$' in posted[0][0], str(posted))
        check(f'{label}: it is unsigned',
              posted and '-ETHAN' not in posted[0][0], str(posted))
        check(f'{label}: and names no chime group',
              posted and f.chat_name(origin) not in posted[0][0], str(posted))
        check(f'{label}: and says nothing about Signal, which is not theirs',
              posted and 'Signal' not in posted[0][0], str(posted))


async def test_tag_changes():
    """The figure is not the only thing that matters, and not the worst to get
    wrong: the right amount to the wrong tag is money that is gone."""
    reset()
    await open_request(GAFFER, mid=820,
                       text='!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200')
    sent.clear()
    await edit_request(GAFFER, 820, '!! Cashout Request !!\nTag name : $hawkins-floral\nAmount : 200')
    notice = [t for t in to(CHIMEREV) if 'HAS BEEN EDITED' in t]
    check('a changed tag is reported',
          notice and 'Tag: $jenny-buhr -> $hawkins-floral' in notice[0], str(notice))
    check('and the unchanged amount is not',
          notice and 'Amount:' not in notice[0], str(notice))

    reset()
    await open_request(GAFFER, mid=821,
                       text='!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200')
    sent.clear()
    await edit_request(GAFFER, 821, '!! Cashout Request !!\nTag name : $hawkins-floral\nAmount : 350')
    notice = [t for t in to(CHIMEREV) if 'HAS BEEN EDITED' in t]
    check('both changes are reported together',
          notice and 'Amount: 200.00$ -> 350.00$' in notice[0]
          and 'Tag: $jenny-buhr -> $hawkins-floral' in notice[0], str(notice))

    # A valid request always carries a tag, so an edit that strips it can only
    # be reached by editing one that is already open - driven directly here.
    check('a tag that has been taken away is called out',
          'Tag: $jenny-buhr -> no longer given' in f._request_changes(
              'Tag name : $jenny-buhr\nAmount : 200', 'Amount : 200'),
          f._request_changes('Tag name : $jenny-buhr\nAmount : 200', 'Amount : 200'))
    check('and one that has just been given',
          'Tag: now $jenny-buhr' in f._request_changes(
              'Amount : 200', 'Tag name : $jenny-buhr\nAmount : 200'),
          f._request_changes('Amount : 200', 'Tag name : $jenny-buhr\nAmount : 200'))

    check('a bare dollar figure is never read as a tag',
          f.request_tag('Amount : 500') is None, str(f.request_tag('Amount : 500')))
    check('a real cashtag is', f.request_tag('pay $Hawkins-Floral-Decor now')
          == '$Hawkins-Floral-Decor')
    check('case alone is not a change',
          f._request_changes('to $Jenny-Buhr', 'to $jenny-buhr') == '',
          repr(f._request_changes('to $Jenny-Buhr', 'to $jenny-buhr')))
    check('a reworded request with nothing readable changed says nothing',
          f._request_changes('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200',
                             '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200') == '')


async def test_larry_hears_the_tag_too():
    reset()
    await open_request(GAFFER, mid=824,
                       text='!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 200')
    dms.clear()
    await edit_request(GAFFER, 824, '!! Cashout Request !!\nTag name : $hawkins-floral\nAmount : 200')
    notes = [t for t in dm_to(LARRY) if 'EDITED' in t]
    check('Larry is told which tag it goes to now',
          notes and 'Tag: $jenny-buhr -> $hawkins-floral' in notes[0], str(notes))


async def test_both_admins_are_told():
    reset()
    await open_request(GAFFER, mid=803)
    dms.clear()
    await edit_request(GAFFER, 803, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')

    for who, name in ((ETHAN, 'Ethan'), (LARRY, 'Larry')):
        notes = [t for t in dm_to(who) if 'EDITED' in t]
        check(f'{name} hears that a request changed', len(notes) == 1,
              str(dm_to(who)))
        check(f'{name} gets the figure',
              notes and '200.00$ -> 350.00$' in notes[0], str(notes))
        check(f'{name} gets the routing, which is theirs alone to see',
              notes and 'CHIME GAFFER' in notes[0]
              and 'Chime Rev' in notes[0], str(notes))
        check(f'{name} is told which group was asked on Signal',
              notes and 'CHIME GAFFER has been asked to confirm on Signal' in notes[0],
              str(notes))
    check('the crew are NOT DMed about it', dm_to(MAY) == [], str(dm_to(MAY)))


async def test_the_signal_ask():
    """Signal is asked of the side that MADE the change - the chime group."""
    for origin, handling in ROUTES:
        reset()
        request = await open_request(origin, mid=830)
        sent.clear()
        await edit_request(origin, 830, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')

        asked = [(t, r) for c, t, r in sent if c == origin]
        label = f.chat_name(origin)
        check(f'{label} is told its request changed', len(asked) == 1, str(asked))
        check(f'{label} is asked to text on Signal',
              asked and f.CASHOUT_SIGNAL_NOTE in asked[0][0], str(asked))
        check(f'{label}: it replies to the request that changed',
              asked and asked[0][1] == request['origin_msg_id'], str(asked))
        check(f'{label}: it carries what moved',
              asked and 'Amount: 200.00$ -> 350.00$' in asked[0][0], str(asked))
        check(f'{label}: it is signed, like everything else sent there',
              asked and asked[0][0].rstrip().endswith('-ETHAN'), str(asked))

        # The one message the bot posts INTO a route source. The keyword there
        # would be a request the bot had asked itself for.
        check(f'{label}: it does not contain the keyword',
              asked and f.CASHOUT_KEYWORD.lower() not in asked[0][0].lower(),
              str(asked))
        check(f'{label}: and names no crew',
              asked and not f.mentions_crew(asked[0][0]), str(asked))

        check(f'{f.chat_name(handling)} hears nothing about Signal',
              [t for t in to(handling) if 'Signal' in t] == [], str(to(handling)))

    # Asked on an EDIT and nothing else - a chase must read as it always did.
    reset()
    await open_request(GAFFER, mid=831)
    await run_watchdog()
    check('a chase never mentions Signal',
          [t for t in to(CHIMEREV) + to(GAFFER) if 'Signal' in t] == [],
          str(to(CHIMEREV)))

    original = f.CASHOUT_SIGNAL_NOTE
    f.CASHOUT_SIGNAL_NOTE = ''
    try:
        reset()
        await open_request(GAFFER, mid=832)
        sent.clear(); dms.clear()
        await edit_request(GAFFER, 832, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
        asked = [t for t in to(GAFFER)]
        check('emptying the note drops the line cleanly',
              asked and 'Signal' not in asked[0]
              and 'passed on.\n\n-ETHAN' in asked[0], repr(asked))
        check('and drops it from the admin DM too',
              all('Signal' not in t for t in dm_to(ETHAN)), str(dm_to(ETHAN)))
    finally:
        f.CASHOUT_SIGNAL_NOTE = original


async def test_the_request_record_follows():
    reset()
    request = await open_request(GAFFER, mid=804)
    await edit_request(GAFFER, 804, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
    check('the open request now holds the new text',
          'Amount : 350' in request['text'], request['text'])
    check('and the amount the /out is checked against moved',
          f.request_amount(request['text']) == 350.0,
          str(f.request_amount(request['text'])))
    check('the fingerprint moved with it',
          request['fingerprint'] == '!! cashout request !! tag name : $jenny-buhr amount : 350',
          request['fingerprint'])


async def test_the_ladder_is_not_restarted():
    reset()
    request = await open_request(GAFFER, mid=805)
    opened = request['opened']
    request['opened'] = opened - timedelta(minutes=45)
    request['seen'] = True
    request['seen_at'] = opened
    sent.clear()

    await edit_request(GAFFER, 805, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
    check('the clock is not put back',
          request['opened'] == opened - timedelta(minutes=45), str(request['opened']))
    check('an acknowledgement is not taken back', request['seen'] is True)
    check('no burst of reminders is posted',
          [t for t in to(CHIMEREV) if 'CROSSED' in t] == [], str(to(CHIMEREV)))


async def test_the_notice_goes_when_the_out_lands():
    reset()
    request = await open_request(GAFFER, mid=806)
    await edit_request(GAFFER, 806, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
    notice_ids = list(request['group_notice'])
    check('the notice is recorded against the request', len(notice_ids) == 1,
          str(notice_ids))

    await f.observe_cashout(CHIMEREV, '/out 350', 807, NOW, user_id=MAY,
                            username='Maynuddin23')
    check('and is taken back with the reminders once it is paid',
          all((CHIMEREV, mid) in deleted for mid in notice_ids), str(deleted))


async def test_nothing_open():
    reset()
    await f.observe_cashout(GAFFER, 'hello there', 808, NOW, user_id=STRANGER,
                            username='someone')
    sent.clear(); edits.clear()

    # Edited INTO a request: this has to open one, as it always did.
    await edit_request(GAFFER, 808, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 90')
    check('a message edited into a request opens one',
          len(f._pending_cashouts.get(CHIMEREV, [])) == 1,
          str(f._pending_cashouts))
    check('and is posted, not edited', len(to(CHIMEREV)) == 1 and edits == [],
          str(to(CHIMEREV)) + str(edits))

    # Already paid: out of the queue, ❤ on it, money gone.
    reset()
    await open_request(GAFFER, mid=809)
    await f.observe_cashout(CHIMEREV, '/out 200', 810, NOW, user_id=MAY,
                            username='Maynuddin23')
    sent.clear(); edits.clear(); dms.clear()
    await edit_request(GAFFER, 809, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
    check('a request already paid is left completely alone',
          sent == [] and edits == [] and dms == [], str(sent) + str(edits))


async def test_no_double_fire():
    reset()
    await open_request(GAFFER, mid=811)
    sent.clear(); edits.clear()

    # The same edit reaches both input paths.
    await edit_request(GAFFER, 811, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
    await edit_request(GAFFER, 811, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
    check('the same edit down both paths acts once',
          len(edits) == 1 and len(to(CHIMEREV)) == 1,
          str(len(edits)) + ' ' + str(to(CHIMEREV)))

    # A second, different edit still gets its turn.
    await edit_request(GAFFER, 811, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 400')
    check('a further edit is acted on', len(edits) == 2 and len(to(CHIMEREV)) == 2,
          str(len(edits)) + ' ' + str(len(to(CHIMEREV))))

    # Telegram re-fires an edit when it attaches a link preview.
    edits.clear(); sent.clear()
    f._seen_messages.clear()
    await edit_request(GAFFER, 811, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 400')
    check('an edit that changed nothing is ignored',
          edits == [] and to(CHIMEREV) == [], str(edits) + str(to(CHIMEREV)))


async def test_keyword_edited_out():
    reset()
    request = await open_request(GAFFER, mid=812)
    sent.clear(); edits.clear()
    await edit_request(GAFFER, 812, 'cancel that one please')
    check('editing the keyword out still updates the group', len(edits) == 1,
          str(edits))
    check('and still tells the crew to look',
          len([t for t in to(CHIMEREV) if 'HAS BEEN EDITED' in t]) == 1,
          str(to(CHIMEREV)))
    check('the request stays open, for a person to settle',
          f._pending_cashouts.get(CHIMEREV) == [request], str(f._pending_cashouts))


async def test_the_copy_is_gone():
    reset()
    request = await open_request(GAFFER, mid=813)
    old_copy = request['message_id']
    sent.clear(); edits.clear()
    FakeBot.fail_edit = True

    await edit_request(GAFFER, 813, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
    posted = [t for t in to(CHIMEREV)]
    check('an unreachable copy is reposted rather than dropped',
          len(posted) == 2, str(posted))
    check('the repost carries the new request',
          posted and 'Amount : 350' in posted[0], str(posted))
    check('and the request now points at it',
          request['message_id'] != old_copy, str(request['message_id']))
    check('the notice replies to the new copy',
          [r for c, _, r in sent if c == CHIMEREV][-1] == request['message_id'],
          str(sent))


async def test_paused_stays_silent():
    reset()
    request = await open_request(GAFFER, mid=814)
    sent.clear(); edits.clear(); dms.clear()
    f.set_paused_chats([CHIMEREV])
    try:
        await edit_request(GAFFER, 814, '!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 350')
        check('a paused handling group is not edited or posted into',
              edits == [] and to(CHIMEREV) == [], str(edits) + str(to(CHIMEREV)))
    finally:
        f.set_paused_chats([])


# --------------------------------------------------------------------------
async def main():
    await test_the_copy_is_rewritten()
    await test_the_crew_are_told()
    await test_tag_changes()
    await test_larry_hears_the_tag_too()
    await test_both_admins_are_told()
    await test_the_signal_ask()
    await test_the_request_record_follows()
    await test_the_ladder_is_not_restarted()
    await test_the_notice_goes_when_the_out_lands()
    await test_nothing_open()
    await test_no_double_fire()
    await test_keyword_edited_out()
    await test_the_copy_is_gone()
    await test_paused_stays_silent()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("request-edit suite passed")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
