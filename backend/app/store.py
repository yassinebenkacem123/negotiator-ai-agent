"""Durable application state backed by Neon Postgres.

The mapping-shaped adapters preserve the existing route/service interfaces while
storing every value in the database. SQLite remains usable when tests override
``DATABASE_URL`` with a temporary ``sqlite:///`` URL.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping, MutableSet
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.database import (
    claim_webhook_event,
    delete_state,
    get_state,
    list_state,
    list_webhook_events,
    release_webhook_event,
    set_state,
    webhook_event_exists,
)
from app.models.job_spec import JobSpec
from app.models.lead import Lead
from app.models.quote import Quote
from app.models.voice import StoredCallArtifact

T = TypeVar("T")


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value


class PersistentMapping(MutableMapping[str, T], Generic[T]):
    def __init__(
        self,
        namespace: str,
        model: type[BaseModel] | None = None,
        *,
        list_model: type[BaseModel] | None = None,
    ) -> None:
        self.namespace = namespace
        self.model = model
        self.list_model = list_model

    def _decode(self, value: Any) -> T:
        if self.model is not None:
            return self.model.model_validate(value)  # type: ignore[return-value]
        if self.list_model is not None:
            return [self.list_model.model_validate(item) for item in value]  # type: ignore[return-value]
        return value

    def __getitem__(self, key: str) -> T:
        value = get_state(self.namespace, key)
        if value is None:
            raise KeyError(key)
        return self._decode(value)

    def __setitem__(self, key: str, value: T) -> None:
        set_state(self.namespace, key, _to_jsonable(value))

    def __delitem__(self, key: str) -> None:
        if get_state(self.namespace, key) is None:
            raise KeyError(key)
        delete_state(self.namespace, key)

    def __iter__(self) -> Iterator[str]:
        return iter(list_state(self.namespace))

    def __len__(self) -> int:
        return len(list_state(self.namespace))


class PersistentWebhookEventSet(MutableSet[str]):
    def __contains__(self, event_key: object) -> bool:
        return isinstance(event_key, str) and webhook_event_exists(event_key)

    def __iter__(self) -> Iterator[str]:
        return iter(list_webhook_events())

    def __len__(self) -> int:
        return len(list_webhook_events())

    def add(self, event_key: str) -> None:
        claim_webhook_event(event_key)

    def discard(self, event_key: str) -> None:
        release_webhook_event(event_key)

    def claim(self, event_key: str) -> bool:
        return claim_webhook_event(event_key)


job_specs: PersistentMapping[JobSpec] = PersistentMapping("job_specs", JobSpec)
leads: PersistentMapping[list[Lead]] = PersistentMapping("leads", list_model=Lead)
quotes: PersistentMapping[list[Quote]] = PersistentMapping("quotes", list_model=Quote)
call_states: PersistentMapping[dict[str, dict[str, Any]]] = PersistentMapping("call_states")
call_artifacts: PersistentMapping[StoredCallArtifact] = PersistentMapping(
    "call_artifacts", StoredCallArtifact
)
processed_webhook_events = PersistentWebhookEventSet()
