"""One-time Telethon login helper.

Run this on your Mac once:

    python3 telethon_login.py

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

    # Log in to a local file session so forwarder.py can be run on this machine
    # immediately. The string printed at the end is for deployment.
    session_name = os.getenv('TELETHON_SESSION_NAME', 'user_session')

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

        print(f"\n💾 Local session saved to ./{session_name}.session")
        print("   You can now run: python3 forwarder.py")

        print("\n" + "=" * 70)
        print("TELETHON_SESSION for Railway (secret - full access to your account):")
        print("=" * 70)
        print(StringSession.save(client.session))
        print("=" * 70)


if __name__ == '__main__':
    asyncio.run(main())
