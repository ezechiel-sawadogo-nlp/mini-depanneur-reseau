# Mini-dépanneur réseau multi-agents

Des agents d'intelligence artificielle qui cherchent la cause d'une panne dans un réseau mobile, sur des données simulées.

> **Toutes les données de ce projet sont inventées.** Le réseau, les pannes, les alarmes et les mesures ont été créés pour l'exercice. Ils ne décrivent le réseau d'aucun opérateur.

Ce document est en cours de rédaction. La partie ci-dessous explique le réseau et le dépannage depuis zéro. Les parties sur les agents, les résultats chiffrés et le mode d'emploi seront ajoutées quand les mesures finales seront faites.

---

## Tout comprendre depuis zéro

Cette partie ne suppose aucune connaissance. Chaque notion est d'abord présentée par une image de la vie courante, puis par son vrai nom. Tous les sigles sont repris dans le [glossaire](#glossaire) à la fin.

### 1. Un réseau mobile, c'est comme la poste

Quand vous envoyez un message depuis votre téléphone, il fait le même trajet qu'une lettre. Il part d'un guichet près de chez vous, voyage sur des routes, puis passe par un centre de tri qui sait où l'envoyer.

Ce trajet traverse trois zones, que les opérateurs appellent des **domaines**.

| Domaine | Dans l'image de la poste | Son rôle | Dans notre réseau |
|---|---|---|---|
| **RAN** | Les guichets de quartier | Parler aux téléphones par ondes radio | 2 sites, 3 cellules |
| **Transport** | Les routes et les camions | Amener le trafic des guichets jusqu'au centre | 3 liens, 1 routeur |
| **Cœur** | Le centre de tri | Reconnaître les abonnés et diriger leurs données | 3 fonctions |

**RAN** est le sigle anglais de *Radio Access Network*, le réseau d'accès radio. C'est la seule partie du réseau qui fonctionne sans fil.

#### Le guichet : un site et ses cellules

Un **site** est un lieu physique : un pylône ou un toit d'immeuble, avec des antennes et une armoire d'équipements. En 5G, l'équipement radio d'un site s'appelle un **gNB** (abréviation de *gNodeB*), ou plus simplement une station de base.

Une **cellule** est la zone couverte par une antenne du site. Imaginez un guichet avec plusieurs fenêtres, chacune tournée vers une rue différente. Si une fenêtre se bloque, seuls les habitants de cette rue sont gênés. Si le guichet entier ferme, toutes ses rues le sont. C'est exactement la différence entre la panne d'une cellule et la panne d'un site.

#### Les routes : les liens et le routeur

Un **lien** est une route entre deux équipements. Notre réseau en utilise deux sortes.

| Type de lien | Ce que c'est | L'image |
|---|---|---|
| **Fibre optique** | Un câble en verre très fin, dans lequel l'information voyage sous forme de lumière | Une route goudronnée : rapide et fiable, mais un coup de pelleteuse peut la couper |
| **Faisceau hertzien** | Une liaison sans câble entre deux antennes qui se font face | Un pont : pratique quand on ne peut pas creuser, mais plus étroit |

Un **routeur** est un carrefour. Il reçoit le trafic de plusieurs routes et l'envoie dans la bonne direction. Le nôtre est un routeur d'**agrégation** : il rassemble le trafic de tous les sites avant de l'envoyer vers le cœur.

L'ensemble des liens qui relient les sites au cœur s'appelle le **backhaul**, ou réseau de collecte en français.

#### Le centre de tri : trois employés

Le cœur de réseau n'est pas une machine unique. C'est un ensemble de programmes, appelés **fonctions**, qui ont chacun un métier.

| Sigle | Nom complet | L'employé de la poste |
|---|---|---|
| **AMF** | *Access and Mobility Management Function* | L'agent d'accueil. Il enregistre votre arrivée et sait dans quel quartier vous êtes |
| **SMF** | *Session Management Function* | Celui qui ouvre votre dossier d'envoi et prépare le chemin de vos données |
| **UPF** | *User Plane Function* | Le tapis roulant. C'est lui qui transporte réellement vos données vers Internet |

