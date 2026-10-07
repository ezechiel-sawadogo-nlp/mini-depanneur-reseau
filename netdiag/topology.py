"""Questions simples sur la topologie du réseau fictif (data/network.json)."""

from netdiag.scenarios import load_network


def domain_of(element: str) -> str:
    """Le domaine (ran, transport, core) auquel appartient un élément."""
    for domain, elements in load_network()["domains"].items():
        if element in elements:
            return domain
    raise ValueError(f"élément inconnu : {element}")


def path_to_core(element: str) -> list[str]:
    """L'élément lui-même, puis tout ce dont il dépend jusqu'au cœur."""
    depends_on = load_network()["depends_on"]
    path = [element]
    for parent in depends_on.get(element, []):
        for e in path_to_core(parent):
            if e not in path:
                path.append(e)
    return path


def all_cells() -> list[str]:
    """Les cellules : les éléments dont aucun autre ne dépend."""
    depends_on = load_network()["depends_on"]
    parents = {p for deps in depends_on.values() for p in deps}
    return sorted(e for e in depends_on if e not in parents)


def all_sites() -> list[str]:
    """Les sites radio : les éléments dont dépendent directement les cellules."""
    depends_on = load_network()["depends_on"]
    return sorted({p for cell in all_cells() for p in depends_on[cell]})


def cells_behind(element: str) -> list[str]:
    """Les cellules qui ont besoin de cet élément pour fonctionner."""
    return [c for c in all_cells() if element in path_to_core(c)]


def sites_behind(element: str) -> list[str]:
    """Les sites radio qui ont besoin de cet élément pour joindre le cœur."""
    return [s for s in all_sites() if element in path_to_core(s)]
