# telegram-forwarder

A Telegram bot that moves payment notifications and cashout requests between
private groups, and keeps a running ledger for each one. It handles real money
figures for real people.

## Read this first

**Pushing to `main` is a production release.** Railway deploys from `main` with
no staging step. A bad forward posts wrong money figures into live groups, and
a duplicate cannot be taken back.

**Run the tests before every push:**

```bash
python3 tests/run.py            # all suites
python3 tests/run.py cashout    # only matching suites
```

410 checks across 12 suites, all stubbed — nothing touches Telegram, the
network, or the live groups. They cover the pre-existing behaviour as well as
the new, so they are the guard against a change quietly altering something that
already worked.

**Testing the unit is not enough.** Both real bugs found on 2026-08-03 came
from *interactions*: a sweep that was correct in isolation but compared against
text another function had rewritten, and a rename that left one call site
pointing at a name that no longer existed. Reasoning that a code path is
"untouched" is not evidence. Exercise it.

## The two directions

Payments travel outward. Cashout requests travel back.

```
MH X LARRY GROUP 2   --"You received"------>  CHIME PICCASO      (Total In  ↑)
Chime Rev & out no-7 --"You received"------>  CHIME GAFFER       (Total In  ↑)

CHIME PICCASO  --"CASHOUT REQUEST"-------->  MH X LARRY GROUP 2
CHIME GAFFER   --"CASHOUT REQUEST"-------->  Chime Rev & out no-7
        ^                                            |
        +--------------- /out --------------------- +   (Total Out ↑, ❤ on the request)
```

`FORWARD_RULES` drives the first. `CASHOUT_ROUTES` drives the second, and is
deliberately a **separate table** — putting the pairs in `FORWARD_RULES` would
drag the chime groups into `TARGET_CHATS` and fire the ledger, the milestones
and the idle watchdog on the wrong side of the flow.

## Two input paths

The Bot API cannot see messages posted by *other* bots, so a Telethon userbot
reads the source chats as a user account. Everything outbound still goes
through the bot token. Both paths funnel into `process_incoming()` and
`observe_cashout()` so the filtering and routing exist in one place.

The user account is allowed to **send** in exactly one case: an escalation DM
the bot cannot deliver, because a bot cannot open a chat with someone who has
never pressed Start and cannot address an `@username` at all. `USERBOT_SEND=0`
disables that.

Both paths take **plain text only**, with one exception. The crew answer a
request with the Cash App screenshot proving they sent the money and write the
`/out` as its caption, so `is_caption_out()` lets a caption through — but only
when it carries a `/out`, and only as far as the cashout flow. The caption is
relayed verbatim to the chime group that asked and books that group's Total
Out, exactly as a typed `/out` does; the screenshot itself is not forwarded.
`process_incoming()` is never reached from a caption, or a screenshot could be
read as a payment notification and invent a deposit. A captioned
`CASHOUT REQUEST` still opens nothing.

## Invariants — do not break these without being asked

- **A `/out` is acted on only while a request the bot forwarded is still open in
  that chat.** With nothing pending it is ordinary traffic and must be left
  completely alone, including the `/add`/`/out`/`/set` ledger commands.
- **Only Ethan (`7578145913`) and Larry (`7418675217`) may move ledger figures.**
- **Anything that changes the ledger must post a message containing BOTH total
  lines.** `recover_ledgers()` rebuilds each group's books after a deploy by
  reading its own newest such message back. Booking silently means the next
  redeploy reverts it. See `book_cashout_out()` for the pattern.
- **Never commit the ledger before the message carrying it has been sent.** The
  books must not run ahead of what the group can see.
- **The ledger follows wherever the `/out` was posted**, never the source —
  otherwise one group's books move while another group displays the figures,
  and both end up wrong.
- **Nothing the bot posts into MH X LARRY or Chime Rev is signed `-ETHAN`.** The
  milestone and idle messages keep the sign-off; those only go to chime groups.
