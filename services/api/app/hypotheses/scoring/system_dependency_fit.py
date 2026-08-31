# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from collections import deque
from app.schemas.hypotheses import Hypothesis
from app.schemas.services import ServiceDependency


def calculate_system_dependency_fit(
    hypothesis: Hypothesis,
    service_dependencies: list[ServiceDependency],
    affected_services: list[str],
) -> float:
    """Calculates system dependency fit score in range [0.0, 20.0].
    
    Evaluates topological directionality and structural linkage:
    - Failing service itself = 20.0
    - Direct (1-hop) upstream dependency = 15.0 - 18.0 (hard) or 5.0 (soft)
    - 2-hop transitive dependency = 4.0 (hard) or 1.5 (soft)
    - 3+ hops or disconnected service = 0.0 - 2.0
    """
    if not affected_services:
        return 10.0

    text = f"{hypothesis.title} {hypothesis.description}".lower()

    # Collect known services
    all_known_services: set[str] = set()
    outbound_calls: dict[str, list[tuple[str, str]]] = {}

    for dep in service_dependencies:
        src = dep.from_service.lower()
        dst = dep.to_service.lower()
        all_known_services.add(src)
        all_known_services.add(dst)
        outbound_calls.setdefault(src, []).append((dst, dep.dependency_strength.lower()))

    # Implicated service
    implicated_service: str | None = None
    for s in all_known_services:
        if s in text:
            implicated_service = s
            break

    if not implicated_service:
        # Non-service or shared infrastructure (DB, broker, network)
        if "database" in text or "db" in text or "postgres" in text:
            return 18.0
        if "traffic" in text or "load" in text or "network" in text:
            return 10.0
        return 0.0

    implicated_lower = implicated_service.lower()
    affected_lower = [a.lower() for a in affected_services]

    # Direct identity: the implicated service is the failing service
    if implicated_lower in affected_lower:
        return 20.0

    # Search paths from affected services down to implicated service
    best_dep_score = 0.0

    for affected in affected_lower:
        queue = deque([(affected, 0, 1.0)])
        visited = {affected: 0}

        while queue:
            curr, hops, strength_factor = queue.popleft()

            if curr == implicated_lower and hops > 0:
                # 1-hop hard: 16.0, 1-hop soft: 4.8
                # 2-hop hard: 5.6, 2-hop soft: 1.4
                decay = 0.35 ** (hops - 1)
                score = 16.0 * strength_factor * decay
                best_dep_score = max(best_dep_score, score)
                continue

            if hops >= 3:
                continue

            for callee, strength in outbound_calls.get(curr, []):
                edge_factor = 1.0 if strength == "hard" else 0.3
                next_strength = strength_factor * edge_factor

                if callee not in visited or visited[callee] > hops + 1:
                    visited[callee] = hops + 1
                    queue.append((callee, hops + 1, next_strength))

    return max(0.0, min(20.0, round(best_dep_score, 2)))
