"""GitHub OAuth account linking: state lifecycle + link storage — no network."""

from datetime import datetime, timedelta, timezone

from app.identity import user_links


def test_state_roundtrip_is_single_use():
    state = user_links.create_state("discord-1")
    assert user_links.consume_state(state) == "discord-1"
    assert user_links.consume_state(state) is None  # no reuse


def test_unknown_state_rejected():
    assert user_links.consume_state("made-up") is None


def test_expired_state_rejected():
    state = user_links.create_state("discord-1")
    later = datetime.now(timezone.utc) + timedelta(minutes=11)
    assert user_links.consume_state(state, now=later) is None


def test_link_mapping_and_signout():
    user_links.link("monologg", "discord-1")
    user_links.link("other", "discord-2")
    assert user_links.mapping() == {"monologg": "discord-1", "other": "discord-2"}
    # relinking replaces
    user_links.link("monologg", "discord-9")
    assert user_links.mapping()["monologg"] == "discord-9"
    # signout removes all links for that Discord user and returns the list of logins
    assert user_links.unlink_discord("discord-9") == ["monologg"]
    assert user_links.unlink_discord("discord-9") == []
    assert "monologg" not in user_links.mapping()


def test_config_users_is_fallback_for_mentions():
    from app.identity import mentions

    config = {"users": {"monologg": "from-config", "config-only": "111"}}
    user_links.link("monologg", "from-oauth")
    merged = mentions.user_mapping(config)
    assert merged["monologg"] == "from-oauth"  # signin link wins over config
    assert merged["config-only"] == "111"
