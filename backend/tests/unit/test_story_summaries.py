"""Story summaries: nothing stored that the reports do not say."""

from __future__ import annotations

import json

import pytest

from gjurme.stories.summaries import InvalidSummaryError, parse_summary, ungrounded

REPORTS = """Haga shpall sot aktgjykimin ndaj Thaçit dhe të tjerëve për pengim të drejtësisë
Dhomat e Specializuara të Kosovës në Hagë shpallin aktgjykimin ndaj Hashim Thaçit dhe tre të
tjerëve. Prokuroria kërkoi 4 vjet burg.
Thaçi dënohet me 3 vjet burg, reagon Presidenca e Kosovës"""


def _answer(
    sq: str, en: str = "The court in The Hague sentenced Thaçi to 3 years in prison."
) -> str:
    return json.dumps({"summary_sq": sq, "summary_en": en}, ensure_ascii=False)


def test_a_summary_of_the_reports_is_kept() -> None:
    sq = (
        "Dhomat e Specializuara në Hagë shpallën aktgjykimin ndaj Hashim Thaçit për pengim "
        "të drejtësisë. Ai u dënua me 3 vjet burg, ndërsa prokuroria kërkoi 4 vjet."
    )
    assert ungrounded(sq, REPORTS) == []
    assert parse_summary(_answer(sq), REPORTS)[0] == sq


def test_a_name_or_number_the_reports_do_not_have_is_refused() -> None:
    invented = (
        "Gjykata në Hagë dënoi Hashim Thaçin me 3 vjet burg. Vendimin e komentoi edhe "
        "Albin Kurti, i cili tha se do ta respektojë."
    )
    assert ungrounded(invented, REPORTS) == ["Albin", "Kurti"]
    with pytest.raises(InvalidSummaryError, match="not in the reports: Albin, Kurti"):
        parse_summary(_answer(invented), REPORTS)
    wrong_number = "Gjykata në Hagë dënoi Hashim Thaçin me 5 vjet burg për pengim të drejtësisë."
    assert ungrounded(wrong_number, REPORTS) == ["5"]
    with pytest.raises(InvalidSummaryError, match="numbers not in the reports: 7"):
        parse_summary(
            _answer("Gjykata në Hagë dënoi Thaçin me 3 vjet burg për pengim të drejtësisë.",
                    "The court in The Hague sentenced Thaçi to 7 years in prison."),
            REPORTS,
        )  # fmt: skip


def test_a_sentence_may_start_with_any_capital() -> None:
    sq = "Sot u shpall aktgjykimi ndaj Thaçit. Prokuroria kërkoi 4 vjet burg për pengim."
    assert ungrounded(sq, REPORTS) == []


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "no JSON object"),
        ("not json", "no JSON object"),
        ('{"summary_sq": "shkurt", "summary_en": "short"}', "summary_sq length"),
        ('{"summary_en": "The court sentenced Thaçi to three years in prison."}', "summary_sq"),
    ],
)
def test_unusable_answers(raw: str, reason: str) -> None:
    with pytest.raises(InvalidSummaryError, match=reason):
        parse_summary(raw, REPORTS)


def test_fenced_json_is_read() -> None:
    sq = "Dhomat e Specializuara në Hagë dënuan Hashim Thaçin me 3 vjet burg për pengim."
    assert parse_summary("```json\n" + _answer(sq) + "\n```", REPORTS)[0] == sq
