"""Menu-driven terminal interface.  Run: python cli.py"""
from __future__ import annotations

import sys
from datetime import date

from core import validation as v
from core.exporter import export_file, write_error_log
from core.importer import import_csv_file
from core.models import CATEGORIES, CURRENCY, MAX_PASSENGERS, MIN_PASSENGERS, MODES, SAMPLE_CSV, Passenger, money
from core.search import search_rides
from core.splitter import build_ride
from core.storage import Store
from core.summary import summarize

C = {"b": "\033[1m", "d": "\033[2m", "r": "\033[31m", "g": "\033[32m", "y": "\033[33m", "c": "\033[36m", "x": "\033[0m"}
if not sys.stdout.isatty():
    C = {k: "" for k in C}


def paint(color, text):
    return f"{C[color]}{text}{C['x']}"


def banner():
    print(paint("c", "=" * 58))
    print(paint("b", "  RIDE SHARE COST SPLITTER"))
    print(paint("d", "  Split any ride fairly. Equal, weighted, percent or fixed."))
    print(paint("c", "=" * 58))


# ---------- input wrappers: loop until the value is valid -------------
def ask(prompt, parser, default=None):
    while True:
        raw = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        if not raw and default is not None:
            raw = str(default)
        try:
            return parser(raw)
        except v.ValidationError as exc:
            print(paint("r", f"  ! {exc}"))
        except (EOFError, KeyboardInterrupt):
            raise


def ask_choice(prompt, options, default=None):
    print(f"  {prompt}: " + ", ".join(options))
    return ask("  Choose", lambda s: v.parse_mode(s) if tuple(options) == MODES else v.parse_category(s), default)


def ask_yes(prompt):
    return input(f"{prompt} (y/n): ").strip().lower().startswith("y")


# ---------- table helpers ---------------------------------------------
def print_rides(rides, page=10):
    if not rides:
        print(paint("y", "  No rides match. Try adding one or loading the sample data."))
        return
    head = f"{'#':>4}  {'Date':<10}  {'Route':<30}  {'Total':>12}  {'Split':<8}  {'Open':>11}"
    for i in range(0, len(rides), page):
        print(paint("b", head))
        print("-" * len(head))
        for r in rides[i:i + page]:
            open_ = money(r.unsettled_cents) if r.unsettled_cents else "-"
            print(f"{r.id:>4}  {r.date:<10}  {r.route[:30]:<30}  {money(r.total_cents):>12}  {r.split_mode:<8}  {open_:>11}")
        if i + page < len(rides):
            if input(paint("d", f"  -- {i + page}/{len(rides)} shown. Enter for more, q to stop -- ")).strip().lower() == "q":
                break


def print_ride_detail(r):
    print(paint("b", f"\n  Ride #{r.id}: {r.route} ({r.date}, {r.category})"))
    print(f"  Fare {money(r.fare_cents)} + extras {money(r.extras_cents)} = {paint('g', money(r.total_cents))}  | {r.split_mode} split | paid by {r.payer}")
    for p in r.passengers:
        state = paint("c", "paid the driver") if p.name == r.payer else (paint("g", "settled") if p.settled else paint("y", "owes"))
        print(f"    {p.name:<20}{money(p.share_cents):>14}  {state}")
    print(paint("d", f"  Shares add up to {money(sum(p.share_cents for p in r.passengers))}"))