Cette répartition aide à dépanner. Si l'accueil est débordé, personne ne peut s'enregistrer. Si c'est l'ouverture des dossiers qui bloque, vous êtes enregistré mais sans Internet. Chaque symptôme pointe vers un employé.

Deux mots reviennent dans ce contexte :

- **S'enregistrer** : votre téléphone se présente au réseau, qui vérifie que vous êtes bien abonné. C'est le travail de l'AMF.
- **Ouvrir une session de données** : le réseau prépare un chemin pour vos données vers Internet. En 5G, cette session s'appelle une **session PDU** (*Protocol Data Unit*, l'unité de données qui circule). C'est le travail du SMF.

**Ce qui est simplifié ici.** Un vrai cœur de réseau 5G compte bien plus de fonctions, et un opérateur gère des milliers de sites. Notre réseau en garde le minimum pour qu'une panne puisse se propager d'un domaine à l'autre.

### 2. Notre réseau miniature

Voici tout le réseau du projet. Il compte douze éléments.

```
C1 ─┐
    ├─ S1 ── L1 ─┐
C2 ─┘            ├─ R1 ── L3 ── cœur (AMF, SMF, UPF)
C3 ─── S2 ── L2 ─┘

 └─── RAN ───┘ └─── transport ───┘ └───── cœur ─────┘
```

| Nom | Ce que c'est | Domaine |
|---|---|---|
| `C1`, `C2` | Les deux cellules du site S1 | RAN |
| `C3` | La cellule du site S2 | RAN |
| `S1`, `S2` | Les deux sites radio | RAN |
| `L1` | Le lien en fibre optique entre le site S1 et le routeur | Transport |
| `L2` | Le lien en faisceau hertzien entre le site S2 et le routeur | Transport |
| `R1` | Le routeur d'agrégation | Transport |
| `L3` | Le lien en fibre optique entre le routeur et le cœur | Transport |
| `AMF`, `SMF`, `UPF` | Les trois fonctions du cœur | Cœur |

Les lettres sont de simples initiales : `C` pour cellule, `S` pour site, `L` pour lien, `R` pour routeur.

#### Qui a besoin de qui

La notion la plus importante du projet est la **dépendance**. Un élément dépend d'un autre quand il ne peut pas fonctionner sans lui.

Reprenez le schéma et suivez le trajet d'un message envoyé depuis la cellule `C1`. Il passe par `S1`, puis `L1`, puis `R1`, puis `L3`, puis le cœur. Si un seul de ces éléments tombe, le message n'arrive pas. On dit que `C1` dépend de tous ces éléments.

| Cellule | Son chemin jusqu'au cœur |
|---|---|
| `C1` | S1, L1, R1, L3, cœur |
| `C2` | S1, L1, R1, L3, cœur |
| `C3` | S2, L2, R1, L3, cœur |

Deux mots servent à se repérer sur ce chemin. Un élément est **en aval** quand il est du côté des téléphones, et **en amont** quand il est du côté du cœur. `L1` est en amont de `S1`. Une panne en amont gêne tout ce qui se trouve en aval, jamais l'inverse.

### 3. Comment un réseau dit qu'il va mal

Un équipement ne peut pas parler. Il laisse quatre sortes de traces, et tout le dépannage consiste à les lire.

| Trace | L'image | Ce qu'elle contient |
|---|---|---|
| **Alarme** | Le voyant rouge sur le tableau de bord d'une voiture | Un nom court, l'équipement concerné, l'heure et une gravité |
| **Mesure** | Les compteurs de la voiture : vitesse, température | Un chiffre suivi dans le temps, qu'on compare avant et pendant l'incident |
| **Log** | Le journal de bord d'un capitaine | Une phrase datée, écrite par l'équipement, plus détaillée qu'une alarme |
| **Changement de configuration** | Le carnet d'entretien : « pneus changés le 3 mars » | Un réglage modifié volontairement par un technicien, avec son heure |

Une alarme dit *qu'*il y a un problème. Le log dit souvent *pourquoi*. Le changement de configuration dit parfois *qui l'a provoqué*.

Une mesure de performance s'appelle un **KPI**, sigle de *Key Performance Indicator*, indicateur clé de performance.

