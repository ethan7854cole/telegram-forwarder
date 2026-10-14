"""Two venmo groups, one handling group (2026-10-14).

MH x LARRY VENMO feeds BOTH GAFFER VENMO and PICCASO VENMO, and both ask for
cashouts in it. The user's rule: a request is remembered with the group that
asked, and its /out goes back to THAT group - "not ever to piccaso venmo" when
gaffer venmo asked, and the other way round. When the bot cannot tell which
request a /out pays, it holds the /out and asks for a reply; it never guesses.

The copy in MH x LARRY VENMO carries no label (the user's call), so the report
and the restart recovery tell the groups apart by tag, amount and timing.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # every route live - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

LVENMO, GVENMO, PVENMO = -1004298140797, -5100231154, -5306739731
CHIMEREV, GAFFER = -1002335630148, -5580596463
CREW, ASKER = 77, 42
BOT = f.BOT_ID
NOW = datetime.now(timezone.utc)

sent, dms, reactions, deleted = [], [], [], []
_ids = [7000]
failures = []


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None, **kw):
        _ids[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text, reply_to_message_id))
        return FakeMsg(_ids[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        _ids[0] += 1
        sent.append((chat_id, caption, None))
        return FakeMsg(_ids[0])

    async def set_message_reaction(self, chat_id, message_id, reaction):
        reactions.append((chat_id, message_id))
        return True

    async def delete_message(self, chat_id, message_id):
        deleted.append((chat_id, message_id))
        return True

    async def edit_message_text(self, *a, **kw):
        return True


f.bot = FakeBot()
f.USERBOT_SEND = False
f._active_client = None


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset():
    sent.clear(); dms.clear(); reactions.clear(); deleted.clear()
    f._pending_cashouts.clear(); f._seen_messages.clear(); f._cashout_claims.clear()
    f._ledger.clear()
    for chat in (GVENMO, PVENMO, GAFFER):
        f.ledger_commit(chat, (1000.0, 0.0))


def request(amount, tag='$jenny-buhr'):
    return f'!! Cashout Request !!\nTag name : {tag}\nAmount : {amount}'


async def ask(group, mid, amount, tag='$jenny-buhr'):
    """A request typed in a venmo group; returns its copy's id in MH x LARRY VENMO."""
    await f.observe_cashout(group, request(amount, tag), mid, datetime.now(timezone.utc),
                            user_id=ASKER, username='asker')
    queue = f._pending_cashouts.get(LVENMO, [])
    mine = [r for r in queue if r['origin'] == group and r['origin_msg_id'] == mid]
    return mine[0]['message_id'] if mine else None


async def out(text, mid, reply_to=None, user_id=CREW, username='Maynuddin23'):
    await f.observe_cashout(LVENMO, text, mid, datetime.now(timezone.utc),
                            user_id=user_id, username=username, reply_to=reply_to)


def to(chat):
    return [t for c, t, _ in sent if c == chat]


def relayed(chat):
    """The /outs relayed into a group - not the totals line booked after it."""
    return [t for t in to(chat) if t.startswith('/out')]


def open_from(group):
    return [r for r in f._pending_cashouts.get(LVENMO, []) if r['origin'] == group]


