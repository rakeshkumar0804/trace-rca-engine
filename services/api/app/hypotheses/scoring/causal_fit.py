# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from collections import deque
from app.schemas.hypotheses import Hypothesis
from app.schemas.services import ServiceDependency


def calculate_causal_fit(
    hypothesis: Hypothesis,
    service_dependencies: list[ServiceDependency],
    affected_services: list[str],
) -> float:
    """Calculates causal fit score in range [0.0, 20.0].
    
    Evaluates whether the service/component implicated by the hypothesis has a viable causal propagation
    path to cause the observed failures in affected services.
    
    Factors considered:
    - Directionality: In microservices, failures propagate UPSTREAM (a failure in service B causes errors in caller service A).
    - Hop distance: Direct dependencies (1-hop) score much higher than multi-hop paths.
    - Dependency strength: Hard (synchronous/blocking) dependencies propagate failures; soft (async/fire-and-forget) dependencies do not.
    """
    if not affected_services:
        return 10.0

    text = f"{hypothesis.title} {hypothesis.description}".lower()

    # Collect known services
    all_known_services: set[str] = set()
    # Map: caller (from_service) -> list of (callee/to_service, strength, protocol)
    outbound_calls: dict[str, list[tuple[str, str, str]]] = {}

    for dep in service_dependencies:
        src = dep.from_service.lower()
        dst = dep.to_service.lower()
        all_known_services.add(src)
        all_known_services.add(dst)
        outbound_calls.setdefault(src, []).append((dst, dep.dependency_strength.lower(), dep.protocol.lower()))

    # Identify which service is implicated by the hypothesis
    implicated_service: str | None = None
    for s in all_known_services:
        if s in text:
            implicated_service = s
            break

    if not implicated_service:
        # Non-service or shared infrastructure (DB, broker, network)
        if "database" in text or "db" in text or "postgres" in text:
            # Check if any affected service owns or uses database
            return 16.0
        if "network" in text or "traffic" in text:
            return 10.0
        return 0.0

    implicated_lower = implicated_service.lower()
    affected_lower = [a.lower() for a in affected_services]

    # 1. Identity: The implicated service is directly one of the failing/affected services
    if implicated_lower in affected_lower:
        return 20.0

    # 2. Causal Propagation Path:
    # Does any affected service depend on the implicated service?
    # We search paths from affected_service -> ... -> implicated_service
    best_path_score = 0.0

    for affected in affected_lower:
        # BFS tracking (current_service, hops, min_strength_factor)
        queue = deque([(affected, 0, 1.0)])
        visited = {affected: 0}

        while queue:
            curr, hops, strength_factor = queue.popleft()

            if curr == implicated_lower and hops > 0:
                # Found path from affected caller down to implicated dependency
                # Score based on hops and strength factor:
                # 1 hop (hard): 16.0 * 1.0 = 16.0
                # 1 hop (soft): 16.0 * 0.3 = 4.8
                # 2 hops (hard): 16.0 * 0.3 = 4.8
                # 2 hops (soft): 16.0 * 0.3 * 0.3 = 1.44
                # 3+ hops: <= 1.0
                distance_decay = 0.35 ** (hops - 1)
                path_score = 16.0 * strength_factor * distance_decay
                best_path_score = max(best_path_score, path_score)
                continue

            if hops >= 3:
                continue

            for callee, strength, _proto in outbound_calls.get(curr, []):
                # Strength factor: hard = 1.0, soft = 0.25 (async/fire-and-forget rarely cascades 5xx)
                edge_factor = 1.0 if strength == "hard" else 0.25
                next_strength = strength_factor * edge_factor

                if callee not in visited or visited[callee] > hops + 1:
                    visited[callee] = hops + 1
                    queue.append((callee, hops + 1, next_strength))

    return max(0.0, min(20.0, round(best_path_score, 2)))