# ---------- actions ---------------------------------------------------
def collect_passengers(mode):
    hint = {"equal": "", "weighted": " (shares, e.g. 2)", "percent": " (percent, must total 100)",
            "fixed": " (amount, blank = pays the rest)"}[mode]
    while True:
        n = ask(f"Number of passengers ({MIN_PASSENGERS}-{MAX_PASSENGERS})", lambda s: _int(s, MIN_PASSENGERS, MAX_PASSENGERS))
        pax = []
        for i in range(1, n + 1):
            name = ask(f"  Passenger {i} name", lambda s: v.parse_text(s, field="Name", max_len=40))
            val = None
            if mode in ("weighted", "percent"):
                val = ask(f"  {name}'s value{hint}", lambda s: v.parse_number(s, field="Value"))
            elif mode == "fixed":
                raw = input(f"  {name}'s amount{hint}: ").strip()
                while raw:
                    try:
                        v.parse_money(raw, field="Amount", allow_zero=True)
                        val = float(raw.replace(",", ""))
                        break
                    except v.ValidationError as exc:
                        print(paint("r", f"  ! {exc}"))
                        raw = input(f"  {name}'s amount{hint}: ").strip()
            pax.append(Passenger(name=name, value=val))
        return pax


def _int(s, lo, hi):
    try:
        n = int(s)
    except ValueError:
        raise v.ValidationError(f"Enter a whole number from {lo} to {hi}.")
    if not lo <= n <= hi:
        raise v.ValidationError(f"Enter a whole number from {lo} to {hi}.")
    return n


def add_ride(store):
    print(paint("b", "\nNew ride"))
    d = ask("Date (YYYY-MM-DD)", v.parse_date, date.today().isoformat())
    route = ask("Route / description", lambda s: v.parse_text(s, field="Route"))
    cat = ask_choice("Category", CATEGORIES, "commute")
    fare = ask(f"Fare ({CURRENCY})", lambda s: (v.parse_money(s, field="Fare"), s)[1])
    extras = ask(f"Extras: tip/toll/fees ({CURRENCY}, 0 for none)", lambda s: (v.parse_money(s, field="Extras", allow_zero=True, allow_blank=True), s)[1], "0")
    mode = ask_choice("Split mode", MODES, "equal")
    total = v.parse_money(fare) + v.parse_money(extras, allow_blank=True, allow_zero=True)
    while True:
        pax = collect_passengers(mode)
        try:
            v.validate_passengers(mode, pax, total)
            break
        except v.ValidationError as exc:
            print(paint("r", f"  ! {exc} Let's re-enter the passengers."))
    names = [p.name for p in pax]
    payer = ask(f"Who paid the driver? ({', '.join(names)})", lambda s: v.parse_text(s, field="Payer"), names[0])
    try:
        ride = build_ride(date=d, route=route, category=cat, fare=fare, extras=extras, split_mode=mode,
                          payer=payer, passengers=pax)
    except v.ValidationError as exc:
        print(paint("r", f"  ! {exc}"))
        return
    store.add(ride)
    print(paint("g", "\n  Saved."))
    print_ride_detail(ride)


def view_rides(store):
    print_rides(sorted(store.rides, key=lambda r: (r.date, r.id), reverse=True))
    pick = input("\nRide # for details (Enter to skip): ").strip()
    if pick.isdigit() and store.get(int(pick)):
        print_ride_detail(store.get(int(pick)))


def search(store):
    kw = input("Keyword (route, name, notes; Enter to skip): ")
    cat = input(f"Category ({', '.join(CATEGORIES)}; Enter for all): ").strip().lower()
    unsettled = ask_yes("Only rides with unsettled balances?")
    print_rides(search_rides(store.rides, kw, cat if cat in CATEGORIES else "", unsettled_only=unsettled))


