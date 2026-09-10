"""Zero-shot classification anchors (design doc §4.2, §4.3).

The anchor text IS the classifier — there is no other tunable parameter and no
labelled data (design doc §9). Each anchor is embedded once at cold start;
classification is nearest-anchor by cosine similarity.
"""

from __future__ import annotations

# Coarse taxonomy. Below COARSE_THRESHOLD (config.py), an article is
# "uncategorized" and excluded from clustering. Deliberately no `tech`
# category — see the design doc §4.2. Rewritten for Indian coverage from
# prd-new's US-worded anchors ("parliament", "United Nations", "olympic").
COARSE_ANCHORS: dict[str, str] = {
    "politics": (
        "Indian government policy, Parliament and Lok Sabha proceedings, state "
        "assembly elections, political parties and alliances, legislation and "
        "bills, judiciary rulings, ministers and chief ministers, campaigns and "
        "voting"
    ),
    "global": (
        "International affairs and geopolitics, foreign diplomacy and "
        "bilateral relations, the United Nations, cross-border military "
        "conflicts, global summits, trade agreements, foreign policy"
    ),
    "business": (
        "Financial markets and stock indices, Sensex and Nifty, RBI monetary "
        "policy and interest rates, corporate earnings, mergers and "
        "acquisitions, inflation and GDP, startups and funding, banking"
    ),
    "sports": (
        "Cricket matches and series, IPL, athletic competitions and "
        "tournaments, professional leagues, match scores, championships, "
        "player transfers, the Olympics"
    ),
    "culture": (
        "Bollywood and regional cinema, film reviews and box office, "
        "television and streaming, music, celebrity news, arts, literature, "
        "theatre, food and lifestyle"
    ),
}

# Detailed business sub-taxonomy (design doc §4.3). Only assigned to a cluster
# whose coarse category is "business" AND at least one member came from one of
# BUSINESS_ELIGIBLE_SOURCES — a cluster made only of general-paper articles
# keeps the coarse code, on the theory that general papers cover business
# generally and forcing a markets-vs-economy call would assert a precision the
# source does not have.
BUSINESS_ANCHORS: dict[str, str] = {
    "markets": (
        "Sensex and Nifty movements, equity trading, bonds, commodities, "
        "rupee exchange rates, IPOs, FII and DII flows, market outlook"
    ),
    "economy": (
        "Macroeconomic data, GDP growth, inflation and CPI, RBI monetary "
        "policy and repo rates, fiscal deficit, the union budget, trade "
        "balance, employment data"
    ),
    "companies": (
        "Corporate earnings and quarterly results, mergers and acquisitions, "
        "management changes, board decisions, expansion and capex, startup "
        "funding rounds"
    ),
    "portfolio": (
        "Equity research and stock recommendations, buy and sell calls, "
        "target prices, mutual fund performance, portfolio allocation, "
        "investment analysis"
    ),
    "personal_finance": (
        "Personal income tax, savings and fixed deposits, insurance, loans "
        "and EMIs, credit cards, retirement and pension planning, PPF and NPS"
    ),
}

# feed_source values (services/india-news-ingest's business.yaml `name:`
# fields, byte-for-byte — this is a cross-service contract, see this
# package's CLAUDE.md) that make a business cluster eligible for a detailed
# sub-category.
BUSINESS_ELIGIBLE_SOURCES: frozenset[str] = frozenset(
    {"Business Standard", "Economic Times", "Hindu BusinessLine"}
)

UNCATEGORIZED = "uncategorized"

# Total distinct source publications. Used as N_papers in the ranking formula
# (design doc §4.5) — fixed rather than derived, so a slow day for one outlet
# cannot inflate every other cluster's consensus term.
N_PAPERS = 5
