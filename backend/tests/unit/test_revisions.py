"""Dedup layer L3b's rule (ADR-034), on headline pairs from the live archive."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gjurme.ingestion.normalize import normalize_key
from gjurme.ingestion.processor import is_headline_revision
from gjurme.ingestion.revisions import ArticleRow, plan_folds

REVISIONS = [
    # KOHA, 2026-11-15 21:30–21:31: an ending changed twice
    (
        "Zulfaj e quan skandaloze interpretimin e muzikës së këngës nacionaliste serbe",
        "Zulfaj e quan skandaloz interpretimin e muzikës së këngës nacionaliste serbe",
    ),
    (
        "Zulfaj e quan skandaloz interpretimin e muzikës së këngës nacionaliste serbe",
        "Zulfaj e quan skandal interpretimin e muzikës së këngës nacionaliste serbe",
    ),
    # Zëri, 2026-11-17 10:47: two words joined by a typo
    (
        "Kënga nacionalisteserbe në Bruksel, Gërvalla kërkon masa konkrete nga Komisioni Evropian",
        "Kënga nacionaliste serbe në Bruksel, Gërvalla kërkon masa konkrete nga Komisioni Evropian",
    ),
    # Zëri, 2026-11-16 10:15: a missing word added
    (
        "“Kosova është e Serbisë”, si u kënga nacionaliste serbe në Forumin e Zgjerimit të BE-së?",
        "“Kosova është e Serbisë”, si u përzgjodh kënga nacionaliste serbe në Forumin e "
        "Zgjerimit të BE-së?",
    ),
    # a letter typo and a label
    (
        "Qeveria miraton projektlijgin e ri për energjinë",
        "Qeveria miraton projektligjin e ri për energjinë",
    ),
    (
        "Qeveria miraton projektligjin e ri për energjinë",
        "VIDEO: Qeveria miraton projektligjin e ri për energjinë",
    ),
    # a case ending
    (
        "Kurti takon ambasadorin amerikan në Prishtinë sot",
        "Kurti takon ambasadorin amerikan në Prishtinën sot",
    ),
    # particles, a starred word, an article added (live archive, November 2026)
    (
        "Supremja ia rrëzon ankesën Blerim Isufajt për shkarkimin nga detyra e Kryeprokurorit",
        "Supremja ia rrëzon ankesën Blerim Isufajt për shkarkimin nga detyra të kryeprokurorit",
    ),
    (
        "Përplasen Tahiri e Haxhiu në Kuvend pas vrasjes së Arlindës, debatojnë për dorëheqjet",
        "Përplasen Tahiri e Haxhiu në Kuvend pas vr*sjes së Arlindës, debatojnë për dorëheqjet",
    ),
    (
        "Kryeprokurori i Shtetit zhvilloi vizitë zyrtare në Prokurorinë Themelore në Ferizaj",
        "Kryeprokurori i shtetit zhvilloi një vizitë zyrtare në Prokurorinë Themelore në Ferizaj",
    ),
]

DIFFERENT = [
    # numbers are content
    (
        "Aksident në Prishtinë, 3 të vdekur dhe disa të plagosur",
        "Aksident në Prishtinë, 5 të vdekur dhe disa të plagosur",
    ),
    (
        "Dy të arrestuar pas përleshjes në Ferizaj mbrëmë",
        "Tre të arrestuar pas përleshjes në Ferizaj mbrëmë",
    ),
    # live updates are new articles
    (
        "LIVE: Numërohen votat në qendrat e votimit në Kosovë",
        "LIVE: Numërohen votat në qendrat e numërimit në Kosovë",
    ),
    (
        "Zgjedhjet minutë pas minute: numërohen votat në Prishtinë",
        "Zgjedhjet minutë pas minute: numërohen votat në Prizren",
    ),
    # series
    ("Dosja e privatizimit të PTK-së, Pjesa 1", "Dosja e privatizimit të PTK-së, Pjesa 2"),
    (
        "Dosja e privatizimit të PTK-së, pjesa e parë",
        "Dosja e privatizimit të PTK-së, pjesa e dytë",
    ),
    ("Dosja e privatizimit të PTK-së, pjesa II", "Dosja e privatizimit të PTK-së, pjesa III"),
    # negation
    (
        "Kurti do të marrë pjesë në takimin e Brukselit",
        "Kurti nuk do të marrë pjesë në takimin e Brukselit",
    ),
    # another place, another person, another verb
    ("Zjarr i madh në Prizren, digjen disa shtëpi", "Zjarr i madh në Gjakovë, digjen disa shtëpi"),
    (
        "Kurti takon ambasadorin amerikan në Prishtinë",
        "Osmani takon ambasadorin amerikan në Prishtinë",
    ),
    ("Rriten çmimet e karburanteve në Kosovë sot", "Ulen çmimet e karburanteve në Kosovë sot"),
    (
        "Presidenti i Shqipërisë kritikon qeverinë sot",
        "Presioni i Shqipërisë kritikon qeverinë sot",
    ),
    # three words changed
    (
        "Kosova fiton ndaj Rumanisë në ndeshjen e sotme kualifikuese",
        "Kosova humb ndaj Zvicrës në ndeshjen e djeshme kualifikuese",
    ),
    # one outlet's look-alike articles in the live archive
    (
        "Bervenicë, dalja e votuesve deri në orën 11 krahasuar me vitin 2025 (Infografik)",
        "Bervenicë, dalja e votuesve deri në orën 13 krahasuar me vitin 2025 (Infografik)",
    ),
    (
        "Fatbardha Nikçi fiton çmimin e dytë në “Akordet e Kosovës”",
        "Troja Bicurri fiton çmimin e parë në “Akordet e Kosovës”",
    ),
    (
        'Vrasja e grave, drejtësia dhe lufta politike - sonte në "Konfront"',
        'Vrasja e grave, drejtësia dhe lufta politike - "Konfront"',
    ),
    (
        "Haxhiu nesër në vizitë zyrtare në Maqedoninë e Veriut",
        "Haxhiu në vizitë zyrtare në Maqedoninë e Veriut",
    ),
    (
        "Përplasen dy trena të shpejtësisë së lartë në Spanjë, të paktën 10 viktima",
        "Përplasen dy trena të shpejtësisë së lartë në Spanjë, të paktën 30 viktima",
    ),
    (
        "Live-Debat në Kuvend. Rama dhe Berisha përplasen për Buxhetin 2027",
        "Debat në Kuvend, Rama dhe Berisha përplasen për Buxhetin 2027",
    ),
    # short headlines are too generic to fold
    ("Moti për nesër", "Moti për sot"),
    ("Lajmet e mbrëmjes", "Lajmet e mëngjesit"),
]


@pytest.mark.parametrize(("a", "b"), REVISIONS)
def test_revisions_of_one_headline(a: str, b: str) -> None:
    assert is_headline_revision(normalize_key(a), normalize_key(b))
    assert is_headline_revision(normalize_key(b), normalize_key(a))


@pytest.mark.parametrize(("a", "b"), DIFFERENT)
def test_different_headlines(a: str, b: str) -> None:
    assert not is_headline_revision(normalize_key(a), normalize_key(b))
    assert not is_headline_revision(normalize_key(b), normalize_key(a))


def _row(i: int, source: str, title: str, minutes: float) -> ArticleRow:
    at = datetime(2026, 11, 15, 20, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    return ArticleRow(i, source, title, normalize_key(title), at, None, i)


def test_plan_folds_per_outlet_within_the_window() -> None:
    t = "Zulfaj e quan {} interpretimin e muzikës së këngës nacionaliste serbe"
    rows = [
        _row(1, "koha", t.format("skandaloze"), 0),
        _row(2, "koha", t.format("skandaloz"), 1),
        _row(3, "koha", t.format("skandal"), 1),
        _row(4, "zeri", t.format("skandaloz"), 2),  # another outlet: not a revision
        _row(5, "koha", t.format("skandaloz"), 60 * 4),  # outside the window: a new article
    ]
    plan = plan_folds(rows)
    assert plan.folds == {2: 1, 3: 1}
    assert plan.newest[1].id == 3
