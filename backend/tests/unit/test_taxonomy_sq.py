"""The Albanian side of the topic taxonomy, which the site shows by default."""

from gjurme import taxonomy


def test_every_topic_has_an_albanian_description() -> None:
    assert set(taxonomy.DESCRIPTION_SQ) == set(taxonomy.TOPIC_SLUGS)
    assert all(d.endswith(".") for d in taxonomy.DESCRIPTION_SQ.values())


def test_albanian_name_by_slug_falls_back_for_an_unknown_topic() -> None:
    assert taxonomy.name_sq("elections") == "Zgjedhje"
    assert taxonomy.name_sq("retired_topic", "Retired") == "Retired"
    assert taxonomy.name_sq(None) is None
