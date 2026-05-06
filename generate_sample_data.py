import random
import string
import pandas as pd
from datetime import datetime, timedelta

random.seed(42)

END_DATE   = datetime(2026, 5, 5)
START_DATE = END_DATE - timedelta(days=180)   # 2025-11-06

LOCATION      = "OptSpot Car Wash - Main St"
NUM_CUSTOMERS = 400

ACTIONS        = ["CHECKIN", "BONUS", "REDEEM", "REFERRAL"]
ACTION_WEIGHTS = [75, 12, 10, 3]

POINTS_MAP = {
    "CHECKIN":  lambda: 10,
    "BONUS":    lambda: random.choice([25, 50]),
    "REFERRAL": lambda: 100,
    "REDEEM":   lambda: random.choice([-50, -100]),
}

# (start_min, end_min, weight_factor) — operating hours 7 AM–9 PM only
TIME_BLOCKS = [
    ( 7 * 60,  9 * 60, 1.0),   # 7–9 AM   morning commuters
    ( 9 * 60, 11 * 60, 0.7),   # 9–11 AM  mid-morning quiet
    (11 * 60, 13 * 60, 1.5),   # 11 AM–1 PM lunch peak
    (13 * 60, 16 * 60, 0.9),   # 1–4 PM   afternoon
    (16 * 60, 19 * 60, 2.0),   # 4–7 PM   evening rush
    (19 * 60, 21 * 60, 1.2),   # 7–9 PM   after-dinner
]
# Weight each block by its duration so wider blocks get proportional share
TIME_BLOCK_WEIGHTS = [(end - start) * w for start, end, w in TIME_BLOCKS]

# Mon(0)–Sun(6)
DOW_WEIGHTS = [1.0, 1.0, 1.0, 1.0, 1.3, 1.8, 1.4]

# Pre-compute full date pool once
all_dates        = [START_DATE.date() + timedelta(days=i) for i in range(181)]
date_dow_weights = [DOW_WEIGHTS[d.weekday()] for d in all_dates]


def rand_time_of_day():
    block              = random.choices(TIME_BLOCKS, weights=TIME_BLOCK_WEIGHTS)[0]
    start_min, end_min, _ = block
    minute             = random.randint(start_min, end_min - 1)
    h, m               = divmod(minute, 60)
    s                  = random.randint(0, 59)
    return f"{h:02d}:{m:02d}:{s:02d}"


def rand_date_after(join_date):
    """Random date >= join_date, weighted by day of week."""
    avail   = [(d, DOW_WEIGHTS[d.weekday()]) for d in all_dates if d >= join_date]
    dates_  = [d for d, _ in avail]
    weights = [w for _, w in avail]
    return random.choices(dates_, weights=weights)[0]


def rand_visit_count():
    tier = random.choices(
        ["one_and_done", "regular", "loyal", "vip"],
        weights=[50, 30, 15, 5],
    )[0]
    return {
        "one_and_done": random.randint(1, 2),
        "regular":      random.randint(3, 7),
        "loyal":        random.randint(8, 15),
        "vip":          random.randint(16, 30),
    }[tier]


def rand_plate():
    letters = "".join(random.choices(string.ascii_uppercase, k=3))
    return letters + f"{random.randint(0, 9999):04d}"


def rand_mobile():
    return f"5550{random.randint(0, 999999):06d}"


# ── build unique customers with staggered join dates ──────────────────────────

customers    = []
used_mobiles = set()
used_plates  = set()

for _ in range(NUM_CUSTOMERS):
    while True:
        mobile = rand_mobile()
        if mobile not in used_mobiles:
            used_mobiles.add(mobile)
            break
    while True:
        plate = rand_plate()
        if plate not in used_plates:
            used_plates.add(plate)
            break
    # Uniform join date → ~67 new customers per month for even cohort spread
    join_date = all_dates[random.randint(0, len(all_dates) - 1)]
    customers.append({"mobile": mobile, "plate": plate, "join_date": join_date})

# ── generate visit rows ───────────────────────────────────────────────────────

rows = []

for customer in customers:
    join_date = customer["join_date"]
    n_visits  = rand_visit_count()

    events = []
    for _ in range(n_visits):
        visit_date = rand_date_after(join_date)
        events.append({
            "date":   visit_date.strftime("%Y-%m-%d"),
            "time":   rand_time_of_day(),
            "action": random.choices(ACTIONS, weights=ACTION_WEIGHTS)[0],
        })

    events.sort(key=lambda x: (x["date"], x["time"]))

    running_total = 0
    for event in events:
        points        = POINTS_MAP[event["action"]]()
        running_total = max(0, running_total + points)
        rows.append({
            "Location":       LOCATION,
            "Mobile":         customer["mobile"],
            "Action":         event["action"],
            "Date":           event["date"],
            "Time":           event["time"],
            "Points Awarded": points,
            "Total Points":   running_total,
            "License Plate":  customer["plate"],
        })

df = (
    pd.DataFrame(rows)
    .sort_values(["Date", "Time"])
    .reset_index(drop=True)
)

df.to_csv("sample_data.csv", index=False)
print(f"Generated {len(df)} rows across {NUM_CUSTOMERS} customers → sample_data.csv")
