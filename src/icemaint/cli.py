"""icemaint : maintenance des tables Iceberg (catalogue Polaris) et client Teradata.

Chaque option peut être fournie par une variable d'environnement (affichée dans --help).
Ordre de priorité : option en ligne de commande > variable d'environnement > valeur par défaut.

Codes retour : 0 = OK, 1 = au moins une table en échec, 2 = paramètre ou configuration invalide.
"""

import datetime as dt
import json
import os
import sys
import time
from typing import Annotated, Callable, Optional

from pathlib import Path

import typer

from icemaint import __version__
from icemaint import teradata as td
from icemaint.spark import CATALOG, ConfigError, build_spark

MB = 1024 * 1024
GB = 1024 * MB

# Dossier des scripts SQL Teradata, monté en lecture seule par les lanceurs (conf/sql).
SQL_DIR = Path(os.environ.get("ICEMAINT_SQL_MOUNT", "/opt/icemaint/sql"))

app = typer.Typer(
    name="icemaint",
    help="Maintenance des tables Iceberg (Polaris, Spark local embarqué) et client Teradata (td-sql, td-load).",
    no_args_is_help=True,
    pretty_exceptions_enable=False,  # pas de variables locales (donc pas de secrets) dans les erreurs
    context_settings={"help_option_names": ["-h", "--help"]},
)

# --------------------------------------------------------------------------- options communes

TableOpt = Annotated[
    str,
    typer.Option(
        "--table", "-t", envvar="ICEMAINT_TABLE", show_envvar=True,
        help="namespace.table ; plusieurs tables séparées par des virgules ; namespace.* pour tout un namespace.",
    ),
]
DryRunOpt = Annotated[
    bool,
    typer.Option(
        "--dry-run/--apply", envvar="ICEMAINT_DRY_RUN", show_envvar=True,
        help="Simulation (par défaut) ou exécution réelle.",
    ),
]
TargetMbOpt = Annotated[
    int,
    typer.Option(envvar="ICEMAINT_TARGET_FILE_SIZE_MB", show_envvar=True, min=1, help="Taille cible des fichiers (Mo)."),
]
WhereOpt = Annotated[
    Optional[str],
    typer.Option(envvar="ICEMAINT_WHERE", show_envvar=True, help="Filtre SQL Spark sur les lignes, ex. \"jour >= '2026-11-01'\"."),
]


def _version(value: bool) -> None:
    if value:
        typer.echo(f"icemaint {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Affiche la version.")
    ] = False,
) -> None:
    """Maintenance des tables Iceberg du catalogue Polaris (Spark local embarqué)."""


# --------------------------------------------------------------------------- utilitaires


def log(msg: str) -> None:
    typer.echo(f"[{dt.datetime.now():%H:%M:%S}] {msg}")


def quote_ident(part: str) -> str:
    return "`" + part.replace("`", "``") + "`"


