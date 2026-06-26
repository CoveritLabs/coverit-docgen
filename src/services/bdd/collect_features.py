from collections import Counter, defaultdict
from src.core.config import get_settings
from src.utils.helpers import jaccard
from urllib.parse import urlparse
from src.utils.helpers import words, upper_snake, title, url_area, jaccard
from src.models.bdd import ResolvedFlow

settings = get_settings()

GENERIC_FEATURE_WORDS = {
    "action",
    "click",
    "flow",
    "navigate",
    "open",
    "page",
    "screen",
    "transition",
    "user",
    "view",
}


def _unique_feature_names(names: list[str]) -> list[str]:
    totals = Counter(names)
    seen: Counter[str] = Counter()
    unique: list[str] = []
    for name in names:
        if totals[name] == 1:
            unique.append(name)
            continue
        seen[name] += 1
        unique.append(f"{name} {seen[name]}")
    return unique


def _destination_anchor(flow: ResolvedFlow) -> str:
    end_state = flow.transitions[-1].to_state
    area = url_area(end_state.url)
    if area:
        return f"url:{area}"
    return f"state:{upper_snake(end_state.name, 'UNKNOWN')}"


def _group_centroid(group: list[int], profiles: list[set[str]]) -> set[str]:
    centroid: set[str] = set()
    for index in group:
        centroid.update(profiles[index])
    return centroid


def _flow_labels(flow: ResolvedFlow) -> list[str]:
    labels = [flow.checkpoint.name]
    labels.extend(transition.name for transition in flow.transitions)
    labels.append(flow.transitions[-1].to_state.name)
    return labels


def _flow_urls(flow: ResolvedFlow) -> list[str]:
    urls = [flow.checkpoint.url]
    for transition in flow.transitions:
        urls.extend([transition.from_state.url, transition.to_state.url])
    return urls


def _scenario_profile(
    flow: ResolvedFlow, scenario_name: str, labels: list[str]
) -> set[str]:
    tokens: set[str] = set()
    labels = _flow_labels(flow)
    labels.append(scenario_name)
    labels.extend(transition.action for transition in flow.transitions)
    for label in labels:
        tokens.update(token.lower() for token in words(label))
    for url in _flow_urls(flow):
        parsed = urlparse(url)
        if parsed.hostname:
            tokens.update(words(parsed.hostname.split(".")[0].lower()))
        tokens.update(token.lower() for token in words(parsed.path))
    return {token for token in tokens if token not in GENERIC_FEATURE_WORDS}


def merge_groups(
    groups: list[list[int]],
    profiles: list[set[str]],
    threshold: float,
) -> list[list[int]]:
    merged = [list(group) for group in groups]
    changed = True
    while changed:
        changed = False
        best_pair: tuple[int, int] | None = None
        best_score = threshold
        for left_index in range(len(merged)):
            left_profile = _group_centroid(merged[left_index], profiles)
            for right_index in range(left_index + 1, len(merged)):
                score = jaccard(
                    left_profile,
                    _group_centroid(merged[right_index], profiles),
                )
                if score >= best_score:
                    best_score = score
                    best_pair = (left_index, right_index)

        if best_pair is None:
            continue

        left_index, right_index = best_pair
        merged[left_index].extend(merged[right_index])
        merged[left_index].sort()
        del merged[right_index]
        changed = True

    return merged


def merge_singletons(
    groups: list[list[int]],
    profiles: list[set[str]],
    threshold: float,
) -> list[list[int]]:
    merged = [list(group) for group in groups]
    for group in list(merged):
        if len(group) != 1 or group not in merged:
            continue
        singleton_index = group[0]
        best_group: list[int] | None = None
        best_score = threshold
        for candidate in merged:
            if candidate == group:
                continue
            score = jaccard(
                profiles[singleton_index],
                _group_centroid(candidate, profiles),
            )
            if score >= best_score:
                best_score = score
                best_group = candidate
        if best_group is None:
            continue
        best_group.append(singleton_index)
        best_group.sort()
        merged.remove(group)
    return merged


def collect_features(
    flows: list[ResolvedFlow], scenario_names: list[str]
) -> list[list[ResolvedFlow]]:
    if not settings.bdd_split_features:
        return [flows]

    feature_similarity_threshold = settings.bdd_feature_similarity_threshold
    singleton_merge_threshold = settings.bdd_singleton_merge_threshold

    profiles = [
        _scenario_profile(flow, scenario_name)
        for flow, scenario_name in zip(flows, scenario_names)
    ]
    anchored: dict[str, list[int]] = defaultdict(list)
    for index, flow in enumerate(flows):
        anchored[_destination_anchor(flow)].append(index)

    groups = list(anchored.values())
    groups = merge_groups(groups, profiles, feature_similarity_threshold)
    groups = merge_singletons(groups, profiles, singleton_merge_threshold)
    groups.sort(key=lambda group: min(group))
    return [[flows[index] for index in group] for group in groups]


def _infer_feature_name(flows: list[ResolvedFlow]) -> str:
    label_tokens: list[set[str]] = []
    for flow in flows:
        for label in _flow_labels(flow):
            tokens = {
                token.lower()
                for token in words(label)
                if token.lower() not in GENERIC_FEATURE_WORDS
            }
            if tokens:
                label_tokens.append(tokens)

    shared = set.intersection(*label_tokens) if label_tokens else set()
    if shared:
        ordered = sorted(shared)
        return f"{' '.join(word.capitalize() for word in ordered)} User Flows"

    hostnames = {
        urlparse(flow.checkpoint.url).hostname
        for flow in flows
        if urlparse(flow.checkpoint.url).hostname
    }
    if len(hostnames) == 1:
        hostname = next(iter(hostnames))
        application = hostname.split(".")[0].replace("-", " ")
        if application:
            return f"{title(application)} User Flows"

    return "Application User Flows"


def infer_feature_names(features):
    return _unique_feature_names([_infer_feature_name(feature) for feature in features])