#### Les gravités d'une alarme

| Gravité | Sens |
|---|---|
| `critical` | Le service est coupé |
| `major` | Le service est fortement dégradé |
| `minor` | Un simple avertissement, le service fonctionne |

#### Les mesures de notre réseau

| Nom dans les données | Sur quel élément | Ce que ça mesure |
|---|---|---|
| `connected_users` | cellule | Le nombre de téléphones connectés à la cellule |
| `data_throughput_mbps` | cellule | Le débit de données, en mégabits par seconde (Mbps) |
| `call_drop_rate_pct` | cellule | Le pourcentage d'appels coupés avant la fin |
| `signal_quality_db` | cellule | La qualité du signal radio, en décibels (dB). Plus le chiffre est haut, mieux c'est |
| `packet_loss_pct` | lien | Le pourcentage de paquets perdus en route |
| `link_utilization_pct` | lien | Le taux d'occupation du lien. À 100 %, la route est pleine |
| `latency_ms` | lien | Le temps de trajet d'un paquet, en millisecondes (ms) |
| `registration_success_pct` | AMF | Le pourcentage d'enregistrements réussis |
| `session_setup_success_pct` | SMF | Le pourcentage d'ouvertures de session réussies |
| `packet_drop_pct` | UPF | Le pourcentage de paquets rejetés par l'UPF |
| `cpu_load_pct` | AMF, SMF, UPF | La charge du processeur. CPU signifie *Central Processing Unit* |

Un **paquet** est un petit morceau de données. Tout ce qui circule sur un réseau est découpé en paquets, comme un déménagement est découpé en cartons. Le suffixe `pct` veut dire « pour cent ».

**Ce qui est simplifié ici.** Les noms d'alarmes et de mesures sont inventés pour être lisibles. Ils ne reprennent la nomenclature d'aucun constructeur, et un vrai réseau suit des centaines de mesures par équipement.

### 4. Les six pannes

Le projet simule six types de panne. Chacune a son étiquette, utilisée partout dans le code.

| Étiquette | En français | L'image | Ce qu'on observe |
|---|---|---|---|
| `fiber_cut` | Fibre coupée | La route est coupée par un éboulement | Le lien perd 100 % des paquets, tout ce qui est en aval s'éteint |
| `link_congestion` | Lien saturé | Un embouteillage | Le lien est occupé à 98 %, les paquets arrivent en retard ou se perdent, le débit s'effondre |
| `hardware_failure` | Panne matérielle | Une machine tombe en panne | L'équipement signale lui-même un défaut et cesse de fonctionner |
| `config_error` | Erreur de configuration | Un réglage mal fait après un passage au garage | Un changement de configuration précède de peu les symptômes |
| `overload` | Surcharge | Un employé débordé par la file d'attente | Le processeur est à 98 %, la fonction refuse des demandes |
| `interference` | Brouillage radio | Quelqu'un crie à côté de vous pendant un appel | La qualité du signal chute sur une cellule, sans aucun changement de réglage |

Deux paires se ressemblent et sont faciles à confondre :

- **Saturation et surcharge.** La saturation touche un *lien*, la surcharge touche une *fonction du cœur*. Dans l'image : l'embouteillage est sur la route, le débordement est au bureau.
- **Erreur de configuration et brouillage.** Les deux dégradent une cellule. La différence est dans le carnet d'entretien : avant une erreur de configuration, quelqu'un a modifié un réglage. Avant un brouillage, personne n'a touché à rien.

### 5. Une panne ne reste jamais seule

Quand un élément tombe, tous ceux qui dépendent de lui le ressentent, et chacun lève sa propre alarme. Une seule panne produit donc une avalanche de signaux. C'est ce qu'on appelle la **propagation**.

Voici l'essentiel de ce que le réseau enregistre quand la fibre `L1` est coupée, dans le scénario `SC01` :

