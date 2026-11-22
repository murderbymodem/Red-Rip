import argparse
import sys


def main() -> int:
    from redrip.oscompat import restore_system_env
    restore_system_env()  # programs we start (ffmpeg, yt-dlp, ...) get the system's libraries
    parser = argparse.ArgumentParser(prog="Red Rip")
    from redrip import __version__
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--self-test", action="store_true",
                        help="check that HTTPS downloads work (certificates), then exit")
    parser.add_argument("--headless", action="store_true",
                        help="run all enabled subscriptions without UI (used by the scheduled task)")
    args = parser.parse_args()
    if args.self_test:
        from redrip.net import self_test
        return self_test()
    if args.headless:
        from redrip.runner import run_headless
        return run_headless()
    from redrip.gui import run_gui
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
