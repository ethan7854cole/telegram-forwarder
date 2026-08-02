#!/usr/bin/env python3
"""Run every suite and report. Exit code 1 if anything failed.

    python3 tests/run.py            all suites
    python3 tests/run.py cashout    only suites whose name contains "cashout"

Each suite stubs the bot and the Telethon client, so nothing here touches
Telegram, the network, or the live groups. Run it before every push: this bot
posts real money figures into real groups, and there is no staging step between
`git push` and production.
"""
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else ''
    suites = sorted(p for p in HERE.glob('test_*.py') if wanted in p.name)
    if not suites:
        print(f"No suites matching {wanted!r}")
        return 1

    env = dict(os.environ, TELEGRAM_BOT_TOKEN='111222:FAKE')
    total = failed = 0
    broken = []

    for suite in suites:
        result = subprocess.run([sys.executable, str(suite)],
                                capture_output=True, text=True, env=env)
        out = result.stdout
        passed = out.count('  ok   ')
        fails = [line for line in out.splitlines() if line.startswith('  FAIL ')]
        total += passed
        failed += len(fails)

        if result.returncode == 0 and not fails:
            print(f"  {suite.stem:<16} PASS  {passed:>3} checks")
        else:
            broken.append(suite.stem)
            print(f"  {suite.stem:<16} FAIL  {passed} passed, {len(fails)} failed")
            for line in fails:
                print(f"      {line.strip()}")
            if result.returncode != 0 and not fails:
                # Crashed rather than failed a check - show why.
                tail = (result.stderr or out).strip().splitlines()[-3:]
                for line in tail:
                    print(f"      {line}")

    print()
    if broken:
        print(f"{failed} check(s) failed in: {', '.join(broken)}")
        return 1
    print(f"all {total} checks passed across {len(suites)} suites")
    return 0


if __name__ == '__main__':
    sys.exit(main())
