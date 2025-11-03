"""Módulo de scraping."""
from .fetchers import fetch_events_from_link
from .betnacional import try_parse_events, scrape_game_result, scrape_live_game_data

