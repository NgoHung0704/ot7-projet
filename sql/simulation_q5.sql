-- Q5 before #10's star loader: compare only applicable shaking or wind classes.
-- Replace 'sample-designation' with a staged Sentry des.
SELECT DISTINCT h.dis_no, d.event_name, d.country, d.start_date,
       h.magnitude, h.max_wind_kmh, h.shaking_class, h.wind_class
FROM simulation.event_toll AS s
JOIN simulation.historical_intensity AS h
  ON (s.shaking_class = h.shaking_class AND s.shaking_class <> 'Not applicable')
  OR (s.wind_class = h.wind_class AND s.wind_class <> 'Not applicable')
JOIN staging.stg_disaster AS d USING (dis_no)
WHERE s.des = 'sample-designation'
ORDER BY d.start_date, h.dis_no;
