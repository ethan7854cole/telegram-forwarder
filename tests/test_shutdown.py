"""SIGTERM must always reach the exit, however badly the disconnect goes.

On 2026-08-03 it did not. Telethon's disconnect() returned a Future,
loop.create_task() accepts only a coroutine, and the TypeError killed the
whole callback before it could schedule os._exit. The outgoing container then
sat there holding the session until Railway SIGKILLed it - which is precisely
the deploy overlap the handler exists to prevent, and which put two containers
on the air long enough to post one cashout request twice.

So the property under test is not "disconnect succeeds". It is "the exit is
scheduled no matter what disconnect does".
"""
import asyncio
import os
import sys

os.environ['TELEGRAM_BOT_TOKEN'] = '111222:FAKE'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forwarder as f

failures = []


def check(label, cond, detail=''):
    print(('  ok   ' if cond else '  FAIL ') + label + (f'  <- {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(label)


class FakeLoop:
    """Only what _install_shutdown_handler and _on_term actually touch."""

    def __init__(self):
        self.later = []
        self.signals = []

    def add_signal_handler(self, sig, fn):
        self.signals.append(sig)

    def call_later(self, delay, fn):
        self.later.append((delay, fn))


# -- the shapes disconnect() comes back as -----------------------------------

class FutureClient:
    """What Telethon actually does, and what used to crash the callback."""
    def __init__(self):
        self.called = False

    def disconnect(self):
        self.called = True
        fut = asyncio.get_event_loop().create_future()
        fut.set_result(None)
        return fut


class CoroutineClient:
    def __init__(self):
        self.called = False

    def disconnect(self):
        self.called = True
        async def go():
            return None
        return go()


class NoneClient:
    """Already disconnected. Not an error."""
    def __init__(self):
        self.called = False

    def disconnect(self):
        self.called = True
        return None


class ExplodingClient:
    def __init__(self):
        self.called = False

    def disconnect(self):
        self.called = True
        raise RuntimeError('session already gone')


async def main():
    # -- 1. every shape is handled, and none of them raises ------------------
    for name, client, expect_task in (
            ('a Future (what Telethon returns)', FutureClient(), True),
            ('a coroutine', CoroutineClient(), True),
            ('None, already disconnected', NoneClient(), False),
            ('an exception out of disconnect()', ExplodingClient(), False)):
        try:
            task = f._schedule_disconnect(client)
            raised = None
        except Exception as e:                       # noqa: BLE001 - that is the point
            task, raised = None, e
        check(f'{name} does not raise', raised is None, repr(raised))
        check(f'{name} still calls disconnect', client.called)
        check(f'{name} scheduling matches expectation',
              (task is not None) == expect_task, f'task={task!r}')
        if task is not None:
            await task

    check('a missing client is a no-op', f._schedule_disconnect(None) is None)

    # -- 2. the exit is scheduled even when the disconnect explodes ----------
    # This is the regression. The old code put create_task() before
    # call_later(), so anything raising above meant the process never left.
    for name, client in (('a healthy client', FutureClient()),
                         ('an exploding client', ExplodingClient()),
                         ('no client at all', None)):
        f._active_client = client
        loop = FakeLoop()
        on_term = f._install_shutdown_handler(loop)
        check(f'{name}: the handler is returned for testing', callable(on_term))
        try:
            on_term()
            raised = None
        except Exception as e:                       # noqa: BLE001
            raised = e
        check(f'{name}: SIGTERM does not raise', raised is None, repr(raised))
        check(f'{name}: the exit IS scheduled', len(loop.later) == 1, str(loop.later))
        if loop.later:
            check(f'{name}: it waits for the disconnect first',
                  loop.later[0][0] == 2, str(loop.later[0][0]))

    # -- 3. both signals are registered --------------------------------------
    import signal as _signal
    f._active_client = None
    loop = FakeLoop()
    f._install_shutdown_handler(loop)
    check('SIGTERM is handled', _signal.SIGTERM in loop.signals, str(loop.signals))
    check('SIGINT is handled', _signal.SIGINT in loop.signals, str(loop.signals))

    # -- 4. a platform without signal handlers must not stop start-up --------
    class NoSignals(FakeLoop):
        def add_signal_handler(self, sig, fn):
            raise NotImplementedError

    try:
        f._install_shutdown_handler(NoSignals())
        raised = None
    except Exception as e:                           # noqa: BLE001
        raised = e
    check('an unsupported platform is tolerated', raised is None, repr(raised))

    f._active_client = None

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + '; '.join(failures))
        sys.exit(1)
    print("all checks passed")


asyncio.run(main())
