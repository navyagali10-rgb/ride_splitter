"""NiceGUI web interface.  Run: python app_gui.py   then open http://localhost:8080"""
from __future__ import annotations

from datetime import date

from nicegui import app, ui

from core.exporter import export_file, write_error_log
from core.importer import import_csv_file, import_csv_text
from core.models import (CATEGORIES, CURRENCY, EXPORT_DIR, MODES, SAMPLE_CSV, Passenger, money)
from core.search import search_rides
from core.splitter import build_ride
from core.storage import Store
from core.summary import summarize
from core.validation import ValidationError, parse_number

store = Store()
EXPORT_DIR.mkdir(exist_ok=True)
app.add_static_files("/exports", str(EXPORT_DIR))

INK, ROAD, AMBER, TEAL, BRICK = "#1B2A41", "#2B3A55", "#F5A623", "#0E7C7B", "#C8553D"

HEAD = f"""
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<style>
  body {{ font-family: 'Source Sans 3', system-ui, sans-serif; background: #F4F6F7; color: {INK}; }}
  h1, h2, h3, .display {{ font-family: 'Sora', system-ui, sans-serif; letter-spacing: -0.01em; }}
  .lane {{ height: 0; border-top: 4px dashed {AMBER}; opacity: .9; }}
  .kpi {{ min-width: 170px; border-left: 5px solid {TEAL}; }}
  .kpi .v {{ font-family: 'Sora', sans-serif; font-size: 1.5rem; font-weight: 700; }}
  .warn-alert {{ border-left: 4px solid {BRICK}; }} .warn-warn {{ border-left: 4px solid {AMBER}; }}
  .warn-info {{ border-left: 4px solid #8A97A8; }}
  @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>
"""

HINTS = {"weighted": "Shares (e.g. 2)", "percent": "Percent", "fixed": "Fixed amount (blank = pays the rest)"}