```
heure     domaine    élément  type    détail
10:01:01  transport  R1       LOG     port P1 (L1): optical rx power -40.0 dBm, loss of signal
10:01:02  transport  L1       ALARME  LINK_DOWN (critical)
10:01:05  ran        S1       ALARME  BACKHAUL_LOSS (critical)
10:01:05  ran        C1       ALARME  CELL_OUT_OF_SERVICE (major)
10:01:05  ran        C2       ALARME  CELL_OUT_OF_SERVICE (major)
10:01:09  core       AMF      ALARME  GNB_UNREACHABLE (major)
10:01:09  core       AMF      LOG     SCTP association with gNB S1 lost
```

Ligne par ligne :

| Ligne | Traduction |
|---|---|
| `optical rx power -40.0 dBm, loss of signal` | Le routeur ne reçoit presque plus de lumière sur le port où arrive `L1`. `rx` veut dire réception. Le **dBm** est une unité de puissance : -40 dBm est une lumière si faible qu'elle est illisible |
| `LINK_DOWN` | Le lien `L1` est déclaré hors service |
| `BACKHAUL_LOSS` | Le site `S1` constate qu'il a perdu sa liaison vers le cœur |
| `CELL_OUT_OF_SERVICE` | Les cellules `C1` et `C2` s'arrêtent, puisqu'elles ne peuvent plus rien acheminer |
| `GNB_UNREACHABLE` | L'AMF signale que la station de base `S1` ne répond plus |
| `SCTP association with gNB S1 lost` | Le canal de dialogue entre l'AMF et `S1` est rompu. **SCTP** (*Stream Control Transmission Protocol*) est le protocole utilisé pour ce dialogue |

Cinq alarmes, trois domaines touchés, une seule panne. Les deux premières lignes désignent la **cause racine** : l'événement initial qui explique tous les autres. Les quatre alarmes suivantes sont des **symptômes**, c'est-à-dire des conséquences.

Dépanner, c'est retrouver la cause racine au milieu des symptômes. Un technicien qui réparerait les cellules `C1` et `C2` perdrait son temps : elles ne sont pas en panne, elles sont coupées du monde.

### 6. Trouver le coupable : le raisonnement par périmètre

Avant de lire le moindre log, un bon dépanneur regarde **qui est touché et qui ne l'est pas**. C'est le raisonnement par périmètre. Il tient en trois gestes.

**Premier geste : écrire le chemin de chaque cellule.** C'est le tableau de la partie 2.

**Deuxième geste : garder ce que les cellules en panne ont en commun.** Si `C1` et `C2` sont en panne, elles partagent `S1`, `L1`, `R1`, `L3` et le cœur. Le coupable est forcément dans cette liste.

**Troisième geste : retirer tout ce qu'une cellule saine utilise aussi.** Si `C3` fonctionne, alors `R1`, `L3` et le cœur fonctionnent, puisque `C3` passe par eux. On les raye.

Il reste deux **suspects** : `S1` et `L1`. Les éléments rayés sont **innocentés**.

Retenez la règle qui se cache derrière le troisième geste : ce qui marche encore innocente autant d'éléments que ce qui est en panne en accuse.

L'image est celle d'une panne de courant dans un immeuble. Si tout votre étage est dans le noir mais que l'étage du dessus est éclairé, le problème n'est pas au compteur général. Il est sur le tableau de votre étage.

#### Deux pannes jumelles

Le périmètre désigne les suspects, il ne choisit pas entre eux. Les scénarios `SC01` et `SC04` le montrent : même ticket, mêmes cellules en panne, deux causes différentes.

| | `SC01` : fibre coupée sur `L1` | `SC04` : panne matérielle du site `S1` |
|---|---|---|
| Alarme dans le transport | `LINK_DOWN` sur `L1` | aucune |
| Perte de paquets sur `L1` | 100 % | 0,1 %, valeur normale |
| Taux d'occupation de `L1` | 0 % | 0 % |
| Alarme sur le site | `BACKHAUL_LOSS` | `HARDWARE_FAULT` |

La troisième ligne est un piège. Un lien occupé à 0 % n'est pas forcément cassé. Dans `SC04`, il est vide parce que les cellules derrière lui sont éteintes : la route est en bon état, mais plus personne ne roule dessus. C'est la perte de paquets qui dit si un lien fonctionne.

### 7. Les événements parasites

