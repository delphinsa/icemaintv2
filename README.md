# Kit icemaint 0.2.0 : maintenance des tables Iceberg (Polaris) et client Teradata

Outil de maintenance unitaire des tables Iceberg du catalogue Polaris : une CLI
Python (typer) qui pilote un Spark local embarqué dans une image Docker, un
lanceur par commande pour $U, et un shell interactif. Depuis la 0.2.0, c'est aussi un
client Teradata : `td-sql` et `td-load` envoient du SQL à Teradata (driver Python,
sans JVM) pour alimenter des tables Iceberg, puis `compact` et `health` les contrôlent.

```
 $U ──► bin/compact.sh conf/jobs/<table>.env ──► docker run icemaint ──► Spark local (JVM)
          (réseau Docker du compose Polaris)                              │ (1) jeton OAuth2, chargement table ──► polaris-server:8181
                                                                          │ (2) lecture / écriture Parquet     ──► ECS (HTTPS)
                                                                          └ (3) commit du nouveau snapshot     ──► Polaris
```

**Pourquoi Spark ?** PyIceberg sait expirer des snapshots mais ne sait ni compacter
ni supprimer les orphelins. Les procédures Iceberg de Spark (`rewrite_data_files`,
`expire_snapshots`, `remove_orphan_files`, `rewrite_manifests`) sont la référence.
Spark tourne ici en mode local, dans le conteneur : pas de cluster.

---

## Les commandes

| Commande | Rôle | Effet | Par défaut |
|---|---|---|---|
| `health` | Petits fichiers, snapshots, volume retenu par l'historique, format-version, codec | Lecture seule | — |
| `compact` | Réécrit les petits fichiers en fichiers de taille cible (bin-pack) | Réversible (rollback) tant que les snapshots ne sont pas expirés | Exécution |
| `expire-snapshots` | Supprime l'historique ancien et les fichiers qu'il était seul à référencer | **Irréversible** | Simulation |
| `remove-orphans` | Supprime les fichiers S3 référencés par aucun snapshot (écritures avortées) | **Irréversible** | Simulation |
| `rewrite-manifests` | Regroupe les manifests (planification des requêtes plus rapide) | Réversible | Exécution |
| `purge` | Supprime les lignes répondant à un filtre (règle de conservation) | Réversible jusqu'à l'expiration des snapshots | Simulation |
| `sql` | Requête libre, en interactif (métadonnées, rollback) | Selon la requête | — |
| `td-sql` | Exécute un script SQL sur Teradata (INSERT dans une table Iceberg, SELECT, DDL) | Selon le script | Simulation : seules les lectures s'exécutent |
| `td-load` | Copie une table Teradata vers une table Iceberg (`INSERT INTO ... SELECT`, colonnes par nom) | Écrit des données | Simulation |

Ordre conseillé : `td-load` (si alimentation), `compact`, `expire-snapshots`, puis `remove-orphans`.
Chaque option de chaque commande a une variable d'environnement, affichée par
`icemaint <commande> --help`.

## Contenu du kit

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image : `python:3.14-slim-bookworm` (épinglée), JRE 17, PySpark 4.1, Iceberg 1.12.0 ; dépendances tirées des Nexus CNAV |
| `pyproject.toml`, `uv.lock` | Dépendances Python gérées par uv (typer, pyspark, teradatasql) ; `uv.lock` donne les versions de référence |
| `src/icemaint/` | Code de la CLI (`cli.py` : commandes ; `spark.py` : connexion Polaris et S3 ; `teradata.py` : connexion Teradata) |
| `bin/shell.sh` | Shell interactif dans l'image |
| `bin/<commande>.sh` | Un lanceur non interactif par commande, pour $U |
| `bin/_run.sh`, `bin/_lib.sh` | Mécanique commune des lanceurs (chargement des env, codes retour) |
| `conf/common.env.example` | Configuration commune (Polaris, S3, réseau, certificats, ressources) à copier en `common.env` |
| `conf/secrets.env.example` | Secrets à copier en `secrets.env` (`chmod 600`) |
| `conf/<commande>.env` | Paramètres par défaut de chaque commande |
| `conf/jobs/` | Un fichier par table (ou groupe de tables), passé en argument par $U |
| `conf/sql/` | Scripts SQL Teradata pour `td-sql`, montés en lecture seule dans le conteneur |
| `scripts/build-image.sh` | Construction de l'image |
| `scripts/export-image.sh` | Export de l'image en archive, pour une autre machine sans accès aux Nexus |

