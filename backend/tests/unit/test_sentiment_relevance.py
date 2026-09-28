"""Unit tests: deterministic financial-relevance screening (relevance.py).

Cases are drawn from real stored NewsAPI titles (TCS/RELIANCE/INFY) plus
targeted synthetics. The contract under test:

- relevant  ⇔  company identity AND financial/business context, no excluded topic
- every verdict carries a machine-readable reason for auditability
- identical input ⇒ identical verdict (determinism)
"""

from app.agents.sentiment.relevance import (
    assess_relevance,
    company_identifiers,
    find_excluded_topic,
    find_financial_hit,
    find_identity_hit,
)
from app.data.universe.universe_config import get_universe_entry


def verdict(text, symbol, description=None):
    return assess_relevance(text, description, None, get_universe_entry(symbol))


# -- retained: genuinely company-financial -------------------------------------

def test_earnings_and_results_retained():
    assert verdict("TCS employees get 50-70% variable in Q1", "TCS").relevant
    assert verdict("TCS beats quarterly estimates", "TCS").relevant
    assert verdict("Infosys Q4 profit rises 7% on large deal wins", "INFY").relevant


def test_orders_and_deals_retained():
    v = verdict(
        "Tejas Networks shares zoom 13% after TCS's Rs 1,537-crore LOI for BSNL 4G rollout",
        "TCS",
    )
    assert v.relevant
    assert v.identity_hit == "TCS"
    v = verdict("L&T bags Rs 5,000 crore order for bullet train project", "LT")
    assert v.relevant
    assert v.identity_hit == "L&T"


def test_sector_move_naming_the_company_retained():
    v = verdict(
        "HCLTech, TCS, Infosys, other IT stocks rally up to 5%",
        "TCS",
        "IT stocks gain as analysts raise target price",
    )
    assert v.relevant
    v = verdict(
        "HCLTech, TCS, Infosys, other IT stocks rally up to 5%",
        "INFY",
        "IT stocks gain as analysts raise target price",
    )
    assert v.relevant


def test_market_wrap_naming_the_company_retained():
    assert verdict(
        "Market wrap: TCS, Tech Mahindra top gainers and losers on Nifty",
        "TCS",
    ).relevant


def test_partnership_announcement_retained():
    assert verdict(
        "Infosys brings enterprise context to CrowdStrike's AI security push",
        "INFY",
    ).relevant


def test_alias_matching():
    assert verdict("RIL announces record dividend payout", "RELIANCE").relevant
    assert verdict("SBI raises Rs 10,000 crore via infrastructure bonds", "SBIN").relevant
    assert verdict("HUL Q2 volumes grow, margins expand", "HINDUNILVR").relevant
    assert verdict("Airtel adds 5 million subscribers in August", "BHARTIARTL").relevant


def test_ticker_identity_with_financial_context():
    v = verdict("INFY falls on profit booking", "INFY")
    assert v.relevant and v.identity_hit == "INFY"


# -- rejected: sponsorships, anecdotes, tragedies -------------------------------

def test_sponsored_sport_rejected_despite_mention():
    for title in (
        "How to Watch the TCS Sydney Marathon 2026",
        "Notable Participants In The Sydney Marathon 2026",
        "TCS World 10K records broken in Bengaluru",
    ):
        v = verdict(title, "TCS")
        assert not v.relevant and v.reason == "excluded_topic", title


def test_career_anecdote_rejected():
    v = verdict("From TCS to Microsoft, techie details 6 things different", "TCS")
    assert not v.relevant and v.reason == "no_financial_context"


def test_tragedy_rejected():
    v = verdict("TCS engineer on way home dies after reversing earthmover rams bike", "TCS")
    assert not v.relevant and v.reason == "excluded_topic"


def test_sponsored_golf_and_retail_promo_rejected():
    # Brand acronym collisions in sport and retail flyers carry no signal.
    v = verdict("Jaipur golfer seals national title with dramatic birdie", "ITC")
    assert not v.relevant and v.reason == "excluded_topic"
    v = verdict(
        "Harbor Freight 4-Day Labor Day Sale: 20% Off ITC or Everyone 10% Off",
        "ITC",
    )
    assert not v.relevant and v.reason == "excluded_topic"
    # ...while a genuine percent-move headline is untouched.
    v = verdict("TCS shares fall 5% on weak sector outlook", "TCS")
    assert v.relevant