@ui.page("/")
def index():
    ui.add_head_html(HEAD)
    ui.colors(primary=TEAL, secondary=INK, accent=AMBER, negative=BRICK)

    form = {"date": date.today().isoformat(), "route": "", "category": "commute",
            "fare": "", "extras": "", "mode": "equal", "payer": "", "notes": ""}
    pax = [{"name": "", "value": ""}, {"name": "", "value": ""}]
    filters = {"kw": "", "cat": "all", "open": False}
    refs = {}
    import_state = {"added": 0, "errors": [], "log": None}

    # ------------------------------------------------------------ helpers
    def current_ride():
        plist = []
        for p in pax:
            raw = p["value"].strip()
            value = None
            if form["mode"] != "equal" and raw:
                value = parse_number(raw, field=f"Value for {p['name'] or 'passenger'}")
            plist.append(Passenger(name=p["name"].strip(), value=value))
        names = [p.name for p in plist if p.name]
        payer = form["payer"] if form["payer"] in names else (names[0] if names else "")
        return build_ride(date=form["date"], route=form["route"], category=form["category"],
                          fare=form["fare"], extras=form["extras"], split_mode=form["mode"],
                          payer=payer, passengers=plist, notes=form["notes"])

    def sync_payer():
        names = [p["name"].strip() for p in pax if p["name"].strip()]
        if form["payer"] not in names:
            form["payer"] = names[0] if names else ""
        if "payer" in refs:
            refs["payer"].set_options(names, value=form["payer"] or None)

    def set_field(key):
        def handler(e):
            form[key] = e.value if e.value is not None else ""
            preview.refresh()
        return handler

    # ------------------------------------------------------------ header
    with ui.header(elevated=False).classes("items-center justify-between px-6 py-3").style(f"background:{INK}"):
        with ui.column().classes("gap-0"):
            ui.label("Ride Share Cost Splitter").classes("display text-white text-xl font-bold")
            ui.label("Split a shared ride fairly, to the last paisa.").classes("text-sm").style("color:#B8C2D0")
    ui.element("div").classes("lane w-full")

    with ui.tabs(on_change=lambda: (summary_view.refresh(), history.refresh())).classes("w-full bg-white") as tabs:
        t_new = ui.tab("New ride", icon="add_road")
        t_hist = ui.tab("History", icon="receipt_long")
        t_sum = ui.tab("Summary", icon="insights")
        t_io = ui.tab("Import / Export", icon="swap_vert")

    # ------------------------------------------------------------ new ride
    @ui.refreshable
    def rows():
        for i, p in enumerate(pax):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                ui.input("Name", value=p["name"], on_change=lambda e, i=i: (
                    pax[i].__setitem__("name", e.value or ""), sync_payer(), preview.refresh())).classes("grow")
                if form["mode"] != "equal":
                    ui.input(HINTS[form["mode"]], value=p["value"], on_change=lambda e, i=i: (
                        pax[i].__setitem__("value", e.value or ""), preview.refresh())).classes("w-48")
                ui.button(icon="close", on_click=lambda i=i: remove_passenger(i)).props("flat round dense").set_enabled(len(pax) > 2)

    def add_passenger():
        if len(pax) >= 10:
            ui.notify("A ride can have at most 10 passengers.", type="warning")
            return
        pax.append({"name": "", "value": ""})
        rows.refresh(); preview.refresh()

    def remove_passenger(i):
        pax.pop(i)
        sync_payer(); rows.refresh(); preview.refresh()

    def change_mode(e):
        form["mode"] = e.value
        rows.refresh(); preview.refresh()

    @ui.refreshable
    def preview():
        ui.label("Live split").classes("display text-lg font-bold")
        if not form["fare"].strip():
            ui.label("Enter a fare and at least two passenger names to see each share.").classes("text-grey-7")
            return
        try:
            ride = current_ride()
        except ValidationError as exc:
            ui.label(str(exc)).classes("text-negative font-semibold")
            return
        ui.label(f"Total {money(ride.total_cents)} paid by {ride.payer}").classes("text-grey-8")
        with ui.column().classes("w-full gap-1"):
            for p in ride.passengers:
                with ui.row().classes("w-full justify-between"):
                    ui.label(p.name)
                    ui.label(money(p.share_cents)).classes("font-bold")
        ui.separator()
        ui.label(f"Shares add up to {money(sum(p.share_cents for p in ride.passengers))}").classes("text-sm text-grey-7")

    def save():
        try:
            ride = current_ride()
        except ValidationError as exc:
            ui.notify(str(exc), type="negative")
            return
        store.add(ride)
        ui.notify(f"Saved ride #{ride.id}: {money(ride.total_cents)} split {len(ride.passengers)} ways.", type="positive")
        form.update({"route": "", "fare": "", "extras": "", "notes": "", "mode": "equal", "payer": ""})
        pax[:] = [{"name": "", "value": ""}, {"name": "", "value": ""}]
        new_ride.refresh(); history.refresh()

    @ui.refreshable
    def new_ride():
        with ui.row().classes("w-full gap-6 items-start no-wrap max-sm:flex-wrap"):
            with ui.card().classes("grow p-5 gap-3"):
                ui.label("Ride details").classes("display text-lg font-bold")
                with ui.row().classes("w-full gap-3"):
                    ui.input("Date", value=form["date"], on_change=set_field("date")).props("type=date").classes("w-44")
                    ui.select(list(CATEGORIES), label="Category", value=form["category"],
                              on_change=set_field("category")).classes("w-40")
                ui.input("Route or description", value=form["route"], on_change=set_field("route")).classes("w-full")
                with ui.row().classes("w-full gap-3"):
                    ui.input(f"Fare ({CURRENCY})", value=form["fare"], on_change=set_field("fare")).classes("grow")
                    ui.input(f"Extras: tip, toll, fees ({CURRENCY})", value=form["extras"], on_change=set_field("extras")).classes("grow")
                ui.label("How should it be split?").classes("text-sm text-grey-7")
                ui.toggle(list(MODES), value=form["mode"], on_change=change_mode)
                ui.separator()
                ui.label("Passengers").classes("display text-lg font-bold")
                rows()
                with ui.row().classes("w-full items-center gap-3"):
                    ui.button("Add passenger", icon="person_add", on_click=add_passenger).props("flat")
                    refs["payer"] = ui.select([], label="Paid the driver", on_change=lambda e: (
                        form.__setitem__("payer", e.value or ""), preview.refresh())).classes("w-52")
                ui.input("Notes (optional)", value=form["notes"], on_change=set_field("notes")).classes("w-full")
                ui.button("Save ride", icon="check", on_click=save).props("unelevated color=primary size=lg")
            with ui.card().classes("p-5 gap-2").style("min-width:300px; max-width:380px; width:100%"):
                preview()
        sync_payer()

    # ------------------------------------------------------------ history
    def open_ride(ride_id):
        r = store.get(ride_id)
        if not r:
            return
        with ui.dialog() as dlg, ui.card().classes("p-5 gap-2").style("min-width:360px"):
            ui.label(f"Ride #{r.id}: {r.route}").classes("display text-lg font-bold")
            ui.label(f"{r.date} · {r.category} · {r.split_mode} split · {money(r.total_cents)}").classes("text-grey-7")
            for p in r.passengers:
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    ui.label(p.name).classes("grow")
                    ui.label(money(p.share_cents)).classes("font-bold")
                    if p.name == r.payer:
                        ui.badge("paid the driver").props("color=secondary")
                    else:
                        ui.switch("Paid back", value=p.settled, on_change=lambda e, n=p.name: (
                            store.set_settled(ride_id, n, e.value), history.refresh(), summary_view.refresh()))
            with ui.row().classes("w-full justify-between pt-2"):
                ui.button("Delete ride", icon="delete", on_click=lambda: confirm_delete(ride_id, dlg)).props("flat color=negative")
                ui.button("Close", on_click=dlg.close).props("flat")
        dlg.open()

    def confirm_delete(ride_id, parent):
        with ui.dialog() as dlg, ui.card():
            ui.label("Delete this ride? This cannot be undone.")
            with ui.row():
                ui.button("Cancel", on_click=dlg.close).props("flat")
                def do():
                    store.delete(ride_id); dlg.close(); parent.close()
                    ui.notify("Ride deleted.", type="positive"); history.refresh(); summary_view.refresh()
                ui.button("Delete", on_click=do).props("color=negative")
        dlg.open()

    @ui.refreshable
    def history():
        found = search_rides(store.rides, filters["kw"], filters["cat"], unsettled_only=filters["open"])
        rows_ = [{"id": r.id, "date": r.date, "route": r.route, "category": r.category,
                  "total": money(r.total_cents), "mode": r.split_mode, "people": len(r.passengers),
                  "open": money(r.unsettled_cents) if r.unsettled_cents else "settled"} for r in found]
        cols = [{"name": k, "label": l, "field": k, "align": a, "sortable": True} for k, l, a in [
            ("id", "#", "left"), ("date", "Date", "left"), ("route", "Route", "left"), ("category", "Category", "left"),
            ("total", "Total", "right"), ("mode", "Split", "left"), ("people", "People", "right"), ("open", "Still owed", "right")]]
        ui.label(f"{len(found)} of {len(store.rides)} rides").classes("text-grey-7")
        if not found:
            ui.label("No rides match. Clear the filters, add a ride, or load the sample data from Import / Export.").classes("py-6")
            return
        table = ui.table(columns=cols, rows=rows_, row_key="id", pagination=10).classes("w-full")
        table.on("row-click", lambda e: open_ride(e.args[1]["id"]))
        table.props("flat bordered")

    # ------------------------------------------------------------ summary
    @ui.refreshable
    def summary_view():
        s = summarize(store.rides)
        if not s["count"]:
            ui.label("No rides yet. Add one on the New ride tab to see totals and trends.").classes("py-6")
            return
        with ui.row().classes("w-full gap-4"):
            for label, val in [("Rides", str(s["count"])), ("Total spent", money(s["total_cents"])),
                               ("Average fare", money(s["avg_fare_cents"])), ("Average share", money(s["avg_share_cents"])),
                               ("Still owed", money(s["unsettled_cents"]))]:
                with ui.card().classes("kpi p-4"):
                    ui.label(val).classes("v")
                    ui.label(label).classes("text-grey-7 text-sm")
        ui.label(s["trend"]).classes("text-grey-8")
        with ui.row().classes("w-full gap-6 items-start max-sm:flex-wrap"):
            with ui.card().classes("grow p-4").style("min-width:320px"):
                ui.label("Monthly spend").classes("display text-lg font-bold")
                ui.echart({
                    "grid": {"left": 60, "right": 16, "top": 20, "bottom": 30},
                    "xAxis": {"type": "category", "data": list(s["monthly"].keys())},
                    "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}"}},
                    "tooltip": {"trigger": "axis"},
                    "series": [{"type": "bar", "data": [round(c / 100, 2) for c in s["monthly"].values()],
                                "itemStyle": {"color": TEAL}}],
                }).classes("w-full h-64")
            with ui.card().classes("p-4").style("min-width:280px"):
                ui.label("Who owes the most").classes("display text-lg font-bold")
                if s["owes"]:
                    for name, c in list(s["owes"].items())[:6]:
                        with ui.row().classes("w-full justify-between"):
                            ui.label(name); ui.label(money(c)).classes("font-bold")
                else:
                    ui.label("Everyone is settled up.")
        ui.label("Warnings").classes("display text-lg font-bold pt-2")
        if not s["warnings"]:
            ui.label("Nothing to flag.")
        for w in s["warnings"]:
            with ui.card().classes(f"warn-{w['level']} p-3 w-full"):
                ui.label(w["text"])

    # ------------------------------------------------------------ import / export
    async def handle_upload(e):
        if hasattr(e, "file"):
            text = await e.file.text()
        else:
            text = e.content.read().decode("utf-8-sig", errors="replace")
        rides, errors = import_csv_text(text)
        store.add_many(rides)
        import_state.update(added=len(rides), errors=errors,
                            log=write_error_log(errors).name if errors else None)
        import_log.refresh(); history.refresh(); summary_view.refresh()
        ui.notify(f"Imported {len(rides)} rides, {len(errors)} rows rejected.", type="positive" if not errors else "warning")

    def load_sample():
        rides, errors = import_csv_file(SAMPLE_CSV)
        store.add_many(rides)
        import_state.update(added=len(rides), errors=errors, log=None)
        import_log.refresh(); history.refresh(); summary_view.refresh()
        ui.notify(f"Loaded {len(rides)} sample rides.", type="positive")

    def do_export(fmt):
        if not store.rides:
            ui.notify("Nothing to export yet.", type="warning")
            return
        ui.download(f"/exports/{export_file(store.rides, fmt).name}")

    @ui.refreshable
    def import_log():
        if not import_state["added"] and not import_state["errors"]:
            return
        ui.label(f"Last import: {import_state['added']} added, {len(import_state['errors'])} rejected").classes("font-semibold")
        if import_state["errors"]:
            ui.table(columns=[{"name": "row", "label": "CSV row", "field": "row", "align": "left"},
                              {"name": "error", "label": "Problem", "field": "error", "align": "left"}],
                     rows=import_state["errors"], row_key="row").classes("w-full").props("flat bordered dense")
            if import_state["log"]:
                ui.button("Download error log", icon="download",
                          on_click=lambda: ui.download(f"/exports/{import_state['log']}")).props("flat")

    # ------------------------------------------------------------ layout
    with ui.tab_panels(tabs, value=t_new).classes("w-full bg-transparent"):
        with ui.tab_panel(t_new):
            new_ride()
        with ui.tab_panel(t_hist):
            with ui.row().classes("w-full items-center gap-3"):
                ui.input("Search route, name, notes", on_change=lambda e: (filters.__setitem__("kw", e.value or ""), history.refresh())).props("clearable").classes("w-72")
                ui.select(["all", *CATEGORIES], value="all", label="Category",
                          on_change=lambda e: (filters.__setitem__("cat", e.value), history.refresh())).classes("w-40")
                ui.switch("Only unsettled", on_change=lambda e: (filters.__setitem__("open", e.value), history.refresh()))
            history()
        with ui.tab_panel(t_sum):
            summary_view()
        with ui.tab_panel(t_io):
            with ui.row().classes("w-full gap-6 items-start max-sm:flex-wrap"):
                with ui.card().classes("p-5 gap-3 grow"):
                    ui.label("Import rides from CSV").classes("display text-lg font-bold")
                    ui.label("Each row is checked on its own. Bad rows are listed with the reason and the rest are still imported.").classes("text-grey-7")
                    ui.upload(label="Drop a .csv file here", auto_upload=True, on_upload=handle_upload).props("accept=.csv flat bordered").classes("w-full")
                    ui.button("Load the 42 sample rides", icon="dataset", on_click=load_sample).props("flat")
                    import_log()
                with ui.card().classes("p-5 gap-3").style("min-width:280px"):
                    ui.label("Export a report").classes("display text-lg font-bold")
                    ui.button("Markdown summary", icon="description", on_click=lambda: do_export("markdown")).props("flat")
                    ui.button("Plain-text audit log", icon="fact_check", on_click=lambda: do_export("text")).props("flat")
                    ui.button("CSV of all rides", icon="table_view", on_click=lambda: do_export("csv")).props("flat")

    if store.notes:
        ui.notify(" ".join(store.notes), type="warning", multi_line=True, close_button=True)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="Ride Share Cost Splitter", port=8080, reload=False, favicon="🚕")
