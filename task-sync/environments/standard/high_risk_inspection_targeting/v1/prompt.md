You are a customs risk analyst responsible for producing the daily physical-inspection shortlist for import declarations filed on 2026-04-20. Every declaration arriving on that date must be scored for anomaly probability, and any declaration whose probability exceeds eighty-five percent must be routed to the inspection queue. The scoring methodology, all parameter weights, and every threshold you need are defined in configuration files you can read from your working directory; do not invent or assume any numeric values.

Begin by reading the anomaly scoring configuration, which specifies five weighted risk factors and how each is calculated. The five factors are shipper compliance, country-of-origin risk, evasion-pattern match, valuation anomaly, and dossier alerts. Each factor produces a score between zero and one, and the final anomaly probability is the weighted sum of these five scores. The weights, tier mappings, blending coefficients, and default values for missing data are all spelled out in the configuration file.

For the shipper compliance factor, retrieve each shipper's profile to obtain their compliance tier and violation history. The tier maps to a base score according to a lookup table in the configuration, and the violation rate — violations divided by total shipments — is scaled by a multiplier also found there. These two components are blended using the configured weights to produce the composite shipper compliance score.

Country-of-origin risk comes from a separate reference file that maps each country to a risk rating on a zero-to-one-hundred scale. Divide by one hundred to normalize it into the zero-to-one range required by the scoring formula.

For the evasion-pattern factor, consult the evasion watchlist file, which pairs HS-code chapters with countries of origin. Look up the chapter of each declaration's HS code (available through the HS-code lookup) and check whether the chapter-and-country combination appears on the watchlist. If it does, use the match score recorded there; otherwise the evasion score is zero.

The valuation anomaly factor compares each declaration's unit price — declared value divided by quantity — against the commodity-category benchmarks documented in the benchmarks reference file. Compute the absolute deviation of the unit price from the benchmark median, divided by the median itself, and cap the result at one.

Finally, the dossier alerts factor draws on shipper dossier files available in your working directory. Each dossier records a recent alert count and a count of pending investigations. Sum these two numbers and divide by the configured divisor to produce the dossier score, capping at one. If no dossier exists for a given shipper, use the configured default score for missing dossiers.

Once you have all five component scores for a declaration, multiply each by its configured weight and sum the products to obtain the anomaly probability. Any declaration whose anomaly probability strictly exceeds the configured threshold belongs on the inspection shortlist.

Save the shortlist as `inspection_shortlist.csv`. The file must contain exactly these columns in this order: `shipment_id`, `shipper_id`, `hs_code`, `country_of_origin`, `declared_value`, `anomaly_probability`. Each anomaly probability should be rounded to four decimal places. Sort the rows in descending order of anomaly probability so the most suspicious declaration appears first.

In your final response, state how many declarations were analyzed in total, how many were flagged for inspection, and identify the highest-risk shipment by its ID along with its anomaly probability. Then list every flagged shipment with its ID, shipper, HS code, country of origin, declared value, and anomaly probability.