def test_common_noun_reliance_rejected():
    for title, description in (
        ("Anthropic evaluates in-house payments", "weighing reliance on Stripe for billing"),
        ("Banks see funding costs ease", "reducing banks' reliance on higher-cost deposits"),
        ("Solana app revenue surges", "Solana's reliance on Pump.fun highlights risks"),
    ):
        v = verdict(title, "RELIANCE", description)
        assert not v.relevant, title
        # lowercase common-noun use must not even register as identity
        assert v.reason in {"no_identity", "no_financial_context"}, (title, v.reason)


def test_capitalized_reliance_company_use_accepted():
    v = verdict("Reliance Q1 profit rises on retail and Jio growth", "RELIANCE")
    assert v.relevant and v.identity_hit == "Reliance"


def test_market_digest_without_mention_rejected():
    v = verdict("Sensex today: Nifty ends at 23,897 as crude keeps sentiment subdued", "INFY")
    assert not v.relevant and v.reason == "no_identity"
    v = verdict("Nifty IT jumps 3.5% as Nvidia results boost AI spend hopes", "TCS")
    assert not v.relevant and v.reason == "no_identity"


def test_two_letter_symbol_never_bare_matched():
    # "LT" collides constantly — only "L&T"/full name identify the company.
    assert find_identity_hit("LT Foods Q4 profit jumps", [("LT", False)]) is None
    assert find_identity_hit("L&T bags metro rail order", [("L&T", False)]) == "L&T"
    v = verdict("LT Foods Q4 profit jumps 20%", "LT")
    assert not v.relevant and v.reason == "no_identity"


def test_substring_name_and_whole_word_symbol():
    idents = company_identifiers(get_universe_entry("TCS"))
    assert find_identity_hit("Tata Consultancy Services wins deal", idents)
    assert find_identity_hit("switches and circuits", idents) is None


def test_former_affiliation_bio_line_rejected():
    # A Coforge story that name-drops an ex-SBI chairman is not SBI news.
    v = verdict(
        "Coforge chairman resigns after audit finds concerns in board evaluation",
        "SBIN",
        "Bhatt, who previously served as chairman of India's largest lender, "
        "State Bank of India, was appointed chair of Coforge's board in 2024",
    )
    assert not v.relevant and v.reason == "no_identity"
    # ...but genuine ex-dividend headlines keep working ("ex-" is not a marker).
    v = verdict("SBI goes ex-dividend tomorrow; record date fixed", "SBIN")
    assert v.relevant
    # And a direct leadership story still counts.
    v = verdict("Former SBI chief joins rival board", "SBIN")
    assert not v.relevant and v.reason == "no_identity"


# -- unit behavior ----------------------------------------------------------------

def test_find_helpers_return_matched_terms():
    assert find_financial_hit("Board declares record dividend") == "dividend"
    assert find_financial_hit("A quiet day at the office") is None
    assert find_excluded_topic("Sydney Marathon 2026 guide") == "marathon"
    assert find_excluded_topic("Q2 earnings beat estimates") is None


def test_verdicts_are_deterministic():
    kwargs = dict(
        title="TCS shares zoom 13% after large BSNL order win",
        description="The counter rallied as analysts raised target price",
        content=None,
        entry=get_universe_entry("TCS"),
    )
    first = assess_relevance(**kwargs)
    second = assess_relevance(**kwargs)
    assert first == second
    assert first.relevant and first.reason == "relevant"


# -- generated aliases: every stock works without curation --------------------
# Dynamic-style entries (no curated aliases) built inline so these tests never
# touch the shared universe registry.


def _dynamic(symbol, name):
    from app.domain.models.universe import UniverseEntry

    return UniverseEntry(
        symbol=symbol,
        name=name,
        exchange="NSE",
        ticker=f"{symbol}.NS",
        sector="Unknown",
        industry="Unknown",
    )


def _check(symbol, name, title, expected, description=None):
    v = assess_relevance(
        title,
        description or ("Market update: " + title),
        None,
        _dynamic(symbol, name),
    )
    assert v.relevant is expected, (symbol, title, v.reason, v.identity_hit)


def test_generated_aliases_reliance():
    from app.agents.sentiment.relevance import generated_aliases

    ids = dict((p.lower(), s) for p, s in generated_aliases(_dynamic("RELIANCE", "Reliance Industries")))
    # Full name non-strict; bare common noun stays strict.
    assert ids["reliance industries"] is False
    assert ids["reliance"] is True
    _check("RELIANCE", "Reliance Industries",
           "Reliance Industries shares jump on strong quarterly profit", True)
    _check("RELIANCE", "Reliance Industries",
           "banks reliance on deposits grows, says report on lending", False)