- **The crew's escalation DM names no group.** Routing between groups is for
  Ethan and Larry only.
- **Never act on the bot's own messages.** The handling groups are also payment
  sources, so without that guard a forward would loop.
- **A private DM is a one-off, never a recurring chase.** `crew_told` and
  `admin_told` gate each to once per request. The repeating part is the group
  post, and only while nobody has acknowledged it.

## The escalation ladder

The group post is the loud, repeating part; a DM is the quiet, one-off part.
Which ladder a request climbs depends on whether anyone has acknowledged it —
a reaction from the crew, or any of them speaking in the handling group.

**Nobody acknowledges it** — `nudge_unacknowledged()`:

| Time | What happens |
|---|---|
| 5 min | group reminder #1, **plus** one DM to Ethan + Larry and one to the crew |
| 10 min | group reminder #2 |
| 15 min | group reminder #3, then reminders **stop** |

**Somebody reacts** — `escalate_acknowledged()`. The reaction resets the clock
and widens the window to `CASHOUT_SEEN_MINUTES` (7). Nothing further is posted
in the group: they have acknowledged it there, so re-tagging them is noise.

| Time | What happens |
|---|---|
| +7 min | one DM to the crew |
| +14 min | one DM to Ethan + Larry, then chasing **stops** |

A `/out` at any point completes it. Stopping is not giving up — the request
stays **open**, so a late `/out` is still forwarded, booked and hearted, and
deleting either copy still settles it.

## Gotchas

- A stale `~/forwarder.py` (unrelated, 1.5 KB) sits in the home directory, and
  shells often start there. Always use the absolute path when compiling or
  grepping, or you will silently check the wrong file.
- Reaction updates only reach a bot that is an **administrator** in the chat,
  and `message_reaction` must be listed in `allowed_updates` explicitly.
- Telegram only says which chat a deletion happened in when it was a channel.
  With no chat, look the message up before acting — dropping the wrong pending
  request silently strands a real cashout.
- Telegram credits a channel post to the channel, not the bot that sent it, so
  filtering history on the bot's own id can match nothing.
- Railway wipes the disk on deploy: no state can live on it. The messages in the
  groups are the durable record.

## Known gaps

- **Open cashout requests do not survive a redeploy.** They live in memory, so a
  restart stops the chasing, loses the ❤, and a later `/out` finds nothing
  pending. Fixable with a boot sweep: re-open any `CASHOUT REQUEST` not yet
  carrying a ❤, which already works as a durable "done" marker.
- **A duplicate payment is not detected.** When the catch-up sweep re-sent a
  window in Aug 2026, it re-booked every amount and nothing noticed. Cashout
  *requests* are guarded (`CASHOUT_DEDUP_SECONDS`); payments are not.
- **Nothing in-process can stop two containers double-posting.** The duplicate
  guard is per-request state held in memory, so two overlapping Railway
  containers each see a clean slate and each post once. If duplicates survive
  the guard, suspect the deploy overlap rather than the code — that is what
  `TELETHON_START_DELAY` exists for.
- **A near-miss keyword is silent.** `CASH OUT REQUEST` matches nothing,
  forwards nowhere, and tells nobody — indistinguishable from a quiet day.
- **The idle watchdog covers only the two CHIME groups**, not the VENMO targets.

## Layout

| Path | What it is |
|---|---|
| `forwarder.py` | The whole bot. Sectioned with comments explaining *why*, not what |
| `tests/run.py` | Test runner; exits non-zero on any failure |
| `tests/test_regress*.py` | Guard the pre-existing behaviour |
| `tests/test_parity.py` | Both cashout routes must behave identically |
| `tests/test_caption.py` | A `/out` captioning a screenshot, through both real dispatchers |
| `backfill.py` | Manual one-off backfill, separate from the boot sweep |
| `telethon_login.py` | Generates a `TELETHON_SESSION`; `--deploy` for Railway |

Config is environment variables with working defaults — see the top of
`forwarder.py` and each section header.
