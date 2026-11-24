-- Exemple : lecture seule, exécuté même en simulation.
-- Plusieurs instructions dans un même fichier : les séparer par une ligne contenant uniquement -----
SELECT COUNT(*) AS nb FROM DB_DWH_VALO_RGCU_DEV.ELCARB WHERE ecb_gen = 1961;