def sql_str(value: str) -> str:
    """Littéral chaîne Spark SQL."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def ts_literal(days_ago: int) -> tuple[str, str]:
    """Horodatage UTC « maintenant - N jours » (la session Spark est en UTC)."""
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    text = when.strftime("%Y-%m-%d %H:%M:%S")
    return f"TIMESTAMP '{text}'", text + " UTC"


class Target:
    """Une table du catalogue : namespace (éventuellement à plusieurs niveaux) + nom."""

    def __init__(self, namespace: list[str], name: str):
        self.namespace, self.name = namespace, name

    def __str__(self) -> str:
        return ".".join([*self.namespace, self.name])

    @property
    def sql(self) -> str:  # référence SQL : polaris.`ns`.`table`
        return ".".join([CATALOG, *map(quote_ident, [*self.namespace, self.name])])

    @property
    def proc_arg(self) -> str:  # argument table => '...' des procédures Iceberg (catalogue inclus)
        return sql_str(".".join([CATALOG, *map(quote_ident, [*self.namespace, self.name])]))


def parse_spec(spec: str) -> list[tuple[list[str], str]]:
    """Valide --table avant de démarrer Spark. Renvoie [(namespace, nom ou '*')]."""
    items = [s.strip() for s in (spec or "").split(",") if s.strip()]
    if not items:
        raise typer.BadParameter("table obligatoire (--table ou ICEMAINT_TABLE)", param_hint="--table")
    parsed = []
    for item in items:
        parts = item.split(".")
        if len(parts) < 2 or not all(parts):
            raise typer.BadParameter(f"« {item} » : format attendu namespace.table", param_hint="--table")
        if "*" in parts[:-1] or ("*" in parts[-1] and parts[-1] != "*"):
            raise typer.BadParameter(f"« {item} » : seul namespace.* est accepté", param_hint="--table")
        parsed.append((parts[:-1], parts[-1]))
    return parsed


def resolve(spark, parsed: list[tuple[list[str], str]]) -> list[Target]:
    targets: list[Target] = []
    for namespace, name in parsed:
        if name != "*":
            targets.append(Target(namespace, name))
            continue
        ns_sql = ".".join([CATALOG, *map(quote_ident, namespace)])
        rows = spark.sql(f"SHOW TABLES IN {ns_sql}").collect()
        targets.extend(Target(namespace, r["tableName"]) for r in sorted(rows, key=lambda r: r["tableName"]))
    return targets


def short_error(exc: Exception) -> str:
    """Cause racine lisible d'une erreur Spark/Java (dernière ligne « Caused by: »)."""
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    causes = [line[len("Caused by:"):].strip() for line in lines if line.startswith("Caused by:")]
    return (causes[-1] if causes else (lines[0] if lines else repr(exc)))[:500]


def first_row(spark, query: str) -> dict:
    rows = spark.sql(query).collect()
    return rows[0].asDict() if rows else {}


def emit(op: str, target: Target, status: str, data: dict, started: float) -> None:
    """Ligne de synthèse lisible par l'ordonnanceur et par un outil de suivi."""
    record = {"operation": op, "table": str(target), "statut": status,
              "duree_s": round(time.monotonic() - started, 1), **data}
    typer.echo("RESULTAT " + json.dumps(record, ensure_ascii=False, default=str))


def run(op: str, spec: str, action: Callable, *, single_table: bool = False) -> None:
    """Démarre Spark, résout les tables et applique « action » à chacune."""
    parsed = parse_spec(spec)
    if single_table and (len(parsed) != 1 or parsed[0][1] == "*"):
        raise typer.BadParameter("cette commande s'applique à une seule table", param_hint="--table")
    try:
        spark = build_spark(f"icemaint-{op}")
    except ConfigError as exc:
        typer.echo(f"ERREUR configuration : {exc}", err=True)
        raise typer.Exit(2)

    failures = 0
    try:
        try:
            targets = resolve(spark, parsed)
        except Exception as exc:  # catalogue injoignable, droits, namespace inconnu...
            typer.echo(f"ERREUR résolution des tables : {short_error(exc)}", err=True)
            raise typer.Exit(1)
        if not targets:
            typer.echo("ERREUR : aucune table trouvée", err=True)
            raise typer.Exit(1)

        for target in targets:
            started = time.monotonic()
            log(f"{op} {target} : début")
            try:
                data = action(spark, target)
                emit(op, target, "OK", data, started)
            except Exception as exc:
                failures += 1
                if os.environ.get("ICEMAINT_DEBUG", "").lower() == "true":
                    typer.echo(str(exc), err=True)  # trace Java complète
                typer.echo(f"ERREUR {target} : {short_error(exc)}", err=True)
                emit(op, target, "KO", {"erreur": short_error(exc)}, started)
    finally:
        spark.stop()
    raise typer.Exit(1 if failures else 0)


# --------------------------------------------------------------------------- commandes


