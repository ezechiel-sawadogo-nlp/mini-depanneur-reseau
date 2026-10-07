"""Génère les 15 scénarios de panne à partir d'une liste de spécifications.

Chaque scénario est construit en trois temps :
  1. la panne elle-même, sur l'élément fautif (la cause racine) ;
  2. ses conséquences, propagées aux éléments qui en dépendent ;
  3. des événements parasites, sans rapport avec la panne.

Tout est déterministe : relancer le script reproduit exactement les mêmes fichiers.
Les données sont inventées et simplifiées ; elles ne décrivent aucun réseau réel.

Usage :
    python -m netdiag.generate
"""

import hashlib
import json

from netdiag.scenarios import DATA_DIR, load_network
from netdiag.topology import all_cells, all_sites, cells_behind, domain_of, sites_behind

# --- Les 15 pannes à simuler ---------------------------------------------------
# split : "dev" sert à mettre au point le système, "test" sert à le noter.
# level : easy = aucun parasite, medium = une alarme parasite,
#         hard = une alarme parasite + un changement de configuration anodin.
SPECS = [
    {"id": "SC01", "split": "dev", "time": "10:01:02", "element": "L1", "fault": "fiber_cut", "level": "easy"},
    {"id": "SC02", "split": "dev", "time": "09:42:00", "element": "C3", "fault": "config_error", "level": "easy", "variant": "tilt"},
    {"id": "SC03", "split": "dev", "time": "14:04:50", "element": "SMF", "fault": "overload", "level": "easy"},
    {"id": "SC04", "split": "dev", "time": "11:20:15", "element": "S1", "fault": "hardware_failure", "level": "medium"},
    {"id": "SC05", "split": "dev", "time": "18:30:00", "element": "L2", "fault": "link_congestion", "level": "hard"},
    {"id": "SC06", "split": "test", "time": "08:15:30", "element": "L3", "fault": "fiber_cut", "level": "medium"},
    {"id": "SC07", "split": "test", "time": "16:45:10", "element": "L3", "fault": "link_congestion", "level": "hard"},
    {"id": "SC08", "split": "test", "time": "13:05:00", "element": "R1", "fault": "config_error", "level": "hard"},
    {"id": "SC09", "split": "test", "time": "15:22:40", "element": "C1", "fault": "config_error", "level": "medium", "variant": "power"},
    {"id": "SC10", "split": "test", "time": "12:10:05", "element": "C2", "fault": "interference", "level": "hard"},
    {"id": "SC11", "split": "test", "time": "19:02:30", "element": "C3", "fault": "hardware_failure", "level": "easy"},
    {"id": "SC12", "split": "test", "time": "10:48:20", "element": "AMF", "fault": "overload", "level": "medium"},
    {"id": "SC13", "split": "test", "time": "17:36:00", "element": "SMF", "fault": "config_error", "level": "hard"},
    {"id": "SC14", "split": "test", "time": "09:05:45", "element": "UPF", "fault": "config_error", "level": "medium"},
    {"id": "SC15", "split": "test", "time": "20:14:10", "element": "UPF", "fault": "hardware_failure", "level": "easy"},
]

# --- Valeurs normales du réseau (avant toute panne) -----------------------------
SITE_OF = {"C1": "S1", "C2": "S1", "C3": "S2"}
PORT_OF = {"L1": "P1", "L2": "P2", "L3": "P3"}
BASELINE = {
    "C1": {"connected_users": 140, "data_throughput_mbps": 42.0, "call_drop_rate_pct": 0.8, "signal_quality_db": 14.0},
    "C2": {"connected_users": 95, "data_throughput_mbps": 35.0, "call_drop_rate_pct": 0.7, "signal_quality_db": 13.0},
    "C3": {"connected_users": 110, "data_throughput_mbps": 38.0, "call_drop_rate_pct": 0.8, "signal_quality_db": 14.0},
    "L1": {"packet_loss_pct": 0.1, "link_utilization_pct": 48.0, "latency_ms": 6.0},
    "L2": {"packet_loss_pct": 0.1, "link_utilization_pct": 41.0, "latency_ms": 8.0},
    "L3": {"packet_loss_pct": 0.1, "link_utilization_pct": 55.0, "latency_ms": 4.0},
    "AMF": {"registration_success_pct": 99.5, "cpu_load_pct": 50.0},
    "SMF": {"session_setup_success_pct": 99.2, "cpu_load_pct": 45.0},
    "UPF": {"packet_drop_pct": 0.1, "cpu_load_pct": 40.0},
}

