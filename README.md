# Mini-dépanneur réseau multi-agents

Des agents d'intelligence artificielle qui cherchent la cause d'une panne dans un réseau mobile, sur des données simulées.

> **Toutes les données de ce projet sont inventées.** Le réseau, les pannes, les alarmes et les mesures ont été créés pour l'exercice. Ils ne décrivent le réseau d'aucun opérateur.

## Sommaire

1. [L'essentiel en une page](#lessentiel-en-une-page) : pour qui a deux minutes
2. [Tout comprendre depuis zéro](#tout-comprendre-depuis-zéro) : le réseau, les pannes, les agents, expliqués sans prérequis
3. [Le projet pas à pas](#le-projet-pas-à-pas) : ce que fait exactement le code
4. [Ce que j'ai mesuré](#ce-que-jai-mesuré) : les chiffres
5. [Ce qui n'a pas marché](#ce-qui-na-pas-marché) : les échecs et ce qu'ils m'ont appris
6. [Limites et pistes](#limites-et-pistes)
7. [Refaire tourner le projet](#refaire-tourner-le-projet)
8. [Organisation du dépôt](#organisation-du-dépôt)
9. [Glossaire](#glossaire) : tous les sigles et tous les termes
10. [Sources](#sources)

---

## L'essentiel en une page

**La question.** Quand un réseau mobile tombe en panne, une seule cause produit une avalanche d'alarmes dans plusieurs parties du réseau. Peut-on confier à des agents d'IA le travail de remonter jusqu'à cette cause ? Et vaut-il mieux un seul agent qui voit tout, ou une équipe de spécialistes coordonnée par un chef ?

**Ce que j'ai construit.**

- Un réseau fictif de 12 éléments, répartis en trois domaines : la radio, le transport et le cœur.
- 15 pannes simulées dont la cause est connue, chacune avec ses alarmes, ses mesures, ses logs et ses changements de configuration. 5 servent à mettre le système au point, 10 servent à le noter.
- Trois systèmes de diagnostic, comparés sur les mêmes pannes :

| Système | En une phrase |
|---|---|
| **Agent seul** | Un agent qui peut consulter les trois domaines et décide lui-même quoi lire |
| **Agent seul aidé** | Le même, avec les trois aides données à l'équipe, pour que la comparaison soit équitable |
| **Équipe** | Trois agents spécialistes, un par domaine, qui ne voient chacun que leurs données, et un orchestrateur qui tranche à partir de leurs rapports |

```
                          ticket d'incident
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
         agent radio       agent transport       agent cœur        chacun ne lit
              │                   │                   │            que son domaine
           rapport             rapport             rapport
              └───────────────────┬───────────────────┘
                                  ▼
             analyse de périmètre, calculée par le code
                                  ▼
                            orchestrateur                          ne voit aucune
                                  ▼                                donnée brute
            diagnostic : domaine, élément, type de panne
```

Le schéma montre qui reçoit quoi. Dans le programme, les trois agents travaillent l'un après l'autre.

**Le résultat**, sur les 10 pannes de test que les systèmes n'avaient jamais vues :

| | Agent seul | Agent seul aidé | Équipe |
|---|---|---|---|
| **Cause racine exacte** | 6/10 | **8/10** | 5/10 |
| dont pannes locales (3) | 3/3 | 3/3 | 3/3 |
| dont pannes touchant tout le réseau (7) | 3/7 | 5/7 | 2/7 |
| Sources de données lues, sur 12 | 3,1 | 6,7 | 12 |
| Tokens lus par diagnostic | 6 154 | 20 823 | 9 490 |
| Tokens écrits par diagnostic | 623 | 1 878 | 799 |

**Ce qu'il faut en retenir.**

- **L'équipe n'a pas fait mieux que l'agent seul.** Elle avait obtenu 5/5 sur les pannes de mise au point. Sur les pannes de test, elle tombe à 5/10.
- **Le point faible est le passage de relais.** Dans 9 cas sur 10, le spécialiste du domaine fautif avait écrit la cause exacte dans son rapport. L'orchestrateur, qui ne lit que des résumés, ne l'a retrouvée que 5 fois sur ces 9.
- **Un bon score peut cacher un mauvais raisonnement.** L'agent seul aidé obtient 8/10, mais dans au moins 4 exécutions sur 10 il a fait semblant de consulter les données : il a inventé des résultats, ou écrit ses demandes d'outils en texte sans qu'elles soient exécutées.
- **Ces écarts sont une tendance, pas une preuve.** 10 pannes, une exécution par panne, un seul modèle : c'est trop peu pour conclure qu'une architecture est meilleure que l'autre.

**Avec quoi.** Python, le modèle de langage `qwen2.5:7b` exécuté sur mon ordinateur avec Ollama, et la bibliothèque LangGraph. Tout est gratuit et libre (*open source*). Aucun service payant, aucune donnée envoyée à l'extérieur.

Le détail de chaque chiffre est dans [Ce que j'ai mesuré](#ce-que-jai-mesuré). Les tableaux principaux se recalculent avec `python -m netdiag.analyze`.

---

## Tout comprendre depuis zéro

Cette partie ne suppose aucune connaissance. Chaque notion est d'abord présentée par une image de la vie courante, puis par son vrai nom. Tous les sigles sont repris dans le [glossaire](#glossaire) à la fin.

Les chapitres 1 à 7 expliquent le réseau et ses pannes. Les chapitres 8 à 13 expliquent les agents et la façon de les évaluer.

### 1. Un réseau mobile, c'est comme la poste

Quand vous envoyez un message depuis votre téléphone, il fait le même trajet qu'une lettre. Il part d'un guichet près de chez vous, voyage sur des routes, puis passe par un centre de tri qui sait où l'envoyer.

Ce trajet traverse trois zones, que les **opérateurs**, les entreprises qui exploitent ces réseaux, appellent des **domaines**.

| Domaine | Dans l'image de la poste | Son rôle | Dans notre réseau |
|---|---|---|---|
| **RAN** | Les guichets de quartier | Parler aux téléphones par ondes radio | 2 sites, 3 cellules |
| **Transport** | Les routes et les camions | Amener le trafic des guichets jusqu'au centre | 3 liens, 1 routeur |
| **Cœur** | Le centre de tri | Reconnaître les abonnés et diriger leurs données | 3 fonctions |

**RAN** est le sigle anglais de *Radio Access Network*, le réseau d'accès radio. C'est la seule partie du réseau qui fonctionne sans fil. Dans la suite, ce domaine est aussi appelé simplement « la radio ».

Le **trafic** est l'ensemble des données qui circulent sur le réseau à un moment donné.

Dans les données et dans le code du projet, les trois domaines portent leur nom anglais : `ran`, `transport` et `core`. *Core* veut dire cœur.

#### Le guichet : un site et ses cellules

Un **site** est un lieu physique : un pylône ou un toit d'immeuble, avec des antennes et une armoire d'équipements. En **5G**, la cinquième génération de réseau mobile, l'équipement radio d'un site s'appelle un **gNB**, ou plus simplement une station de base. gNB est l'abréviation de *gNodeB* : *NodeB* est le nom des stations de base dans les normes, et le *g* a été ajouté pour la 5G.

Une **cellule** est la zone couverte par une antenne du site. Imaginez un guichet avec plusieurs fenêtres, chacune tournée vers une rue différente. Si une fenêtre se bloque, seuls les habitants de cette rue sont gênés. Si le guichet entier ferme, toutes ses rues le sont. C'est exactement la différence entre la panne d'une cellule et la panne d'un site.

#### Les routes : les liens et le routeur

Un **lien** est une route entre deux équipements. Notre réseau en utilise deux sortes.

| Type de lien | Ce que c'est | L'image |
|---|---|---|
| **Fibre optique** | Un câble en verre très fin, dans lequel l'information voyage sous forme de lumière | Une route goudronnée : rapide et fiable, mais un coup de pelleteuse peut la couper |
| **Faisceau hertzien** | Une liaison sans câble entre deux antennes qui se font face | Un pont : pratique quand on ne peut pas creuser, mais plus étroit. Il fait passer moins de trafic |

Un **routeur** est un carrefour. Il reçoit le trafic de plusieurs routes et l'envoie dans la bonne direction. Le nôtre est un routeur d'**agrégation** : il rassemble le trafic de tous les sites avant de l'envoyer vers le cœur.

L'ensemble des liens qui relient les sites au cœur s'appelle le **backhaul**, ou réseau de collecte en français.

#### Le centre de tri : trois employés

Le cœur de réseau n'est pas une machine unique. C'est un ensemble de programmes, appelés **fonctions**, qui ont chacun un métier.

| Sigle | Nom complet | L'employé de la poste |
|---|---|---|
| **AMF** | *Access and Mobility Management Function*, fonction de gestion de l'accès et de la mobilité | L'agent d'accueil. Il enregistre votre arrivée et sait dans quel quartier vous êtes |
| **SMF** | *Session Management Function*, fonction de gestion des sessions | Celui qui ouvre votre dossier d'envoi et prépare le chemin de vos données |
| **UPF** | *User Plane Function*, fonction du plan utilisateur | Le manutentionnaire. C'est lui qui transporte réellement vos données vers Internet |

Le **plan utilisateur** est la partie du réseau qui transporte les données des abonnés, par opposition à celle qui organise ce transport.

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

└─ RAN ─┘    └─ transport ─┘    └────── cœur ──────┘
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

Le plan du réseau, avec ses éléments et leurs dépendances, s'appelle sa **topologie**.

### 3. Comment un réseau dit qu'il va mal

Un équipement ne peut pas parler. Il laisse quatre sortes de traces, et tout le dépannage consiste à les lire.

| Trace | L'image | Ce qu'elle contient |
|---|---|---|
| **Alarme** | Le voyant rouge sur le tableau de bord d'une voiture | Un nom court, l'équipement concerné, l'heure et une gravité |
| **Mesure** | Les compteurs de la voiture : vitesse, température | Un chiffre suivi dans le temps, qu'on compare avant et pendant l'incident |
| **Log** | Le journal de bord, tenu par le conducteur | Une phrase datée, écrite par l'équipement, plus détaillée qu'une alarme |
| **Changement de configuration** | Le carnet d'entretien : « pneus changés le 3 mars » | Un réglage modifié volontairement par un technicien, avec son heure |

Une alarme dit *qu'*il y a un problème. Le log dit souvent *pourquoi*. Le changement de configuration dit parfois *qui l'a provoqué*.

Une mesure de performance s'appelle un **KPI**, sigle de *Key Performance Indicator*, indicateur clé de performance.

#### Les gravités d'une alarme

| Gravité | Sens |
|---|---|
| `critical` (critique) | La défaillance la plus grave : un équipement ou un lien entier est hors d'usage |
| `major` (majeure) | Le service est coupé ou fortement dégradé sur une partie du réseau |
| `minor` (mineure) | Un avertissement ou une dégradation légère |

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
| `cpu_load_pct` | AMF, SMF, UPF | La charge du processeur, la puce qui exécute les calculs d'une machine. En anglais **CPU**, *Central Processing Unit* |

Le **débit** est la quantité de données transmise chaque seconde. Il se compte en bits, la plus petite unité d'information : un mégabit vaut un million de bits.

Un **paquet** est un petit morceau de données. Tout ce qui circule sur un réseau est découpé en paquets, comme un déménagement est découpé en cartons. Le suffixe `pct` veut dire « pour cent ».

**Ce qui est simplifié ici.** Les noms d'alarmes et de mesures sont inventés pour être lisibles. Ils ne reprennent les noms utilisés par aucun fabricant d'équipements, et un vrai réseau suit des centaines de mesures par équipement.

### 4. Les six pannes

Le projet simule six types de panne. Chacune a son étiquette, utilisée partout dans le code.

| Étiquette | En français | L'image | Ce qu'on observe |
|---|---|---|---|
| `fiber_cut` | Fibre coupée | La route est coupée par un éboulement | Le lien perd 100 % des paquets, tout ce qui est en aval s'éteint |
| `link_congestion` | Lien saturé | Un embouteillage | Le lien est occupé à 98 %, les paquets arrivent en retard ou se perdent, le débit s'effondre |
| `hardware_failure` | Panne matérielle | Une machine tombe en panne | L'équipement signale lui-même un défaut et cesse de fonctionner |
| `config_error` | Erreur de configuration | Un réglage mal fait après un passage au garage | Un changement de configuration précède de peu les symptômes |
| `overload` | Surcharge | Un employé débordé par la file d'attente | Le processeur est à 98 %, la fonction refuse des demandes |
| `interference` | Brouillage radio | Quelqu'un crie à côté de vous pendant un appel | La qualité du signal chute sur une cellule, sans aucun changement de réglage sur cette cellule |

Deux paires se ressemblent et sont faciles à confondre :

- **Saturation et surcharge.** La saturation touche un *lien*, la surcharge touche une *fonction du cœur*. Dans l'image : l'embouteillage est sur la route, le débordement est au bureau.
- **Erreur de configuration et brouillage.** Sur une cellule, les deux se ressemblent. La différence est dans le carnet d'entretien : avant une erreur de configuration, quelqu'un a modifié un réglage de la cellule. Avant un brouillage, personne n'y a touché.

### 5. Une panne ne reste jamais seule

Quand un élément tombe, tous ceux qui dépendent de lui le ressentent, et chacun lève sa propre alarme. Une seule panne produit donc une avalanche de signaux. C'est ce qu'on appelle la **propagation**.

Chaque panne simulée du projet s'appelle un **scénario**. Il y en a quinze, numérotés `SC01` à `SC15`. Un scénario commence par un **ticket** : la phrase par laquelle l'incident est signalé aux dépanneurs, par exemple « Depuis 10:01, dans la zone du site S1, les abonnés n'ont plus aucun service mobile. »

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
| `optical rx power -40.0 dBm, loss of signal` | Le routeur ne reçoit presque plus de lumière sur le port où arrive `L1`. Un **port** est la prise du routeur où se branche un lien : `P1` est celle de `L1`. *Optical* : optique. `rx` : réception. *Loss of signal* : perte du signal. Le **dBm** est une unité de puissance : -40 dBm est une lumière si faible qu'elle est illisible |
| `LINK_DOWN` | Le lien `L1` est déclaré hors service |
| `BACKHAUL_LOSS` | Le site `S1` constate qu'il a perdu sa liaison vers le cœur |
| `CELL_OUT_OF_SERVICE` | Les cellules `C1` et `C2` s'arrêtent, puisqu'elles ne peuvent plus rien acheminer |
| `GNB_UNREACHABLE` | L'AMF signale que la station de base `S1` ne répond plus |
| `SCTP association with gNB S1 lost` | Le canal de dialogue entre l'AMF et `S1` est rompu. **SCTP** (*Stream Control Transmission Protocol*) est le protocole utilisé pour ce dialogue. Un **protocole** est un ensemble de règles que deux équipements suivent pour se parler |

Cinq alarmes, trois domaines touchés, une seule panne. Les deux premières lignes désignent la **cause racine** : l'événement initial qui explique tous les autres. Les quatre alarmes suivantes sont des **symptômes**, c'est-à-dire des conséquences.

Dépanner, c'est retrouver la cause racine au milieu des symptômes. Un technicien qui réparerait les cellules `C1` et `C2` perdrait son temps : elles ne sont pas en panne, elles sont coupées du monde.

### 6. Trouver le coupable : le raisonnement par périmètre

Avant de lire le moindre log, un bon dépanneur regarde **qui est touché et qui ne l'est pas**. C'est le raisonnement par périmètre. Il tient en trois gestes.

**Premier geste : écrire le chemin de chaque cellule.** C'est le tableau du chapitre 2.

**Deuxième geste : garder ce que les cellules en panne ont en commun.** Si `C1` et `C2` sont en panne, elles partagent `S1`, `L1`, `R1`, `L3` et le cœur. Le coupable est forcément dans cette liste.

**Troisième geste : retirer tout ce qu'une cellule saine utilise aussi.** Si `C3` fonctionne, alors `R1`, `L3` et le cœur fonctionnent, puisque `C3` passe par eux. On les raye.

Il reste deux **suspects** : `S1` et `L1`. Les éléments rayés sont **innocentés**.

Les éléments que les cellules en panne n'ont pas en commun, comme `S2` ou `L2`, n'entrent pas dans ce calcul : ils ne peuvent pas expliquer à eux seuls la panne de `C1` et de `C2`.

Retenez la règle qui se cache derrière le troisième geste : ce qui marche encore innocente autant d'éléments que ce qui est en panne en accuse.

L'image est celle d'une panne de courant dans un immeuble. Si tout votre étage est dans le noir mais que l'étage du dessus est éclairé, le problème n'est pas au compteur général. Il est sur le tableau électrique de votre étage.

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

Dans un vrai réseau, il se passe toujours autre chose en même temps que la panne. Une porte d'armoire restée ouverte, un certificat de sécurité qui expire dans trois semaines, une mise à jour faite le matin. Ces événements sont réels, mais ils n'ont aucun rapport avec l'incident. On les appelle ici des **parasites**.

Le projet en ajoute de deux sortes, dans dix scénarios sur quinze :

| Parasite | Exemple | Pourquoi il trompe |
|---|---|---|
| Une alarme mineure et ancienne | `CABINET_DOOR_OPEN` sur un site, trente minutes avant la panne | C'est l'événement le plus ancien de la liste, et on est tenté de croire que le plus ancien est la cause |
| Un changement de configuration anodin | Mise à jour de la liste des cellules voisines, deux heures et demie avant | Il porte sur un élément touché par la panne ou sur l'un de ses voisins, donc il ressemble à un coupable |

Deux questions suffisent presque toujours à les écarter. L'événement est-il proche du début des symptômes ? L'élément concerné fait-il partie des suspects ?

### 8. Un modèle de langage, c'est un stagiaire qui a tout lu

Un **modèle de langage** est un programme qui a lu une quantité immense de textes et qui a appris une seule chose : deviner la suite d'un texte. On lui donne un début, il écrit ce qui vient le plus probablement après. Son nom anglais est **LLM**, pour *Large Language Model*, grand modèle de langage.

L'image utilisée dans toute la suite est celle d'un **stagiaire brillant**. Il a lu des milliers de livres, il écrit bien, il raisonne. Mais il n'a jamais mis les pieds dans votre entreprise, et il n'a aucun souvenir de la veille. Il ne sait rien de votre réseau ni de la panne en cours. Tout ce qu'il en saura, il devra le lire dans ce qu'on pose sur son bureau.

| Vrai nom | Dans l'image du stagiaire | Ce que c'est |
|---|---|---|
| **Prompt** | Tout ce qu'on pose sur son bureau | Le texte donné au modèle |
| **Prompt système** | Sa fiche de poste | Les consignes permanentes : son rôle, sa méthode, ce qu'on attend de lui. Dans la suite : « les consignes » |
| **Token** | Une syllabe | Le morceau de texte que le modèle lit ou écrit en une fois. Un mot courant fait un token, un mot long ou rare en fait plusieurs |
| **Fenêtre de contexte** | La surface de son bureau | La quantité maximale de texte qu'il peut avoir sous les yeux en même temps. Ici 8 192 tokens. Ce qui dépasse tombe du bureau |
| **Température** | Son degré de fantaisie | À 0, il choisit toujours le mot le plus probable. Plus elle monte, plus il varie. Ici elle vaut 0 |
| **Hallucination** | Il invente plutôt que d'avouer qu'il ne sait pas | Le modèle écrit une information fausse avec la même assurance qu'une vraie |

Deux faits mesurés dans ce projet découlent de ce tableau.

**Lire est rapide, écrire est lent.** Le modèle lit un texte bien plus vite qu'il n'en écrit un, car il écrit ses tokens un par un. Sur mon ordinateur, il en écrit 3 à 4 par seconde. La durée d'un diagnostic dépend donc surtout de la longueur de ce que le modèle écrit.

**Le modèle n'a pas de mémoire.** À chaque fois qu'on lui parle, il relit toute la conversation depuis le début. Ce qui ressemble à une mémoire n'est que l'historique qu'on lui repose sur le bureau.

#### Le modèle du projet

| | |
|---|---|
| Nom | `qwen2.5:7b` |
| Publié par | L'équipe Qwen de l'entreprise Alibaba, sous une licence libre (Apache 2.0) |
| Taille | Environ 7 milliards de **paramètres**. C'est le sens de `7b` : *7 billion*, sept milliards en anglais. `2.5` est le numéro de version |
| Où il tourne | Sur mon ordinateur, grâce au logiciel **Ollama** |

Un **paramètre** est l'un des nombres que le modèle a réglés pendant son apprentissage. Plus il y en a, plus le modèle est capable, et plus il est lourd à faire tourner.

**Ollama** est un logiciel libre qui télécharge un modèle et le fait fonctionner sur votre propre machine. Rien ne part sur Internet. Un modèle utilisé ainsi est dit **local**.

Un logiciel **libre**, *open source* en anglais, est un logiciel dont le code est public et que chacun peut utiliser gratuitement.

Ce choix a un prix. Un modèle de 7 milliards de paramètres est petit par rapport à ceux des grands services en ligne, et mon ordinateur le fait tourner sur son processeur, sans carte graphique. Une carte graphique est une puce spécialisée dans les calculs massifs, sur laquelle ces modèles tournent bien plus vite. Le mien est donc lent, et il commet des erreurs qu'un modèle plus gros ferait sans doute moins souvent. Je ne l'ai pas mesuré : ce projet n'utilise qu'un seul modèle.

**Ce qui est simplifié ici.** « Deviner la suite d'un texte » résume le principe, pas la technique. L'explication suffit pour comprendre le projet, pas pour construire un modèle.

### 9. Donner des mains au stagiaire : les outils

Un modèle de langage ne fait qu'écrire du texte. Il ne peut pas ouvrir un fichier ni interroger une base de données. Pour qu'il enquête sur une panne, il faut lui donner des **outils**.

Un outil est une fonction de mon programme que le modèle a le droit de *demander*. Le mot important est « demander ».

En programmation, une **fonction** est un petit morceau de programme qui accomplit une tâche précise quand on l'appelle. Ce mot n'a rien à voir ici avec les fonctions du cœur de réseau du chapitre 1.

L'image : le stagiaire n'a pas accès aux archives. Il remplit un **bon de demande** et le tend à l'archiviste. L'archiviste va chercher le document et le pose sur son bureau. Le stagiaire ne touche jamais aux étagères. L'archiviste, c'est mon programme.

Voici le même échange avec les vrais noms :

| Étape | Ce qui se passe |
|---|---|
| 1 | Mon programme décrit les outils au modèle : leur nom, à quoi ils servent, quels arguments ils attendent |
| 2 | Le modèle répond par une demande au lieu d'une phrase : `get_alarms(domain="transport")` |
| 3 | Mon programme exécute la fonction |
| 4 | Le résultat est ajouté à la conversation, et le modèle reprend sa réflexion |

Un **argument** est une précision donnée à une fonction. `get_alarms(domain="transport")` se lit : la fonction `get_alarms`, avec l'argument `domain` qui vaut `transport`.

Ce mécanisme s'appelle l'**appel d'outil**, *tool calling* en anglais. Il tient en une règle : **le modèle demande, le code exécute.** C'est donc le code, et non le modèle, qui décide de ce qui est permis.

Voici un échange réel, sur le scénario `SC01` :

```
[modèle] demande get_alarms(domain='transport')
  [outil] get_alarms a renvoyé :
      10:01:02 L1 LINK_DOWN (critical)
```

#### Les quatre outils du projet

| Outil | Ce qu'il renvoie |
|---|---|
| `get_alarms` | Les alarmes d'un domaine : heure, élément, nom, gravité |
| `get_kpis` | Les mesures d'un domaine : leur valeur avant et pendant l'incident |
| `get_logs` | Les lignes de log des équipements d'un domaine |
| `get_config_changes` | Les changements de configuration récents d'un domaine |

Chaque outil prend un seul argument : le domaine à consulter. Quatre outils et trois domaines font **douze sources** de données. Ce chiffre revient souvent dans la suite.

Le préfixe `get` veut dire « obtenir ». Ces outils ne font que lire : aucun ne modifie le réseau.

#### Un bon de demande avec des cases à cocher

Pour décrire un outil au modèle, on utilise un **schéma JSON**. **JSON** (*JavaScript Object Notation*, notation des objets du langage JavaScript) est une façon d'écrire des données que les programmes lisent facilement : des noms, des valeurs, des accolades. Un schéma JSON est la description d'un formulaire : quels champs, de quel type.

Dans ce formulaire, le champ « domaine » n'est pas un texte libre. C'est une liste fermée de trois valeurs : `ran`, `transport`, `core`. Une liste fermée s'appelle une **enum**, abréviation d'*énumération*. Le bon de demande a des cases à cocher, pas une ligne blanche. Le modèle voit donc exactement quelles valeurs sont attendues. Cela ne l'empêche pas absolument d'écrire autre chose : dans ce cas, c'est le code qui refuse.

#### Quand le stagiaire remplit mal son bon

Un modèle se trompe parfois : il invente un argument, il oublie un champ. Dans ce cas, mon programme ne plante pas. L'archiviste rend le bon avec un mot : « ERREUR : arguments invalides {'domain': 'ran', 'element': 'C2'}. Argument attendu : domain. » Le modèle lit ce mot comme n'importe quel résultat, et se corrige au tour suivant.

C'est arrivé pendant les évaluations. Sur le scénario `SC10`, le modèle a demandé deux fois les logs d'un seul équipement, avec un argument `element` qui n'existe pas. Il a reçu deux fois l'erreur, a écrit « il semble qu'il y ait une limitation dans la fonction », puis a poursuivi son enquête avec les autres outils. Le programme ne s'est pas arrêté. En revanche, le modèle n'a pas pensé à refaire sa demande sans l'argument en trop : il n'a jamais lu ces logs.

La règle : **une erreur d'outil est une information rendue au modèle, pas un arrêt du programme.**

Dans le même esprit, un outil qui ne trouve rien le dit en toutes lettres : « Aucune alarme active dans le domaine core ». « Il n'y a pas d'alarme » et « je n'ai pas pu consulter les alarmes » sont deux informations opposées. Les confondre ferait croire qu'un domaine est sain alors qu'on ne l'a pas regardé.

### 10. Un agent, c'est une boucle

Un **agent** est un modèle de langage, des outils, et une boucle qui les relie.

Le stagiaire enquête maintenant comme un détective. Il réfléchit, demande une pièce, la lit, réfléchit à nouveau, en demande une autre. Il s'arrête quand il estime en savoir assez, et rend son rapport.

```
             ┌──────────────────────────────────────┐
             ▼                                      │
   le modèle réfléchit ──► il demande un outil ──► le code l'exécute
             │
             └──► il n'en demande plus ──► réponse finale
```

Cette boucle a un nom dans la littérature : **ReAct**, contraction de *Reason* (raisonner) et *Act* (agir).

Chaque passage dans la boucle est un **tour**. Le modèle peut demander plusieurs outils dans le même tour. À chaque tour, le modèle relit toute l'enquête depuis le début, puisqu'il n'a pas de mémoire. L'**historique** des messages est sa seule mémoire, et il s'allonge à chaque tour.

#### Trois précautions

**Un plafond de tours.** Un modèle peut tourner en rond et redemander sans fin la même chose. Le code l'arrête après un nombre fixé de tours, 8 pour l'agent seul, et lui impose de conclure avec ce qu'il a.

**Une réponse finale dans un formulaire.** Si l'agent rendait sa conclusion en texte libre, un programme ne pourrait pas la noter : « la fibre du site 1 », « le lien L1 » et « L1 » désignent la même chose pour un humain, pas pour un ordinateur. La réponse finale est donc un formulaire à trois cases, chacune avec une liste fermée. Les programmeurs appellent ces cases des **champs**.

| Case | Valeurs possibles |
|---|---|
| `domain` | `ran`, `transport`, `core` |
| `element` | l'un des 12 éléments du réseau |
| `fault` | l'un des 6 types de panne |

**Un formulaire qu'il ne peut pas mal remplir.** Demander poliment au modèle de respecter un format ne suffit pas toujours. Ollama propose mieux : on lui passe le schéma, et il empêche le modèle d'écrire un token qui sortirait du formulaire. Le modèle ne *peut* pas répondre `L4` ou oublier une case. Cette technique s'appelle la **sortie structurée**, ou le décodage contraint.

Attention à ce que cette garantie ne couvre pas. Elle vérifie chaque case séparément, pas leur combinaison. Le modèle a par exemple répondu « coupure de fibre sur le site radio `S1` », ce qui n'a pas de sens : `S1` n'est pas une fibre. Chaque case était valide, l'ensemble ne l'était pas.

### 11. Le graphe : qui fait quoi, et dans quel ordre

Il reste à organiser tout cela dans un programme. J'utilise **LangGraph**, une bibliothèque libre qui décrit un traitement sous forme de **graphe** : des étapes, et des flèches entre elles. Une **bibliothèque** est du code écrit par d'autres, prêt à être réutilisé.

L'image est celle d'un **dossier qui circule de service en service** dans une administration.

| Vrai nom | Dans l'image | Ce que c'est |
|---|---|---|
| **État** | Le dossier | Les données partagées par toutes les étapes |
| **Nœud** | Un service | Une fonction qui lit le dossier et y ajoute quelque chose |
| **Arête** | Le couloir entre deux services | Elle fixe quel nœud vient après quel autre |
| **Arête conditionnelle** | Un aiguillage | Le service suivant dépend de ce que contient le dossier |
| **Reducer** | La règle « on ajoute une page, on ne remplace pas le dossier » | Elle dit comment ranger ce qu'un nœud renvoie |

Deux de ces notions méritent une phrase de plus.

**Un nœud ne renvoie que ce qu'il change.** Un service ne réécrit pas tout le dossier. Il rend sa page, et c'est LangGraph qui la range.

**Le reducer évite une erreur classique.** Par défaut, ce qu'un nœud renvoie *remplace* l'ancienne valeur. Pour l'historique des messages, ce serait une catastrophe : le dernier message effacerait tous les précédents, et le modèle oublierait son enquête à chaque tour. Le reducer dit : pour cette donnée, on ajoute à la suite.

Le graphe d'un agent du projet compte quatre nœuds :

```
 début ──► call_model ──► (il demande des outils ?)     ──► run_tools ──► call_model ...
                      ──► (il lui manque des sources ?) ──► remind    ──► call_model ...
                      ──► (sinon)                       ──► conclude  ──► fin
```

| Nœud | Son travail |
|---|---|
| `call_model` (appeler le modèle) | Le modèle lit l'historique et décide de la suite |
| `run_tools` (exécuter les outils) | Le code exécute les outils demandés |
| `remind` (rappeler) | Le code rappelle au modèle les sources qu'il n'a pas consultées |
| `conclude` (conclure) | Un dernier appel au modèle, dont la réponse est contrainte au formulaire |

Le nœud `remind` ne sert qu'aux agents à qui l'on impose de consulter certaines sources avant de conclure. C'est expliqué dans [Le projet pas à pas](#le-projet-pas-à-pas). Pour ces agents, le graphe peut aussi passer directement de `run_tools` à `conclude` dès que toutes les sources imposées sont lues.

Un graphe n'a pas besoin de modèle de langage. Le premier que j'ai écrit automatise le raisonnement par périmètre du chapitre 6, en deux nœuds : garder ce que les cellules touchées ont en commun, puis rayer ce qu'une cellule saine utilise. C'est du calcul pur, sans aucune IA. Il a resservi plus tard, comme on va le voir.

### 12. Une équipe et son chef

Jusqu'ici, un seul agent enquête sur tout le réseau. L'autre façon de faire est de monter une **équipe**.

L'idée de départ : la radio, le transport et le cœur sont trois métiers, avec chacun ses équipements et ses connaissances. On confie donc chaque domaine à un spécialiste, et on charge quelqu'un d'autre de faire la synthèse.

L'image est celle d'un hôpital. Le cardiologue lit l'électrocardiogramme, le biologiste lit les analyses de sang, le pneumologue écoute les poumons. Aucun ne voit les examens des autres. Chacun écrit un compte rendu, et c'est le médecin référent qui pose le diagnostic en les lisant tous.

| Vrai nom | Dans l'image | Dans le projet |
|---|---|---|
| **Agent de domaine** | Le spécialiste | Un agent qui n'a accès qu'aux quatre outils de son domaine |
| **Orchestrateur** | Le médecin référent | Un appel au modèle, sans outil, qui lit les trois rapports et rend le diagnostic |
| **Cloisonnement** | Chacun n'ouvre que ses examens | Le code refuse à un agent toute donnée d'un autre domaine |
| **Rapport structuré** | Le compte rendu sur un formulaire commun | Un formulaire identique pour les trois agents |

Un système organisé ainsi est dit **multi-agents**. L'orchestrateur n'est pourtant pas un agent au sens du chapitre 10 : il n'a ni outil ni boucle. Il lit et il tranche, en une seule fois.

#### Le compte rendu d'un spécialiste

Un spécialiste ne voit qu'un morceau du réseau. Il ne peut pas toujours savoir si ce qu'il observe est la cause ou une conséquence. Son rapport doit donc dire à quel point il est sûr de lui. Il choisit l'un de trois statuts :

| Statut | Sens | Dans l'image |
|---|---|---|
| `healthy` (sain) | Rien d'anormal chez moi | « Examen normal » |
| `impacted` (touché) | Je vois des symptômes, mais pas leur origine | « Anomalie visible, cause à chercher ailleurs » |
| `local_cause` (cause locale) | J'ai une preuve directe que la panne est née chez moi | « Lésion visible à l'examen » |

Le rapport contient aussi la liste des éléments anormaux, l'élément accusé, le type de panne, l'heure du premier événement et quelques phrases d'analyse.

#### Ce que voit l'orchestrateur

L'orchestrateur ne voit **aucune donnée du réseau**. Il reçoit trois choses : le ticket, les trois rapports, et une **analyse de périmètre**.

Cette analyse est celle du chapitre 6, et ce n'est pas le modèle qui la fait. Le code prend la liste des cellules que le spécialiste radio déclare touchées, parcourt le plan du réseau, et calcule la liste des suspects et celle des innocentés. Le résultat est donné tout fait à l'orchestrateur.

La raison est simple. Suivre des dépendances sur un plan est un calcul exact, qu'un programme fait sans jamais se tromper. Un petit modèle de langage, lui, s'y perd. La répartition retenue est donc : **le modèle lit et résume, le code raisonne sur le plan du réseau.**

**Ce qui est simplifié ici.** Dans ce projet, les trois spécialistes travaillent l'un après l'autre et toujours dans le même ordre. Aucun ne lit le rapport des autres, et l'orchestrateur ne peut pas leur poser de question. C'est le plan le plus simple possible. Un système plus élaboré laisserait l'orchestrateur décider qui interroger, et relancer un spécialiste en cas de doute.

### 13. Savoir si ça marche

Construire un agent est une chose. Savoir s'il est bon en est une autre, et c'est la partie la plus délicate.

#### Le corrigé

Pour chaque panne simulée, la cause est connue à l'avance, puisque c'est le programme qui l'a fabriquée. Cette bonne réponse s'appelle la **vérité terrain**. Elle est rangée dans un fichier à part. Aucun agent et aucun outil n'y ont accès. Seuls la lisent le programme de notation, l'affichage d'un scénario quand on lui demande la réponse, et les vérifications automatiques du code.

Faire tourner un système une fois sur un scénario s'appelle une **exécution**.

Un diagnostic compte trois cases. On le note de deux façons :

| Note | Ce qu'elle dit |
|---|---|
| **Exact** | Les trois cases sont justes |
| **Par case** | Le domaine est-il bon ? L'élément ? Le type de panne ? |

La note par case sépare deux compétences. Trouver le bon élément, c'est **localiser** la panne. Trouver le bon type, c'est l'**identifier**. Un agent qui répond « lien `L1`, saturé » alors que la fibre est coupée a localisé sans identifier. Savoir laquelle des deux échoue dit où travailler.

#### Les annales et l'examen

Quand on améliore un système, on le fait tourner sur des pannes, on regarde ses erreurs, on corrige, on recommence. Le danger est de finir par régler le système *sur ces pannes-là*. Il les réussit toutes, et on se croit arrivé.

L'image est celle d'un élève qui a tant refait les annales qu'il en connaît les réponses par cœur. Son 20/20 aux annales ne dit rien de sa note à l'examen.

On sépare donc les pannes en deux paquets :

| Paquet | Dans l'image | Son usage | Dans le projet |
|---|---|---|---|
| **Jeu de mise au point** (*dev*) | Les annales | On s'en sert autant qu'on veut pour corriger le système | 5 pannes, `SC01` à `SC05` |
| **Jeu de test** | L'examen | On ne s'en sert qu'une fois, à la fin, quand plus rien ne bouge | 10 pannes, `SC06` à `SC15` |

Un système qui réussit ses annales et rate son examen souffre de **surajustement**, *overfitting* en anglais. Ce projet en donne un exemple, raconté plus bas.

#### Le témoin

Pour savoir si une idée apporte quelque chose, il faut la comparer à un point de repère. Ce repère s'appelle un **témoin**, *baseline* en anglais. Ici, le témoin de l'équipe est l'agent seul.

Une comparaison n'est honnête que si l'on ne change **qu'une chose à la fois**. Mon équipe avait reçu trois aides que l'agent seul n'avait pas. Elles sont détaillées dans [Le projet pas à pas](#le-projet-pas-à-pas). Si elle gagnait, impossible de dire si c'était grâce à l'équipe ou grâce aux aides. J'ai donc ajouté un second témoin : l'agent seul *avec* les mêmes aides.

#### Le prix d'un diagnostic

Un diagnostic juste qui coûte dix fois plus cher n'est pas forcément meilleur. Le coût se mesure ici en **tokens** lus et écrits, plutôt qu'en secondes.

La raison : les secondes dépendent de la machine. Le même calcul prend deux minutes sur un ordinateur et dix sur un autre, ou sur le même s'il est occupé à autre chose. Le nombre de tokens, lui, ne dépend que du système mesuré.

Les tokens lus sont additionnés sur tous les appels au modèle d'un même diagnostic. Comme l'historique est relu à chaque tour, ce total peut dépasser de beaucoup la taille de la fenêtre de contexte.

#### La prudence sur les petits nombres

Avec 10 pannes, une seule réponse qui bascule déplace le score d'un point sur dix. Et le modèle ne donne pas toujours la même réponse à la même question, même réglé pour être le plus régulier possible. Un écart de 8/10 contre 5/10 indique une direction. Il ne prouve rien.

---

## Le projet pas à pas

Cette partie décrit ce que fait exactement le code. Les notions utilisées sont expliquées dans les chapitres précédents.

### Les étapes de construction

Le projet a été construit du plus simple au plus complet. Chaque étape fonctionnait avant de passer à la suivante.

| Étape | Ce qui a été ajouté | Fichiers principaux |
|---|---|---|
| 0 | Vérifier que le modèle sait demander un outil | `scripts/00_check_tool_calling.py` |
| 1 | Le réseau fictif, trois pannes écrites à la main, un affichage lisible | `data/network.json`, `netdiag/show.py` |
| 2 | L'analyse de périmètre, premier graphe sans modèle. Puis un agent seul, ses outils et son diagnostic structuré | `netdiag/scope.py`, `netdiag/tools.py`, `netdiag/agent.py` |
| 3 | La notation automatique, la mesure du coût en tokens, une expérience sur la longueur des réponses | `netdiag/evaluate.py` |
| 4 | Un générateur de 15 pannes avec des parasites, séparées en deux jeux | `netdiag/generate.py` |
| 5 | L'équipe : trois agents de domaine et un orchestrateur | `netdiag/team.py` |
| 6 | Le témoin équitable, puis l'évaluation finale sur le jeu de test | `netdiag/agent.py`, `netdiag/analyze.py` |
| 7 | Des vérifications automatiques de la mécanique, sans modèle | `tests/` |

`netdiag` est le dossier qui contient le code. Son nom est l'abréviation de *network diagnosis*, diagnostic de réseau. Les fichiers en `.py` sont écrits en **Python**, le langage de programmation du projet.

### Les 15 pannes

Chaque scénario contient un ticket, des alarmes, des mesures, des logs et des changements de configuration. Il ne contient jamais sa propre réponse.

| Scénario | Jeu | Cause racine | Étendue | Parasites |
|---|---|---|---|---|
| `SC01` | mise au point | Fibre `L1` coupée | locale | aucun |
| `SC02` | mise au point | Erreur de configuration sur `C3` (inclinaison de l'antenne) | locale | aucun |
| `SC03` | mise au point | Surcharge du `SMF` | tout le réseau | aucun |
| `SC04` | mise au point | Panne matérielle du site `S1` | locale | une alarme |
| `SC05` | mise au point | Lien `L2` saturé | locale | une alarme et un changement |
| `SC06` | test | Fibre `L3` coupée | tout le réseau | une alarme |
| `SC07` | test | Lien `L3` saturé | tout le réseau | une alarme et un changement |
| `SC08` | test | Erreur de configuration sur le routeur `R1` | tout le réseau | une alarme et un changement |
| `SC09` | test | Erreur de configuration sur `C1` (puissance d'émission) | locale | une alarme |
| `SC10` | test | Brouillage radio sur `C2` | locale | une alarme et un changement |
| `SC11` | test | Panne matérielle de `C3` | locale | aucun |
| `SC12` | test | Surcharge de l'`AMF` | tout le réseau | une alarme |
| `SC13` | test | Erreur de configuration sur le `SMF` | tout le réseau | une alarme et un changement |
| `SC14` | test | Erreur de configuration sur l'`UPF` | tout le réseau | une alarme |
| `SC15` | test | Panne matérielle de l'`UPF` | tout le réseau | aucun |

Une panne est dite **locale** quand elle ne touche qu'une partie des cellules. Elle touche **tout le réseau** quand l'élément fautif se trouve sur le chemin de toutes les cellules : le routeur, le lien `L3` ou le cœur.

La colonne « Parasites » correspond aux trois niveaux de difficulté que j'avais prévus : facile sans parasite, moyen avec une alarme parasite, difficile avec une alarme et un changement de configuration parasites.

Trois choix de construction évitent que les agents trichent sans le vouloir :

- **Le même tableau de bord partout.** Chaque scénario affiche les 27 mesures du réseau, y compris celles qui n'ont pas bougé. La liste des mesures présentes ne trahit donc pas l'endroit de la panne.
- **Des données reproductibles.** Le générateur ne tire rien au hasard. Le relancer redonne exactement les mêmes fichiers, au caractère près.
- **Une réponse rangée ailleurs.** La vérité terrain est dans `data/ground_truth.json`, que ni les agents ni les outils ne lisent.

### Système 1 : l'agent seul

Un seul agent, avec les quatre outils et l'accès aux trois domaines.

| Réglage | Valeur |
|---|---|
| Consignes | Le plan du réseau, ses dépendances, les six types de panne, et une méthode en quatre points : consulter, regarder le périmètre, regarder la chronologie, déduire le type de panne |
| Liberté | Il choisit lui-même quoi consulter et quand s'arrêter |
| Plafond | 8 tours |
| Réponse finale | Le formulaire à trois cases, imposé par sortie structurée |

Son déroulement type : il consulte quelques sources, rédige un raisonnement, puis un dernier appel transforme sa conclusion en formulaire.

### Système 3 : l'équipe

L'équipe est présentée avant le système 2, parce que le système 2 en reprend les aides.

```
 début ──► agent radio ──► agent transport ──► agent cœur ──► orchestrateur ──► fin
```

Les trois agents de domaine s'exécutent l'un après l'autre. Chacun ne reçoit que le ticket. Aucun ne voit le rapport des autres.

**Un agent de domaine** utilise le même graphe que l'agent seul, avec quatre réglages différents :

| Réglage | Valeur | Pourquoi |
|---|---|---|
| Domaines autorisés | Le sien uniquement | C'est le cloisonnement |
| Consigne | Appeler ses quatre outils d'un coup, avant d'écrire quoi que ce soit | Un seul tour suffit pour tout lire |
| Sources obligatoires | Ses quatre sources | Le code lui réclame celles qu'il oublie. La part des sources consultées s'appelle la **couverture** |
| Plafond | 4 tours | Il n'a que quatre sources à lire |
| Réponse finale | Le rapport, écrit dans le formulaire sans étape de rédaction libre avant | Le champ `analysis` (analyse) vient en premier : le modèle raisonne par écrit avant de choisir un statut |

Le cloisonnement est assuré deux fois. Le formulaire de l'outil ne propose à l'agent que son propre domaine. Et si le modèle demandait quand même un autre domaine, la fonction refuserait et lui rendrait une erreur.

**L'orchestrateur** est un unique appel au modèle, sans outil. Il reçoit le ticket, les trois rapports, l'analyse de périmètre, et une méthode en quatre règles :

1. Un élément innocenté par l'analyse de périmètre ne peut pas être la cause, même si un agent l'accuse.
2. Parmi les suspects, retenir ceux qu'un agent désigne avec le statut `local_cause`.
3. S'il en reste plusieurs, la cause est le plus en amont : sa panne explique les symptômes de ceux qui dépendent de lui, l'inverse est impossible.
4. S'il n'en reste aucun, choisir le suspect que les rapports décrivent comme le plus directement défaillant.

Voici ce que l'orchestrateur a réellement reçu pour le scénario `SC06`, où la fibre `L3` est coupée. Les phrases d'analyse et la consigne finale sont retirées pour la lisibilité. Les domaines y portent leur nom de code : `ran` pour la radio, `core` pour le cœur.

```
Ticket : Depuis 08:15, sur l'ensemble du réseau, les abonnés n'ont plus aucun service mobile.

Rapport de l'agent ran : statut local_cause ; élément S2 ; panne fiber_cut ;
  éléments anormaux C1, C2, C3 ; premier événement 08:15:33
Rapport de l'agent transport : statut local_cause ; élément L3 ; panne fiber_cut ;
  éléments anormaux L3 ; premier événement 08:15:30
Rapport de l'agent core : statut impacted ; élément AMF ; panne interference ;
  éléments anormaux aucun ; premier événement 08:15:37

Analyse de périmètre (calculée à partir de la topologie, donc fiable) :
- cellules touchées : C1, C2, C3 ; cellules saines : aucune
- éléments suspects, de l'aval vers l'amont : R1, L3, AMF, SMF, UPF
- éléments innocentés : aucun
```

Cet exemple montre le mécanisme et ses défauts à la fois. L'agent transport a trouvé la bonne cause. L'agent radio s'accuse à tort : il parle d'une coupure de fibre sur un site radio. L'agent cœur associe un brouillage radio à l'`AMF`, ce qui n'a pas de sens. L'orchestrateur a répondu `L3`, fibre coupée, ce qui est juste : `S2` n'est pas sur le chemin commun aux trois cellules, donc pas parmi les suspects.

### Système 2 : l'agent seul aidé

C'est le témoin équitable. Un seul agent, qui voit les trois domaines, avec les trois aides de l'équipe.

| Aide | Dans l'équipe | Pour l'agent seul aidé |
|---|---|---|
| **Couverture** | Chaque agent doit lire ses 4 sources | Il doit lire les 12 sources |
| **Exigence de preuve** | Le statut `local_cause` demande une alarme ou un log au début des symptômes, ou un changement de configuration dans l'heure qui précède | Les mêmes repères sont ajoutés à ses consignes |
| **Analyse de périmètre** | Calculée par le code à partir du rapport radio | Calculée par le code à partir des cellules qu'il déclare touchées, et donnée avant son diagnostic |

La différence principale avec l'équipe est l'**architecture**, c'est-à-dire la façon dont le système est découpé : un agent qui lit tout dans une seule conversation, contre trois spécialistes et un chef.

Il reste une autre différence, que je n'ai pas neutralisée. Les spécialistes reçoivent d'emblée la consigne d'appeler leurs quatre outils. L'agent seul aidé enquête librement, et n'est rappelé à l'ordre que s'il veut conclure trop tôt.

Son plafond est de 16 tours, le double de l'agent seul, puisqu'il doit lire bien plus de sources.

### Les garde-fous

Un **garde-fou** est une règle appliquée par le code, quoi que décide le modèle.

| Garde-fou | Ce qu'il empêche |
|---|---|
| Listes fermées dans les outils | Que le modèle ignore quelles valeurs sont permises. Elles le guident, sans le contraindre |
| Cloisonnement | Qu'un agent de domaine lise les données d'un autre. S'il le demande, le code refuse |
| Erreur rendue en texte | Qu'une demande mal formée arrête le programme |
| Plafond de tours | Qu'un agent tourne sans fin |
| Rappel de couverture | Qu'un agent conclue sans avoir lu les sources obligatoires. Le code vérifie et les réclame, deux fois au plus |
| Sortie structurée | Une réponse finale illisible par un programme |
| Rapport illisible signalé | Filet de sécurité : si un rapport était malgré tout inutilisable, l'orchestrateur lirait « rapport illisible » plutôt qu'un rapport rassurant |

Le rappel de couverture a une faille connue, décrite dans [Ce qui n'a pas marché](#ce-qui-na-pas-marché) : il réclame, mais il ne peut pas forcer.

---

## Ce que j'ai mesuré

### Le protocole

| | |
|---|---|
| Modèle | `qwen2.5:7b`, température 0, fenêtre de contexte de 8 192 tokens |
| Machine | Un ordinateur portable. Le modèle tourne entièrement sur le processeur, sans carte graphique |
| Mise au point | Sur les 5 scénarios `SC01` à `SC05`, autant de fois que nécessaire |
| Évaluation finale | Sur les 10 scénarios `SC06` à `SC15`, **une seule fois**, après avoir figé les trois systèmes |
| Répétitions | Une exécution par scénario et par système |
| Notation | Automatique, par comparaison avec la vérité terrain |

Aucun système n'a été modifié après l'évaluation finale. Les fichiers de résultats sont dans `results/`. Chacun contient, pour chaque exécution, le diagnostic et les compteurs de tokens. Tous sauf les trois plus anciens contiennent aussi les sources consultées et les textes écrits par le modèle.

### Le résultat final

Sur les 10 scénarios de test. Les lignes de coût sont des moyennes par diagnostic.

| | Agent seul | Agent seul aidé | Équipe |
|---|---|---|---|
| **Cause racine exacte** | 6/10 | **8/10** | 5/10 |
| Bon domaine | 8/10 | 10/10 | 6/10 |
| Bon élément | 6/10 | 10/10 | 5/10 |
| Bon type de panne | 7/10 | 8/10 | 5/10 |
| Pannes locales | 3/3 | 3/3 | 3/3 |
| Pannes touchant tout le réseau | 3/7 | 5/7 | 2/7 |
| Sources lues, sur 12 | 3,1 | 6,7 | 12 |
| Exécutions où les 12 sources ont été lues | 0/10 | 2/10 | 10/10 |
| Appels au modèle | 4,4 | 9,3 | 7,0 |
| Tokens lus | 6 154 | 20 823 | 9 490 |
| Tokens écrits | 623 | 1 878 | 799 |

Deux précisions sur ce tableau. Les tokens sont additionnés sur tous les appels au modèle d'un diagnostic. Et une source est comptée comme lue dès que l'agent la demande : une seule demande a échoué sans être refaite (`SC10`, agent seul aidé), sans laquelle sa moyenne serait de 6,6.

Le détail, scénario par scénario. ✓ : cause racine exacte. ✗ : erreur, suivie de la réponse donnée par le système.

| Scénario | Cause attendue | Agent seul | Agent seul aidé | Équipe |
|---|---|---|---|---|
| `SC06` | `L3`, fibre coupée | ✗ `L1`, fibre coupée | ✓ | ✓ |
| `SC07` | `L3`, lien saturé | ✓ | ✓ | ✗ `R1`, surcharge |
| `SC08` | `R1`, erreur de configuration | ✗ `L1`, fibre coupée | ✗ `R1`, fibre coupée | ✗ `S1`, fibre coupée |
| `SC09` | `C1`, erreur de configuration | ✓ | ✓ | ✓ |
| `SC10` | `C2`, brouillage | ✓ | ✓ | ✓ |
| `SC11` | `C3`, panne matérielle | ✓ | ✓ | ✓ |
| `SC12` | `AMF`, surcharge | ✗ `S1`, panne matérielle | ✓ | ✗ `S1`, panne matérielle |
| `SC13` | `SMF`, erreur de configuration | ✓ | ✗ `SMF`, surcharge | ✓ |
| `SC14` | `UPF`, erreur de configuration | ✗ `L3`, lien saturé | ✓ | ✗ `R1`, lien saturé |
| `SC15` | `UPF`, panne matérielle | ✓ | ✓ | ✗ `L1`, fibre coupée |

### Comment lire ces chiffres

**1. Tout se joue sur les pannes qui touchent tout le réseau.** Les trois systèmes réussissent les trois pannes locales. Les écarts viennent entièrement des sept autres. Une panne locale laisse des cellules saines, qui innocentent la plupart des éléments. Quand tout le réseau est touché, plus rien n'innocente personne, et il faut départager cinq suspects à la seule lecture des traces.

**2. Dans l'équipe, les spécialistes ont fait leur travail.** Le spécialiste du domaine fautif a écrit la cause exacte dans son rapport 9 fois sur 10. La dixième fois (`SC07`), il a trouvé le bon élément et s'est trompé d'étiquette, en écrivant « surcharge » pour un lien saturé.

**3. L'orchestrateur a perdu l'information.** Il n'a rendu la cause exacte que 5 fois sur 10. Dans trois de ses cinq erreurs, il a accusé un élément qui ne figurait pas dans la liste des suspects qu'on lui avait fournie (`SC08`, `SC12`, `SC15`). Dans une autre (`SC14`), il a écarté le bon coupable en écrivant que les cellules étaient touchées « avant 09:05:45 », l'heure donnée par l'agent cœur. Le rapport radio indiquait « 09:05 », sans les secondes : l'écart vient probablement de cet arrondi.

**4. Les spécialistes s'accusent trop.** Sur les 20 rapports venant d'un domaine qui n'était pas en cause, 5 se déclaraient tout de même cause locale. Deux fois, c'est un parasite qui a trompé l'agent : un test de batterie sur `S1` (`SC12`), un avertissement de licence sur l'`UPF` (`SC08`). Une fois, c'est le piège décrit au chapitre 6 : l'agent transport a vu un lien occupé à 0 % et a conclu à une coupure, alors que le lien était simplement vide (`SC15`).

**5. L'agent seul aidé gagne, mais pas proprement.** Il lit en moyenne 6,7 sources sur 12, malgré les rappels du code. Dans au moins 4 exécutions sur 10, il a fait semblant de consulter : il a écrit ses demandes d'outils en texte sans qu'elles soient exécutées (`SC06`), ou rédigé lui-même des résultats qui n'existent pas (`SC08`, `SC13`, `SC14`). `SC08` et `SC13` sont justement ses deux erreurs. Son 8/10 coûte aussi plus de deux fois plus de tokens que l'équipe, lus comme écrits.

**6. L'agent seul lit très peu.** 3,1 sources sur 12 en moyenne. Il s'arrête dès qu'une explication lui paraît plausible. Sur `SC06`, il a conclu sans jamais consulter les alarmes du transport, là où se trouvait la réponse.

**7. La difficulté que j'avais prévue n'était pas la bonne.** J'avais classé les scénarios selon le nombre de parasites. Ce classement ne prédit pas les erreurs : l'agent seul réussit 3 scénarios « difficiles » sur 4 et seulement 1 « moyen » sur 4. Ce qui prédit les erreurs, c'est l'étendue de la panne.

### Les résultats intermédiaires

**Sur le jeu de mise au point**, avant l'évaluation finale :

| | Agent seul | Agent seul aidé | Équipe |
|---|---|---|---|
| Cause racine exacte | 3/5 | 4/5 | 5/5 |
| Sources lues, sur 12 | non mesuré | 7,4 | 12 |
| Tokens lus | 5 656 | 18 970 | 9 453 |
| Tokens écrits | 712 | 1 649 | 788 |

Ce tableau donnait l'équipe gagnante. Le jeu de test dit le contraire. L'explication est dans la partie suivante.

**L'expérience sur la longueur des réponses.** Au début du projet, sur trois scénarios écrits à la main et répétés trois fois chacun, j'ai comparé deux versions des consignes de l'agent seul. La seconde ajoutait « sois bref ».

| | Consignes normales | Avec « sois bref » |
|---|---|---|
| Cause racine exacte | 9/9 | 3/9 |
| Tokens écrits par diagnostic | 577 | 193 |
| Durée moyenne | 158 s | 67 s |

Ces trois premiers scénarios ont ensuite été remplacés par ceux du générateur. Les deux fichiers de résultats correspondants sont conservés dans `results/` sous les noms `single_agent_verbose.json` et `single_agent_brief.json`. *Verbose* veut dire bavard, *brief* veut dire bref.

### Les durées, à titre indicatif

Sur mon ordinateur, pendant l'évaluation finale, la moitié des diagnostics ont pris moins de 3 minutes pour l'agent seul, moins de 6 pour l'équipe et moins de 9 pour l'agent seul aidé. Cette valeur du milieu s'appelle la **médiane**. L'évaluation complète des trois systèmes a duré 3 heures et demie.

Ces durées ne valent que pour cette machine. Lors d'une évaluation précédente, le même calcul a pris jusqu'à quinze fois plus longtemps, l'ordinateur ayant été laissé sans surveillance. C'est pour cela que les tableaux comptent en tokens.

---

## Ce qui n'a pas marché

Cette partie est la plus utile du projet. Chaque échec est décrit avec ce que j'ai essayé, ce qui s'est passé, et ce que j'en retiens.

### 1. Demander au modèle d'être bref

**Ce que j'ai essayé.** Le modèle écrit lentement. Pour gagner du temps, j'ai ajouté « sois bref » à ses consignes.

**Ce qui s'est passé.** Il est allé plus de deux fois plus vite, et sa précision est passée de 9/9 à 3/9.

**Ce que j'en retiens.** Ce que le modèle écrit avant de conclure n'est pas du bavardage. C'est son raisonnement. Le lui retirer, c'est lui demander de répondre sans réfléchir. J'ai gardé la variante dans le code pour pouvoir refaire la comparaison, mais elle n'est pas utilisée.

### 2. La première équipe : tous coupables

**Ce que j'ai essayé.** Une première équipe où chaque spécialiste disait librement ce qu'il pensait.

**Ce qui s'est passé.** Sur le scénario `SC05`, les trois agents se sont déclarés cause de la panne. Chacun voyait une anomalie chez lui et en concluait que la panne venait de chez lui. L'orchestrateur, sans moyen de les départager, a pris la dépendance à l'envers et rendu un mauvais diagnostic.

**Ce que j'en retiens.** Un spécialiste qui ne voit qu'un domaine ne peut pas distinguer une cause d'une conséquence. J'ai ajouté les trois statuts avec leur exigence de preuve, et l'analyse de périmètre calculée par le code à partir des éléments que l'agent radio déclare anormaux. L'équipe est alors passée à 5/5 sur le jeu de mise au point. L'exigence de preuve n'a marché qu'à moitié : même après, des agents continuent de s'accuser à tort.

### 3. L'équipe réussit les annales et rate l'examen

**Ce qui s'est passé.** 5/5 sur le jeu de mise au point, 5/10 sur le jeu de test.

**Pourquoi.** Mon jeu de mise au point était mal équilibré. Il contenait 4 pannes locales sur 5. Le jeu de test contient 7 pannes touchant tout le réseau sur 10. Or l'analyse de périmètre, qui a fait l'essentiel du progrès de l'équipe, n'aide que pour les pannes locales. J'ai réglé l'équipe sur le cas facile sans m'en rendre compte.

**Ce que j'en retiens.** C'est un surajustement, et je ne l'ai vu que parce que le jeu de test était resté intact. Un jeu de mise au point doit ressembler au jeu de test. J'aurais dû vérifier, avant de commencer, que les pannes locales et les pannes touchant tout le réseau étaient réparties de la même façon dans les deux jeux.

### 4. L'orchestrateur ne suit pas sa méthode

**Ce qui s'est passé.** Les quatre règles d'arbitrage étaient écrites dans ses consignes. Dans trois de ses cinq erreurs, il a pourtant accusé un élément absent de la liste des suspects.

**Ce que j'en retiens.** Écrire une règle dans des consignes ne garantit pas qu'un petit modèle l'applique. Les règles qui comptent doivent être appliquées par le code. C'est la leçon que j'avais déjà tirée pour l'analyse de périmètre, et que je n'ai pas poussée jusqu'au bout.

Par curiosité, j'ai calculé après coup ce qu'auraient donné les trois premières règles appliquées par un programme, sur les rapports enregistrés : 7/10 sur le jeu de test, mais 4/5 sur le jeu de mise au point, soit moins bien que le modèle. Ce n'est donc pas une solution miracle. Ma règle 3 a d'ailleurs un défaut : entre les trois fonctions du cœur, qui ne dépendent pas l'une de l'autre, « le plus en amont » ne veut rien dire. Et ce chiffre n'est pas un résultat : adopter cette correction maintenant reviendrait à régler le système sur le jeu de test.

### 5. On ne peut pas forcer un modèle à lire

**Ce que j'ai essayé.** Un garde-fou de couverture : si l'agent veut conclure sans avoir lu toutes ses sources, le code les lui réclame.

**Ce qui s'est passé.** Les spécialistes de l'équipe ont toujours lu leurs 4 sources. L'agent seul aidé, qui en a 12, n'a tout lu que 2 fois sur 10. La comparaison n'est pas à armes égales : les spécialistes reçoivent dès le départ la consigne d'appeler tous leurs outils, alors que l'agent seul aidé n'est rappelé à l'ordre qu'au moment de conclure. Ce qui reste vrai dans tous les cas : rappelé à l'ordre, il lui arrive d'écrire les résultats lui-même au lieu d'appeler les outils. Sur le jeu de mise au point, il a ainsi rendu un diagnostic juste en s'appuyant sur des débits de 900 Mbps, dans un réseau où une cellule en débite 40.

**Ce que j'en retiens.** Un rappel n'est pas une contrainte. Et une bonne réponse ne prouve pas un bon raisonnement : c'est pour cela que j'enregistre ce que l'agent a demandé et écrit, et pas seulement sa réponse finale. Pour garantir la couverture, il aurait fallu que le code appelle lui-même les outils manquants.

Ce garde-fou a une seconde faille, trouvée en relisant les résultats. Il considère une source comme lue dès qu'elle a été demandée, même si la demande a échoué. Sur `SC10`, des logs demandés avec un mauvais argument ont été comptés comme lus.

### 6. Une analyse « fiable » dépend de ce qu'on lui donne

**Ce qui s'est passé.** L'analyse de périmètre est un calcul exact. Mais elle part de la liste des cellules touchées, et cette liste est écrite par un modèle. Sur `SC13`, panne touchant tout le réseau, l'agent radio a oublié la cellule `C2`. Le calcul a donc considéré `C2` comme saine, et a innocenté le routeur, le lien `L3` et tout le cœur, donc le coupable avec eux. L'orchestrateur a heureusement ignoré cette analyse. Le même oubli figurait déjà dans une exécution du jeu de mise au point (`SC03`) : le diagnostic était juste, et je ne l'avais pas remarqué.

**Ce que j'en retiens.** J'avais écrit « calculée à partir de la topologie, donc fiable » dans le texte donné à l'orchestrateur. C'est trop affirmatif. Un calcul juste sur une entrée fausse donne un résultat faux. La liste des cellules touchées aurait dû être calculée elle aussi par le code, à partir des mesures.

### 7. La température 0 ne rend pas le modèle régulier

**Ce qui s'est passé.** Avec exactement le même scénario, les mêmes consignes et la température à 0, l'agent seul a répondu « erreur de configuration » une fois et « panne matérielle » une autre fois sur `SC02`.

**Ce que j'en retiens.** Une seule exécution par scénario est une mesure fragile. Je n'ai pas cherché la cause de cette variation. La seule parade que je connaisse est de répéter les mesures, ce que la lenteur de ma machine ne m'a permis de faire qu'au tout début.

### 8. Le cache ne profite pas à l'équipe

**Le principe.** À chaque tour, le modèle relit toute la conversation. Ollama garde en mémoire le début déjà lu : si le début du texte est identique à celui de l'appel précédent, il ne le relit pas. C'est le **cache de préfixe**. J'en ai tenu compte en plaçant dans les consignes ce qui ne change pas avant ce qui change. Un oubli de ma part sur le dernier appel faisait tout relire : il coûtait 31 secondes.

**Ce qui s'est passé.** L'équipe lit deux fois moins de tokens que l'agent seul aidé, et y passe pourtant deux fois plus de temps : 99 secondes de lecture par diagnostic contre 46, en médiane. La lecture pèse environ un quart de son temps, contre un dixième pour les deux agents seuls.

**Ce que j'en retiens.** J'avais placé la description du réseau en tête des consignes des quatre membres de l'équipe, en espérant qu'elle reste en cache de l'un à l'autre. Ces chiffres suggèrent que cela ne suffit pas : chaque membre ouvre une conversation nouvelle, dont la suite des consignes et les outils diffèrent. Je n'ai pas vérifié cette explication.

### 9. Mes premières mesures de durée étaient inutilisables

**Ce qui s'est passé.** Une série d'évaluations a duré quatre heures au lieu d'une. Un scénario a pris 2 h 31 pour écrire 2 193 tokens, quinze fois plus lentement que d'habitude. L'ordinateur, laissé sans surveillance, avait très probablement réduit sa puissance ou s'était mis en veille.

**Ce que j'en retiens.** J'ai cessé de comparer des durées, et j'ai modifié le programme d'évaluation pour qu'il enregistre ses résultats après chaque scénario, au lieu de tout écrire à la fin.

---

## Limites et pistes

### Ce que ce projet ne montre pas

- **Les données sont simulées et très simples.** Douze éléments, six types de panne, une seule panne à la fois, des traces courtes et propres. Un vrai réseau est sans commune mesure. Aucun résultat d'ici ne se transpose tel quel.
- **Les données tiennent sur le bureau d'un seul agent.** Les douze sources d'un scénario n'occupent qu'une petite partie de la fenêtre de contexte. L'argument habituel en faveur d'une équipe, « un seul agent serait débordé », ne s'applique donc pas ici. Sur des données réelles et volumineuses, la comparaison pourrait s'inverser.
- **La comparaison n'est pas parfaitement contrôlée.** Les spécialistes de l'équipe et l'agent seul aidé ne reçoivent pas exactement les mêmes consignes de lecture, comme expliqué plus haut.
- **L'échantillon est petit.** 10 scénarios de test, une exécution chacun. L'équipe et l'agent seul aidé ne diffèrent que sur 5 scénarios.
- **Un seul modèle, et petit.** Rien ne dit qu'un modèle plus capable ferait les mêmes erreurs d'arbitrage.
- **Les parasites suivent une règle simple.** Ce sont toujours des événements anciens. Je connaissais cette règle en écrivant les consignes. La résistance à d'autres sortes de parasites n'est pas mesurée.
- **L'agent ne peut pas dire « je ne sais pas ».** Le formulaire l'oblige à choisir un élément et un type de panne, même quand il n'a rien trouvé.
- **L'équipe suit un plan fixe.** L'orchestrateur ne peut ni choisir qui interroger, ni reposer une question.

### Ce que j'essaierais ensuite

- **Faire arbitrer le code.** Appliquer les règles de l'orchestrateur par un programme, et ne garder le modèle que pour départager les cas que les règles ne tranchent pas. À valider sur de nouveaux scénarios, pas sur ceux du jeu de test.
- **Calculer les cellules touchées à partir des mesures**, au lieu de se fier à la liste écrite par un agent.
- **Donner à l'orchestrateur les preuves, pas seulement les conclusions.** Chaque rapport citerait la ligne d'alarme ou de log qui le justifie.
- **Laisser l'orchestrateur reposer une question** à un spécialiste quand deux rapports se contredisent.
- **Rééquilibrer le jeu de mise au point** et répéter chaque mesure plusieurs fois.
- **Ajouter la réponse « cause indéterminée ».**
- **Exposer les outils par un serveur MCP.** **MCP** (*Model Context Protocol*) est un standard ouvert qui décrit comment une application d'IA se branche sur des outils extérieurs. Les quatre outils du projet sont aujourd'hui de simples fonctions Python, utilisables seulement par ce programme. Un **serveur** est un programme qui rend un service aux programmes qui le lui demandent. Derrière un serveur MCP, n'importe quel agent compatible pourrait utiliser ces outils sans rien réécrire. Je ne l'ai pas fait, par manque de temps.

---

## Refaire tourner le projet

### Ce qu'il faut

- Python 3.10 ou plus récent. Le projet a été développé avec Python 3.14 sous Windows.
- [Ollama](https://ollama.com), gratuit.
- Environ 6 Go de mémoire vive libre pour le modèle. La mémoire vive est la mémoire de travail de l'ordinateur.

### Installation

Les commandes sont données pour l'invite de commandes de Windows, la fenêtre où l'on tape des commandes au clavier. Une commande par ligne, depuis le dossier du projet.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
ollama pull qwen2.5:7b
```

| Ligne | Ce qu'elle fait |
|---|---|
| `python -m venv .venv` | Crée un **environnement virtuel** : un dossier `.venv` où ranger les bibliothèques du projet, sans toucher au reste de l'ordinateur |
| `.venv\Scripts\activate` | Entre dans cet environnement |
| `pip install -r requirements.txt` | Installe les deux bibliothèques listées dans le fichier `requirements.txt` : `ollama`, pour parler au modèle, et `langgraph`. `pip` est l'installateur de bibliothèques de Python |
| `ollama pull qwen2.5:7b` | Télécharge le modèle, environ 4,7 Go |

Sous Linux ou macOS, la deuxième ligne devient `source .venv/bin/activate`.

### Sans modèle : quelques secondes

```
python -m unittest
python -m netdiag.show SC01
python -m netdiag.show SC01 --answer
python -m netdiag.scope --affected C1 C2 --healthy C3
python -m netdiag.analyze
python -m netdiag.generate
```

| Commande | Ce qu'elle fait |
|---|---|
| `python -m unittest` | Lance les 27 vérifications automatiques du code, appelées tests unitaires. Elles contrôlent les données, les outils, le périmètre et la mécanique des agents. Le modèle y est remplacé par un faux : une fonction écrite à la main qui renvoie des réponses prévues d'avance |
| `netdiag.show` | Affiche un scénario comme le verrait un technicien. Avec `--answer` (réponse), affiche aussi la cause attendue |
| `netdiag.scope` | Calcule les suspects et les innocentés. `--affected` : les cellules touchées. `--healthy` : les cellules saines |
| `netdiag.analyze` | Recalcule les tableaux principaux de ce document à partir de `results/` |
| `netdiag.generate` | Régénère les 15 scénarios. Le résultat doit être identique aux fichiers présents |

### Avec le modèle : plusieurs minutes par scénario

```
python scripts\00_check_tool_calling.py
python -m netdiag.agent SC01
python -m netdiag.agent SC01 --aided
python -m netdiag.team SC01
```

| Commande | Ce qu'elle fait |
|---|---|
| `00_check_tool_calling.py` | Pose une question simple au modèle et vérifie qu'il répond par une demande d'outil |
| `netdiag.agent SC01` | Lance l'agent seul sur le scénario `SC01` |
| `netdiag.agent SC01 --aided` | Lance l'agent seul aidé. *Aided* veut dire aidé |
| `netdiag.team SC01` | Lance l'équipe. *Team* veut dire équipe |

Les trois dernières affichent l'enquête au fil de l'eau : chaque demande d'outil, chaque résultat, chaque raisonnement, et le coût de chaque appel au modèle.

Pour refaire les évaluations :

```
python -m netdiag.evaluate --system single --split test
python -m netdiag.evaluate --system single_aided --split test
python -m netdiag.evaluate --system team --split test
```

`--system` choisit le système : `single` (seul), `single_aided` (seul aidé) ou `team` (équipe). `--split` choisit le jeu de scénarios : `test`, ou `dev` pour les 5 scénarios de mise au point. Sur un ordinateur sans carte graphique, comptez environ 3 heures et demie pour les trois commandes ci-dessus. Les résultats ne seront pas forcément identiques aux miens, pour la raison donnée au point 7 de [Ce qui n'a pas marché](#ce-qui-na-pas-marché).

---

## Organisation du dépôt

Un **dépôt** est le dossier d'un projet tel qu'il est publié, avec l'historique de ses modifications.

```
mini-depanneur-reseau/
├── README.md
├── requirements.txt            les deux bibliothèques utilisées, avec leur version
├── data/
│   ├── network.json            le réseau : éléments, dépendances, types de panne
│   ├── scenarios/              les 15 pannes, SC01.json à SC15.json
│   ├── ground_truth.json       la cause attendue de chaque panne (jamais lue par les agents)
│   └── splits.json             quels scénarios servent à la mise au point, lesquels au test
├── netdiag/
│   ├── scenarios.py            charger le réseau, un scénario, la vérité terrain
│   ├── topology.py             questions sur le plan du réseau : chemin, cellules derrière un élément
│   ├── generate.py             fabriquer les 15 scénarios
│   ├── show.py                 afficher un scénario
│   ├── tools.py                les quatre outils et leur cloisonnement
│   ├── scope.py                l'analyse de périmètre
│   ├── agent.py                le graphe d'un agent, l'agent seul et l'agent seul aidé
│   ├── team.py                 les agents de domaine et l'orchestrateur
│   ├── evaluate.py             lancer un système sur un jeu de scénarios et le noter
│   └── analyze.py              relire les résultats : tableaux et analyse d'erreurs
├── tests/                      27 vérifications automatiques, sans modèle
├── scripts/
│   └── 00_check_tool_calling.py   vérifier que le modèle sait demander un outil
└── results/                    un fichier par système et par jeu de scénarios
```

Les fichiers en `.md`, comme celui-ci, sont des textes mis en forme. Ceux en `.json` contiennent des données. Ceux en `.py` contiennent du code Python.

| Fichier de résultats | Contenu |
|---|---|
| `single_agent_verbose_test.json` | Agent seul, jeu de test |
| `single_agent_aided_test.json` | Agent seul aidé, jeu de test |
| `team_test.json` | Équipe, jeu de test |
| les mêmes avec `_dev` | Jeu de mise au point |
| `single_agent_verbose.json`, `single_agent_brief.json` | L'expérience sur la longueur des réponses, sur les trois premiers scénarios écrits à la main |

Dans ces noms, *single agent* veut dire agent seul et *team* équipe.

---

## Glossaire

Tous les sigles et tous les termes du document, par ordre alphabétique. Trois tableaux complètent celui-ci : les mots du code, les noms d'alarmes et les mots anglais des logs.

| Terme | Signification |
|---|---|
| **3GPP** | *3rd Generation Partnership Project*. L'organisme international qui écrit les normes des réseaux mobiles. Ses documents s'appellent **TS** (*Technical Specification*, spécification technique) ou **TR** (*Technical Report*, rapport technique) |
| **5G** | Cinquième génération de réseau mobile |
| **Agent** | Un modèle de langage, des outils, et une boucle qui les relie. Il enquête par étapes au lieu de répondre d'un seul coup |
| **Agent de domaine** | Agent spécialiste qui n'a accès qu'aux données d'un seul domaine |
| **Agrégation** | Le fait de rassembler le trafic de plusieurs sites avant de l'envoyer vers le cœur |
| **Alarme** | Message émis par un équipement quand il détecte un état anormal |
| **AMF** | *Access and Mobility Management Function*, fonction de gestion de l'accès et de la mobilité. Fonction du cœur qui enregistre les abonnés et suit leur position |
| **Amont, aval** | En amont : du côté du cœur. En aval : du côté des téléphones |
| **Appel d'outil** | *Tool calling*. Le modèle demande l'exécution d'une fonction, le code l'exécute et lui rend le résultat |
| **Architecture** | La façon dont un système est découpé en parties, et dont ces parties communiquent |
| **Arête** | Dans un graphe, le lien qui fixe quel nœud vient après quel autre |
| **Arête conditionnelle** | Arête dont la destination dépend du contenu de l'état |
| **Argument** | Précision donnée à une fonction quand on l'appelle. Ici, le domaine à consulter |
| **Backhaul** | Ensemble des liens qui relient les sites radio au cœur. En français : réseau de collecte |
| **Bibliothèque** | Du code écrit par d'autres, prêt à être réutilisé dans un programme |
| **Bit, mégabit** | Le bit est la plus petite unité d'information. Un mégabit vaut un million de bits |
| **Cache de préfixe** | Mémoire qui évite au modèle de relire le début d'un texte quand il est identique à celui de l'appel précédent |
| **Carte graphique** | Puce spécialisée dans les calculs massifs. Les modèles de langage y tournent bien plus vite que sur un processeur |
| **Cause racine** | L'événement initial qui explique tous les symptômes d'un incident |
| **Cellule** | Zone couverte par une antenne d'un site radio |
| **Champ** | Une case d'un formulaire, dans le vocabulaire des programmeurs |
| **Cloisonnement** | Le fait qu'un agent de domaine ne puisse lire que les données de son domaine |
| **Cœur de réseau** | Partie centrale du réseau, qui reconnaît les abonnés et dirige leurs données |
| **Consignes** | Mot utilisé dans ce document pour le prompt système |
| **core** | Mot anglais pour cœur. Nom du domaine cœur dans le code et dans les données |
| **Couverture** | La part des sources de données qu'un agent a consultées avant de conclure |
| **CPU** | *Central Processing Unit*, le processeur : la puce qui exécute les calculs d'une machine |
| **dB** | Décibel, unité utilisée ici pour la qualité du signal radio |
| **dBm** | Décibel-milliwatt, unité de puissance. Sert ici à mesurer la lumière reçue sur une fibre |
| **Débit** | Quantité de données transmise chaque seconde |
| **Dépendance** | Un élément dépend d'un autre quand il ne peut pas fonctionner sans lui |
| **Dépôt** | Le dossier d'un projet tel qu'il est publié, avec l'historique de ses modifications |
| **dev** | Abréviation de *development*. Désigne le jeu de mise au point |
| **Domaine** | Grande zone du réseau : RAN, transport ou cœur |
| **Enum** | Abréviation d'*énumération*. Liste fermée de valeurs autorisées dans un formulaire |
| **Environnement virtuel** | Dossier où l'on range les bibliothèques d'un projet Python, sans toucher au reste de l'ordinateur |
| **État** | Dans un graphe, les données partagées par tous les nœuds |
| **Exécution** | Le fait de faire tourner un système une fois sur un scénario |
| **Exigence de preuve** | Règle donnée aux agents : n'accuser un élément que si une alarme, un log ou un changement de configuration récent le justifie |
| **Faisceau hertzien** | Liaison sans câble entre deux antennes qui se font face |
| **Fenêtre de contexte** | Quantité maximale de texte qu'un modèle peut avoir sous les yeux en même temps, comptée en tokens |
| **Fibre optique** | Câble en verre dans lequel l'information voyage sous forme de lumière |
| **Fonction** | Deux sens dans ce document. Dans le réseau : un programme du cœur qui a un métier (AMF, SMF, UPF). En programmation : un morceau de programme qui accomplit une tâche quand on l'appelle |
| **Garde-fou** | Règle appliquée par le code, quoi que décide le modèle |
| **gNB** | *gNodeB*, la station de base d'un réseau 5G. *NodeB* est le nom des stations de base dans les normes |
| **Go** | Gigaoctet, unité de taille de mémoire |
| **Graphe** | Description d'un traitement sous forme d'étapes (les nœuds) reliées par des flèches (les arêtes) |
| **Hallucination** | Information fausse écrite par un modèle avec la même assurance qu'une vraie |
| **Historique** | La suite de tous les messages d'une enquête. C'est la seule mémoire d'un agent |
| **IA** | Intelligence artificielle |
| **Innocenté** | Se dit d'un élément utilisé par une cellule saine : il fonctionne forcément |
| **Invite de commandes** | La fenêtre de Windows où l'on tape des commandes au clavier |
| **IP** | *Internet Protocol*. Une adresse IP est le numéro qui rend un appareil joignable sur un réseau |
| **Jeu de mise au point** | Les scénarios dont on se sert pour corriger un système. En anglais *dev set* |
| **Jeu de test** | Les scénarios gardés de côté pour noter le système une seule fois, à la fin |
| **JSON** | *JavaScript Object Notation*. Façon d'écrire des données que les programmes lisent facilement |
| **KPI** | *Key Performance Indicator*, une mesure de performance suivie dans le temps |
| **LangGraph** | Bibliothèque libre qui organise un traitement sous forme de graphe. Utilisée ici pour construire les agents |
| **Latence** | Temps de trajet d'un paquet |
| **Libre, open source** | Se dit d'un logiciel dont le code est public et que chacun peut utiliser gratuitement |
| **Lien** | Une route entre deux équipements : une fibre optique ou un faisceau hertzien |
| **LLM** | *Large Language Model*, grand modèle de langage. Programme qui a appris, sur d'immenses quantités de texte, à écrire la suite d'un texte |
| **Local (modèle)** | Modèle qui tourne sur l'ordinateur de l'utilisateur, sans rien envoyer sur Internet |
| **Localiser, identifier** | Localiser une panne : trouver le bon élément. L'identifier : trouver le bon type de panne |
| **Log** | Ligne de texte datée, écrite par un équipement |
| **Mbps** | Mégabit par seconde, unité de débit |
| **MCP** | *Model Context Protocol*. Standard ouvert qui décrit comment une application d'IA se branche sur des outils extérieurs. Non utilisé dans ce projet |
| **Médiane** | La valeur du milieu : la moitié des mesures sont en dessous, l'autre moitié au-dessus |
| **Mémoire vive** | La mémoire de travail d'un ordinateur, comptée en gigaoctets |
| **Mesure** | Un chiffre suivi dans le temps sur un équipement. Voir KPI |
| **Modèle de langage** | Voir LLM |
| **Multi-agents** | Se dit d'un système où plusieurs agents se partagent le travail |
| **netdiag** | Nom du dossier de code. Abréviation de *network diagnosis*, diagnostic de réseau |
| **Nœud** | Dans un graphe, une étape : une fonction qui lit l'état et y ajoute quelque chose |
| **Ollama** | Logiciel libre qui télécharge un modèle de langage et le fait tourner sur l'ordinateur de l'utilisateur |
| **Opérateur** | Entreprise qui exploite un réseau mobile |
| **Orchestrateur** | Membre de l'équipe qui ne consulte aucune donnée, lit les rapports des agents de domaine et rend le diagnostic |
| **Outil** | Fonction du programme qu'un modèle a le droit de demander. Le projet en compte quatre |
| **Paquet** | Petit morceau de données. Tout ce qui circule sur un réseau est découpé en paquets |
| **Paramètre** | L'un des nombres qu'un modèle a réglés pendant son apprentissage. Leur nombre donne la taille du modèle |
| **Parasite** | Événement réel mais sans rapport avec la panne étudiée |
| **Périmètre** | L'ensemble des éléments touchés par une panne, comparé à ceux qui fonctionnent encore |
| **PFCP** | *Packet Forwarding Control Protocol*. Protocole du dialogue entre le SMF et l'UPF |
| **Plan utilisateur** | La partie du réseau qui transporte les données des abonnés, par opposition à celle qui organise ce transport |
| **Port** | La prise d'un routeur où se branche un lien |
| **Processeur** | La puce qui exécute les calculs d'une machine. Voir CPU |
| **Prompt** | Le texte donné à un modèle de langage |
| **Prompt système** | La partie du prompt qui contient les consignes permanentes : rôle, méthode, format attendu |
| **Propagation** | Le fait qu'une panne produise des symptômes sur tout ce qui dépend de l'élément fautif |
| **Protocole** | Ensemble de règles que deux équipements suivent pour se parler |
| **Python** | Le langage de programmation du projet |
| **qwen2.5:7b** | Le modèle de langage utilisé. Publié par l'équipe Qwen d'Alibaba, environ 7 milliards de paramètres |
| **RAN** | *Radio Access Network*, le réseau d'accès radio |
| **Rapport structuré** | Le compte rendu d'un agent de domaine, écrit dans un formulaire identique pour tous |
| **ReAct** | Contraction de *Reason* et *Act*. La boucle d'un agent : raisonner, agir avec un outil, lire le résultat, recommencer |
| **Reducer** | Règle qui dit comment ranger dans l'état ce qu'un nœud renvoie : remplacer l'ancienne valeur, ou ajouter à la suite |
| **Routeur** | Équipement qui reçoit le trafic et l'envoie dans la bonne direction |
| **SC01 à SC15** | Les noms des 15 scénarios. `SC` est l'abréviation de scénario |
| **Scénario** | Une panne simulée : un ticket, des alarmes, des mesures, des logs et des changements de configuration |
| **Schéma JSON** | Description d'un formulaire : quels champs, de quel type, avec quelles valeurs permises |
| **SCTP** | *Stream Control Transmission Protocol*, protocole utilisé pour le dialogue entre une station de base et l'AMF |
| **Serveur** | Programme qui rend un service aux programmes qui le lui demandent |
| **Session PDU** | *Protocol Data Unit session*. En 5G, le chemin ouvert pour les données d'un abonné |
| **Site** | Lieu physique qui porte les antennes et les équipements radio |
| **SMF** | *Session Management Function*, fonction de gestion des sessions. Fonction du cœur qui ouvre et gère les sessions de données |
| **Sortie structurée** | Technique qui empêche le modèle d'écrire autre chose qu'une réponse conforme à un schéma. Aussi appelée décodage contraint |
| **Source** | Un type de trace dans un domaine, par exemple les alarmes du transport. Le projet en compte 12 : 4 types de traces fois 3 domaines |
| **Station de base** | L'équipement radio d'un site. Voir gNB |
| **Surajustement** | *Overfitting*. Un système réglé de trop près sur ses exemples de mise au point, qui réussit ceux-là et échoue sur de nouveaux |
| **Suspect** | Élément qui se trouve sur le chemin de toutes les cellules en panne et qu'aucune cellule saine n'utilise |
| **Symptôme** | Conséquence visible d'une panne, par opposition à sa cause |
| **Témoin** | *Baseline*. Le système de référence auquel on compare une idée nouvelle |
| **Température** | Réglage de la fantaisie d'un modèle. À 0, il choisit toujours le mot le plus probable |
| **Test unitaire** | Vérification automatique d'un petit morceau de code. À ne pas confondre avec le jeu de test, qui sert à noter les systèmes |
| **Ticket** | La phrase par laquelle un incident est signalé à l'équipe de dépannage |
| **TLS** | *Transport Layer Security*. Protocole qui sécurise les échanges entre deux équipements |
| **Token** | Morceau de texte qu'un modèle lit ou écrit en une fois : un mot court, ou un fragment de mot |
| **Topologie** | Le plan du réseau : quels éléments existent et qui dépend de qui |
| **Tour** | Un passage dans la boucle d'un agent : un appel au modèle, suivi des outils qu'il demande |
| **Trafic** | L'ensemble des données qui circulent sur le réseau à un moment donné |
| **UE** | *User Equipment*, l'équipement de l'utilisateur : son téléphone |
| **UPF** | *User Plane Function*, fonction du plan utilisateur. Fonction du cœur qui transporte les données des abonnés vers Internet |
| **Vérité terrain** | La bonne réponse connue à l'avance, à laquelle on compare la réponse du système |

### Les mots du code

Le code et les données sont écrits en anglais, comme c'est l'usage. Voici ce que veulent dire les mots qui apparaissent dans ce document.

| Dans le code | Signification |
|---|---|
| `ran`, `transport`, `core` | Les trois domaines : la radio, le transport, le cœur |
| `fiber_cut` | Type de panne : fibre coupée |
| `link_congestion` | Type de panne : lien saturé |
| `hardware_failure` | Type de panne : panne matérielle |
| `config_error` | Type de panne : erreur de configuration |
| `overload` | Type de panne : surcharge d'une fonction du cœur |
| `interference` | Type de panne : brouillage radio |
| `critical`, `major`, `minor` | Gravité d'une alarme : critique, majeure, mineure |
| `healthy`, `impacted`, `local_cause` | Statut d'un rapport : sain, touché, cause locale |
| `get_alarms`, `get_kpis`, `get_logs`, `get_config_changes` | Les quatre outils : obtenir les alarmes, les mesures, les logs, les changements de configuration |
| `domain`, `element`, `fault` | Les trois champs d'un diagnostic : domaine, élément, type de panne |
| `analysis`, `status`, `affected_elements`, `first_event_time` | Champs d'un rapport : analyse, statut, éléments anormaux, heure du premier événement |
| `call_model`, `run_tools`, `remind`, `conclude` | Les nœuds du graphe d'un agent : appeler le modèle, exécuter les outils, rappeler, conclure |
| `single`, `single_aided`, `team` | Les trois systèmes : agent seul, agent seul aidé, équipe |
| `dev`, `test` | Les deux jeux de scénarios : mise au point, test |
| `verbose`, `brief` | Les deux versions des consignes dans l'expérience sur la longueur des réponses : bavard, bref |
| `before`, `during` | Valeur d'une mesure avant et pendant l'incident |
| `pct` | Suffixe d'une mesure exprimée en pour cent |
| `mbps`, `ms`, `db` | Suffixes d'unité : mégabits par seconde, millisecondes, décibels |
| `--answer`, `--aided`, `--system`, `--split`, `--affected`, `--healthy` | Options des commandes : réponse, aidé, système, jeu de scénarios, cellules touchées, cellules saines |
| `.py`, `.json`, `.md`, `.txt` | Types de fichier : code Python, données, texte mis en forme, texte simple |

### Les alarmes du projet

Ces noms sont inventés pour être lisibles. Ceux marqués « parasite » ne servent qu'à brouiller les pistes.

| Alarme | Ce qu'elle veut dire | |
|---|---|---|
| `BACKHAUL_LOSS` | Le site a perdu sa liaison vers le cœur |  |
| `BATTERY_TEST_RUNNING` | Un test de batterie programmé est en cours sur un site | parasite |
| `CABINET_DOOR_OPEN` | La porte de l'armoire d'un site est ouverte | parasite |
| `CELL_OUT_OF_SERVICE` | La cellule est hors service |  |
| `CERTIFICATE_EXPIRY_WARNING` | Un certificat de sécurité arrive bientôt à expiration | parasite |
| `COVERAGE_DEGRADED` | La zone couverte par la cellule a rétréci |  |
| `CPU_OVERLOAD` | Le processeur de la fonction est saturé |  |
| `FAN_SPEED_WARNING` | Un ventilateur tourne plus vite que la normale | parasite |
| `GNB_UNREACHABLE` | L'AMF n'arrive plus à joindre une station de base |  |
| `HARDWARE_FAULT` | L'équipement signale lui-même une panne matérielle |  |
| `HIGH_CALL_DROP_RATE` | Trop d'appels sont coupés avant la fin |  |
| `HIGH_PACKET_DROP` | L'UPF rejette une part anormale des paquets |  |
| `HIGH_UPLINK_NOISE` | Trop de bruit radio dans le sens téléphone vers antenne |  |
| `HIGH_UTILIZATION` | Le lien est presque plein |  |
| `LICENSE_USAGE_WARNING` | L'usage d'une licence logicielle approche de sa limite | parasite |
| `LINK_DOWN` | Le lien est hors service |  |
| `LOW_THROUGHPUT` | Le débit de la cellule est anormalement faible |  |
| `REGISTRATION_FAILURE_HIGH` | Trop d'enregistrements d'abonnés échouent |  |
| `ROUTE_LOSS` | Le routeur a perdu son chemin vers le cœur |  |
| `SESSION_SETUP_FAILURE_HIGH` | Trop d'ouvertures de session de données échouent |  |
| `UPF_UNREACHABLE` | Le SMF n'arrive plus à joindre l'UPF |  |

### Les mots anglais des logs

Les logs du projet imitent le style des équipements réels, donc ils sont en anglais.

| Dans les données | Signification |
|---|---|
| `baseband unit` | Unité de bande de base : le calculateur d'un site radio, qui traite les signaux des antennes |
| `buffer, queue` | File d'attente de paquets dans un équipement. `output buffer full` : la file est pleine. `queue drops` : des paquets sont jetés faute de place |
| `congestion control` | Protection d'une fonction surchargée, qui refuse des demandes pour ne pas s'effondrer |
| `electrical_tilt` | Inclinaison électrique : l'angle vers le bas du faisceau d'une antenne, en degrés. Trop incliné, le faisceau porte moins loin |
| `fan tray` | Bloc de ventilateurs d'un équipement |
| `handover` | Passage d'un téléphone d'une cellule à une autre pendant qu'il se déplace |
| `heartbeat, timeout` | Un *heartbeat* est un signal de vie que deux équipements s'échangent régulièrement. *Timeout* : aucune réponse n'est arrivée dans le délai prévu |
| `interface, port` | La prise du routeur sur laquelle arrive un lien. `P1`, `P2` et `P3` sont les ports des liens `L1`, `L2` et `L3` |
| `license` | Droit d'utiliser un logiciel, souvent limité à une certaine capacité |
| `line card` | Carte électronique d'un équipement, qui porte ses ports et fait transiter les paquets |
| `log_level` | Réglage du niveau de détail des logs d'un équipement. `INFO` : tout noter. `WARNING` : ne noter que les avertissements |
| `monitoring agent` | Petit programme de supervision installé sur un équipement. Sans rapport avec les agents d'IA de ce projet |
| `neighbour list` | Liste des cellules voisines d'une cellule, utilisée pour les *handovers* |
| `next hop` | Prochaine étape sur le chemin d'un paquet. `no valid next hop` : le routeur ne sait plus où envoyer le trafic |
| `packet filter` | Règles qui disent quels paquets laisser passer et lesquels rejeter |
| `PFCP` | *Packet Forwarding Control Protocol*. Protocole du dialogue entre le SMF et l'UPF |
| `radio link failure` | Rupture de la liaison radio entre un téléphone et sa cellule |
| `radio unit, transmitter` | L'unité radio d'une cellule et son émetteur |
| `routing policy` | Règles qui disent au routeur par où envoyer le trafic |
| `rx, tx` | Réception et émission. `tx_power_w` : puissance d'émission d'une cellule, en watts (W) |
| `TLS certificate` | **TLS** signifie *Transport Layer Security*. Un certificat est la pièce d'identité numérique d'un équipement. Elle a une date d'expiration |
| `ue_ip_pool_size` | Taille de la réserve d'adresses à distribuer aux abonnés. **UE** signifie *User Equipment*, le téléphone. **IP** signifie *Internet Protocol* : une adresse IP est le numéro qui rend un appareil joignable |
| `uplink` | Sens montant : du téléphone vers le réseau. `uplink noise rise` : le bruit radio augmente dans ce sens |

---

## Sources

Les définitions du réseau mobile ont été vérifiées sur les spécifications publiques. Les explications sur les agents s'appuient sur la documentation des outils utilisés.

- [3GPP TR 21.915, répartition des fonctions entre la radio et le cœur](https://itecspec.com/3gpp/21.915/s/5.5.1)
- [3GPP TS 29.244, le protocole PFCP entre le SMF et l'UPF](https://itecspec.com/3gpp/29.244/s/1)
- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629), l'article qui a donné son nom à la boucle d'un agent
- [Documentation d'Ollama : l'appel d'outil](https://docs.ollama.com/capabilities/tool-calling)
- [Documentation d'Ollama : la sortie structurée](https://docs.ollama.com/capabilities/structured-outputs)
- [Le modèle qwen2.5 dans la bibliothèque d'Ollama](https://ollama.com/library/qwen2.5)
- [Documentation de LangGraph : état, nœuds, arêtes et reducers](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Présentation du Model Context Protocol](https://modelcontextprotocol.io/docs/getting-started/intro)