@app.command()
def health(table: TableOpt = "", target_file_size_mb: TargetMbOpt = 512) -> None:
    """État d'une table, en lecture seule : petits fichiers, snapshots, volume retenu par l'historique."""
    small = int(target_file_size_mb * MB * 0.75)  # seuil sous lequel la compaction bin-pack réécrit

    def action(spark, t: Target) -> dict:
        data = first_row(spark, f"""
            SELECT count(*) AS fichiers,
                   coalesce(sum(file_size_in_bytes), 0) AS octets,
                   coalesce(sum(CASE WHEN file_size_in_bytes < {small} THEN 1 ELSE 0 END), 0) AS petits_fichiers,
                   coalesce(sum(record_count), 0) AS lignes
            FROM {t.sql}.data_files""")
        deletes = first_row(spark, f"SELECT count(*) AS n FROM {t.sql}.delete_files")["n"]
        snaps = first_row(spark, f"""
            SELECT count(*) AS n, min(committed_at) AS plus_ancien, max(committed_at) AS plus_recent
            FROM {t.sql}.snapshots""")
        manifests = first_row(spark, f"SELECT count(*) AS n FROM {t.sql}.manifests")["n"]
        history = first_row(spark, f"""
            SELECT count(*) AS fichiers, coalesce(sum(file_size_in_bytes), 0) AS octets
            FROM (SELECT DISTINCT file_path, file_size_in_bytes FROM {t.sql}.all_data_files)""")
        props = {r["key"]: r["value"] for r in spark.sql(f"SHOW TBLPROPERTIES {t.sql}").collect()}

        avg_mb = data["octets"] / data["fichiers"] / MB if data["fichiers"] else 0
        retained_files = history["fichiers"] - data["fichiers"]
        retained_bytes = history["octets"] - data["octets"]
        log(f"  fichiers de données : {data['fichiers']} ({data['octets'] / GB:.2f} Go, "
            f"moyenne {avg_mb:.1f} Mo), dont {data['petits_fichiers']} sous {small // MB} Mo")
        log(f"  fichiers de suppression : {deletes}")
        log(f"  snapshots : {snaps['n']} (du {snaps['plus_ancien']} au {snaps['plus_recent']}) ; manifests : {manifests}")
        log(f"  retenu uniquement par l'historique : {retained_files} fichiers, {retained_bytes / GB:.2f} Go")
        log(f"  format-version={props.get('format-version', '?')} ; "
            f"codec={props.get('write.parquet.compression-codec', '(défaut moteur)')}")
        return {
            "fichiers": data["fichiers"], "octets": data["octets"], "taille_moyenne_mo": round(avg_mb, 1),
            "petits_fichiers": data["petits_fichiers"], "lignes": data["lignes"],
            "fichiers_suppression": deletes, "snapshots": snaps["n"],
            "snapshot_plus_ancien": snaps["plus_ancien"], "manifests": manifests,
            "historique_fichiers": retained_files, "historique_octets": retained_bytes,
            "proprietes": {k: v for k, v in props.items()
                           if k.startswith(("format-version", "write.", "history.", "commit."))},
        }

    run("health", table, action)


@app.command()
def compact(
    table: TableOpt = "",
    target_file_size_mb: TargetMbOpt = 512,
    min_input_files: Annotated[int, typer.Option(envvar="ICEMAINT_MIN_INPUT_FILES", show_envvar=True, min=2,
        help="Nombre minimal de petits fichiers pour réécrire un groupe.")] = 5,
    max_concurrent: Annotated[int, typer.Option(envvar="ICEMAINT_MAX_CONCURRENT", show_envvar=True, min=1,
        help="Groupes réécrits en parallèle (au plus le nombre de cœurs Spark).")] = 2,
    max_group_size_gb: Annotated[int, typer.Option(envvar="ICEMAINT_MAX_GROUP_SIZE_GB", show_envvar=True, min=1,
        help="Taille maximale d'un groupe ; chaque groupe terminé est validé (commit) sans attendre la fin.")] = 10,
    where: WhereOpt = None,
) -> None:
    """Compaction bin-pack des petits fichiers (procédure rewrite_data_files)."""
    options = {
        "target-file-size-bytes": target_file_size_mb * MB,
        "min-input-files": min_input_files,
        "max-concurrent-file-group-rewrites": max_concurrent,
        "max-file-group-size-bytes": max_group_size_gb * GB,
        "partial-progress.enabled": "true",  # un job interrompu garde les groupes déjà réécrits
        "partial-progress.max-commits": 10,
    }
    opts_sql = ", ".join(f"{sql_str(k)}, {sql_str(str(v))}" for k, v in options.items())
    where_sql = f", where => {sql_str(where)}" if where else ""

    def action(spark, t: Target) -> dict:
        return first_row(spark, f"CALL {CATALOG}.system.rewrite_data_files(table => {t.proc_arg}, "
                                f"strategy => 'binpack', options => map({opts_sql}){where_sql})")

    run("compact", table, action)


