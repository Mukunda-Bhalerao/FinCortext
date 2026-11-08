import math
from datetime import date

from app.tools import ipo as I

# Row shapes as NSE publishes them (consolidated subscription table, issue information).
ACTIVE_CAT = [
    {"category": "Category", "noOfTotalMeant": "No. of times of total meant for the category"},
    {"category": "Qualified Institutional Buyers(QIBs)", "noOfTotalMeant": "70.55"},
    {"category": "Foreign Institutional Investors(FIIs)", "noOfTotalMeant": ""},
    {"category": "Non Institutional Investors", "noOfTotalMeant": "14.00"},
    {
        "category": "Non Institutional Investors(Bid amount of more than Ten Lakh Rupees)",
        "noOfTotalMeant": "15.89",
    },
    {
        "category": "Non Institutional Investors(Bid amount of more than Two Lakh Rupees upto Ten "
        "Lakh Rupees)",
        "noOfTotalMeant": "10.22",
    },
    {"category": "Retail Individual Investors(RIIs)", "noOfTotalMeant": "2.72"},
    {"category": "Employees", "noOfTotalMeant": "2.93"},
    {"category": "Total", "noOfTotalMeant": "22.19"},
]


def test_subscription_categories():
    s = I.parse_subscription(ACTIVE_CAT)
    assert s == {
        "qib": 70.55,
        "nii": 14.0,
        "nii_big": 15.89,
        "nii_small": 10.22,
        "retail": 2.72,
        "employee": 2.93,
        "total": 22.19,
    }


def test_text_fields():
    assert I.parse_date("04-NOV-2026") == date(2026, 11, 4)
    assert I.parse_date("2026-10-28") == date(2026, 10, 28)
    assert I.parse_date("-") is None
    assert I.parse_band("Rs.1065 to Rs.1119") == (1065, 1119)
    assert I.parse_band("402") == (402, 402)
    assert I.parse_price("    82") == 82
    assert I.parse_price("-") is None
    assert I.parse_lot("12 Equity Shares and in multiples thereof") == 12
    assert I.issue_period("21-Oct-2026 to 23-Oct-2026") == (date(2026, 10, 21), date(2026, 10, 23))
    info = I.parse_issue_info(
        [
            {"title": "Book Running Lead Managers", "value": '"Kotak'},
            {"title": None, "value": "Morgan Stanley"},
            {"title": "Red Herring Prospectus", "value": "https://nsearchives/RHP.zip"},
        ]
    )
    assert info["Book Running Lead Managers"] == "Kotak\nMorgan Stanley"


def _past(qib, gain, i=0):
    return I.PastIssue(f"S{i}", date(2026, 1, 1), qib, qib, gain)


def test_odds_come_from_the_matching_demand_band():
    history = [_past(80 + i, 0.2 + i / 100, i) for i in range(9)] + [_past(60, -0.05, 99)]
    history += [_past(2, -0.1, 200 + i) for i in range(4)]
    o = I.odds_for(history, qib=120, total=None)
    assert o is not None and o.bucket == "50x or more" and o.sample == 10
    assert math.isclose(o.above_issue, 0.9)
    assert o.worst == -0.05
    # Too few comparable issues in the 1x-10x band: no odds rather than a weak guess.
    assert I.odds_for(history, qib=3, total=None) is None


def test_mood_counts_recent_listings_only():
    today = date(2026, 11, 7)
    listings = [
        (date(2026, 11, 3), 0.65, 0.57),
        (date(2026, 10, 28), 0.21, 0.26),
        (date(2026, 10, 22), -0.05, None),
        (date(2026, 8, 1), 0.5, 0.1),
    ]
    m = I.mood(listings, today, 30)
    assert m.listed == 3
    assert math.isclose(m.above_issue_at_open, 2 / 3)
    assert m.median_listing_gain == 0.21
    assert m.above_issue_now == 1.0
