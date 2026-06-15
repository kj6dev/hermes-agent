"""Tests for Telegram movie-monitor dry-run inline buttons."""

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
