"""
Thin async wrapper over google-cloud-pubsub for the coordinator <-> specialist
dispatch/results flow. Topics + subscriptions are already provisioned in GCP by
infra/setup.sh (STEP 6): csf-dispatch-{function} x 6, csf-results, each with a
pull subscription {topic}-sub.

Message shapes per docs/lld.md §3:
  dispatch (coordinator -> specialist), topic csf-dispatch-{function}:
    {run_id, session_id, function, category_ids, rubric_version, snapshot_ref}
  results (specialist -> coordinator), topic csf-results:
    {run_id, function, status, category_count, failed_ids, duration_ms,
     flash_calls, tokens_in, tokens_out}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google.cloud import pubsub_v1

from csf_coordinator.config import get_settings

log = logging.getLogger("csf-coordinator.pubsub")

_publisher: pubsub_v1.PublisherClient | None = None
_subscriber: pubsub_v1.SubscriberClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _get_subscriber() -> pubsub_v1.SubscriberClient:
    global _subscriber
    if _subscriber is None:
        _subscriber = pubsub_v1.SubscriberClient()
    return _subscriber


async def publish_dispatch(function: str, payload: dict[str, Any]) -> str:
    """Publish a dispatch message to csf-dispatch-{function}. Returns the message id."""
    s = get_settings()
    client = _get_publisher()
    topic = f"{s.pubsub_dispatch_prefix}{function}"
    topic_path = client.topic_path(s.google_cloud_project, topic)
    data = json.dumps(payload).encode("utf-8")

    def _publish() -> str:
        future = client.publish(topic_path, data)
        return future.result(timeout=30)

    message_id = await asyncio.to_thread(_publish)
    log.info("published dispatch -> %s (message_id=%s): %s", topic, message_id, payload)
    return message_id


async def publish_result(payload: dict[str, Any]) -> str:
    """Publish a completion message to csf-results. Returns the message id."""
    s = get_settings()
    client = _get_publisher()
    topic_path = client.topic_path(s.google_cloud_project, s.pubsub_results_topic)
    data = json.dumps(payload).encode("utf-8")

    def _publish() -> str:
        future = client.publish(topic_path, data)
        return future.result(timeout=30)

    message_id = await asyncio.to_thread(_publish)
    log.info("published result -> %s (message_id=%s): %s", s.pubsub_results_topic, message_id, payload)
    return message_id


async def pull_dispatch(function: str, max_messages: int = 1, timeout: float = 30.0) -> list[dict[str, Any]]:
    """Pull + ack up to max_messages from csf-dispatch-{function}-sub."""
    s = get_settings()
    client = _get_subscriber()
    topic = f"{s.pubsub_dispatch_prefix}{function}"
    sub_path = client.subscription_path(s.google_cloud_project, f"{topic}-sub")
    return await _pull_and_ack(client, sub_path, max_messages, timeout)


async def pull_results(max_messages: int = 10, timeout: float = 30.0) -> list[dict[str, Any]]:
    """Pull + ack up to max_messages from csf-results-sub."""
    s = get_settings()
    client = _get_subscriber()
    sub_path = client.subscription_path(s.google_cloud_project, f"{s.pubsub_results_topic}-sub")
    return await _pull_and_ack(client, sub_path, max_messages, timeout)


async def _pull_and_ack(
    client: pubsub_v1.SubscriberClient,
    subscription_path: str,
    max_messages: int,
    timeout: float,
) -> list[dict[str, Any]]:
    def _pull() -> list[dict[str, Any]]:
        response = client.pull(
            subscription=subscription_path, max_messages=max_messages, timeout=timeout,
        )
        if not response.received_messages:
            return []
        ack_ids = [msg.ack_id for msg in response.received_messages]
        client.acknowledge(subscription=subscription_path, ack_ids=ack_ids)
        return [json.loads(msg.message.data.decode("utf-8")) for msg in response.received_messages]

    messages = await asyncio.to_thread(_pull)
    if messages:
        log.info("pulled %d message(s) from %s", len(messages), subscription_path)
    return messages