# --- Événements parasites possibles ----------------------------------------------
NOISE_ALARMS = [
    ("R1", "FAN_SPEED_WARNING", "fan tray 2 speed above nominal"),
    ("AMF", "CERTIFICATE_EXPIRY_WARNING", "TLS certificate expires in 21 days"),
    ("S2", "CABINET_DOOR_OPEN", "cabinet door sensor: open"),
    ("S1", "BATTERY_TEST_RUNNING", "scheduled battery test started"),
    ("UPF", "LICENSE_USAGE_WARNING", "license usage at 82% of capacity"),
]
NOISE_CHANGES = {
    "C1": ("Mise à jour de la liste des cellules voisines (changement planifié).", "configuration applied: neighbour list updated (3 entries)"),
    "C2": ("Mise à jour de la liste des cellules voisines (changement planifié).", "configuration applied: neighbour list updated (3 entries)"),
    "C3": ("Mise à jour de la liste des cellules voisines (changement planifié).", "configuration applied: neighbour list updated (2 entries)"),
    "S1": ("Mise à jour de l'agent de supervision du site (changement planifié).", "configuration applied: monitoring agent v4.2 (previous=v4.1)"),
    "S2": ("Mise à jour de l'agent de supervision du site (changement planifié).", "configuration applied: monitoring agent v4.2 (previous=v4.1)"),
    "R1": ("Description de l'interface P2 mise à jour.", "configuration applied: interface P2 description updated"),
    "AMF": ("Niveau de journalisation passé de INFO à WARNING.", "configuration applied: log_level=WARNING (previous=INFO)"),
    "SMF": ("Rotation quotidienne des journaux activée.", "configuration applied: log_rotation=daily"),
    "UPF": ("Rotation quotidienne des journaux activée.", "configuration applied: log_rotation=daily"),
}


def pick(scenario_id: str, salt: str, n: int) -> int:
    """Un entier entre 0 et n-1, pseudo-aléatoire mais toujours le même.

    On hache un texte au lieu d'utiliser le module random : le résultat est
    identique sur toutes les machines et toutes les versions de Python.
    """
    digest = hashlib.sha256(f"{scenario_id}-{salt}".encode()).hexdigest()
    return int(digest, 16) % n


class Builder:
    """Accumule les événements d'un scénario. Les heures sont relatives à la panne."""

    def __init__(self, spec: dict):
        self.spec = spec
        h, m, s = (int(x) for x in spec["time"].split(":"))
        self.t0 = h * 3600 + m * 60 + s  # l'instant de la panne, en secondes
        self.ticket = ""
        self.alarms, self.logs, self.changes = [], [], []
        # Le tableau de bord : toutes les mesures, de tous les éléments, toujours présentes.
        self.kpis = {(e, name): [v, v] for e, values in BASELINE.items() for name, v in values.items()}
        self.forced = set()  # mesures fixées explicitement par la panne
        self.involved = {spec["element"]}  # éléments qui portent un événement lié à la panne

    def at(self, offset: int) -> str:
        t = self.t0 + offset
        return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"

    def alarm(self, offset: int, element: str, name: str, severity: str) -> None:
        self.involved.add(element)
        self.alarms.append({"time": self.at(offset), "domain": domain_of(element), "element": element, "name": name, "severity": severity})

    def log(self, offset: int, element: str, message: str) -> None:
        self.involved.add(element)
        self.logs.append({"time": self.at(offset), "domain": domain_of(element), "element": element, "message": message})

    def change(self, offset: int, element: str, description: str) -> None:
        self.changes.append({"time": self.at(offset), "domain": domain_of(element), "element": element, "description": description})

    def set(self, element: str, name: str, during: float) -> None:
        self.kpis[(element, name)][1] = during
        self.forced.add((element, name))

    def scale(self, element: str, name: str, factor: float) -> None:
        before = self.kpis[(element, name)][0]
        value = before * factor
        self.set(element, name, round(value) if isinstance(before, int) else round(value, 1))


