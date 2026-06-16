"""Tests for Telegram movie-monitor dry-run inline buttons."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms import telegram as telegram_mod
from gateway.platforms.telegram import TelegramAdapter


class _Button:
    def __init__(self, text, callback_data=None, url=None):
        self.text = text
        self.callback_data = callback_data
        self.url = url


class _Markup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard


@pytest.fixture(autouse=True)
def _fake_buttons(monkeypatch):
    monkeypatch.setattr(telegram_mod, "InlineKeyboardButton", _Button)
    monkeypatch.setattr(telegram_mod, "InlineKeyboardMarkup", _Markup)


@pytest.fixture
def adapter(monkeypatch):
    config = PlatformConfig(enabled=True, token="test-token")
    instance = TelegramAdapter(config)
    instance._bot = AsyncMock()
    monkeypatch.setattr(instance, "_is_callback_user_authorized", lambda *a, **k: True)
    return instance


def _query(data, markup):
    query = MagicMock()
    query.data = data
    query.from_user = SimpleNamespace(id="777", first_name="Adrien")
    query.message = SimpleNamespace(
        chat_id=-1003940719735,
        chat=SimpleNamespace(type="supergroup"),
        message_thread_id=1692,
        text="🎬 Demo deals",
        reply_markup=markup,
    )
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    return query


def _base_markup():
    return _Markup([
        [
            _Button("Dune: Part Two", callback_data="mv:sel:1725365997"),
            _Button("Poor Things", callback_data="mv:sel:646332703"),
        ],
        [
            _Button("Asteroid City", callback_data="mv:sel:1686832433"),
            _Button("Arrival", callback_data="mv:sel:1163659233"),
        ],
    ])


@pytest.mark.asyncio
async def test_select_movie_expands_action_row(adapter):
    query = _query("mv:sel:1725365997", _base_markup())
    context = SimpleNamespace(bot=AsyncMock())

    await adapter._handle_movie_monitor_callback(
        query,
        query.data,
        context,
        query_chat_id=-1003940719735,
        query_chat_type="supergroup",
        query_thread_id=1692,
        query_user_name="Adrien",
    )

    query.answer.assert_called_once()
    assert "Dune" in query.answer.call_args.kwargs["text"]
    sent_markup = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
    assert sent_markup.inline_keyboard[0][0].text.startswith("▸ Dune")
    action_row = sent_markup.inline_keyboard[1]
    assert action_row[0].text == "🍿 Buy on Apple"
    assert action_row[0].url == "https://itunes.apple.com/us/movie/id1725365997?uo=4"
    assert action_row[1].text == "✅ Bought"
    assert action_row[1].callback_data == "mv:bought:1725365997"


@pytest.mark.asyncio
async def test_bought_marks_movie_and_sends_dry_run_ack(adapter, monkeypatch):
    recorded = []
    monkeypatch.setattr(
        adapter,
        "_record_movie_monitor_dry_run_event",
        lambda **kwargs: recorded.append(kwargs),
    )
    expanded = _Markup([
        [
            _Button("▸ Dune: Part Two", callback_data="mv:sel:1725365997"),
            _Button("Poor Things", callback_data="mv:sel:646332703"),
        ],
        [
            _Button("🍿 Buy on Apple", url="https://itunes.apple.com/us/movie/id1725365997?uo=4"),
            _Button("✅ Bought", callback_data="mv:bought:1725365997"),
        ],
    ])
    query = _query("mv:bought:1725365997", expanded)
    bot = AsyncMock()
    context = SimpleNamespace(bot=bot)

    await adapter._handle_movie_monitor_callback(
        query,
        query.data,
        context,
        query_chat_id=-1003940719735,
        query_chat_type="supergroup",
        query_thread_id=1692,
        query_user_name="Adrien",
    )

    assert recorded == [{
        "action": "bought",
        "track_id": "1725365997",
        "title": "Dune: Part Two",
        "user_name": "Adrien",
    }]
    sent_markup = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
    assert len(sent_markup.inline_keyboard) == 1
    assert sent_markup.inline_keyboard[0][0].text.startswith("✓ Dune")
    bot.send_message.assert_called_once()
    assert "Letterboxd not touched" in bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_movie_buttons_are_authorized_fail_closed(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "_is_callback_user_authorized", lambda *a, **k: False)
    query = _query("mv:sel:1725365997", _base_markup())
    context = SimpleNamespace(bot=AsyncMock())

    await adapter._handle_movie_monitor_callback(
        query,
        query.data,
        context,
        query_chat_id=-1003940719735,
        query_chat_type="supergroup",
        query_thread_id=1692,
        query_user_name="Adrien",
    )

    assert "not authorized" in query.answer.call_args.kwargs["text"]
    query.edit_message_reply_markup.assert_not_called()


def _director_markup():
    return _Markup([
        [
            _Button("Dune: Part Three", callback_data="dc:sel:c0"),
            _Button("Bugonia", callback_data="dc:sel:c1"),
        ],
    ])


@pytest.fixture
def director_state(tmp_path, monkeypatch):
    candidates_path = tmp_path / "director_candidates.json"
    state_path = tmp_path / "director_state.json"
    events_path = tmp_path / "dryrun_events.jsonl"
    candidates_path.write_text(json.dumps({
        "candidates": [
            {
                "id": "c0",
                "letterboxd": {
                    "title": "Dune: Part Three",
                    "year": 2026,
                    "slug": "dune-part-three",
                    "url": "https://letterboxd.com/film/dune-part-three/",
                },
                "director": {"slug": "denis-villeneuve", "name": "Denis Villeneuve"},
                "threshold": 4.99,
            },
            {
                "id": "c1",
                "letterboxd": {
                    "title": "Bugonia",
                    "year": 2025,
                    "slug": "bugonia",
                    "url": "https://letterboxd.com/film/bugonia/",
                },
                "director": {"slug": "yorgos-lanthimos", "name": "Yorgos Lanthimos"},
                "threshold": 4.99,
            },
        ]
    }), encoding="utf-8")
    monkeypatch.setattr(
        TelegramAdapter,
        "_director_state_paths",
        staticmethod(lambda: (candidates_path, state_path, events_path)),
    )
    return candidates_path, state_path, events_path


@pytest.mark.asyncio
async def test_select_director_candidate_expands_action_row(adapter, director_state):
    query = _query("dc:sel:c0", _director_markup())

    await adapter._handle_director_candidate_callback(
        query,
        query.data,
        query_chat_id=-1003940719735,
        query_chat_type="supergroup",
        query_thread_id=1692,
        query_user_name="Adrien",
    )

    query.answer.assert_called_once()
    sent_markup = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
    assert sent_markup.inline_keyboard[0][0].text.startswith("▸ Dune")
    action_row = sent_markup.inline_keyboard[1]
    assert action_row[0].text == "➕ Add to LB"
    assert action_row[0].url == "https://letterboxd.com/film/dune-part-three/"
    assert action_row[1].callback_data == "dc:track:c0"
    assert action_row[2].callback_data == "dc:ignore:c0"


@pytest.mark.asyncio
async def test_director_track_records_price_only_state(adapter, director_state):
    _candidates_path, state_path, events_path = director_state
    expanded = _Markup([
        [_Button("▸ Dune: Part Three", callback_data="dc:sel:c0")],
        [
            _Button("➕ Add to LB", url="https://letterboxd.com/film/dune-part-three/"),
            _Button("⏱ Track price", callback_data="dc:track:c0"),
            _Button("🚫 Ignore", callback_data="dc:ignore:c0"),
        ],
    ])
    query = _query("dc:track:c0", expanded)

    await adapter._handle_director_candidate_callback(
        query,
        query.data,
        query_chat_id=-1003940719735,
        query_chat_type="supergroup",
        query_thread_id=1692,
        query_user_name="Adrien",
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["tracked_movies"]["dune-part-three"]["director_slug"] == "denis-villeneuve"
    assert "dune-part-three" not in state["ignored_movies"]
    assert "director_track" in events_path.read_text(encoding="utf-8")
    sent_markup = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
    assert sent_markup.inline_keyboard[0][0].text.startswith("⏱ Dune")


@pytest.mark.asyncio
async def test_director_ignore_records_movie_ignore(adapter, director_state):
    _candidates_path, state_path, events_path = director_state
    expanded = _Markup([
        [_Button("▸ Bugonia", callback_data="dc:sel:c1")],
        [
            _Button("➕ Add to LB", url="https://letterboxd.com/film/bugonia/"),
            _Button("⏱ Track price", callback_data="dc:track:c1"),
            _Button("🚫 Ignore", callback_data="dc:ignore:c1"),
        ],
    ])
    query = _query("dc:ignore:c1", expanded)

    await adapter._handle_director_candidate_callback(
        query,
        query.data,
        query_chat_id=-1003940719735,
        query_chat_type="supergroup",
        query_thread_id=1692,
        query_user_name="Adrien",
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["ignored_movies"]["bugonia"]["director_slug"] == "yorgos-lanthimos"
    assert "bugonia" not in state["tracked_movies"]
    assert "director_ignore" in events_path.read_text(encoding="utf-8")
    sent_markup = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
    assert sent_markup.inline_keyboard[0][0].text.startswith("🚫 Bugonia")
