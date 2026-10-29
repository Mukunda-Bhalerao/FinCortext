from datetime import date

from app.providers.upstox import parse_holding
from app.services import analyst as C
from app.services.planner import apply_custom

KNOWN = {"INFY", "RELIANCE", "TORNTPHARM", "ONGC", "NESTLEIND", "GOLD", "TCS"}
HELD = {"INFY", "RELIANCE", "TORNTPHARM"}
TODAY = date(2026, 10, 27)


def r(q: str) -> C.Route:
    return C.route(q, KNOWN, HELD, TODAY)


def test_amounts_years_and_monthly_parse():
    assert C.parse_target("Can I reach 50 lakh in 10 years adding 10k a month?") == 5_000_000
    assert C.parse_years("Can I reach 50 lakh in 10 years?", TODAY) == 10
    assert C.parse_years("1 crore by 2036", TODAY) == 10
    assert C.parse_monthly("adding 10k a month") == 10_000
    assert C.parse_monthly("with a SIP of 25,000") == 25_000
    assert C.parse_target("Rs 1.5 crore by 2040") == 15_000_000


def test_symbols_need_capitals_unless_already_in_the_plan():
    assert C.find_symbols("what about infy and gold", KNOWN, HELD) == ["INFY"]
    assert C.find_symbols("what about GOLD", KNOWN, HELD) == ["GOLD"]


def test_routes_scenarios():
    s = r("What if I drop RELIANCE and add ONGC?")
    assert s.tool == "scenario" and s.remove == ["RELIANCE"] and s.add == ["ONGC"]
    s = r("Replace RELIANCE with NESTLEIND")
    assert s.remove == ["RELIANCE"] and s.add == ["NESTLEIND"]
    s = r("What if INFY were 40%?")
    assert s.tool == "scenario" and s.weights == {"INFY": 0.4}
    s = r("Put 30% in TORNTPHARM")
    assert s.weights == {"TORNTPHARM": 0.3}


def test_routes_other_tools():
    assert r("Compare the objectives for me").tool == "compare"
    assert r("Why is INFY underperforming?").tool == "investigate"
    assert r("Why is infy down?").symbols == ["INFY"]
    g = r("Can I reach 50 lakh in 10 years adding 10k a month?")
    assert g.tool == "goal" and g.target == 5_000_000 and g.years == 10 and g.monthly == 10_000
    assert r("Switch to lower risk").objective == "lower_risk"
    assert r("What is the biggest risk?").tool == "general"


def test_custom_weights_fix_some_and_share_the_rest():
    w, note = apply_custom([0.5, 0.3, 0.2], ["A", "B", "C"], {"A": 0.2})
    assert abs(w[0] - 0.2) < 1e-12 and abs(w[1] - 0.48) < 1e-12 and abs(w[2] - 0.32) < 1e-12
    assert note is None
    w, note = apply_custom([0.5, 0.5], ["A", "B"], {"A": 0.9, "B": 0.6})
    assert abs(sum(w) - 1) < 1e-12 and note


def test_parse_broker_holding_adds_t1_and_keeps_gaps():
    h = parse_holding(
        {
            "instrument_token": "NSE_EQ|INE009A01021",
            "trading_symbol": "INFY",
            "quantity": 10,
            "t1_quantity": 2,
            "average_price": 0,
            "last_price": 1500,
        }
    )
    assert h.quantity == 12 and h.average_price is None and h.pnl is None
    assert h.instrument_key == "NSE_EQ|INE009A01021"


def test_candidates_can_be_added_in_lower_case():
    s = C.route("What if INFY were 15% and I add nestleind?", KNOWN, HELD, TODAY, {"NESTLEIND"})
    assert s.weights == {"INFY": 0.15} and s.add == ["NESTLEIND"]


def test_model_json_is_recovered_from_wrapped_output():
    from app.providers.ollama import _json_object

    assert _json_object('{"answer": "x"}') == {"answer": "x"}
    assert _json_object('Here you go:\n```json\n{"answer": "x"}\n```') == {"answer": "x"}
    assert _json_object("") is None and _json_object("[1, 2]") is None