# --- Conséquences communes ---------------------------------------------------------

def zone(cells: list[str]) -> str:
    """Comment un client décrirait la zone touchée."""
    if set(cells) == set(all_cells()):
        return "sur l'ensemble du réseau"
    sites = {SITE_OF[c] for c in cells}
    if len(sites) == 1 and set(cells) == set(cells_behind(next(iter(sites)))):
        return f"dans la zone du site {next(iter(sites))}"
    return f"dans la zone couverte par la cellule {cells[0]}"


def cell_down(b: Builder, cell: str) -> None:
    b.set(cell, "connected_users", 0)
    b.set(cell, "data_throughput_mbps", 0.0)
    b.set(cell, "call_drop_rate_pct", 0.0)


def site_unreachable(b: Builder, site: str, delay: int, backhaul: bool) -> None:
    """Un site ne joint plus le cœur : ses cellules tombent et le cœur le signale."""
    if backhaul:  # le site fonctionne mais sa liaison vers le cœur est perdue
        b.alarm(delay, site, "BACKHAUL_LOSS", "critical")
        b.log(delay, site, "transport heartbeat timeout, no route to core")
    for cell in cells_behind(site):
        b.alarm(delay, cell, "CELL_OUT_OF_SERVICE", "major")
        cell_down(b, cell)
    b.alarm(delay + 4, "AMF", "GNB_UNREACHABLE", "major")
    b.log(delay + 4, "AMF", f"SCTP association with gNB {site} lost")


# --- Les pannes ----------------------------------------------------------------------

def fiber_cut(b: Builder, link: str) -> None:
    port = PORT_OF[link]
    b.log(-1, "R1", f"port {port} ({link}): optical rx power -40.0 dBm, loss of signal")
    b.log(0, "R1", f"interface {port} ({link}) state changed to DOWN")
    b.alarm(0, link, "LINK_DOWN", "critical")
    b.set(link, "packet_loss_pct", 100.0)
    b.set(link, "link_utilization_pct", 0.0)
    for site in sites_behind(link):
        site_unreachable(b, site, delay=3, backhaul=True)
    b.ticket = f"Depuis {b.at(0)[:5]}, {zone(cells_behind(link))}, les abonnés n'ont plus aucun service mobile."


def link_congestion(b: Builder, link: str) -> None:
    b.alarm(0, link, "HIGH_UTILIZATION", "major")
    b.log(5, "R1", f"queue drops increasing on port {PORT_OF[link]} ({link}): output buffer full")
    b.set(link, "link_utilization_pct", 98.0)
    b.set(link, "packet_loss_pct", 4.2)
    b.set(link, "latency_ms", 95.0)
    for cell in cells_behind(link):
        b.scale(cell, "data_throughput_mbps", 0.22)
        b.alarm(240, cell, "LOW_THROUGHPUT", "minor")
    b.ticket = f"Depuis {b.at(0)[:5]} environ, {zone(cells_behind(link))}, les abonnés se plaignent d'un débit très faible."


