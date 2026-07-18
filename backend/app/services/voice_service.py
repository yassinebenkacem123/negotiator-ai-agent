"""SRP: Conversation Design.

Owns the "Agent Script" — how the job spec (addresses, date, trips, bags) gets
injected into the ElevenLabs agent's context so it negotiates on the right
details. Does not manage the phone connection itself (see telephony.py).
"""

from app.clients import eleven_client
from app.models.job_spec import JobSpec
from app.playbook.negotiation_playbook import NEGOTIATION_PLAYBOOK


def build_caller_context(job_spec: JobSpec, known_competing_prices: list[float]) -> dict:
    """Build the dynamic variables injected into the Caller agent's session.

    known_competing_prices lets the agent use real leverage from earlier calls
    in this session — never a fabricated number (see negotiation_playbook.py
    honesty constraints).
    """
    return {
        "origin_address": job_spec.origin_address,
        "origin_floor": job_spec.origin_floor,
        "origin_has_elevator": job_spec.origin_has_elevator,
        "destination_address": job_spec.destination_address,
        "destination_floor": job_spec.destination_floor,
        "destination_has_elevator": job_spec.destination_has_elevator,
        "distance_miles": job_spec.distance_miles,
        "move_date": job_spec.move_date,
        "num_trips": job_spec.num_trips,
        "num_bags": job_spec.num_bags,
        "known_competing_prices": known_competing_prices,
        "negotiation_playbook": NEGOTIATION_PLAYBOOK,
    }


def start_caller_session(job_spec: JobSpec, known_competing_prices: list[float]) -> str:
    """Start an ElevenLabs Caller agent session, return the session/conversation id."""
    client = eleven_client.get_client()
    context = build_caller_context(job_spec, known_competing_prices)
    # TODO: wire to the actual ElevenLabs conversational session API once
    # agent IDs are configured (see app/config.py: elevenlabs_agent_id_caller)
    conversation = client.conversational_ai.start_session(
        agent_id=eleven_client.caller_agent_id(),
        dynamic_variables=context,
    )
    return conversation.conversation_id