def show_summary(store):
    s = summarize(store.rides)
    if not s["count"]:
        print(paint("y", "  Nothing to summarise yet."))
        return
    print(paint("b", "\nSummary"))
    print(f"  Rides {s['count']}   Total {money(s['total_cents'])}   Avg fare {money(s['avg_fare_cents'])}   Avg share {money(s['avg_share_cents'])}")
    print(f"  Unsettled {paint('y', money(s['unsettled_cents']))}   Trend: {s['trend']}")
    top = max(s["monthly"].values())
    print(paint("b", "\n  Monthly spend"))
    for m, c in s["monthly"].items():
        print(f"  {m}  {money(c):>13}  {paint('c', '#' * max(1, round(c / top * 30)))}")
    print(paint("b", "\n  By category"))
    for k, c in s["by_category"].items():
        print(f"  {k:<10}{money(c):>14}")
    if s["owes"]:
        print(paint("b", "\n  Who owes the most"))
        for k, c in list(s["owes"].items())[:5]:
            print(f"  {k:<10}{money(c):>14}")
    if s["warnings"]:
        print(paint("b", "\n  Warnings"))
        colors = {"alert": "r", "warn": "y", "info": "d"}
        for w in s["warnings"][:8]:
            print("  " + paint(colors[w["level"]], f"[{w['level']}] {w['text']}"))
        if len(s["warnings"]) > 8:
            print(paint("d", f"  ...and {len(s['warnings']) - 8} more (see exported report)"))


def settle(store):
    rid = ask("Ride #", lambda s: _int(s, 1, 10**9))
    r = store.get(rid)
    if not r:
        print(paint("r", "  ! No ride with that number."))
        return
    print_ride_detail(r)
    name = input("Passenger who paid back (name, or 'all'): ").strip()
    targets = [p.name for p in r.passengers if p.name != r.payer] if name.lower() == "all" else [name]
    done = [t for t in targets if store.set_settled(rid, t, True)]
    print(paint("g", f"  Marked settled: {', '.join(done)}") if done else paint("r", "  ! No matching passenger (the payer is always settled)."))


def delete(store):
    rid = ask("Ride # to delete", lambda s: _int(s, 1, 10**9))
    r = store.get(rid)
    if not r:
        print(paint("r", "  ! No ride with that number."))
    elif ask_yes(f"Delete '{r.route}' ({money(r.total_cents)})?"):
        store.delete(rid)
        print(paint("g", "  Deleted."))


def export(store):
    fmt = ask("Format: markdown, text, csv", lambda s: s if s in ("markdown", "text", "csv") else (_ for _ in ()).throw(v.ValidationError("Pick markdown, text or csv.")), "markdown")
    print(paint("g", f"  Wrote {export_file(store.rides, fmt)}"))


def bulk_import(store):
    path = input(f"CSV path (Enter for sample data at {SAMPLE_CSV.name}): ").strip() or str(SAMPLE_CSV)
    try:
        rides, errors = import_csv_file(path)
    except OSError as exc:
        print(paint("r", f"  ! Cannot read file: {exc}"))
        return
    store.add_many(rides)
    print(paint("g", f"  Imported {len(rides)} rides."))
    if errors:
        print(paint("y", f"  {len(errors)} rows rejected:"))
        for e in errors[:10]:
            print(paint("r", f"   row {e['row']}: {e['error']}"))
        print(f"  Full log: {write_error_log(errors)}")


MENU = [("1", "Add a ride", add_ride), ("2", "View rides", view_rides), ("3", "Search rides", search),
        ("4", "Summary and warnings", show_summary), ("5", "Mark a payment as settled", settle),
        ("6", "Delete a ride", delete), ("7", "Export a report", export), ("8", "Import rides from CSV", bulk_import)]


def main():
    store = Store()
    banner()
    for note in store.notes:
        print(paint("y", f"  Note: {note}"))
    print(f"  {len(store.rides)} rides loaded.")
    actions = {k: fn for k, _, fn in MENU}
    while True:
        print()
        for k, label, _ in MENU:
            print(f"  {paint('c', k)}  {label}")
        print(f"  {paint('c', '0')}  Exit")
        try:
            choice = input("\nChoose an option: ").strip()
            if choice == "0":
                print("Goodbye. Your data is saved.")
                return
            if choice in actions:
                actions[choice](store)
            else:
                print(paint("r", "  ! Pick a number from the menu."))
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye. Your data is saved.")
            return


if __name__ == "__main__":
    main()
