import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="ytdl-sub-win-gui")
    parser.add_argument("--headless", action="store_true",
                        help="run all enabled subscriptions without UI (used by the scheduled task)")
    args = parser.parse_args()
    if args.headless:
        from ytdlsub_win_gui.runner import run_headless
        return run_headless()
    from ytdlsub_win_gui.gui import run_gui
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