async def main():
    # -- 0. the wiring ---------------------------------------------------------
    check('MH x LARRY VENMO pays into both venmo groups',
          f.FORWARD_RULES[LVENMO] == [GVENMO, PVENMO], str(f.FORWARD_RULES[LVENMO]))
    check('PICCASO VENMO asks in MH x LARRY VENMO',
          f.CASHOUT_ROUTES[PVENMO]['handling'] == LVENMO)
    check('and its /out comes home to PICCASO VENMO',
          f.CASHOUT_ROUTES[PVENMO]['out_to'] == PVENMO)
    check('the handling group knows both', f._CASHOUT_HANDLERS[LVENMO] == [GVENMO, PVENMO],
          str(f._CASHOUT_HANDLERS[LVENMO]))
    check('and is the only shared one',
          [h for h in f._CASHOUT_HANDLERS if f.shared_handling(h)] == [LVENMO])
    check('the chime routes still have one asker each',
          f._CASHOUT_HANDLERS[CHIMEREV] == [GAFFER])

    # -- 1. a payment lands in both, booked in both ----------------------------
    reset()
    await f.process_incoming(LVENMO, 'You received $10.00\nTotal In: 50\nTotal Out: 5',
                             'test', from_bot=True, sent_at=NOW)
    check('a venmo payment reaches GAFFER VENMO', len(to(GVENMO)) == 1, str(sent))
    check('and PICCASO VENMO', len(to(PVENMO)) == 1, str(sent))
    check('each books it on its own figures',
          f.ledger_snapshot(GVENMO) == (1010.0, 0.0)
          and f.ledger_snapshot(PVENMO) == (1010.0, 0.0),
          f"{f.ledger_snapshot(GVENMO)} {f.ledger_snapshot(PVENMO)}")

    # -- 2. both groups ask; identical words are still two cashouts ------------
    reset()
    g_copy = await ask(GVENMO, 101, 150)
    p_copy = await ask(PVENMO, 201, 150)
    check('GAFFER VENMO\'s request is posted', g_copy is not None)
    check('PICCASO VENMO\'s identical request is NOT taken for a duplicate',
          p_copy is not None and p_copy != g_copy, f"{g_copy} {p_copy}")
    check('both are open, each with its own group',
          len(open_from(GVENMO)) == 1 and len(open_from(PVENMO)) == 1)
    again = await ask(PVENMO, 202, 150)
    check('the same group sending it twice IS still a duplicate',
          len(open_from(PVENMO)) == 1, str(f._pending_cashouts.get(LVENMO)))

    # -- 3. a reply settles exactly the request it answers ---------------------
    sent.clear()
    await out('/out 150', 301, reply_to=p_copy)
    check('a /out replying to PICCASO VENMO\'s request goes to PICCASO VENMO',
          relayed(PVENMO) == ['/out 150'], str(sent))
    check('and NEVER to GAFFER VENMO', to(GVENMO) == [], str(sent))
    check('booked in PICCASO VENMO only',
          f.ledger_snapshot(PVENMO)[1] == 150.0 and f.ledger_snapshot(GVENMO)[1] == 0.0,
          f"{f.ledger_snapshot(PVENMO)} {f.ledger_snapshot(GVENMO)}")
    check('the ❤ goes on PICCASO VENMO\'s original', reactions == [(PVENMO, 201)],
          str(reactions))
    check('GAFFER VENMO\'s request is still open', len(open_from(GVENMO)) == 1)

    # -- 4. no reply, but only one group has anything open: that group ---------
    sent.clear(); reactions.clear()
    await out('/out 150', 302)
    check('with only GAFFER VENMO open, a bare /out goes there',
          relayed(GVENMO) == ['/out 150'] and to(PVENMO) == [], str(sent))
    check('and closes it', LVENMO not in f._pending_cashouts)

    # -- 5. no reply, the figure picks one group -------------------------------
    reset()
    await ask(GVENMO, 111, 80)
    await ask(PVENMO, 211, 300)
    sent.clear()
    await out('/out 300', 311)
    check('a bare /out matching only PICCASO VENMO\'s figure goes there',
          relayed(PVENMO) == ['/out 300'] and to(GVENMO) == [], str(sent))

    # -- 6. no reply, could be either: HELD -----------------------------------
    reset()
    await ask(GVENMO, 121, 200)
    await ask(PVENMO, 221, 200)
    sent.clear(); dms.clear()
    await out('/out 200', 321)
    check('a /out that could pay either group reaches neither',
          to(GVENMO) == [] and to(PVENMO) == [], str(sent))
    check('books nothing',
          f.ledger_snapshot(GVENMO)[1] == 0.0 and f.ledger_snapshot(PVENMO)[1] == 0.0)
    check('places no ❤', reactions == [], str(reactions))
    check('both requests stay open',
          len(open_from(GVENMO)) == 1 and len(open_from(PVENMO)) == 1)
    held = to(LVENMO)
    check('the crew are asked, under their /out, to reply to the request',
          len(held) == 1 and 'REPLY' in held[0]
          and [r for c, _, r in sent if c == LVENMO] == [321], str(sent))
    check('naming neither venmo group to the crew',
          held and 'GAFFER' not in held[0] and 'PICCASO' not in held[0], str(held))
    check('Ethan and Larry are told it was held',
          any('HELD' in t for _, t, _ in dms), str(dms))

    # A figure that matches nothing, with both open, is just as unclear.
    sent.clear()
    await out('/out 999', 322)
    check('a figure matching nothing, with both open, is held too',
          to(GVENMO) == [] and to(PVENMO) == [], str(sent))
    sent.clear()
    await out('/out done', 323)
    check('as is a /out with no figure at all', to(GVENMO) == [] and to(PVENMO) == [],
          str(sent))

    # Replying then settles it, to the right group.
    sent.clear()
    g_req = open_from(GVENMO)[0]
    await out('/out 200', 324, reply_to=g_req['message_id'])
    check('replying to GAFFER VENMO\'s request then sends it there',
          relayed(GVENMO) == ['/out 200'] and to(PVENMO) == [], str(sent))

    # -- 7. a reply to a request's reminder counts as a reply to the request --
    reset()
    await ask(GVENMO, 131, 50)
    await ask(PVENMO, 231, 50)
    p_req = open_from(PVENMO)[0]
    p_req['group_notice'].append(4444)          # a reminder posted under it
    sent.clear()
    await out('/out 50', 331, reply_to=4444)
    check('a /out replying to PICCASO VENMO\'s reminder goes to PICCASO VENMO',
          relayed(PVENMO) == ['/out 50'] and to(GVENMO) == [], str(sent))

    # -- 8. Ethan or Larry with nothing open: no group to send it to ----------
    reset()
    sent.clear(); dms.clear()
    await out('/out 75', 341, user_id=f.LARRY_ID, username='Larryyxx')
    check('an admin /out with nothing open is not relayed to either',
          to(GVENMO) == [] and to(PVENMO) == [], str(sent))
    check('nor booked',
          f.ledger_snapshot(GVENMO)[1] == 0.0 and f.ledger_snapshot(PVENMO)[1] == 0.0)
    check('and the admins are told why',
          any('cannot tell which' in t for _, t, _ in dms), str(dms))

    # ...while on a chime route, which has one asker, it still completes.
    reset()
    await f.observe_cashout(CHIMEREV, '/out 75', 342, datetime.now(timezone.utc),
                            user_id=f.LARRY_ID, username='Larryyxx')
    check('on Chime Rev the admin /out still completes as before',
          relayed(GAFFER) == ['/out 75'], str(sent))

    # -- 9. a chime route keeps its old, looser rule ---------------------------
    reset()
    await f.observe_cashout(GAFFER, request(80), 141, datetime.now(timezone.utc), user_id=ASKER)
    await f.observe_cashout(GAFFER, request(90, '$other'), 142, datetime.now(timezone.utc), user_id=ASKER)
    sent.clear()
    await f.observe_cashout(CHIMEREV, '/out 999', 343, datetime.now(timezone.utc),
                            user_id=CREW, username='Maynuddin23')
    check('Chime Rev still settles the oldest when nothing else decides',
          relayed(GAFFER) == ['/out 999'], str(sent))

    # -- 10. telling copies apart without a label ------------------------------
    t0 = NOW - timedelta(hours=1)
    at = lambda s: t0 + timedelta(seconds=s)
    owner = f.attribute_copies(
        [(1, at(5), '$a', 100.0), (2, at(65), '$b', 50.0), (3, at(125), '$c', 20.0),
         (4, at(200), '$z', 9.0)],
        {GVENMO: [(11, at(2), '$a', 100.0), (13, at(120), '$c', 20.0)],
         PVENMO: [(21, at(60), '$b', 50.0), (23, at(121), '$c', 20.0)]})
    check('a copy matches the group whose original it repeats',
          owner[1] == GVENMO and owner[2] == PVENMO, str(owner))
    check('the same tag and amount from both groups is AMBIGUOUS, never guessed',
          owner[3] == f.AMBIGUOUS, str(owner))
    check('no original anywhere is unknown', owner[4] is None, str(owner))
    late = f.attribute_copies([(5, at(5000), '$a', 100.0)],
                              {GVENMO: [(11, at(2), '$a', 100.0)]})
    check('an original long before the copy does not count', late[5] is None, str(late))

    # -- 11. the report gives each group only its own --------------------------
    await test_report()

    # -- 12. a restart re-opens each request against the right group ----------
    await test_recover()

    # -- 13. catch-up never back-fills PICCASO VENMO from before it was fed ---
    check('PICCASO VENMO has a feed start', PVENMO in f.FEED_STARTED)

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print('all passed')


