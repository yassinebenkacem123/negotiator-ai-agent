"""Central configuration — the swappable levers referenced across services.

Nothing outside this file should hardcode a threshold, tactic list, or vendor
credential. If ranking.py needs the red-flag cutoff, it imports it from here.
"""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"

    # --- Vendor credentials (loaded from .env, never hardcoded) ---
    openai_api_key: str = ""
    tavily_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_caller_agent_id: str = ""
    elevenlabs_webhook_secret: str = ""
    backend_public_url: str = "http://localhost:8000"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = Field(
        default="",
        validation_alias=AliasChoices("TWILIO_PHONE_NUMBER", "TWILIO_FROM_NUMBER"),
    )
    ip_api_base_url: str = "http://ip-api.com/json"

    # --- Negotiation / ranking levers ---
    red_flag_below_median_pct: float = 0.30  # 30%+ below median => red flag
    negotiation_max_rounds: int = 2  # how many push-back attempts per call

    # --- Discovery levers ---
    max_companies_per_search: int = 10
    search_query_template: str = "residential moving company in {city}"

    # --- Calling levers ---
    respect_working_hours: bool = True
    default_timezone: str = "America/New_York"
    # Real pages frequently don't list hours in scrapeable text (verified: most
    # of a live Tavily sample of moving-company sites had none). Rather than
    # let the working-hours gate skip most real companies, assume this default
    # when extraction finds nothing. This is a real tradeoff (accuracy vs. call
    # volume), not a guess dressed up as fact — flagged here explicitly so it's
    # easy to find and change.
    default_working_hours: dict[str, str] = {
        "mon": "08:00-18:00",
        "tue": "08:00-18:00",
        "wed": "08:00-18:00",
        "thu": "08:00-18:00",
        "fri": "08:00-18:00",
        "sat": "08:00-18:00",
    }


settings = Settings()