def test_generated_aliases_adanipower():
    from app.agents.sentiment.relevance import generated_aliases

    ids = [p for p, _ in generated_aliases(_dynamic("ADANIPOWER", "ADANI POWER LTD"))]
    assert "ADANI POWER" in ids  # first-two-words form, non-strict
    _check("ADANIPOWER", "ADANI POWER LTD",
           "Adani Power shares rise as group stocks rally on results", True)
    # Sister company must NOT match: "Adani" alone is never an alias.
    _check("ADANIPOWER", "ADANI POWER LTD",
           "Adani Enterprises wins port contract, shares gain", False)
    _check("ADANIPOWER", "ADANI POWER LTD",
           "Adani Power commissions 800 MW unit, shares gain on outlook", True)


def test_generated_aliases_tatamotors():
    _check("TATAMOTORS", "Tata Motors Ltd.",
           "Tata Motors launches new SUV; shares climb on strong demand", True)
    _check("TATAMOTORS", "Tata Motors Ltd.",
           "Tata Motors Q1 profit beats estimates", True)
    # Sister companies must NOT match.
    _check("TATAMOTORS", "Tata Motors Ltd.",
           "Tata Steel reports record profit for the quarter", False)
    _check("TATAMOTORS", "Tata Motors Ltd.",
           "Tata Power commissions solar plant, shares rise", False)


def test_generated_aliases_hdfcbank():
    _check("HDFCBANK", "HDFC Bank Limited",
           "HDFC Bank Q1 profit beats estimates, shares gain", True)
    # Sister company must NOT match.
    _check("HDFCBANK", "HDFC Bank Limited",
           "HDFC Life insurance premium collection rises", False)


def test_generated_aliases_zomato():
    from app.agents.sentiment.relevance import generated_aliases

    ids = dict((p.lower(), s) for p, s in generated_aliases(_dynamic("ZOMATO", "Zomato Limited")))
    assert ids["zomato"] is True  # single word stays strict (capitalized only)
    _check("ZOMATO", "Zomato Limited",
           "Zomato shares surge after strong quarterly results", True)
    _check("ZOMATO", "Zomato Limited",
           "zomato delivery late again, customers complain", False)


def test_generated_aliases_titan_strict():
    _check("TITAN", "Titan Company Limited",
           "Titan Company Q2 profit rises on jewellery demand", True)
    _check("TITAN", "Titan Company Limited",
           "the titan of industry fell from grace yesterday", False)


def test_curated_aliases_keep_priority():
    # Static RELIANCE keeps its curated strict "Reliance" first.
    ids = company_identifiers(get_universe_entry("RELIANCE"))
    first_reliance = next(s for s, _ in ids if s.lower() == "reliance")
    assert first_reliance == "Reliance"
    assert verdict("Reliance shares jump on strong results", "RELIANCE").relevant


def test_generated_ampersand_variants():
    from app.agents.sentiment.relevance import generated_aliases

    entry = _dynamic("XYZ", "Foo & Bar Limited")
    forms = [p for p, _ in generated_aliases(entry)]
    assert "Foo & Bar" in forms
    assert "Foo and Bar" in forms
    # "&" and "and" phrasings both identify the company.
    assert assess_relevance(
        "Foo & Bar reports strong quarterly profit", None, None, entry
    ).relevant
    assert assess_relevance(
        "Foo and Bar reports strong quarterly profit", None, None, entry
    ).relevant
    # ...but never without financial context.
    assert not assess_relevance(
        "Foo and Bar opens new office", "New branch in town", None, entry
    ).relevant


def test_generated_first_two_words_for_long_names():
    from app.agents.sentiment.relevance import generated_aliases

    entry = _dynamic("BHELXYZ", "Bharat Heavy Electricals Limited")
    forms = [p for p, _ in generated_aliases(entry)]
    assert "Bharat Heavy Electricals" in forms
    assert "Bharat Heavy" in forms
    assert assess_relevance(
        "Bharat Heavy shares jump on strong order inflows", None, None, entry
    ).relevant


def test_generated_allcaps_single_token_is_nonstrict():
    # Ticker-like single tokens (BHEL) match case-insensitively, unlike
    # common-noun words (Titan/Page), which stay strict.
    from app.agents.sentiment.relevance import generated_aliases

    ids = [p.lower() for p, _ in generated_aliases(_dynamic("BHEL", "Bharat Heavy Electricals"))]
    # Bare "bhel" is NOT generated (the internal symbol already covers it);
    # multi-word forms come from the name.
    assert "bhel" not in ids
    assert "bharat heavy electricals" in ids
    entry = _dynamic("BHEL", "Bharat Heavy Electricals")
    assert assess_relevance("BHEL bags large order, shares gain", None, None, entry).relevant