def hardware_failure(b: Builder, element: str) -> None:
    if element in all_sites():
        b.log(0, element, "baseband unit fault: board not responding, restart failed")
        b.alarm(0, element, "HARDWARE_FAULT", "critical")
        site_unreachable(b, element, delay=2, backhaul=False)
        b.ticket = f"Depuis {b.at(0)[:5]}, {zone(cells_behind(element))}, les abonnés n'ont plus aucun service mobile."
    elif element in all_cells():
        b.log(0, element, "radio unit fault: transmitter failure")
        b.alarm(0, element, "HARDWARE_FAULT", "major")
        b.alarm(1, element, "CELL_OUT_OF_SERVICE", "major")
        cell_down(b, element)
        b.ticket = f"Depuis {b.at(0)[:5]}, {zone([element])}, les abonnés n'ont plus aucun service mobile."
    else:  # UPF
        b.log(0, "UPF", "line card fault: packet forwarding stopped")
        b.alarm(0, "UPF", "HARDWARE_FAULT", "critical")
        b.set("UPF", "packet_drop_pct", 100.0)
        b.log(3, "SMF", "PFCP heartbeat to UPF lost")
        b.alarm(3, "SMF", "UPF_UNREACHABLE", "major")
        b.alarm(40, "SMF", "SESSION_SETUP_FAILURE_HIGH", "major")
        b.set("SMF", "session_setup_success_pct", 4.0)
        for cell in all_cells():
            b.set(cell, "data_throughput_mbps", 0.0)
        b.ticket = f"Depuis {b.at(0)[:5]}, sur l'ensemble du réseau, les abonnés sont enregistrés mais n'ont plus aucun accès aux données."


def config_error(b: Builder, element: str) -> None:
    variant = b.spec.get("variant")
    if variant == "tilt":
        b.change(-600, element, "Inclinaison électrique de l'antenne modifiée de 4° à 12° (optimisation planifiée).")
        b.log(-599, element, "configuration applied: electrical_tilt=12 (previous=4)")
        b.log(-60, element, "radio link failures increasing: 37 in last 5 min")
        b.alarm(300, element, "HIGH_CALL_DROP_RATE", "minor")
        b.set(element, "call_drop_rate_pct", 6.5)
        b.set(element, "signal_quality_db", 5.0)
        b.scale(element, "data_throughput_mbps", 0.6)
        b.ticket = f"Depuis {b.at(0)[:5]} environ, {zone([element])}, les abonnés se plaignent d'appels coupés et d'un débit faible."
    elif variant == "power":
        b.change(-420, element, "Puissance d'émission modifiée de 40 W à 5 W (maintenance planifiée).")
        b.log(-419, element, "configuration applied: tx_power_w=5 (previous=40)")
        b.log(0, element, "served users decreasing: 88 handovers out in last 5 min")
        b.alarm(180, element, "COVERAGE_DEGRADED", "minor")
        b.scale(element, "connected_users", 0.4)
        b.scale(element, "data_throughput_mbps", 0.45)
        b.set(element, "signal_quality_db", 6.0)
        b.set(element, "call_drop_rate_pct", 3.1)
        b.ticket = f"Depuis {b.at(0)[:5]} environ, {zone([element])}, les abonnés signalent une couverture très dégradée."
    elif element == "R1":
        b.change(-60, "R1", "Mise à jour de la politique de routage (changement planifié).")
        b.log(-59, "R1", "configuration applied: routing policy v12 (previous=v11)")
        b.log(0, "R1", "route to core network withdrawn: no valid next hop")
        b.alarm(0, "R1", "ROUTE_LOSS", "critical")
        for site in sites_behind("R1"):
            site_unreachable(b, site, delay=3, backhaul=True)
        b.ticket = f"Depuis {b.at(0)[:5]}, sur l'ensemble du réseau, les abonnés n'ont plus aucun service mobile."
    elif element == "SMF":
        b.change(-120, "SMF", "Taille du pool d'adresses IP des abonnés réduite de 65000 à 2000 (changement planifié).")
        b.log(-119, "SMF", "configuration applied: ue_ip_pool_size=2000 (previous=65000)")
        b.log(0, "SMF", "PDU session rejected: no IP address available in pool")
        b.alarm(30, "SMF", "SESSION_SETUP_FAILURE_HIGH", "major")
        b.set("SMF", "session_setup_success_pct", 58.0)
        for cell in all_cells():
            b.scale(cell, "data_throughput_mbps", 0.6)
        b.ticket = f"Depuis {b.at(0)[:5]}, sur l'ensemble du réseau, de nombreux abonnés sont enregistrés mais n'arrivent pas à ouvrir de session de données."
    else:  # UPF
        b.change(-90, "UPF", "Règles de filtrage du trafic mises à jour (changement planifié).")
        b.log(-89, "UPF", "configuration applied: packet filter set v8 (previous=v7)")
        b.log(0, "UPF", "packets dropped by filter rule 14: 61% of uplink traffic")
        b.alarm(20, "UPF", "HIGH_PACKET_DROP", "major")
        b.set("UPF", "packet_drop_pct", 61.0)
        for cell in all_cells():
            b.scale(cell, "data_throughput_mbps", 0.39)
        b.ticket = f"Depuis {b.at(0)[:5]}, sur l'ensemble du réseau, les abonnés se plaignent d'un débit très faible."