@app.command("expire-snapshots")
def expire_snapshots(
    table: TableOpt = "",
    older_than_days: Annotated[int, typer.Option(envvar="ICEMAINT_OLDER_THAN_DAYS", show_envvar=True, min=1,
        help="Expire les snapshots plus anciens que N jours.")] = 7,
    retain_last: Annotated[int, typer.Option(envvar="ICEMAINT_RETAIN_LAST", show_envvar=True, min=1,
        help="Conserve toujours les N snapshots les plus récents.")] = 5,
    dry_run: DryRunOpt = True,
) -> None:
    """Expire les anciens snapshots et supprime les fichiers qu'eux seuls référençaient."""
    cutoff_sql, cutoff = ts_literal(older_than_days)

    def action(spark, t: Target) -> dict:
        if dry_run:
            sim = first_row(spark, f"""
                SELECT count(*) AS snapshots,
                       coalesce(sum(CASE WHEN rn > {retain_last} AND committed_at < {cutoff_sql} THEN 1 ELSE 0 END), 0)
                         AS a_expirer
                FROM (SELECT committed_at, row_number() OVER (ORDER BY committed_at DESC) AS rn
                      FROM {t.sql}.snapshots)""")
            log(f"  SIMULATION : {sim['a_expirer']} snapshot(s) sur {sim['snapshots']} plus ancien(s) que {cutoff} "
                f"(hors {retain_last} derniers ; les tags et branches en protègent aussi)")
            return {"simulation": True, "date_limite": cutoff, **sim}
        return {"simulation": False, "date_limite": cutoff, **first_row(spark, f"""
            CALL {CATALOG}.system.expire_snapshots(table => {t.proc_arg}, older_than => {cutoff_sql},
                 retain_last => {retain_last}, stream_results => true)""")}

    run("expire-snapshots", table, action)


@app.command("remove-orphans")
def remove_orphans(
    table: TableOpt = "",
    older_than_days: Annotated[int, typer.Option(envvar="ICEMAINT_OLDER_THAN_DAYS", show_envvar=True, min=1,
        help="Ne supprime que les fichiers orphelins plus anciens que N jours (protège les écritures en cours).")] = 3,
    dry_run: DryRunOpt = True,
) -> None:
    """Supprime les fichiers présents sur S3 sous l'emplacement de la table mais référencés par aucun snapshot."""
    cutoff_sql, cutoff = ts_literal(older_than_days)

    def action(spark, t: Target) -> dict:
        # prefix_listing : listage via S3FileIO (pas besoin du connecteur Hadoop s3a)
        rows = spark.sql(f"""
            CALL {CATALOG}.system.remove_orphan_files(table => {t.proc_arg}, older_than => {cutoff_sql},
                 dry_run => {'true' if dry_run else 'false'}, prefix_listing => true, stream_results => true)""").collect()
        files = [r[0] for r in rows]
        verb = "à supprimer (SIMULATION)" if dry_run else "supprimés"
        log(f"  {len(files)} fichier(s) orphelin(s) plus ancien(s) que {cutoff} {verb}")
        for path in files[:20]:
            log(f"    {path}")
        if len(files) > 20:
            log(f"    ... ({len(files) - 20} autres)")
        return {"simulation": dry_run, "date_limite": cutoff, "orphelins": len(files)}

    run("remove-orphans", table, action)


