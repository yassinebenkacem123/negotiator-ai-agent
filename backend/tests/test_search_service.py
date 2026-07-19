import json
from unittest.mock import patch

from app.services import search_service


def _tavily_result(url, title, content="", raw_content=None):
    return {"url": url, "title": title, "content": content, "raw_content": raw_content}


# --- resolve_city ---------------------------------------------------------


def test_resolve_city_uses_openai_result():
    with patch.object(search_service.openai_client, "complete_json") as mock_complete:
        mock_complete.return_value = json.dumps({"city": "Charlotte, NC"})
        city = search_service.resolve_city("6161 Brookshire Blvd, Charlotte, NC 28216")
    assert city == "Charlotte, NC"


def test_resolve_city_falls_back_to_heuristic_when_openai_fails():
    with patch.object(search_service.openai_client, "complete_json", side_effect=RuntimeError("boom")):
        city = search_service.resolve_city("6161 Brookshire Blvd, Charlotte, NC 28216")
    assert city == "Charlotte, NC 28216"


def test_resolve_city_falls_back_when_openai_returns_null():
    with patch.object(search_service.openai_client, "complete_json") as mock_complete:
        mock_complete.return_value = json.dumps({"city": None})
        city = search_service.resolve_city("Charlotte, NC")
    assert city == "Charlotte, NC"


# --- find_movers: aggregator filtering -------------------------------------


def test_aggregator_domains_are_skipped():
    results = [
        _tavily_result("https://www.yelp.com/search?find_loc=Charlotte", "THE BEST 10 MOVERS", raw_content="call 704-555-0000"),
        _tavily_result("https://realmover.com", "Real Mover Co", raw_content="Call us at 704-555-1111"),
    ]
    with patch.object(search_service.tavily_client, "raw_search", return_value=results), \
         patch.object(search_service.openai_client, "complete_json", return_value="{}"):
        leads = search_service.find_movers("Charlotte, NC")

    assert len(leads) == 1
    assert leads[0].name == "Real Mover Co"


# --- find_movers: dedup -----------------------------------------------------


def test_duplicate_phone_numbers_are_deduplicated():
    results = [
        _tavily_result("https://mover-a.com", "Mover A", raw_content="Call (704) 555-2222"),
        _tavily_result("https://mover-a-alt-listing.com", "Mover A (alt listing)", raw_content="Call 704-555-2222"),
    ]
    with patch.object(search_service.tavily_client, "raw_search", return_value=results), \
         patch.object(search_service.openai_client, "complete_json", return_value="{}"):
        leads = search_service.find_movers("Charlotte, NC")

    assert len(leads) == 1


# --- find_movers: no phone dropped ------------------------------------------


def test_leads_without_a_phone_number_are_dropped():
    results = [_tavily_result("https://no-phone.com", "No Phone Movers", raw_content="We move things.")]
    with patch.object(search_service.tavily_client, "raw_search", return_value=results), \
         patch.object(search_service.openai_client, "complete_json", return_value="{}"):
        leads = search_service.find_movers("Charlotte, NC")

    assert leads == []


# --- find_movers: working_hours sanitization --------------------------------


def test_non_string_working_hours_values_are_filtered_and_fallback_applies():
    results = [_tavily_result("https://mover-b.com", "Mover B", raw_content="Call 704-555-3333")]
    profile = {"phone": None, "working_hours": {"mon": "08:00-18:00", "tue": None, "wed": 123}}
    with patch.object(search_service.tavily_client, "raw_search", return_value=results), \
         patch.object(search_service.openai_client, "complete_json", return_value=json.dumps(profile)):
        leads = search_service.find_movers("Charlotte, NC")

    assert len(leads) == 1
    assert leads[0].working_hours == {"mon": "08:00-18:00"}


def test_empty_working_hours_falls_back_to_default():
    results = [_tavily_result("https://mover-c.com", "Mover C", raw_content="Call 704-555-4444")]
    profile = {"phone": None, "working_hours": {}}
    with patch.object(search_service.tavily_client, "raw_search", return_value=results), \
         patch.object(search_service.openai_client, "complete_json", return_value=json.dumps(profile)):
        leads = search_service.find_movers("Charlotte, NC")

    assert leads[0].working_hours == search_service.settings.default_working_hours


# --- find_movers: field cleanup ---------------------------------------------


def test_pipe_null_artifacts_are_cleaned_from_address_and_website():
    results = [_tavily_result("https://mover-d.com", "Mover D", raw_content="Call 704-555-5555")]
    profile = {
        "phone": None,
        "address": "Charlotte, NC|null",
        "website": "null|https://mover-d.com/real",
        "working_hours": {},
    }
    with patch.object(search_service.tavily_client, "raw_search", return_value=results), \
         patch.object(search_service.openai_client, "complete_json", return_value=json.dumps(profile)):
        leads = search_service.find_movers("Charlotte, NC")

    assert leads[0].address == "Charlotte, NC"
    assert leads[0].website == "https://mover-d.com/real"


def test_website_falls_back_to_source_url_when_not_extracted():
    results = [_tavily_result("https://mover-e.com", "Mover E", raw_content="Call 704-555-6666")]
    with patch.object(search_service.tavily_client, "raw_search", return_value=results), \
         patch.object(search_service.openai_client, "complete_json", return_value="{}"):
        leads = search_service.find_movers("Charlotte, NC")

    assert leads[0].website == "https://mover-e.com"


# --- find_movers_near --------------------------------------------------------


def test_find_movers_near_resolves_city_then_searches():
    with patch.object(search_service, "resolve_city", return_value="Charlotte, NC") as mock_resolve, \
         patch.object(search_service, "find_movers", return_value=[]) as mock_find:
        search_service.find_movers_near("6161 Brookshire Blvd, Charlotte, NC 28216")

    mock_resolve.assert_called_once_with("6161 Brookshire Blvd, Charlotte, NC 28216")
    mock_find.assert_called_once_with("Charlotte, NC")
