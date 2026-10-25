-- StockSense USL view, any snapshot date. Run with: python3 -I infra/apply_zetaris.py
-- Replaces the K2 version (killtests/k2/zetaris_k2.sql step 5), which had
-- the date fixed to 2022-07-04 and read river and rain from REST tables.
-- Same columns, so the compiled USL schema is unchanged.
-- Statements end with ";" at the end of a line; no ";" inside literals.

REGISTER DATASOURCE TABLES ('river_daily', 'rain_daily') FROM stocksense_pg;

ACTIVATE USL TABLE lightning.metastore.stocksense.k2_usl.clinic_risk AS
SELECT
    COALESCE(c.clinic_id, '') AS clinic_id,
    c.name AS clinic_name,
    s.as_of AS as_of,
    s.stock_courses AS stock_courses,
    s.daily_use_rainy AS daily_use_rainy,
    s.stock_courses / s.daily_use_rainy AS days_of_stock,
    r.road_id AS road_id,
    r.surface AS road_surface,
    CAST(r.closes_above_m3s AS DOUBLE) AS closes_above_m3s,
    q.discharge_m3s AS river_discharge_m3s,
    CAST(r.closes_above_m3s AS DOUBLE) - q.discharge_m3s AS headroom_m3s,
    fc.first_closure_date AS first_closure_date,
    w.rain_7d_mm AS rain_7d_mm,
    'stock+roads SYNTHETIC, river+rain Open-Meteo' AS data_label
FROM stocksense_pg.clinics c
JOIN stocksense_pg.stock s
    ON s.clinic_id = c.clinic_id AND s.item = 'ACT'
LEFT JOIN k2_src.road_register r
    ON r.clinic_id = c.clinic_id
LEFT JOIN stocksense_pg.river_daily q
    ON q.river_point = r.river_point AND q.obs_date = s.as_of
LEFT JOIN (
    SELECT rr.road_id, MIN(rd.obs_date) AS first_closure_date
    FROM k2_src.road_register rr
    JOIN stocksense_pg.river_daily rd
        ON rd.river_point = rr.river_point AND rd.discharge_m3s >= CAST(rr.closes_above_m3s AS DOUBLE)
    WHERE rr.closes_above_m3s IS NOT NULL
    GROUP BY rr.road_id
) fc ON fc.road_id = r.road_id
LEFT JOIN (
    SELECT river_point, obs_date,
           ROUND(SUM(precipitation_mm) OVER (PARTITION BY river_point ORDER BY obs_date
                 ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS rain_7d_mm
    FROM stocksense_pg.rain_daily
) w ON w.river_point = r.river_point AND w.obs_date = s.as_of;