@app.command("rewrite-manifests")
def rewrite_manifests(table: TableOpt = "") -> None:
    """Regroupe les manifests (accélère la planification des requêtes)."""

    def action(spark, t: Target) -> dict:
        return first_row(spark, f"CALL {CATALOG}.system.rewrite_manifests(table => {t.proc_arg})")

    run("rewrite-manifests", table, action)


@app.command()
def purge(table: TableOpt = "", where: WhereOpt = None, dry_run: DryRunOpt = True) -> None:
    """Purge métier : supprime les lignes répondant au filtre (une seule table à la fois).

    Les données restent lisibles en time travel jusqu'à l'expiration des snapshots.
    """
    if not where:
        raise typer.BadParameter("filtre obligatoire (--where ou ICEMAINT_WHERE)", param_hint="--where")

    def action(spark, t: Target) -> dict:
        n = first_row(spark, f"SELECT count(*) AS n FROM {t.sql} WHERE {where}")["n"]
        if dry_run:
            log(f"  SIMULATION : {n} ligne(s) seraient supprimées")
        elif n:
            spark.sql(f"DELETE FROM {t.sql} WHERE {where}")
            log(f"  {n} ligne(s) supprimées")
        return {"simulation": dry_run, "filtre": where, "lignes": n}

    run("purge", table, action, single_table=True)


@app.command()
def sql(
    query: Annotated[str, typer.Argument(help="Requête Spark SQL ; le catalogue courant est « polaris ».")],
    limit: Annotated[int, typer.Option(min=1, help="Lignes affichées au maximum.")] = 100,
) -> None:
    """Exécute une requête SQL (usage interactif : métadonnées, rollback, propriétés...)."""
    try:
        spark = build_spark("icemaint-sql")
    except ConfigError as exc:
        typer.echo(f"ERREUR configuration : {exc}", err=True)
        raise typer.Exit(2)
    try:
        spark.sql(f"USE {CATALOG}")
        spark.sql(query).show(limit, truncate=False)
    except Exception as exc:
        typer.echo(f"ERREUR : {short_error(exc)}", err=True)
        raise typer.Exit(1)
    finally:
        spark.stop()


# --------------------------------------------------------------------------- client Teradata


def td_connect():
    """Session Teradata ou sortie propre (2 = configuration, 1 = connexion refusée)."""
    try:
        return td.connect()
    except td.TdConfigError as exc:
        typer.echo(f"ERREUR configuration : {exc}", err=True)
        raise typer.Exit(2)
    except Exception as exc:
        typer.echo(f"ERREUR connexion Teradata : {short_error(exc)}", err=True)
        raise typer.Exit(1)


def read_sql_file(name: str) -> str:
    """Lit un script du dossier monté (SQL_DIR) ; refuse tout chemin extérieur."""
    base = SQL_DIR.resolve()
    path = (base / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(base):
        raise typer.BadParameter(f"« {name} » : seuls les fichiers du dossier {base} sont acceptés", param_hint="--file")
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise typer.BadParameter(f"fichier introuvable : {path}", param_hint="--file")
    except PermissionError:
        raise typer.BadParameter(
            f"lecture refusée : {path} (sur la VM : chmod 755 conf/sql ; chmod 644 conf/sql/*.sql)", param_hint="--file")


def td_run_statement(cur, stmt: str, limit: int) -> dict:
    """Exécute une instruction ; affiche au plus « limit » lignes si elle renvoie un résultat."""
    cur.execute(stmt)
    if cur.description:
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit + 1)
        log("  " + " | ".join(columns))
        for row in rows[:limit]:
            log("  " + " | ".join("" if v is None else str(v) for v in row))
        truncated = len(rows) > limit
        if truncated:
            log(f"  … affichage limité à {limit} lignes")
        return {"colonnes": len(columns), "lignes_affichees": min(len(rows), limit), "tronque": truncated}
    return {"lignes": cur.rowcount}