Dans un vrai réseau, il se passe toujours autre chose en même temps que la panne. Une porte d'armoire restée ouverte, un certificat qui expire dans trois semaines, une mise à jour faite le matin. Ces événements sont réels, mais ils n'ont aucun rapport avec l'incident. On les appelle ici des **parasites**.

Le projet en ajoute de deux sortes dans les scénarios les plus difficiles :

| Parasite | Exemple | Pourquoi il trompe |
|---|---|---|
| Une alarme mineure et ancienne | `CABINET_DOOR_OPEN` sur un site, trente minutes avant la panne | C'est l'événement le plus ancien de la liste, et on est tenté de croire que le plus ancien est la cause |
| Un changement de configuration anodin | Mise à jour de la liste des cellules voisines, deux heures et demie avant | Il porte sur un élément réellement touché par la panne, donc il ressemble à un coupable |

Deux questions suffisent presque toujours à les écarter. L'événement est-il proche du début des symptômes ? L'élément concerné fait-il partie des suspects ?

---

## Glossaire

| Terme | Signification |
|---|---|
| **Alarme** | Message émis par un équipement quand il détecte un état anormal |
| **AMF** | *Access and Mobility Management Function*. Fonction du cœur qui enregistre les abonnés et suit leur position |
| **Amont, aval** | En amont : du côté du cœur. En aval : du côté des téléphones |
| **Backhaul** | Ensemble des liens qui relient les sites radio au cœur. En français : réseau de collecte |
| **Cause racine** | L'événement initial qui explique tous les symptômes d'un incident |
| **Cellule** | Zone couverte par une antenne d'un site radio |
| **Cœur de réseau** | Partie centrale du réseau, qui reconnaît les abonnés et dirige leurs données |
| **CPU** | *Central Processing Unit*, le processeur |
| **dB** | Décibel, unité utilisée ici pour la qualité du signal radio |
| **dBm** | Décibel-milliwatt, unité de puissance. Sert ici à mesurer la lumière reçue sur une fibre |
| **Dépendance** | Un élément dépend d'un autre quand il ne peut pas fonctionner sans lui |
| **Domaine** | Grande zone du réseau : RAN, transport ou cœur |
| **Faisceau hertzien** | Liaison sans câble entre deux antennes qui se font face |
| **Fibre optique** | Câble en verre dans lequel l'information voyage sous forme de lumière |
| **gNB** | *gNodeB*, la station de base d'un réseau 5G |
| **KPI** | *Key Performance Indicator*, une mesure de performance suivie dans le temps |
| **Latence** | Temps de trajet d'un paquet |
| **Log** | Ligne de texte datée, écrite par un équipement |
| **Mbps** | Mégabit par seconde, unité de débit |
| **Paquet** | Petit morceau de données. Tout ce qui circule sur un réseau est découpé en paquets |
| **Parasite** | Événement réel mais sans rapport avec la panne étudiée |
| **Périmètre** | L'ensemble des éléments touchés par une panne, comparé à ceux qui fonctionnent encore |
| **Propagation** | Le fait qu'une panne produise des symptômes sur tout ce qui dépend de l'élément fautif |
| **RAN** | *Radio Access Network*, le réseau d'accès radio |
| **Routeur** | Équipement qui reçoit le trafic et l'envoie dans la bonne direction |
| **SCTP** | *Stream Control Transmission Protocol*, protocole utilisé pour le dialogue entre une station de base et l'AMF |
| **Session PDU** | *Protocol Data Unit session*. En 5G, le chemin ouvert pour les données d'un abonné |
| **Site** | Lieu physique qui porte les antennes et les équipements radio |
| **SMF** | *Session Management Function*. Fonction du cœur qui ouvre et gère les sessions de données |
| **Symptôme** | Conséquence visible d'une panne, par opposition à sa cause |
| **Ticket** | Description d'un incident telle qu'elle arrive à l'équipe de dépannage |
| **UPF** | *User Plane Function*. Fonction du cœur qui transporte les données des abonnés vers Internet |

## Sources

- [3GPP TR 21.915, répartition des fonctions entre la radio et le cœur](https://itecspec.com/3gpp/21.915/s/5.5.1)
