"""Negotiation playbook — kept separate from voice_service.py so tactics can be
iterated on quickly without touching agent-wiring code. Extend NEGOTIATION_PLAYBOOK
with more resources as they come in; do not inline tactics into prompts elsewhere.
"""

NEGOTIATION_PLAYBOOK = {
    "opening": (
        "Hi, I'm calling to get a moving quote — I'm an AI assistant calling on "
        "behalf of a customer, is that alright to go through some details with you?"
    ),
    "disclosure_rule": "Always say plainly you are an AI if asked. Never claim to be human.",
    "pitch_rule": "Describe the job spec identically every call. Never add or remove details.",
    "leverage_rule": (
        "You may cite a competing price only if it is already present in "
        "known_competing_prices for this session. Never invent a competing offer."
    ),
    "push_sequence": [
        "Ask for an itemized breakdown if only a lump sum is given.",
        "Ask if there is flexibility on price given you are comparing multiple quotes.",
        "If a competing price is known, ask if they can match or beat it.",
    ],
    "max_rounds": 2,  # keep in sync with config.negotiation_max_rounds
    "failure_rule": (
        "If they will not move on price, accept the original number, thank them, "
        "and log the outcome — never leave a call without a structured result."
    ),
    "closing_outcomes": ["quote", "callback_scheduled", "declined", "no_answer"],
}
