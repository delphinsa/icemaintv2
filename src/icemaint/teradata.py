"""Client Teradata (driver Python « teradatasql », sans JVM).

Configuration par variables d'environnement (conf/secrets.env) :
    TERADATA_HOST, TERADATA_USER, TERADATA_PASSWORD   obligatoires
    TERADATA_LOGMECH, TERADATA_DBS_PORT               facultatives (mécanisme d'authentification, port)

Le travail est fait par Teradata : ce module n'envoie que du SQL. Les données
d'un « INSERT INTO <table iceberg> SELECT ... » ne transitent pas par le conteneur.
"""

import os
import re

REQUIRED = ["TERADATA_HOST", "TERADATA_USER", "TERADATA_PASSWORD"]

# Instructions qui ne modifient rien : exécutées même en simulation.
READ_ONLY = {"SELECT", "SEL", "SHOW", "HELP", "EXPLAIN", "WITH"}

IDENT = re.compile(r"^[A-Za-z0-9_$#]+$")


class TdConfigError(Exception):
    """Configuration Teradata absente ou invalide (code retour 2)."""


def check_config() -> None:
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        raise TdConfigError("variables d'environnement manquantes : " + ", ".join(missing))
    todo = [name for name in REQUIRED if "<" in os.environ[name]]
    if todo:
        raise TdConfigError("valeurs à compléter dans conf/secrets.env : " + ", ".join(todo))


def connect():
    """Ouvre une session Teradata (import tardif : « icemaint --help » reste instantané)."""
    check_config()
    import teradatasql

    env = os.environ
    params = {"host": env["TERADATA_HOST"], "user": env["TERADATA_USER"], "password": env["TERADATA_PASSWORD"]}
    if env.get("TERADATA_LOGMECH"):
        params["logmech"] = env["TERADATA_LOGMECH"]
    if env.get("TERADATA_DBS_PORT"):
        params["dbs_port"] = env["TERADATA_DBS_PORT"]
    return teradatasql.connect(**params)


def split_statements(text: str, delimiter: str = "-----") -> list[str]:
    """Découpe un script : les instructions sont séparées par une ligne contenant uniquement le délimiteur.

    Sans délimiteur, le fichier entier est une seule instruction (cas d'un INSERT ... SELECT unique).
    """
    parts: list[list[str]] = [[]]
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip() == delimiter:
            parts.append([])
        else:
            parts[-1].append(line)
    return [stmt for stmt in ("\n".join(p).strip() for p in parts) if stmt]


def first_keyword(stmt: str) -> str:
    """Premier mot SQL, commentaires ignorés."""
    text = re.sub(r"/\*.*?\*/", " ", stmt, flags=re.S)
    text = re.sub(r"--[^\n]*", " ", text)
    match = re.search(r"[A-Za-z]+", text)
    return match.group(0).upper() if match else ""


def is_read_only(stmt: str) -> bool:
    return first_keyword(stmt) in READ_ONLY


def mask_secrets(sql: str) -> str:
    """Masque les mots de passe éventuels avant d'écrire une instruction dans un journal."""
    return re.sub(r"(password\s*=\s*)(['\"])[^'\"]*\2", r"\1'********'", sql, flags=re.I)


def one_line(stmt: str, width: int = 300) -> str:
    text = " ".join(mask_secrets(stmt).split())
    return text if len(text) <= width else text[:width] + " …"


def check_ident(value: str, what: str) -> str:
    """Nom qualifié (base.table ou serveur.base.table), sans guillemets : refuse tout autre caractère."""
    parts = value.split(".")
    if not 2 <= len(parts) <= 4 or not all(IDENT.match(p) for p in parts):
        raise ValueError(f"{what} « {value} » : format attendu base.table (lettres, chiffres, _ $ #)")
    return value
