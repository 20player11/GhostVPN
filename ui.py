"""Rich terminal UI components for GhostVPN. Falls back to basic print if rich not installed."""

import os
import sys
import threading
import time

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
    from rich.text import Text
    from rich.align import Align
    from rich import box
    RICH = True
    C = Console()
except ImportError:
    RICH = False
    C = None

try:
    import questionary
    from questionary import Style as QStyle
    QUESTIONARY = True
    QSTYLE = QStyle([
        ("qmark", "fg:cyan"),
        ("question", "fg:white bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:cyan"),
        ("text", "fg:white"),
        ("instruction", "fg:gray italic"),
    ])
except ImportError:
    QUESTIONARY = False
    QSTYLE = None


def print_logo():
    import pyfiglet
    raw = pyfiglet.figlet_format("GHOSTVPN", font="slant")
    if RICH:
        panel = Panel(
            Align.center(Text(raw.rstrip(), style="bold cyan")),
            border_style="cyan",
            padding=(1, 2),
            subtitle="👻  ROTATING IP VPN  👻",
            subtitle_align="center",
        )
        C.print(panel)
    else:
        lines = raw.rstrip("\n").split("\n")
        for i, line in enumerate(lines):
            t = i / max(len(lines) - 1, 1)
            r = int(40 + (160 - 40) * t)
            g = int(200 + (50 - 200) * t)
            b = int(255 + (255 - 255) * t)
            print(f"\033[38;2;{r};{g};{b}m{line}\033[0m")
        chars = list("              👻  ROTATING IP VPN  👻")
        n = len(chars)
        out = []
        for i, ch in enumerate(chars):
            t = i / max(n - 1, 1)
            r = int(0 + (180 - 0) * t)
            g = int(200 + (50 - 200) * t)
            b = int(255 + (255 - 255) * t)
            out.append(f"\033[38;2;{r};{g};{b}m{ch}")
        out.append("\033[0m")
        print("".join(out))
        print()


def menu(header: str, opts: list[tuple[str, str]]) -> str:
    clear()
    print_logo()
    if QUESTIONARY and sys.stdout.isatty():
        try:
            choices = [
                questionary.Choice(title=label, value=str(i), shortcut_key=str(i))
                for i, (label, desc) in enumerate(opts, 1)
            ]
            result = questionary.select(
                header,
                choices=choices,
                qmark="",
                style=QSTYLE,
                use_shortcuts=True,
                instruction="(arrows to move, enter to confirm, or press number key)",
            ).ask()
            if result is not None:
                return result
        except Exception:
            pass
    if RICH:
        rows = []
        for i, (label, desc) in enumerate(opts, 1):
            row = f"[bold white]{i}.[/] {label}"
            if desc:
                row += f"\n   [dim]{desc}[/]"
            rows.append(row)
        panel = Panel(
            "\n\n".join(rows),
            title=f"[bold cyan]{header}[/]",
            border_style="cyan",
            padding=(1, 2),
            box=box.ROUNDED,
        )
        C.print(panel)
        c = C.input("[bold cyan]  └─ Choice: [/]").strip()
    else:
        print(f"  {header}\n")
        for i, (label, desc) in enumerate(opts, 1):
            print(f"     [{i}] {label}")
            if desc:
                print(f"         {desc}")
        print()
        c = input("  └─ Choice: ").strip()
    try:
        return str(int(c))
    except (ValueError, IndexError):
        return ""


def step(number: int, total: int, text: str, ok: bool | None = None):
    if RICH:
        status = "[green]✓[/]" if ok else "[red]✗[/]" if ok is False else "[yellow]…[/]"
        label = f"[bold]{number}/{total}[/]  {status}  {text}"
        C.print(Panel(label, border_style="green" if ok else "red" if ok is False else "dim", padding=(0, 1), box=box.MINIMAL))
    else:
        sym = "✓" if ok else "✗" if ok is False else "…"
        print(f"  [{number}/{total}] {sym} {text}")


class StatusDisplay:
    def __init__(self, pool, proxy=None):
        self.pool = pool
        self.proxy = proxy
        self._ev = threading.Event()
        self._thr: threading.Thread | None = None

    def start(self):
        self._ev.clear()
        self._thr = threading.Thread(target=self._run, daemon=True)
        self._thr.start()

    def stop(self):
        self._ev.set()
        if self._thr:
            self._thr.join(timeout=3)

    def _render(self) -> Panel | str:
        active = self.pool.get()
        host = "none"
        ptype = ""
        if active:
            host = f"{active[0].split('.')[0]}.{active[0].split('.')[1]}.*.*"
            ptype = f" {active[2]}"

        if RICH:
            table = Table.grid(padding=(0, 2))
            table.add_column()
            table.add_column()
            elapsed = "?"
            conns = "?"
            data = "?"
            if self.proxy and hasattr(self.proxy, "stats_line"):
                parts = self.proxy.stats_line().split(" • ")
                if len(parts) >= 1:
                    elapsed = parts[0]
                if len(parts) >= 2:
                    conns = parts[1].split(" ")[0]
                if len(parts) >= 3:
                    data = parts[2]
            table.add_row("[bold]Elapsed[/]", f"[cyan]{elapsed}[/]")
            table.add_row("[bold]Active conns[/]", f"[yellow]{conns}[/]")
            table.add_row("[bold]Data[/]", f"[magenta]{data}[/]")
            table.add_row("[bold]Pool[/]", f"[green]{self.pool.size()}[/]")
            table.add_row("[bold]Proxy[/]", f"[yellow]{host}[/][dim]{ptype}[/]")
            return Panel(table, title="[bold cyan]GHOSTVPN[/]", border_style="cyan", box=box.ROUNDED)
        else:
            cols = 80
            try:
                cols = os.get_terminal_size().columns
            except Exception:
                pass
            s = ""
            if self.proxy and hasattr(self.proxy, "stats_line"):
                s = self.proxy.stats_line()
            bar = f"  GHOSTVPN │ {s} │ pool {self.pool.size()} │ proxy {host}{ptype}  "
            if len(bar) >= cols:
                bar = bar[: cols - 1]
            else:
                bar = bar.ljust(cols - 1)
            return bar

    def _run(self):
        if RICH:
            with Live(self._render(), refresh_per_second=1, screen=False) as live:
                while not self._ev.is_set():
                    live.update(self._render())
                    self._ev.wait(1)
        else:
            while not self._ev.is_set():
                bar = self._render()
                sys.stdout.write(f"\r{bar}")
                sys.stdout.flush()
                self._ev.wait(1)
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()


def clear():
    if RICH:
        C.clear()
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def about():
    clear()
    print_logo()
    text = """\
[bold]GhostVPN[/] 👻

A rotating-IP VPN that routes your traffic through a
pool of free SOCKS5 proxies. No paid APIs.

Mode      │  TUN (Linux)    — system-wide VPN
          │  Wintun (Win)   — system-wide VPN
          │  SOCKS (all)    — local proxy, configure apps

Version   │  v1.5.1
License   │  MIT
Repo      │  https://github.com/20player11/GhostVPN
"""
    if RICH:
        C.print(Panel(text.strip(), border_style="cyan", box=box.ROUNDED))
        C.input("[dim]Press Enter to return...[/]")
    else:
        print(text)
        try:
            input()
        except Exception:
            pass
