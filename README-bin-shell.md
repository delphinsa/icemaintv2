# exmeple de commande exécutable dans le conteneur

```bash
[gdpfod1@SLD16315 maintenance-iceberg]$ bin/shell.sh
icemaint@7fda5cb3abe7:~$ icemaint sql 'SELECT name, snapshot_id FROM polaris.`RGCU`.`ELCARB_10GO_ICEBERG`.refs'
Picked up JAVA_TOOL_OPTIONS: -Djavax.net.ssl.trustStore=/opt/icemaint/tls/cacerts
Picked up JAVA_TOOL_OPTIONS: -Djavax.net.ssl.trustStore=/opt/icemaint/tls/cacerts
WARNING: Using incubator modules: jdk.incubator.vector
Using Spark's default log4j profile: org/apache/spark/log4j2-defaults.properties
Setting default log level to "WARN".
To adjust logging level use sc.setLogLevel(newLevel). For SparkR, use setLogLevel(newLevel).
26/11/23 14:28:22 WARN NativeCodeLoader: Unable to load native-hadoop library for your platform... using builtin-java classes where applicable
26/11/23 14:28:30 WARN AuthManagers: Inferring rest.auth.type=oauth2 since property credential was provided. Please explicitly set rest.auth.type to avoid this warning.
+----+-------------------+
|name|snapshot_id        |
+----+-------------------+
|main|3835819359375686595|
+----+-------------------+

icemaint@7fda5cb3abe7:~$ icemaint sql 'SELECT snapshot_id, committed_at, operation FROM polaris.`RGCU`.`ELCARB_10GO_ICEBERG`.snapshots ORDER BY committed_at'
Picked up JAVA_TOOL_OPTIONS: -Djavax.net.ssl.trustStore=/opt/icemaint/tls/cacerts
Picked up JAVA_TOOL_OPTIONS: -Djavax.net.ssl.trustStore=/opt/icemaint/tls/cacerts
WARNING: Using incubator modules: jdk.incubator.vector
Using Spark's default log4j profile: org/apache/spark/log4j2-defaults.properties
Setting default log level to "WARN".
To adjust logging level use sc.setLogLevel(newLevel). For SparkR, use setLogLevel(newLevel).
26/11/23 14:29:45 WARN NativeCodeLoader: Unable to load native-hadoop library for your platform... using builtin-java classes where applicable
26/11/23 14:29:50 WARN AuthManagers: Inferring rest.auth.type=oauth2 since property credential was provided. Please explicitly set rest.auth.type to avoid this warning.
+-------------------+-----------------------+---------+
|snapshot_id        |committed_at           |operation|
+-------------------+-----------------------+---------+
|6567241267651741870|2026-11-23 10:19:16.112|append   |
|5059286369396354325|2026-11-23 12:15:15.873|replace  |
|7126741019941253555|2026-11-23 12:30:30.852|replace  |
|4859377388581514460|2026-11-23 12:53:55.035|replace  |
|5984612886080883790|2026-11-23 13:13:08.233|replace  |
|8969175925045594403|2026-11-23 13:34:19.868|replace  |
|5513078738528692155|2026-11-23 13:59:26.91 |replace  |
|4470869818191962454|2026-11-23 14:14:29.162|replace  |
|3835819359375686595|2026-11-23 14:15:37.046|replace  |
+-------------------+-----------------------+---------+

icemaint@7fda5cb3abe7:~$ ^C
icemaint@7fda5cb3abe7:~$
exit
[gdpfod1@SLD16315 maintenance-iceberg]$ bin/health.sh conf/jobs/rgcu.elcarb10go.env
[2026-11-23 15:31:11] icemaint health | table=RGCU.ELCARB_10GO_ICEBERG | image=icemaint:0.1.0 | conteneur=icemaint-health-RGCU.ELCARB_10GO_ICEBERG
Picked up JAVA_TOOL_OPTIONS: -Djavax.net.ssl.trustStore=/opt/icemaint/tls/cacerts
Picked up JAVA_TOOL_OPTIONS: -Djavax.net.ssl.trustStore=/opt/icemaint/tls/cacerts
WARNING: Using incubator modules: jdk.incubator.vector
Using Spark's default log4j profile: org/apache/spark/log4j2-defaults.properties
Setting default log level to "WARN".
To adjust logging level use sc.setLogLevel(newLevel). For SparkR, use setLogLevel(newLevel).
26/11/23 14:31:15 WARN NativeCodeLoader: Unable to load native-hadoop library for your platform... using builtin-java classes where applicable
[14:31:18] health RGCU.ELCARB_10GO_ICEBERG : début
26/11/23 14:31:19 WARN AuthManagers: Inferring rest.auth.type=oauth2 since property credential was provided. Please explicitly set rest.auth.type to avoid this warning.
[14:31:30]   fichiers de données : 809 (6.30 Go, moyenne 8.0 Mo), dont 807 sous 384 Mo
[14:31:30]   fichiers de suppression : 0
[14:31:30]   snapshots : 9 (du 2026-11-23 10:19:16.112000 au 2026-11-23 14:15:37.046000) ; manifests : 9
[14:31:30]   retenu uniquement par l'historique : 4914 fichiers, 5.44 Go
[14:31:30]   format-version=2 ; codec=zstd
RESULTAT {"operation": "health", "table": "RGCU.ELCARB_10GO_ICEBERG", "statut": "OK", "duree_s": 11.9, "fichiers": 809, "octets": 6762498171, "taille_moyenne_mo": 8.0, "petits_fichiers": 807, "lignes": 237290687, "fichiers_suppression": 0, "snapshots": 9, "snapshot_plus_ancien": "2026-11-23 10:19:16.112000", "manifests": 9, "historique_fichiers": 4914, "historique_octets": 5839586638, "proprietes": {"format-version": "2", "write.parquet.compression-codec": "zstd"}}
[2026-11-23 15:31:31] icemaint health terminé : code 0 (OK)
[gdpfod1@SLD16315 maintenance-iceberg]$^C
[gdpfod1@SLD16315 maintenance-iceberg]$
```