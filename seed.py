"""Generate demo data.  python seed.py            -> writes data/sample_rides.csv/.json and data/sample_bad.csv
                         python seed.py --install  -> also loads the sample into data/rides.json
"""
import json
import random
import sys
from datetime import date, timedelta

from core.exporter import to_csv
from core.importer import import_csv_text
from core.models import DATA_FILE
from core.storage import Store

random.seed(59)
TODAY = date.today()
NAMES = ["Asha", "Ben", "Chitra", "Dev", "Esha", "Farid", "Gita", "Harsh", "Isha", "Jay"]
ROUTES = {
    "commute": ["Medchal to Hitech City", "Kompally to Gachibowli", "Secunderabad to Madhapur"],
    "airport": ["Home to RGIA Airport", "RGIA Airport to Kukatpally", "Begumpet to RGIA Airport"],
    "event": ["Hitex Expo return trip", "Ramoji Film City day trip", "Stadium match night"],
    "leisure": ["Necklace Road dinner", "Charminar evening", "Shamirpet weekend drive"],
    "office": ["Client visit Banjara Hills", "Team offsite Shamshabad", "Vendor meeting Uppal"],
    "other": ["Hospital drop", "Railway station pickup", "Late night return"],
}


def d(days_ago):
    return (TODAY - timedelta(days=days_ago)).isoformat()


# date, route, category, fare, extras, mode, payer, passengers, settled, notes
rows = [
    # boundary and edge cases first
    [d(3), "Tiny hop", "other", "0.01", "", "equal", "Asha", "Asha;Ben;Chitra", "", "Smallest possible fare, 3 people"],
    [d(5), "Airport charter, full cab", "airport", "50000.00", "0", "equal", "Dev",
     "Dev;Asha;Ben;Chitra;Esha;Farid;Gita;Harsh;Isha;Jay", "Asha;Ben", "Maximum fare, 10 passengers"],
    [d(8), "Three-way split", "leisure", "100.00", "", "percent", "Gita", "Gita:33.33;Harsh:33.33;Isha:33.34", "", "Percent that cannot divide evenly"],
    [d(12), "Fixed amounts, one covers rest", "office", "900.00", "60.00", "fixed", "Jay", "Jay;Asha:250;Ben:300", "", "Blank amount = pays the remainder"],
    [d(15), "Everyone fixed", "event", "600.00", "", "fixed", "Esha", "Esha:200;Farid:150;Dev:250", "Farid", "Fixed amounts add up exactly"],
    [d(18), "Longer ride gets more", "commute", "480.00", "", "weighted", "Chitra", "Chitra:1.5;Ben:1;Harsh:0.5", "", "Fractional weights"],
    [d(21), "Surge pricing night", "event", "4400.00", "950.00", "equal", "Farid", "Farid;Gita;Dev;Esha", "", "High total, triggers warning"],
    [d(26), "Toll-heavy highway run", "other", "300.00", "150.00", "equal", "Ben", "Ben;Asha", "Asha", "Extras over 30% of fare"],
    [d(110), "Old trip, never repaid", "leisure", "840.00", "", "equal", "Isha", "Isha;Jay;Harsh", "", "Stale unsettled balance"],
]
kinds = ["equal", "equal", "weighted", "percent", "fixed"]
while len(rows) < 42:
    age = random.randint(1, 150)
    cat = random.choice(list(ROUTES))
    k = random.randint(2, 5)
    crew = random.sample(NAMES, k)
    mode = random.choice(kinds)
    fare = {"airport": random.randint(900, 2600), "event": random.randint(500, 1800)}.get(cat, random.randint(120, 900))
    extras = random.choice(["", "", "20.00", "40.00", "60.00", "100.00"])
    if mode == "equal":
        pax = ";".join(crew)
    elif mode == "weighted":
        pax = ";".join(f"{n}:{random.choice([1, 1, 2, 3])}" for n in crew)
    elif mode == "percent":
        cuts = sorted(random.sample(range(5, 95, 5), k - 1))
        parts = [b - a for a, b in zip([0] + cuts, cuts + [100])]
        pax = ";".join(f"{n}:{p}" for n, p in zip(crew, parts))
    else:
        pax = ";".join([crew[0]] + [f"{n}:{random.choice([50, 75, 100])}" for n in crew[1:]])
        if (fare + (float(extras) if extras else 0)) < 100 * (k - 1):
            mode, pax = "equal", ";".join(crew)
    payer = random.choice(crew)
    settled = ";".join(n for n in crew if age > 21 and random.random() < 0.97) if age > 21 else ""
    rows.append([d(age), random.choice(ROUTES[cat]), cat, f"{fare:.2f}", extras, mode, payer, pax, settled, ""])

import csv, io
buf = io.StringIO()
w = csv.writer(buf, lineterminator="\n")
w.writerow(["date", "route", "category", "fare", "extras", "split_mode", "payer", "passengers", "settled", "notes"])
w.writerows(rows)
rides, errors = import_csv_text(buf.getvalue())
assert not errors, errors
rides.sort(key=lambda r: r.date)
for i, r in enumerate(rides, 1):
    r.id = i

with open("data/sample_rides.csv", "w", encoding="utf-8", newline="") as fh:
    fh.write(to_csv(rides))
with open("data/sample_rides.json", "w", encoding="utf-8") as fh:
    json.dump({"version": 1, "rides": [r.to_dict() for r in rides]}, fh, indent=2, ensure_ascii=False)

bad = """date,route,category,fare,extras,split_mode,payer,passengers,settled,notes
%s,Valid ride,commute,250,,equal,Asha,Asha;Ben,,ok
%s,Negative fare,commute,-40,,equal,Asha,Asha;Ben,,
%s,Text fare,commute,abc,,equal,Asha,Asha;Ben,,
2999-01-01,Future date,commute,100,,equal,Asha,Asha;Ben,,
%s,One passenger,commute,100,,equal,Asha,Asha,,
%s,Percent off,commute,100,,percent,Asha,Asha:60;Ben:50,,
%s,Duplicate names,commute,100,,equal,Asha,Asha;asha,,
%s,Fixed too big,commute,100,,fixed,Asha,Asha:80;Ben:80,,
%s,Unknown payer,commute,100,,equal,Zed,Asha;Ben,,
%s,Bad category,teleport,100,,equal,Asha,Asha;Ben,,
""" % tuple([d(2)] * 9)
open("data/sample_bad.csv", "w", encoding="utf-8").write(bad)

if "--install" in sys.argv:
    store = Store(DATA_FILE)
    store.rides = []
    store.add_many(rides)
print(f"Wrote {len(rides)} sample rides.")
