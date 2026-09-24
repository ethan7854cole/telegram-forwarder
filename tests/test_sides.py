"""The two sides never see each other's people - names included, not just @handles.

The standing rule, restated "by any cost" on 2026-09-24: the chime groups and
the handling groups must never learn each other's names, usernames or anything
identifying the other side's crew, in either direction. @handles were always
stripped; a plain name ("asked by John", "Maynuddin sent it") was not, because
nothing knew whose name it was. The bot now files everyone it sees under the
side their group belongs to, and strips those names from anything crossing.

What must survive: the tag, every $cashtag, the amount and the keyword - a
cashout stripped of those cannot be paid. And forwarded PAYMENTS are never
touched: their payer names are customers, and the catch-up sweep compares them.

Nothing here touches Telegram or the network.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
os.environ.setdefault('PAUSED_CHATS', '')      # both routes live here - see run.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

PICCASO, GAFFER = -5350880041, -5580596463
MHLARRY, CHIMEREV = -1003894781195, -1002335630148
GVENMO, LVENMO = -5100231154, -1004298140797
ETHAN, LARRY = f.ETHAN_ID, f.LARRY_ID

sent, dms = [], []
_ids = [1000]


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    async def send_message(self, chat_id, text, reply_to_message_id=None):
        _ids[0] += 1
        (dms if chat_id > 0 else sent).append((chat_id, text))
        return FakeMsg(_ids[0])

    async def copy_message(self, chat_id, from_chat_id, message_id, caption=None, **kw):
        sent.append((chat_id, caption))
        return FakeMsg(9500)

    async def set_message_reaction(self, *a, **k):
        return True


class User:
    def __init__(self, uid, first=None, last=None, username=None, bot=False):
        self.id, self.first_name, self.last_name = uid, first, last
        self.username, self.bot = username, bot


f.bot = FakeBot()
f.USERBOT_SEND = False
f.USERBOT_REACT = False
f._active_client = None
failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


def reset_people():
    f._side_people['chime'].clear()
    f._side_people['handling'].clear()


def seed():
    """A chime-side asker, a handling-side crew member, and people on both."""
    reset_people()
    f.note_person(GAFFER, User(501, 'John', 'Smith', 'gaffer_boss'))
    f.note_person(GVENMO, User(502, 'Priya', None, 'venmo_lead'))
    f.note_person(CHIMEREV, User(601, 'Maynuddin', 'Ahmed', 'Maynuddin23'))
    f.note_person(LVENMO, User(602, 'Rafi', None, 'rafi_pays'))


def reset():
    sent.clear(); dms.clear()
    f._pending_cashouts.clear()
    f._seen_messages.clear()
    f._cashout_claims.clear()
    f._ledger.clear()
    f._cashout_stopped = False
    f.ledger_commit(GAFFER, (500.0, 0.0))
    f.ledger_commit(GVENMO, (500.0, 0.0))


async def main():
    now = datetime.now(timezone.utc)

    # -- 1. who gets filed where --------------------------------------------
    seed()
    check('a chime-group member is on the chime side', 501 in f._side_people['chime'])
    check('a handling-group member is on the handling side',
          601 in f._side_people['handling'])
    check('by first, last, full name and handle',
          f._side_people['chime'][501] >= {'john', 'smith', 'john smith', 'gaffer_boss'},
          str(f._side_people['chime'][501]))
    f.note_person(GAFFER, User(ETHAN, 'Ethan', None, 'ethannxxxx'))
    f.note_person(CHIMEREV, User(LARRY, 'Larry', None, 'Larryyxx'))
    check('Ethan and Larry are never filed - both sides know them',
          ETHAN not in f._side_people['chime'] and LARRY not in f._side_people['handling'])
    f.note_person(CHIMEREV, User(700, 'Chime', 'Alerts', 'chime_notify_bot', bot=True))
    check('a bot is never filed', 700 not in f._side_people['handling'])
    f.note_person(GAFFER, User(800, 'Sam', None, None))
    f.note_person(CHIMEREV, User(800, 'Sam', None, None))
    check('someone in groups on BOTH sides is not hidden from either',
          'sam' not in f.names_from('chime') and 'sam' not in f.names_from('handling'))
    f.note_person(GAFFER, User(801, 'Al', None, None))
    check('names under three letters are not filed', 'al' not in f.names_from('chime'))
    f.note_person(GAFFER, User(802, 'Cash', 'Request', None))
    check('nor words a request is made of',
          not ({'cash', 'request'} & f.names_from('chime')), str(f.names_from('chime')))

    # -- 2. chime -> crew: the request ---------------------------------------
    seed()
    req = ('!! Cashout Request !!\nTag name : $jenny-buhr\nAmount : 150\n'
           'asked by John Smith, ping gaffer_boss or Priya if stuck')
    clean = f.strip_foreign_handles(req)
    check("the asker's full name is taken out", 'john' not in clean.lower()
          and 'smith' not in clean.lower(), clean)
    check('so is a handle written without its @', 'gaffer_boss' not in clean.lower(), clean)
    check('and another chime member named in passing', 'priya' not in clean.lower(), clean)
    check('the keyword, tag and amount all survive',
          'Cashout Request' in clean and '$jenny-buhr' in clean and 'Amount : 150' in clean,
          clean)

    # A chime member called "Jenny" must not carve up the tag.
    f.note_person(GAFFER, User(503, 'Jenny', None, None))
    clean = f.strip_foreign_handles('!! Cashout Request !!\nTag name : $jenny-buhr\n'
                                    'Amount : 150\nfrom Jenny')
    check('a name inside the cashtag leaves the cashtag whole',
          '$jenny-buhr' in clean and 'from Jenny' not in clean, clean)
    venmo = ('!! Cashout Request !!\nTag name : @priya-sharma-7\nAmount : 80\n'
             'Priya asked')
    clean = f.strip_foreign_handles(venmo)
    check('a venmo tag that contains a chime name survives',
          '@priya-sharma-7' in clean and 'Priya asked' not in clean, clean)

    # End to end: the copy the crew actually receive.
    seed()
    reset()
    await f.observe_cashout(GAFFER, req, 910, now, user_id=501, username='gaffer_boss')
    copy = [t for c, t in sent if c == CHIMEREV]
    check('the copy in Chime Rev names nobody from the chime side',
          copy and not any(n in copy[0].lower()
                           for n in ('john', 'smith', 'gaffer_boss', 'priya')), str(copy))
    check('and still tags the crew', copy and '@Maynuddin23' in copy[0], str(copy))

    # The crew's private chase DM carries the request too.
    request = f._pending_cashouts[CHIMEREV][0]
    crew_dm = f.cashout_crew_dm_text(request, 10)
    check('the crew DM names nobody from the chime side',
          not any(n in crew_dm.lower() for n in ('john', 'smith', 'priya')), crew_dm)
    # Ethan and Larry are the exception, as everywhere.
    admin_dm = f.cashout_admin_dm_text(request, CHIMEREV, 5)
    check('the admins still see who asked', 'John Smith' in admin_dm, admin_dm)

    # An edit notice to the crew shows the changed line, cleaned the same way.
    await f.observe_cashout(GAFFER, req + '\nJohn says rush it', 910, now,
                            user_id=501, username='gaffer_boss', is_edit=True)
    notice = [t for c, t in sent if c == CHIMEREV and 'HAS BEEN EDITED' in t]
    check('the edit notice shows the change without the name',
          notice and 'rush it' in notice[0] and 'john' not in notice[0].lower(), str(notice))

    # -- 3. crew -> chime: the /out ------------------------------------------
    sent.clear()
    await f.observe_cashout(CHIMEREV, '/out 150 $jenny-buhr - Maynuddin sent, Rafi checked',
                            911, now, user_id=603, username='someone_else')
    out = [t for c, t in sent if c == GAFFER and '/out' in t]
    check('the /out reaches CHIME GAFFER', out, str(sent))
    check('with no crew member named - not only the sender',
          out and 'maynuddin' not in out[0].lower() and 'rafi' not in out[0].lower(), str(out))
    check('rebuilt from the figure and the cashtag',
          out and out[0] == '/out 150\n$jenny-buhr', str(out))

    # -- 4. the venmo route, both directions --------------------------------
    seed()
    reset()
    vreq = ('!! Cashout Request !!\nTag name : @michelle-surman-2\nAmount : 80\n'
            'from Priya (venmo_lead)')
    await f.observe_cashout(GVENMO, vreq, 920, now, user_id=502, username='venmo_lead')
    copy = [t for c, t in sent if c == LVENMO]
    check('the venmo copy names nobody from GAFFER VENMO',
          copy and 'priya' not in copy[0].lower() and 'venmo_lead' not in copy[0].lower(),
          str(copy))
    check('and keeps the venmo tag', copy and '@michelle-surman-2' in copy[0], str(copy))
    sent.clear()
    await f.observe_cashout(LVENMO, '/out 80 done by Rafi', 921, now, user_id=603,
                            username='someone_else')
    out = [t for c, t in sent if c == GVENMO and '/out' in t]
    check('the venmo /out names nobody from MH x LARRY VENMO',
          out and 'rafi' not in out[0].lower(), str(out))

    # -- 5. payments are never touched ---------------------------------------
    # The payer is a customer. And the catch-up sweep matches copies by name and
    # amount - rewriting the name would make it re-send and re-book the payment.
    seed()
    reset()
    f.note_person(CHIMEREV, User(604, 'Gabriel', 'W.', None))
    payment = 'You received $15.00 from Gabriel W.\n03:35 AM - 03 Aug 2026'
    await f.process_incoming(CHIMEREV, payment, 'test', from_bot=True, sent_at=now,
                             source_msg_id=930)
    fwd = [t for c, t in sent if c == GAFFER]
    check('a payment keeps its payer name, even one a crew member shares',
          fwd and 'Gabriel W.' in fwd[0], str(fwd))

    # -- 6. the member lists are read at boot --------------------------------
    reset_people()

    class Entity:
        def __init__(self, cid):
            self.id = cid

    class Client:
        async def get_entity(self, cid):
            return Entity(cid)

        def iter_participants(self, entity):
            members = {GAFFER: [User(501, 'John', 'Smith', 'gaffer_boss')],
                       CHIMEREV: [User(601, 'Maynuddin', None, 'Maynuddin23'),
                                  User(ETHAN, 'Ethan', None, 'ethannxxxx')]}

            async def gen():
                for u in members.get(entity.id, []):
                    yield u
            return gen()

    await f.learn_sides(Client())
    check('boot files the chime side from the member list',
          'john smith' in f.names_from('chime'), str(f.names_from('chime')))
    check('and the handling side', 'maynuddin' in f.names_from('handling'),
          str(f.names_from('handling')))
    check('still never Ethan', 'ethan' not in f.names_from('handling'))

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
