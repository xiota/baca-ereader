import argparse
import sys
import textwrap
from pathlib import Path
from typing import Type

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .. import __appname__, __version__
from ..ebooks import Azw, Ebook, Epub
from .queries import (
    get_all_reading_history,
    get_best_match_from_history,
    get_last_read_ebook,
    get_nth_file_from_history,
)


def print_danger(message: str):
    console = Console()
    console.print(Text(f"BacaError: {message}", style="bold red"))
    sys.exit(-1)


def print_reading_history() -> None:
    table = Table(title="Baca History")
    table.add_column("#", style="cyan", no_wrap=True, justify="right")
    table.add_column("Last Read", style="cyan", no_wrap=True)
    table.add_column("Progress", style="cyan", no_wrap=True, justify="right")
    table.add_column("Title", style="magenta", no_wrap=True)
    table.add_column("Author", style="green", no_wrap=True)
    table.add_column("Path", style="white", no_wrap=True)

    for n, rh in enumerate(get_all_reading_history()):
        table.add_row(
            str(n + 1),
            f"{rh.last_read:%b %d, %Y %I:%M %p}",
            f"{round(rh.reading_progress*100, 2)}%",  # type: ignore
            rh.title,  # type: ignore
            rh.author,  # type: ignore
            rh.filepath,  # type: ignore
        )

    Console().print(table)


def parse_cli_args() -> argparse.Namespace:
    prog = __appname__
    positional_arg_help_str = "[PATH | # | PATTERN | URL]"
    args_parser = argparse.ArgumentParser(
        prog=prog,
        # usage=f"%(prog)s [-h] [-r] [-d] [-v] {positional_arg_help_str}",
        usage=f"%(prog)s [-h] [-v] {positional_arg_help_str}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="TUI Ebook Reader",
        epilog=textwrap.dedent(
            f"""\
        examples:
          {prog} /path/to/ebook    read /path/to/ebook file
          {prog} 3                 read #3 file from reading history
          {prog} count monte       read file matching 'count monte'
                                from reading history
        """
        ),
    )
    args_parser.add_argument("-r", "--history", action="store_true", help="print reading history")
    args_parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"v{__version__}",
        help="print version and exit",
    )
    args_parser.add_argument(
        "ebook",
        action="store",
        nargs="*",
        metavar=positional_arg_help_str,
        help="ebook path, history number, pattern or URL",
    )
    return args_parser.parse_args()


def find_file() -> Path:
    args = parse_cli_args()
    if args.history:
        print_reading_history()
        sys.exit(0)

    elif len(args.ebook) == 0:
        last_read = get_last_read_ebook()
        if last_read is not None:
            return last_read
        else:
            print_danger("found no last read ebook file!")

    elif len(args.ebook) == 1:
        arg = args.ebook[0]
        try:
            nth = int(arg)
            ebook_path = get_nth_file_from_history(nth)
            if ebook_path is None:
                print_reading_history()
                print_danger(f"#{nth} file not found from history!")
            else:
                return ebook_path

        except ValueError:
            if Path(arg).is_file():
                return Path(arg)

    pattern = " ".join(args.ebook)
    ebook_path = get_best_match_from_history(pattern)
    if ebook_path is None:
        print_danger("found no matching ebook!")
    else:
        return ebook_path


def get_ebook_class(ebook_path: Path) -> Type[Ebook]:
    ext = ebook_path.suffix.lower()
    try:
        return {
            ".epub": Epub,
            ".epub3": Epub,
            ".azw": Azw,
            ".azw3": Azw,
        }[ext]
    except KeyError:
        print_danger("format not supported!")