---

## Prérequis

- **VM** : Docker, le compose Polaris démarré, l'agent $U avec un compte autorisé à
  lancer `docker`. Environ 3 Go libres sur le disque de Docker pour construire
  l'image (pyspark est compilé depuis ses sources), 1,2 Go ensuite pour l'image.
- **Accès aux Nexus CNAV** depuis la VM (déjà configurés comme valeurs par défaut du
  `Dockerfile`) : PyPI `python.artifact.ul.cnavts.fr`, Maven
  `maven.artifact.ul.cnavts.fr/repository/group`, et Docker Hub pour les images de base.
- **Polaris** : un principal pour la maintenance. Pour le POC, le plus simple dans la
  console web : créer le principal `icemaint` (noter client_id et secret), créer un
  rôle principal `icemaint_role`, le donner au principal, puis lui accorder **le même
  rôle de catalogue que celui de `teradata`** (déjà validé en écriture). En cible :
  un rôle de catalogue dédié aux droits minimaux. Ne jamais utiliser `root`.
- **S3** : un jeu de clés avec lecture, écriture, listage **et suppression** sur le
  bucket. Polaris est en `stsUnavailable` : il ne délivre pas de clés. Pour le POC,
  les clés Teradata conviennent ; en cible, des clés dédiées.

## Installation pas à pas

### Étape 1 : construire l'image (sur la VM)

```bash
cd /opt/dataplatform/maintenance-iceberg
chmod +x bin/*.sh scripts/*.sh          # le kit est passé par Windows
./scripts/build-image.sh                # environ 2 minutes ; attendu : « Image construite : icemaint:0.2.1 »
docker builder prune -af                # libère le cache de build (l'image est conservée)
```

L'export (`scripts/export-image.sh`) ne sert que pour installer l'image sur une
autre machine qui n'a pas accès aux Nexus.

### Étape 2 : configurer

```bash
cp conf/common.env.example conf/common.env
cp conf/secrets.env.example conf/secrets.env && chmod 600 conf/secrets.env
vi conf/common.env conf/secrets.env     # remplacer toutes les valeurs <...>
```

Points propres à la VM du POC, déjà prévus dans `common.env.example` :

- **Réseau** : le démon Docker a les *user namespaces* activés, ce qui interdit
  `--network host`. icemaint rejoint donc le réseau du compose Polaris
  (`docker inspect polaris-server` pour son nom, ici `polaris-catalog_default`) et
  joint Polaris par le nom de son conteneur : `POLARIS_URI=http://polaris-server:8181/api/catalog`
  (port interne 8181, pas le port publié sur l'hôte).
- **Certificats ECS** : comme pour Polaris, Java utilise le magasin de confiance du
  système (`/etc/pki/ca-trust/extracted/java/cacerts`), monté en lecture seule.
  Le message `Picked up JAVA_TOOL_OPTIONS` au démarrage est normal.
- **Teradata (facultatif)** : `TERADATA_HOST`, `TERADATA_USER` et `TERADATA_PASSWORD` vont
  dans `conf/secrets.env`. Le conteneur doit joindre l'hôte Teradata (port 1025 par
  défaut) depuis le réseau Docker du compose Polaris : à tester avec `bin/shell.sh`
  puis `icemaint td-sql -q "SELECT 1"`.