# -- history stand-ins ---------------------------------------------------------

class Sender:
    def __init__(self, uid, username=None):
        self.id, self.username = uid, username
        self.first_name = self.last_name = None


class Msg:
    def __init__(self, mid, text, minutes_ago, sender_id, reply_to=None):
        self.id, self.raw_text, self.message = mid, text, text
        self.date = NOW - timedelta(minutes=minutes_ago)
        self.sender_id = sender_id
        self.sender = Sender(sender_id)
        self.reply_to_msg_id = reply_to
        self.reactions = None
        self.caption = None


def tagged(text):
    return f"{text}\n\n@Maynuddin23 @MHSUPPORTZONE"


async def test_report():
    global history
    history = {
        GVENMO: [Msg(1, request(100, '$a'), 50, ASKER),
                 Msg(2, '/out 100', 40, BOT)],
        PVENMO: [Msg(3, request(40, '$b'), 30, ASKER)],
        LVENMO: [Msg(10, tagged(request(100, '$a')), 50, BOT),
                 Msg(11, tagged(request(40, '$b')), 30, BOT),
                 Msg(12, '/out 100', 40, CREW, reply_to=10),
                 Msg(13, '/out 40', 20, CREW)],
    }

    async def fake_scan(client, chat, start, end):
        return sorted(history.get(chat, []), key=lambda m: m.date)


    real = f._report_scan
    f._report_scan = fake_scan
    try:
        report = await f.build_report(None, NOW - timedelta(hours=2), NOW, NOW.date())
    finally:
        f._report_scan = real
    rows = {p['chime']: p for p in report['pairs']}
    g, p = rows.get(GVENMO), rows.get(PVENMO)
    check('the report has a PICCASO VENMO row', p is not None, str(list(rows)))
    if g and p:
        check('GAFFER VENMO\'s row has only its own request',
              [c['asked'] for c in g['cashouts']] == [100.0], str(g['cashouts']))
        check('PICCASO VENMO\'s row has only its own request',
              [c['asked'] for c in p['cashouts']] == [40.0], str(p['cashouts']))
        check('each paid by its own /out',
              all(c['paid_at'] is not None for c in g['cashouts'] + p['cashouts']))
        check('and the /outs are not counted twice',
              g['seen_out'] == 100.0 and p['seen_out'] == 40.0,
              f"{g['seen_out']} {p['seen_out']}")

    # A bare /out that could have paid either group's request was HELD live,
    # so the report must not hand it to either.
    history = {
        GVENMO: [Msg(1, request(70, '$x'), 50, ASKER)],
        PVENMO: [Msg(3, request(70, '$y'), 49, ASKER)],
        LVENMO: [Msg(10, tagged(request(70, '$x')), 50, BOT),
                 Msg(11, tagged(request(70, '$y')), 49, BOT),
                 Msg(12, '/out 70', 40, CREW)],
    }
    f._report_scan = fake_scan
    try:
        report = await f.build_report(None, NOW - timedelta(hours=2), NOW, NOW.date())
    finally:
        f._report_scan = real
    rows = {p['chime']: p for p in report['pairs']}
    g, p = rows.get(GVENMO), rows.get(PVENMO)
    check('a /out that could pay either group is counted in neither row',
          g and p and g['seen_out'] == 0.0 and p['seen_out'] == 0.0
          and all(c['paid_at'] is None for c in g['cashouts'] + p['cashouts']),
          f"{g and g['cashouts']} {p and p['cashouts']}")


