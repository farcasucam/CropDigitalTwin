# Novagric typologies: data found in the public catalogue

Source: https://novagric.com/invernaderos/ and each typology page (read 2026-10-20). Only what the pages state is
recorded. Each value is `DOCUMENTED_COMMERCIAL` (marketing page, not a drawing or datasheet). Anything absent is `NOT_PUBLISHED`
and must be a provisional, user-supplied value with its own provenance. No commercial assets were downloaded.
The pages say more options and combinations exist, so these ranges are not full catalogues. Quoted wording is Spanish.

| Typology | Page | Width (m) | Gutter height (m) | Ridge / apex | Pillar spacing (m) | Other published facts |
|---|---|---|---|---|---|---|
| Multitunel Capilla | `/invernadero-capilla/` | 8 or 9.60 | 4 / 4.50 / 5 / 5.50 | +1.80 to 2.20 above gutter | 5 (interior) / 2.50 (exterior) | Metal structure; semicircular curved arches |
| Multitunel Gotico | `/invernadero-gotico/` | Standard 8 / 9.60; wide 12.80 / 14.40 / 16 | 4 to 6.50 | +2.50 to 3 depending on model | every 2.50 or 3; floating arches alternate, or all with pillars in polar and Lux models | Mentions heating, ventilation, cooling, CO2 enrichment can be installed |
| Multitunel Tropical-Asimetrico | `/invernadero-asimetrico-o-tropical/` | Standard 9.60 | 4 to 6.50 | NOT_PUBLISHED | every 2 to 2.50 | Fixed roof ventilation ("ventilacion cenital, siendo esta fija"); one roof side steeper than the other, no angles |
| Multitunel Grande LUX | `/invernadero-lux/` | 12.80 / 14.40 / 16 | 4 to 6.50 | +2.50 to 3 (page wording unclear) | every 3, all pillars or alternating floating arches | Structure parts listed, material not stated |
| Raspa y Amagado | `/invernadero-raspa-y-amagado/` | 8 / 9.60 / 10 | NOT_PUBLISHED | NOT_PUBLISHED | 5 / 9.60 / 10 (interior); 5 (exterior) | Pillar height 7 m; galvanized tube pillars; allows roof ("cenitales") windows; raspa = upper part, amagado = lower part |
| Invernadero Tunel | `/invernadero-tipo-tunel/` | 8 / 9.60 | Height 4 / 5 | arch (curved or ogival) | arch spacing 2.50 (exterior) | Galvanized cylindrical tube arches; roof and side windows possible; no concrete footings |

Catalogue also lists (out of scope): sheet-metal greenhouses, CasaSombra, Kit, Photovoltaic, Feedlot.

## Not published for any typology (must stay provisional)

Length, number of modules, orientation, cover material and thickness, thermal/optical properties (U-value, SHGC,
transmittance), vent window dimensions and area, screens/shading systems, infiltration/airtightness, and equipment capacities.
The pages say only that heating, ventilation, cooling and CO2 enrichment can be installed.

## Rules for the parametric model

- Geometry fields above may fill `GeometryParameters` with `evidence_status = DOCUMENTED_COMMERCIAL`.
- Unclear readings stay flagged: LUX ridge ("cenil", "+" sign) and the unit of "16" are ambiguous on the page.
- Physical properties are never inferred from the typology name; they come from configurable, provenance-tagged values.
- Rendered geometry is `PARAMETRIC_SCHEMATIC`, not a Novagric drawing.