def overload(b: Builder, element: str) -> None:
    b.log(-2, element, "CPU load 98%, request queue full")
    b.alarm(0, element, "CPU_OVERLOAD", "critical")
    b.set(element, "cpu_load_pct", 98.0)
    if element == "SMF":
        b.log(20, "SMF", "rejecting PDU session establishment requests (congestion control active)")
        b.alarm(40, "SMF", "SESSION_SETUP_FAILURE_HIGH", "major")
        b.log(40, "AMF", "timeout waiting for SMF response on session creation")
        b.set("SMF", "session_setup_success_pct", 61.0)
        for cell in all_cells():
            b.scale(cell, "data_throughput_mbps", 0.6)
        b.ticket = f"Depuis {b.at(0)[:5]}, sur l'ensemble du réseau, de nombreux abonnés sont enregistrés mais n'arrivent pas à ouvrir de session de données."
    else:  # AMF
        b.log(20, "AMF", "rejecting registration requests (congestion control active)")
        b.alarm(40, "AMF", "REGISTRATION_FAILURE_HIGH", "major")
        b.set("AMF", "registration_success_pct", 64.0)
        for cell in all_cells():
            b.scale(cell, "connected_users", 0.85)
            b.scale(cell, "data_throughput_mbps", 0.85)
        b.ticket = f"Depuis {b.at(0)[:5]}, sur l'ensemble du réseau, de nombreux abonnés n'arrivent pas à s'enregistrer sur le réseau."


def interference(b: Builder, cell: str) -> None:
    b.log(0, cell, "uplink noise rise detected: +12 dB above baseline")
    b.alarm(0, cell, "HIGH_UPLINK_NOISE", "minor")
    b.log(120, cell, "radio link failures increasing: 29 in last 5 min")
    b.alarm(180, cell, "HIGH_CALL_DROP_RATE", "minor")
    b.set(cell, "signal_quality_db", 4.0)
    b.set(cell, "call_drop_rate_pct", 5.9)
    b.scale(cell, "data_throughput_mbps", 0.55)
    b.ticket = f"Depuis {b.at(0)[:5]} environ, {zone([cell])}, les abonnés se plaignent d'appels coupés et d'un débit faible."


FAULTS = {
    "fiber_cut": fiber_cut,
    "link_congestion": link_congestion,
    "hardware_failure": hardware_failure,
    "config_error": config_error,
    "overload": overload,
    "interference": interference,
}


# --- Finitions ------------------------------------------------------------------------