- **Fichiers montés** : avec les user namespaces, le conteneur ne lit pas les
  dossiers en `drwx------` comme `/opt/dataplatform`. Tout fichier à monter doit
  être lisible par tous (c'est le cas de `/etc/pki`). Pour `conf/sql` :
  `chmod 755 conf/sql ; chmod 644 conf/sql/*.sql`.

### Étape 3 : premier contrôle, en lecture seule

```bash
cp conf/jobs/exemple-poc_db.t_ventes.env conf/jobs/poc_db.t_ventes.env   # adapter ICEMAINT_TABLE
bin/health.sh conf/jobs/poc_db.t_ventes.env
```

Attendu : quelques lignes d'état, puis `RESULTAT {... "statut": "OK" ...}` et `code 0`.
En cas d'échec, la ligne `ERREUR` donne la cause racine. Pour la trace Java complète,
ajouter `ICEMAINT_DEBUG=true` dans le fichier job.

| Symptôme | Cause probable |
|---|---|
| `valeurs à compléter` ou `variables manquantes`, code 2 | `common.env` ou `secrets.env` incomplet, ou non copié sur la VM |
| `cannot share the host's network namespace` | `ICEMAINT_DOCKER_NETWORK` absent de `common.env` |
| `network ... not found` | Nom du réseau du compose Polaris erroné |
| `Connection refused`, `UnknownHost` (Polaris) | `POLARIS_URI` : nom du conteneur et port interne 8181 |
| `401` / `unauthorized` | client_id ou secret Polaris |
| `400` / `invalid_scope` | `POLARIS_SCOPE` (Polaris 1.8 exige `PRINCIPAL_ROLE:...`) |
| `403` / `NotAuthorized` | Droits du rôle Polaris |
| `PKIX path`, `unable to find valid certification path` | `ICEMAINT_TLS_DIR` / `JAVA_TOOL_OPTIONS` (magasin de confiance) |
| `Permission denied` sur `cacerts` | SELinux : le compose Polaris monte ce fichier en `:Z` (privé). Passer en `:ro,z` côté Polaris |
| `AccessDenied` (S3) | Clés S3 ou policy du bucket |
| Code 125 | `docker run` refusé : lire le message Docker juste au-dessus |

### Étape 4 : recette de compatibilité Teradata (avant toute planification)

Spark réécrit des fichiers que Teradata relira ensuite. À faire sur une table de test
écrite par Teradata, avec plusieurs petits fichiers (par exemple une dizaine
d'`INSERT` successifs de quelques lignes) :

1. Teradata : noter le résultat de `SELECT COUNT(*), SUM(<colonne numérique>) FROM <table>;`.
2. `bin/health.sh <job.env>` : noter le nombre de fichiers. Puis `bin/shell.sh` et
   noter le snapshot courant :
   `icemaint sql "SELECT snapshot_id, committed_at FROM poc_db.t_ventes.snapshots ORDER BY committed_at DESC"`
3. `bin/compact.sh <job.env>` : `rewritten_data_files_count` doit être supérieur à 0.
   Sinon, mettre `ICEMAINT_MIN_INPUT_FILES=2` dans le fichier job.
4. Teradata : relancer la requête de l'étape 1 (résultat identique), plus une requête
   time travel si vous en utilisez. `bin/health.sh` : moins de fichiers,
   `format-version` inchangé.
5. En cas d'échec côté Teradata : revenir en arrière avec
   `icemaint sql "CALL polaris.system.rollback_to_snapshot('poc_db.t_ventes', <snapshot_id>)"`,
   puis réessayer avec `ICEMAINT_COMPRESSION_CODEC=snappy` dans `common.env`.

### Étape 5 : planifier dans $U

Ligne de commande d'un job : `/opt/dataplatform/maintenance-iceberg/bin/compact.sh /opt/dataplatform/maintenance-iceberg/conf/jobs/poc_db.t_ventes.env`

La configuration est chargée dans cet ordre, la dernière valeur l'emporte :
`common.env` < `secrets.env` < `conf/<commande>.env` < fichier job. Des options
peuvent être ajoutées après `--` : `bin/compact.sh <job.env> -- --max-concurrent 1`.

| Code retour | Signification | Action |
|---|---|---|
| 0 | OK | — |
| 1 | Au moins une table en échec | Lignes `ERREUR` et `RESULTAT ... "KO"` du journal |
| 2 | Paramètre ou configuration invalide | Fichiers `conf/` |
| 125 | `docker run` refusé | Message Docker : exécution déjà en cours sur la table, image absente, option refusée |
| 137 | Conteneur tué | Mémoire : augmenter `ICEMAINT_DOCKER_MEMORY` ou réduire la concurrence |

Point de départ de planification :

| Job | Fréquence | Mode |
|---|---|---|
| `compact` | Quotidien, après les chargements Teradata | Réel |
| `expire-snapshots` | Quotidien, après `compact` | Simulation 2 semaines, puis réel |
| `rewrite-manifests` | Hebdomadaire | Réel |
| `remove-orphans` | Hebdomadaire | Simulation plusieurs semaines |
| `health` | Hebdomadaire | Lecture seule ; les lignes `RESULTAT` donnent l'historique |

- Hors fenêtres de chargement Teradata : un commit concurrent provoque un conflit
  (Iceberg relance quelques fois, puis échoue en code 1 ; les groupes déjà compactés sont conservés).
- Un seul job icemaint à la fois sur la VM du POC (ressource $U), pour ne pas
  pénaliser Polaris.
- Passer du mode simulation au mode réel : `ICEMAINT_DRY_RUN=false` dans le fichier job.

---

## Client Teradata : alimenter Iceberg depuis ce conteneur

Les deux commandes n'ont pas de Spark : elles envoient du SQL à Teradata, qui lit
sa table interne et écrit en Iceberg sur S3 par la table étrangère
(`serveur.namespace.table`, ex. `iceberg_onprem_s3_polaris_POC.RGCU.TABLE`).
Les données ne transitent pas par le conteneur. Un conteneur de 1 Go suffit.

**Copie d'une table** (`td-load`) : source, cible et filtre dans un fichier job
(`conf/jobs/exemple-td-load.env`).

```bash
bin/td-load.sh conf/jobs/exemple-td-load.env                    # simulation : colonnes, nombre de lignes
ICEMAINT_DRY_RUN=false bin/td-load.sh conf/jobs/exemple-td-load.env   # copie réelle
```

La simulation vérifie la connexion, lit les colonnes de la source dans `DBC.ColumnsV`
(jamais `SELECT *` : sur une table très large, Teradata refuse un résultat de plus
de 1 Mo par ligne, erreur 9991), vérifie que la cible existe et compte les lignes à
copier. Les colonnes sont appariées par nom, pas par position ; si l'une manque dans
la cible, c'est l'`INSERT` qui échoue. La copie réelle compare ce compte au
nombre de lignes annoncé par Teradata : en cas d'écart, statut `ECART` et code 1.

**Script SQL libre** (`td-sql`) : déposer le fichier dans `conf/sql/`, le nommer
dans un job (`ICEMAINT_TD_FILE=mon_insert.sql`). Plusieurs instructions dans un
fichier : les séparer par une ligne contenant uniquement `-----`. Par défaut,
seules les lectures (SELECT, SHOW, HELP, EXPLAIN) s'exécutent ; les INSERT, DDL et
DELETE sont listés puis ignorés tant que `ICEMAINT_DRY_RUN` n'est pas `false` (ou
`-- --apply`). L'exécution s'arrête à la première erreur.

```bash
bin/td-sql.sh conf/jobs/exemple-td-sql.env
bin/shell.sh     # puis : icemaint td-sql -q "SELECT COUNT(*) FROM DB.TABLE"
```

Précautions :

- **Compte Teradata** : un compte dédié (lecture sur les bases sources, écriture
  sur le serveur Iceberg), pas un compte SYSDBA. Le conteneur lit les données
  de la CNAV avec les droits de ce compte.
- **Durée** : une copie de plusieurs dizaines de minutes se lance sous `tmux` ou
  `nohup ... &`, pas dans une session PuTTY seule. Si la session est coupée, vérifier
  côté Teradata que la requête n'est plus active avant de relancer, pour ne pas
  dupliquer les lignes.
- **Relance** : `td-load` ajoute des lignes (`INSERT`) sans vider la cible.
  Relancer deux fois la même copie la duplique ; vider ou recréer la table avant.
- **Petits fichiers** : la taille des fichiers écrits dépend de Teradata. Après une
  copie, `bin/health.sh` sur la cible (`taille_moyenne_mo`, `petits_fichiers`), puis
  `bin/compact.sh` si besoin.
- **Journaux** : les instructions sont écrites sur une ligne tronquée à 300
  caractères ; un `PASSWORD = '...'` éventuel est masqué. Un SELECT affiche des
  lignes de données (20 par défaut, `ICEMAINT_TD_LIMIT`) : ne pas l'utiliser sur des
  colonnes sensibles si les journaux sont conservés.
- **Recette** : `td-sql` et `td-load` sont testés avec une session simulée, pas
  encore contre le Teradata de la CNAV.

## Dimensionnement

Point de départ, fixé par `common.env` : 2 cœurs et 3 Go pour Spark, plafonds Docker
de 2 CPU et 4 Go. Garder la mémoire Spark à environ 75 % du plafond Docker.

Pour mesurer, lancer une compaction depuis `bin/shell.sh` et suivre l'interface Spark
sur `http://<vm>:4040` (port publié par `shell.sh`), avec `docker stats` :

- temps de GC supérieur à 10 % du temps des tâches : plus de mémoire ;
- écritures sur disque (spill) : plus de mémoire, ou `ICEMAINT_MAX_GROUP_SIZE_GB` plus petit ;
- CPU sous 70 % : le réseau ou S3 limite, ajouter des cœurs ne sert à rien ;
- code 137 : plafond mémoire Docker atteint.

Le volume à compacter par nuit est proche du volume chargé par Teradata dans la
journée sur ces tables. `ICEMAINT_WHERE` limite la compaction aux partitions récentes.

## Garde-fous et limites

- **Rétention des snapshots** : elle doit dépasser l'âge de la plus ancienne sauvegarde
  PostgreSQL du catalogue que vous pourriez restaurer. Sinon, une restauration
  pointerait vers des fichiers déjà supprimés.
- **Orphelins** : ne pas exécuter pendant la migration ECS vers Hitachi. Si le bucket
  est versionné, une suppression ne libère pas l'espace. Une erreur
  `prefix mismatch` est une protection : ne pas la contourner sans analyse.
- **Purge** : les lignes supprimées restent lisibles en time travel tant que les
  snapshots ne sont pas expirés.
- **Ressources partagées** : sur la VM du POC, icemaint partage CPU, mémoire, disque
  et réseau avec Polaris. En production, une machine dédiée.
- **Secrets** : `conf/secrets.env` en `chmod 600`. Les lanceurs transmettent les
  valeurs au conteneur par l'environnement, pas sur la ligne de commande. Le flux
  vers Polaris reste en HTTP, comme le reste du POC.
- **Construction** : la vérification du certificat du Nexus PyPI est désactivée
  (`PIP_TRUSTED_HOST` dans le `Dockerfile`). En cible, ajouter l'AC CNAV à l'étape
  de construction.
- **Versions Python** : `uv.lock` pointe vers pypi.org ; le build refait la
  résolution via le Nexus en gardant ces versions autant que possible. Les bornes
  de `pyproject.toml` (`typer>=0.21.1`, `pyspark>=4.1.4,<4.2`) restent garanties.
- **Recette** : la chaîne a été validée de bout en bout sur une table vide
  (Polaris, ECS en HTTPS). La compaction réelle et la relecture par Teradata
  restent à valider (étape 4).

## Évolutions possibles

- Polaris peut stocker des politiques de maintenance (compaction, expiration,
  orphelins) par catalogue, namespace ou table. Une commande `auto` pourrait les
  lire, à la place des fichiers job.
- Mettre à jour Iceberg ou Spark : modifier ensemble `ICEBERG_VERSION` (Dockerfile)
  et la contrainte `pyspark` (pyproject.toml), puis `uv lock`.
- Migration Hitachi : si sa PKI diffère, l'ajouter au magasin de confiance du
  système de la VM (`update-ca-trust`) ; icemaint et Polaris en profitent tous deux.
