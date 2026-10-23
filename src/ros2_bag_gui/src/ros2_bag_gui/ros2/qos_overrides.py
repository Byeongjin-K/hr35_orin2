"""Subscription QoS for ros2 bag record where its own choice would lose messages."""
import os
from typing import Final, Iterable, Protocol, Sequence, TypedDict

import yaml
from rclpy.qos import QoSReliabilityPolicy
from rclpy.topic_endpoint_info import TopicEndpointInfo

OVERRIDES_FILE: Final = 'qos_overrides.yaml'


class PublisherGraph(Protocol):
    def get_publishers_info_by_topic(self, topic: str, /) -> Sequence[TopicEndpointInfo]: ...


class QosOverride(TypedDict):
    """One topic's subscription profile, in the short keys ros2 bag record reads."""

    history: str
    depth: int
    reliability: str
    durability: str


def mixed_durability_overrides(node: PublisherGraph, topics: Iterable[str]) -> dict[str, QosOverride]:
    """A volatile subscription for each topic whose publishers do not agree on durability.

    ros2 bag record picks its subscription QoS from the publishers it knows when it
    subscribes. On a topic with a transient-local and a volatile publisher it can meet
    the transient-local one first, subscribe transient-local, and never receive from
    the volatile one ("offering incompatible QoS ... DURABILITY_QOS_POLICY"). A volatile
    subscription matches both; it only misses what was latched before Start.
    """
    overrides: dict[str, QosOverride] = {}
    for topic in topics:
        publishers = node.get_publishers_info_by_topic(topic)
        if len(publishers) < 2:
            continue
        if len({p.qos_profile.durability for p in publishers}) < 2:
            continue
        reliable = all(
            p.qos_profile.reliability == QoSReliabilityPolicy.RELIABLE for p in publishers)
        overrides[topic] = QosOverride(
            history='keep_last', depth=10,
            reliability='reliable' if reliable else 'best_effort', durability='volatile')
    return overrides


def write_qos_overrides(session_folder: str, overrides: dict[str, QosOverride]) -> str:
    """Write the overrides where ros2 bag record reads them; "" when there are none."""
    if not overrides:
        return ""
    path = os.path.join(session_folder, OVERRIDES_FILE)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(dict(overrides), f, sort_keys=True)
    return path