@app.command("td-sql")
def td_sql(
    file: Annotated[Optional[str], typer.Option("--file", "-f", envvar="ICEMAINT_TD_FILE", show_envvar=True,
        help="Script SQL du dossier conf/sql (nom relatif).")] = None,
    query: Annotated[Optional[str], typer.Option("--query", "-q", envvar="ICEMAINT_TD_QUERY", show_envvar=True,
        help="Instruction SQL Teradata passée directement.")] = None,
    delimiter: Annotated[str, typer.Option(envvar="ICEMAINT_TD_DELIMITER", show_envvar=True,
        help="Ligne séparant plusieurs instructions dans un fichier.")] = "-----",
    limit: Annotated[int, typer.Option(envvar="ICEMAINT_TD_LIMIT", show_envvar=True, min=1,
        help="Lignes affichées au maximum pour un SELECT.")] = 20,
    dry_run: DryRunOpt = True,
) -> None:
    """Exécute du SQL sur Teradata (INSERT dans une table Iceberg, SELECT, DDL...).

    Par défaut seules les lectures (SELECT, SHOW, HELP, EXPLAIN) sont exécutées ;
    les autres instructions sont listées sans être exécutées. --apply les exécute.
    """
    if bool(file) == bool(query):
        raise typer.BadParameter("indiquer exactement un des deux : --file ou --query")
    text = read_sql_file(file) if file else query
    statements = td.split_statements(text, delimiter)
    if not statements:
        raise typer.BadParameter("aucune instruction SQL", param_hint="--file")
    label = file or "requête"

    started = time.monotonic()
    conn = td_connect()
    details: list[dict] = []
    failed = False
    try:
        log(f"td-sql {label} : connexion OK, {len(statements)} instruction(s), "
            f"mode {'SIMULATION' if dry_run else 'EXÉCUTION'}")
        cur = conn.cursor()
        for i, stmt in enumerate(statements, 1):
            kind = td.first_keyword(stmt)
            log(f"[{i}/{len(statements)}] {kind} : {td.one_line(stmt)}")
            if dry_run and not td.is_read_only(stmt):
                log("  SIMULATION : non exécutée (utiliser --apply)")
                details.append({"n": i, "type": kind, "simulee": True})
                continue
            t0 = time.monotonic()
            try:
                info = td_run_statement(cur, stmt, limit)
            except Exception as exc:
                failed = True
                typer.echo(f"ERREUR instruction {i} : {short_error(exc)}", err=True)
                details.append({"n": i, "type": kind, "erreur": short_error(exc)})
                break  # les instructions suivantes peuvent dépendre de celle-ci
            elapsed = round(time.monotonic() - t0, 1)
            log(f"  terminée en {elapsed} s")
            details.append({"n": i, "type": kind, "duree_s": elapsed, **info})
    finally:
        conn.close()
    emit("td-sql", label, "KO" if failed else "OK",
         {"simulation": dry_run, "instructions": len(statements), "details": details}, started)
    raise typer.Exit(1 if failed else 0)


