"""One-time Telethon login helper.

Run this on your Mac once:

    python3 telethon_login.py

For the Railway deployment, run it with --deploy instead:

    python3 telethon_login.py --deploy

That creates a SECOND, independent session. Railway and this Mac must never
share one: Telegram revokes an auth key that connects from two places at once,
which silently stops forwarding.

It logs in with your Telegram account and does two things:

  1. Saves a local <TELETHON_SESSION_NAME>.session file, so you can run
     `python3 forwarder.py` on this machine to test without any extra setup.
  2. Prints a TELETHON_SESSION string to paste into your Railway variables -
     the deployed bot cannot do an interactive login on its own.

Both the session file and the printed string grant full access to your Telegram
account. The file is gitignored; never commit or share either one.

To find the real numeric ids of your groups:

    python3 telethon_login.py --list-chats

This script never sends messages. It only authenticates and reads your dialog
list.
"""

import asyncio
import os
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession


def _prompt(name, current):
    if current:
        return current
    return input(f"{name}: ").strip()


async def main():
    api_id = _prompt('TELEGRAM_API_ID', os.getenv('TELEGRAM_API_ID'))
    api_hash = _prompt('TELEGRAM_API_HASH', os.getenv('TELEGRAM_API_HASH'))

    # Two INDEPENDENT sessions are required. Telegram invalidates an auth key
    # that connects from two places at once, so the deployed bot and this Mac
    # must never share one. --deploy logs in again as a separate device.
    deploy = '--deploy' in sys.argv
    session_name = ('railway_session' if deploy
                    else os.getenv('TELETHON_SESSION_NAME', 'user_session'))
    if deploy:
        print("Creating a SEPARATE session for Railway (independent of the local one).\n")

    async with TelegramClient(session_name, int(api_id), api_hash) as client:
        me = await client.get_me()
        print(f"\n✅ Logged in as {me.first_name} (@{me.username}) id={me.id}")

        if '--list-chats' in sys.argv:
            print("\nGroups and channels visible to your account:")
            print(f"{'CHAT ID':>16}  TYPE        TITLE")
            async for dialog in client.iter_dialogs():
                if dialog.is_user:
                    continue
                kind = 'channel' if dialog.is_channel else 'group'
                print(f"{dialog.id:>16}  {kind:<10}  {dialog.name}")
            print("\nUse these exact ids in FORWARD_RULES.")

        print(f"\n💾 Session saved to ./{session_name}.session")
        if deploy:
            print("   This one is for Railway only. Do not run local scripts with it.")
        else:
            print("   You can now run: python3 forwarder.py and python3 backfill.py")

        print("\n" + "=" * 70)
        if deploy:
            print("TELETHON_SESSION for Railway (secret - full access to your account):")
        else:
            print("Local session string (secret). For Railway use --deploy instead,")
            print("so the deployment gets its own key and the two cannot clash:")
        print("=" * 70)
        print(StringSession.save(client.session))
        print("=" * 70)


if __name__ == '__main__':
    asyncio.run(main())
