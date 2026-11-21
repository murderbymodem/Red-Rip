import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="Red-Rip")
    from redrip import __version__
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--headless", action="store_true",
                        help="run all enabled subscriptions without UI (used by the scheduled task)")
    args = parser.parse_args()
    if args.headless:
        from redrip.runner import run_headless
        return run_headless()
    from redrip.gui import run_gui
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