@app.command("td-load")
def td_load(
    source: Annotated[str, typer.Option("--source", envvar="ICEMAINT_TD_SOURCE", show_envvar=True,
        help="Table Teradata à lire : base.table")] = "",
    target: Annotated[str, typer.Option("--target", envvar="ICEMAINT_TD_TARGET", show_envvar=True,
        help="Table Iceberg à alimenter, vue par Teradata : serveur.namespace.table")] = "",
    where: Annotated[Optional[str], typer.Option(envvar="ICEMAINT_TD_WHERE", show_envvar=True,
        help="Filtre SQL Teradata sur la source, ex. \"ecb_gen = 1961\".")] = None,
    dry_run: DryRunOpt = True,
) -> None:
    """Copie une table Teradata vers une table Iceberg (INSERT INTO ... SELECT, colonnes par nom).

    La simulation contrôle la connexion, l'existence de la cible et le nombre de lignes, sans rien écrire.
    La table cible doit exister (CREATE TABLE côté Teradata, voir le README).
    """
    try:
        source = td.check_ident(source, "source")
        target = td.check_ident(target, "cible")
        if source.count(".") != 1:
            raise ValueError(f"source « {source} » : format attendu base.table")
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
    where_sql = f" WHERE {where}" if where else ""

    started = time.monotonic()
    conn = td_connect()
    label = f"{source} -> {target}"
    try:
        cur = conn.cursor()
        # Pas de « SELECT * » : sur une table très large, la description du résultat dépasse la limite
        # de 1 Mo par ligne de réponse (erreur 9991). Les colonnes viennent du dictionnaire DBC.
        try:
            t0 = time.monotonic()
            cur.execute("SELECT ColumnName FROM DBC.ColumnsV WHERE DatabaseName = ? AND TableName = ? ORDER BY ColumnId",
                        [source.split(".")[0], source.split(".")[1]])
            src_cols = [row[0].strip() for row in cur.fetchmany(5000)]
            if not src_cols:
                raise RuntimeError(f"source {source} introuvable dans DBC.ColumnsV (nom ou droits)")
            log(f"  source : {len(src_cols)} colonnes lues dans DBC ({round(time.monotonic() - t0, 1)} s)")
            t0 = time.monotonic()
            cur.execute(f"SELECT {src_cols[0]} FROM {target} WHERE 1=0")   # la cible existe-t-elle ?
            log(f"  cible : accessible ({round(time.monotonic() - t0, 1)} s)")
            t0 = time.monotonic()
            cur.execute(f"SELECT COUNT(*) FROM {source}{where_sql}")
            expected = cur.fetchone()[0]
            log(f"  source : {expected} ligne(s) à copier ({round(time.monotonic() - t0, 1)} s)")
        except Exception as exc:
            typer.echo(f"ERREUR contrôles préalables : {short_error(exc)}", err=True)
            emit("td-load", label, "KO", {"erreur": short_error(exc)}, started)
            raise typer.Exit(1)

        columns = ",\n  ".join(src_cols)
        stmt = f"INSERT INTO {target} (\n  {columns}\n)\nSELECT\n  {columns}\nFROM {source}{where_sql}"
        log(f"td-load {label} : {len(src_cols)} colonnes, {expected} ligne(s) à copier "
            "(colonnes de la cible non comparées une à une : l'INSERT échoue si l'une manque)")
        if dry_run:
            log("  SIMULATION : rien n'est écrit (utiliser --apply)")
            emit("td-load", label, "OK", {"simulation": True, "colonnes": len(src_cols), "lignes_source": expected}, started)
            raise typer.Exit(0)

        t0 = time.monotonic()
        try:
            cur.execute(stmt)
        except Exception as exc:
            typer.echo(f"ERREUR insertion : {short_error(exc)}", err=True)
            emit("td-load", label, "KO", {"erreur": short_error(exc)}, started)
            raise typer.Exit(1)
        written = cur.rowcount
        log(f"  terminée en {round(time.monotonic() - t0, 1)} s ; lignes annoncées par Teradata : {written}")
        # Le driver annonce parfois -1 : dans ce cas aucun contrôle automatique, à vérifier avec un COUNT(*).
        mismatch = isinstance(written, int) and written >= 0 and written != expected
        data = {"simulation": False, "colonnes": len(src_cols), "lignes_source": expected, "lignes_ecrites": written}
        if mismatch:
            typer.echo(f"ERREUR écart : {expected} lignes à la source, {written} écrites", err=True)
        emit("td-load", label, "ECART" if mismatch else "OK", data, started)
        raise typer.Exit(1 if mismatch else 0)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(app())