def derive_link_utilization(b: Builder) -> None:
    """Un lien transporte moins de trafic quand les cellules derrière lui en écoulent moins."""
    for link in PORT_OF:
        key = (link, "link_utilization_pct")
        if key in b.forced:
            continue
        cells = cells_behind(link)
        before = sum(b.kpis[(c, "data_throughput_mbps")][0] for c in cells)
        during = sum(b.kpis[(c, "data_throughput_mbps")][1] for c in cells)
        b.kpis[key][1] = round(b.kpis[key][0] * during / before, 1)


def add_noise(b: Builder) -> None:
    """Ajoute les événements parasites prévus par le niveau de difficulté."""
    spec, root = b.spec, b.spec["element"]
    if spec["level"] in ("medium", "hard"):
        # une alarme mineure, ancienne, sur un élément étranger à la panne
        choices = [n for n in NOISE_ALARMS if n[0] not in b.involved]
        element, name, message = choices[pick(spec["id"], "alarm", len(choices))]
        offset = -(1200 + pick(spec["id"], "alarm-time", 2100))  # 20 à 55 min avant
        b.alarms.append({"time": b.at(offset), "domain": domain_of(element), "element": element, "name": name, "severity": "minor"})
        b.logs.append({"time": b.at(offset), "domain": domain_of(element), "element": element, "message": message})
    if spec["level"] == "hard":
        # un changement de configuration anodin, sur un élément touché par la panne
        # (mais pas le fautif) ; à défaut, sur un voisin du même domaine
        choices = sorted(e for e in b.involved if e != root and e in NOISE_CHANGES)
        if not choices:
            same_domain = load_network()["domains"][domain_of(root)]
            choices = sorted(e for e in same_domain if e != root and e in NOISE_CHANGES)
        element = choices[pick(spec["id"], "change", len(choices))]
        description, message = NOISE_CHANGES[element]
        offset = -(7200 + pick(spec["id"], "change-time", 7200))  # 2 à 4 h avant
        b.changes.append({"time": b.at(offset), "domain": domain_of(element), "element": element, "description": description})
        b.logs.append({"time": b.at(offset + 1), "domain": domain_of(element), "element": element, "message": message})


def build(spec: dict) -> dict:
    b = Builder(spec)
    FAULTS[spec["fault"]](b, spec["element"])  # 1 et 2 : la panne et ses conséquences
    derive_link_utilization(b)
    add_noise(b)  # 3 : les parasites
    by_time = lambda event: event["time"]
    return {
        "id": spec["id"],
        "ticket": b.ticket,
        "alarms": sorted(b.alarms, key=by_time),
        "kpis": [
            {"domain": domain_of(e), "element": e, "name": name, "before": before, "during": during}
            for (e, name), (before, during) in b.kpis.items()
        ],
        "config_changes": sorted(b.changes, key=by_time),
        "logs": sorted(b.logs, key=by_time),
    }


def write_json(path, data) -> str:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return text


def main() -> None:
    (DATA_DIR / "scenarios").mkdir(parents=True, exist_ok=True)
    everything = ""
    for spec in SPECS:
        everything += write_json(DATA_DIR / "scenarios" / f"{spec['id']}.json", build(spec))

    truth = {
        s["id"]: {"domain": domain_of(s["element"]), "element": s["element"], "fault": s["fault"]}
        for s in SPECS
    }
    splits = {name: [s["id"] for s in SPECS if s["split"] == name] for name in ("dev", "test")}
    everything += write_json(DATA_DIR / "ground_truth.json", truth)
    everything += write_json(DATA_DIR / "splits.json", splits)

    print(f"{len(SPECS)} scénarios écrits dans data/scenarios/")
    print(f"dev  ({len(splits['dev'])}) : {' '.join(splits['dev'])}")
    print(f"test ({len(splits['test'])}) : {' '.join(splits['test'])}")
    # L'empreinte change dès qu'un seul caractère des données change.
    print(f"empreinte des données : {hashlib.sha256(everything.encode()).hexdigest()[:12]}")


if __name__ == "__main__":
    main()
