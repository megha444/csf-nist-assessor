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
from typing import Callable, Any

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


async def pull_results(
    max_messages: int = 10,
    timeout: float = 30.0,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Pull from csf-results-sub, acking ONLY what this caller consumes.

    Pass `run_id` whenever you care about a specific run. All coordinators share
    one csf-results subscription, so without a filter this call would ack every
    completion it happens to see -- including ones belonging to OTHER in-flight
    runs, permanently destroying them. The owning run would then wait out its
    full 900s timeout having silently lost its completions, even though its
    workers succeeded and wrote their scores. Observed live 2026-08-28 with two
    concurrent assessments.

    Omitting run_id keeps the old ack-everything behaviour, which is only safe
    when nothing else is running.
    """
    s = get_settings()
    client = _get_subscriber()
    sub_path = client.subscription_path(s.google_cloud_project, f"{s.pubsub_results_topic}-sub")
    keep = None if run_id is None else (lambda m: m.get("run_id") == run_id)
    return await _pull_and_ack(client, sub_path, max_messages, timeout, keep=keep)


async def _pull_and_ack(
    client: pubsub_v1.SubscriberClient,
    subscription_path: str,
    max_messages: int,
    timeout: float,
    keep: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    """Pull messages, ack only the ones `keep` accepts (plus unparseable ones).

    `keep=None` means take everything — correct for the per-Function dispatch
    subscriptions, which have exactly one consumer. It is NOT correct for the
    shared results subscription; see pull_results.
    """
    def _pull() -> list[dict[str, Any]]:
        response = client.pull(
            subscription=subscription_path, max_messages=max_messages, timeout=timeout,
        )
        if not response.received_messages:
            return []

        # Ack ONLY what we take responsibility for. Two rules, for two different
        # failure modes we hit for real on 2026-08-28:
        #
        #  1. Unparseable payload -> ack and drop. Parsing used to happen in one
        #     comprehension AFTER a blanket ack, so a single bad message raised
        #     straight out of here and killed the whole assessment. Ack it so it
        #     is not redelivered forever, but never let it be fatal.
        #  2. Message for a DIFFERENT run -> do NOT ack. Every coordinator shares
        #     one csf-results subscription. Blanket-acking destroyed other runs'
        #     completions, leaving those runs stalled at completed_agents=0 until
        #     their 900s timeout despite their workers having succeeded. Leaving
        #     them unacked lets Pub/Sub redeliver them to their owner.
        to_ack: list[str] = []
        parsed: list[dict[str, Any]] = []
        skipped = 0
        for msg in response.received_messages:
            try:
                data = json.loads(msg.message.data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                log.warning(
                    "skipping unparseable message on %s (%s): %r",
                    subscription_path, e, msg.message.data[:120],
                )
                to_ack.append(msg.ack_id)
                continue
            if keep is not None and not keep(data):
                skipped += 1          # someone else's — leave it for them
                continue
            to_ack.append(msg.ack_id)
            parsed.append(data)

        if to_ack:
            client.acknowledge(subscription=subscription_path, ack_ids=to_ack)
        if skipped:
            log.info(
                "left %d message(s) on %s for other run(s) — not acked",
                skipped, subscription_path,
            )
        return parsed

    messages = await asyncio.to_thread(_pull)
    if messages:
        log.info("pulled %d message(s) from %s", len(messages), subscription_path)
    return messages