async def test_recover():
    reset()
    history = {
        GVENMO: [Msg(1, request(100, '$a'), 50, ASKER),
                 Msg(5, request(60, '$same'), 20, ASKER)],
        PVENMO: [Msg(3, request(40, '$b'), 30, ASKER),
                 Msg(6, request(60, '$same'), 20, ASKER)],
        LVENMO: [Msg(10, tagged(request(100, '$a')), 50, BOT),
                 Msg(11, tagged(request(40, '$b')), 30, BOT),
                 Msg(14, tagged(request(60, '$same')), 20, BOT),
                 Msg(15, tagged(request(60, '$same')), 20, BOT)],
    }

    async def fake_scan(client, chat, since):
        return sorted(history.get(chat, []), key=lambda m: m.date, reverse=True)

    real = f._recover_scan
    f._recover_scan = fake_scan
    try:
        await f.recover_open_requests(object())
    finally:
        f._recover_scan = real
    queue = f._pending_cashouts.get(LVENMO, [])
    by_copy = {r['message_id']: r['origin'] for r in queue}
    check('after a restart GAFFER VENMO\'s request is open as GAFFER VENMO\'s',
          by_copy.get(10) == GVENMO, str(by_copy))
    check('and PICCASO VENMO\'s as PICCASO VENMO\'s', by_copy.get(11) == PVENMO,
          str(by_copy))
    check('requests that cannot be told apart are NOT re-opened',
          14 not in by_copy and 15 not in by_copy, str(by_copy))
    check('and the admins are told about them',
          any('cannot tell WHICH group' in t for _, t, _ in dms), str(dms))


asyncio.run(main())
