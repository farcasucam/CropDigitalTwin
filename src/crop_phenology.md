# CropDigitalTwin — evidencia fenológica externa

**Fecha:** 2026-08-30. Corpus trazable, sin activación de modelo.

## Método
Búsquedas independientes por los siete cultivos sobre GDD/umbral/evento, y para frutales además CH, CP/Dynamic, Utah y GDH. Se priorizaron artículos, PMC/Frontiers, OENO One, ISHS, CSIC y extensión. Se incluyó explícitamente Paredes et al. (2025), DOI 10.1016/j.agwat.2025.109755.

## Resultado
- Fuentes: 20; parámetros: 35; por cultivo: {'tomato': 6, 'lettuce': 4, 'pepper': 3, 'grape': 6, 'peach': 4, 'plum': 6, 'apple': 6}.
- Unidades originales conservadas; no hay conversión CH↔CP ni GDD↔GDH.
- Transferibilidad se reduce, no se excluye, cuando el cultivar/zona difiere.

## Conflictos
Tomate: 7, 7.2 y 10 °C; lechuga: 4 y 4.4 °C; pimiento: 7 y 10 °C; vid: umbrales dependientes de estadio, cultivar y zona. No se resolvieron ni promediaron.

## Limitaciones
`search_exhaustion=true`: no se alcanzan cinco fuentes numéricas independientes por cada cultivo. No se inventaron números. Persisten huecos de eventos en lechuga/pimiento/tomate, valores detallados de Paredes 2025 para todos los cultivos y tablas cultivar-por-cultivar de manzano. Próxima tarea: extraer PDF/suplementos y añadir filas sólo tras verificación primaria.


## Promot usado

PROMPT — INVESTIGACIÓN WEB EXHAUSTIVA DE PARÁMETROS FENOLÓGICOS PARA CROP DIGITAL TWIN
Objetivo
Realiza una investigación bibliográfica y web exhaustiva para obtener los parámetros fenológicos numéricos externos necesarios para la Fase 4.7 del proyecto CropDigitalTwin.
El resultado principal de tu trabajo NO debe ser una explicación en texto.
Tu entregable principal debe ser un archivo estructurado:
phenology_external_evidence.json
y, adicionalmente:
phenology_external_evidence.csv
Ambos deben quedar completamente rellenados con los datos encontrados y ser aptos para incorporarlos directamente al repositorio.
1. PROYECTO
El sistema simula siete cultivos:
tomato
lettuce
pepper
grape
peach
plum
apple

El proyecto dispone actualmente de estas variedades/parcela como contexto, pero NO debes exigir que una fuente utilice exactamente la misma variedad para considerar válida la evidencia:
tomato  → RAF
pepper  → Lamuyo
grape   → Monastrell
plum    → Suplum 26

Para:
lettuce
peach
apple

no existe actualmente una variedad local suficientemente especificada.
La variedad concreta NO es un criterio de exclusión.
Una fuente para otra variedad de la misma especie puede proporcionar evidencia perfectamente válida como:
EXTERNAL_EVIDENCE
o:
PROVISIONAL
si el método y el contexto son adecuados.
La diferencia varietal debe registrarse en:
reference_cultivar
y:
transferability
pero NO debe eliminar el dato.
2. OBJETIVO AGRONÓMICO
Necesitamos obtener datos para construir un modelo de desarrollo fenológico basado en:
Hortícolas
tomato
lettuce
pepper
Principalmente:
GDD / thermal time
Vid
grape
Principalmente:
forcing / GDD
y, cuando exista evidencia:
budburst → flowering → fruit set → veraison → harvest
Frutales
peach
plum
apple
Investigar modelos:
chilling → forcing
incluyendo:
Chill Hours;
Chill Portions;
Utah model;
Dynamic Model;
GDH;
GDD;
otros modelos publicados.
NO reduzcas automáticamente un modelo de chilling + forcing a un único GDD.
3. FUENTES PRIORITARIAS
Realiza búsqueda web real.
Prioridad:
Nivel 1 — literatura científica primaria
artículos peer-reviewed;
revisiones sistemáticas;
estudios experimentales;
estudios de campo;
tesis universitarias si contienen datos experimentales;
datasets científicos.
Nivel 2 — organismos científicos
FAO;
universidades;
servicios de extensión universitaria;
USDA;
UC Agriculture;
Cornell;
Penn State;
University of Minnesota;
Oregon State;
Washington State;
INRAE;
CSIC;
CITA;
IRTA;
instituciones agronómicas españolas;
instituciones europeas.
Nivel 3
Bases bibliográficas:
Google Scholar;
Crossref;
PubMed;
Semantic Scholar;
AGRIS;
repositories institucionales.
Nivel 4
Fuentes secundarias únicamente si permiten rastrear claramente el artículo original.
4. FUENTE ESPECIALMENTE IMPORTANTE
Investiga y utiliza explícitamente esta publicación:
Paredes et al. (2025)
"Base and upper temperature thresholds to support the calculation of growing degree days aiming at their use with the FAO56rev crop coefficients curve"
DOI:
10.1016/j.agwat.2025.109755
La revisión recopila valores de Tbase y Tupper para 117 cultivos y advierte que pueden variar según cultivo, etapa, cultivar/variedad y método.
Extrae de ella todos los datos relevantes para:
lettuce;
tomato;
pepper;
grape;
peach;
plum;
apple.
No basta con citar la revisión.
Cuando la revisión proporcione una referencia primaria, intenta localizar también el estudio original.
5. INVESTIGACIÓN POR CULTIVO
Debes investigar CADA UNO de los siete cultivos por separado.
No aceptes una búsqueda genérica como suficiente.
TOMATO
Buscar:
tomato phenology GDD
tomato growing degree days flowering
tomato growing degree days fruit set
tomato growing degree days maturity
tomato base temperature
tomato upper temperature
tomato thermal time emergence
tomato thermal time transplant flowering
tomato thermal time harvest

Registrar cuando exista:
Tbase;
Tupper;
GDD/GDH;
método;
biofix;
evento;
duración térmica entre eventos.
Intentar obtener específicamente:
emergence
flowering
fruit set
maturity
harvest

6. LETTUCE
Buscar:
lettuce phenology GDD
lettuce growing degree days
lettuce base temperature
lettuce thermal time
lettuce emergence GDD
lettuce harvest GDD
lettuce maturity GDD

Investigar especialmente las diferencias entre:
3.5 °C;
4 °C;
4.5 °C;
si aparecen en la bibliografía.
NO elegir arbitrariamente.
Conservar cada valor con su fuente.
7. PEPPER
Buscar:
pepper Capsicum annuum GDD
pepper phenology thermal time
pepper growing degree days flowering
pepper fruit set GDD
pepper maturity GDD
pepper base temperature
pepper upper temperature
bell pepper GDD
chili pepper GDD

Registrar por separado si la fuente distingue:
bell pepper;
chili pepper;
sweet pepper.
No considerar que sean automáticamente equivalentes.
8. GRAPE / GRAPEVINE
Investigar:
grapevine phenology GDD
grapevine thermal time
grapevine base temperature
grapevine budburst GDD
grapevine flowering GDD
grapevine fruit set GDD
grapevine veraison GDD
grapevine harvest GDD
Monastrell phenology
Mourvedre phenology GDD

Buscar especialmente evidencia para:
Vitis vinifera;
Mediterranean climates;
Spain;
France;
Italy;
California;
Australia.
Registrar:
budburst
flowering
fruit set
veraison
maturity
harvest

Si existe evidencia específica de Monastrell/Mourvèdre, marcarla como mayor transferibilidad.
Si no, utilizar evidencia de Vitis vinifera.
9. PEACH
Investigar por separado:
Chilling
peach chilling hours
peach chill portions
peach chilling requirement
peach dynamic model
peach Utah model
peach chilling requirement cultivar

Forcing
peach GDH
peach growing degree hours
peach GDD flowering
peach thermal time budburst
peach flowering thermal time
peach maturity GDD

Registrar:
Chill Hours;
Chill Portions;
método;
GDH;
GDD;
Tbase;
evento.
NO mezclar Chill Hours con Chill Portions.
NO convertirlos.
10. PLUM
Investigar específicamente:
Japanese plum chilling requirement
plum chilling hours
plum chill portions
plum GDH
plum GDD flowering
plum phenology
Japanese plum phenology
Prunus salicina chilling
Prunus salicina forcing

Buscar especialmente literatura española/europea.
La variedad local Suplum 26 NO debe ser una barrera.
Si existen datos para otras variedades de Prunus salicina, conservarlos.
Registrar:
cultivar de referencia;
región;
chilling;
forcing;
evento.
11. APPLE
Investigar:
apple chilling requirement
apple chill portions
apple chilling hours
apple dynamic model
apple Utah model
apple forcing GDH
apple GDD flowering
apple budburst GDD
apple phenology thermal time
apple flowering chilling forcing

Buscar específicamente:
Malus domestica;
estudios de España;
estudios mediterráneos;
estudios europeos;
estudios de Elstar;
Golden Delicious;
Gala;
Fuji;
otras variedades.
No rechazar una fuente por utilizar otra variedad.
Registrar claramente la variedad de referencia.
12. EVENTOS FENOLÓGICOS
Para cada cultivo intenta obtener datos para:
emergence
transplant
budburst
flowering
fruit_set
veraison
maturity
harvest

No todos aplican a todos los cultivos.
Si una fuente no permite determinar el evento:
event = UNKNOWN

NO inventarlo.
13. UNIDADES
Conserva SIEMPRE la unidad original.
Valores posibles:
degC
GDD
GDH
chill_hours
chill_portions
days

Si una publicación proporciona:
GDD
no lo conviertas a:
GDH.
Si proporciona:
Chill Portions
no lo conviertas a:
Chill Hours.
Si haces una conversión, debe aparecer:
conversion_applied = true
conversion_method = ...

pero preferiblemente conserva el valor original.
14. MÉTODO GDD
Registrar explícitamente cuando sea posible:
average
modified_average
single_sine
double_sine
triangle
other
unknown

Registrar además:
base_temperature_c
upper_temperature_c

si la fuente los proporciona.
15. BIOFIX
Buscar el punto inicial utilizado para acumular tiempo térmico.
Ejemplos:
sowing
emergence
transplant
budburst
January 1
fixed calendar date
flowering
other

No inventar biofix.
Si no se conoce:
biofix = null

16. RANGOS
Si una fuente proporciona:
277–851 chill hours

NO convertirlo en:
564 chill hours

Conservar:
"minimum": 277,
"maximum": 851

Si proporciona un valor único:
"value": 500

Si proporciona varios cultivares:
crear una entrada por cultivar cuando sea posible.
17. CONFLICTOS ENTRE FUENTES
Si encuentras:
Fuente A:
Tbase = 10

Fuente B:
Tbase = 7

NO elijas una arbitrariamente.
Crear entradas independientes:
source A
source B

y además:
conflict_group

Ejemplo:
tomato_tbase_001
tomato_tbase_002

La selección posterior corresponde al proyecto.
18. CALIDAD DE EVIDENCIA
Cada entrada debe tener:
evidence_level

con:
PRIMARY_EXPERIMENT
PEER_REVIEWED_REVIEW
INSTITUTIONAL
SECONDARY
TERTIARY

Y:
confidence

con:
HIGH
MEDIUM
LOW

Y:
transferability

con:
HIGH
MEDIUM
LOW

19. REGLA SOBRE CULTIVARES
MUY IMPORTANTE:
NO hagas esto:
"La fuente utiliza otra variedad, por tanto el valor no sirve."
Eso es incorrecto para esta fase.
Haz esto:
reference_cultivar = cultivar de la publicación
transferability = MEDIUM

si la evidencia es de la misma especie y el contexto agronómico es razonablemente comparable.
Si la fuente es de otra especie:
transferability = LOW

y normalmente no debe utilizarse como parámetro candidato.
20. FORMATO JSON OBLIGATORIO
Genera:
phenology_external_evidence.json
Con esta estructura:
{
  "schema_version": "1.0",
  "research_date": "YYYY-MM-DD",
  "project": "CropDigitalTwin",
  "sources": [],
  "parameters": []
}

Cada parámetro:
{
  "id": "unique-id",
  "crop": "tomato",
  "species": "Solanum lycopersicum",
  "stage": "flowering",
  "event": "flowering",
  "parameter": "GDD",
  "value": 500,
  "minimum": null,
  "maximum": null,
  "unit": "GDD",
  "method": "average",
  "base_temperature_c": 10,
  "upper_temperature_c": null,
  "biofix": "transplant",
  "reference_cultivar": "cultivar",
  "reference_region": "region",
  "growing_condition": "field",
  "source_id": "SRC-001",
  "evidence_level": "PRIMARY_EXPERIMENT",
  "confidence": "HIGH",
  "transferability": "MEDIUM",
  "evidence_status": "EXTERNAL_EVIDENCE",
  "activation_status": "NOT_ACTIVATED",
  "stage_mapping_status": "UNMAPPED",
  "notes": ""
}

21. FUENTES
El JSON debe contener una sección:
"sources": [
  {
    "source_id": "SRC-001",
    "authors": "...",
    "year": 2025,
    "title": "...",
    "journal": "...",
    "doi": "...",
    "url": "...",
    "source_type": "PEER_REVIEWED_REVIEW"
  }
]

Cada valor numérico DEBE poder rastrearse a una fuente.
No aceptar:
source = "internet"

No aceptar:
source = "literature"

sin referencia concreta.
22. CSV
Genera también:
phenology_external_evidence.csv
Una fila por parámetro.
Columnas:
id
crop
species
stage
event
parameter
value
minimum
maximum
unit
method
base_temperature_c
upper_temperature_c
biofix
reference_cultivar
reference_region
growing_condition
source_id
authors
year
doi
url
evidence_level
confidence
transferability
evidence_status
activation_status
stage_mapping_status
notes

El CSV debe poder abrirse directamente con Excel y pandas.
23. CANTIDAD MÍNIMA DE INVESTIGACIÓN
NO termines después de encontrar un único valor por cultivo.
Objetivo mínimo:
tomato
≥ 5 fuentes independientes cuando existan.
lettuce
≥ 4 fuentes.
pepper
≥ 4 fuentes.
grape
≥ 5 fuentes.
peach
≥ 5 fuentes.
plum
≥ 5 fuentes.
apple
≥ 5 fuentes.
Si no existen suficientes fuentes, documenta:
search_exhaustion = true

y explica qué consultas/repositorios se revisaron.
24. BÚSQUEDA DE REFERENCIAS PRIMARIAS
Cuando una revisión diga:
"Smith et al. (2018) found Tbase = 10 °C"
NO te limites a citar la revisión.
Busca:
Smith 2018 tomato Tbase

y localiza el artículo original.
Si puedes verificarlo:
evidence_level = PRIMARY_EXPERIMENT

Si solo puedes verificar la revisión:
evidence_level = PEER_REVIEWED_REVIEW

25. TRAZABILIDAD
Para cada número debes poder contestar:
¿De dónde salió?
¿Quién lo publicó?
¿En qué año?
¿Qué cultivo?
¿Qué variedad?
¿Dónde?
¿En qué condiciones?
¿Qué método?
¿Qué evento?
¿Qué unidad?
¿Qué Tbase?
¿Qué Tupper?

Si alguna respuesta no está disponible:
null

NO inventar.
26. DATOS QUE NO DEBEN ENTRAR
NO incluir valores procedentes de:
blogs sin referencias;
foros;
respuestas de IA;
páginas comerciales;
calculadoras sin metodología;
conocimiento interno del modelo;
valores inventados;
medias calculadas por ti a partir de estudios diferentes;
conversiones no justificadas.
Wikipedia puede servir para descubrir una referencia, pero no como fuente final de un parámetro.
27. BÚSQUEDA ESPECÍFICA PARA ESPAÑA / MEDITERRÁNEO
Dado que el proyecto se utilizará en España, realizar búsquedas específicas:
tomato phenology Spain GDD
pepper phenology Spain GDD
grapevine phenology Spain GDD
Monastrell phenology Spain
peach chilling Spain
plum chilling Spain
apple chilling Spain
Prunus salicina Spain chilling
Vitis vinifera Spain thermal time

Buscar también:
site:csic.es
site:irta.cat
site:upv.es
site:uco.es
site:um.es
site:upct.es
site:uclm.es
site:mapa.gob.es

28. RESULTADO FINAL OBLIGATORIO
No respondas únicamente con un informe.
DEBES CREAR FÍSICAMENTE:
phenology_external_evidence.json
phenology_external_evidence.csv

Si el entorno permite generar archivos, entrégalos como archivos descargables.
Además crea:
phenology_research_report.md

Este informe debe explicar:
metodología de búsqueda;
bases consultadas;
consultas utilizadas;
fuentes encontradas;
fuentes descartadas;
parámetros encontrados;
conflictos;
incertidumbres;
huecos de información;
recomendaciones.
29. CRITERIO DE ÉXITO
La investigación se considera completada cuando:
los siete cultivos han sido investigados individualmente;
existen múltiples fuentes por cultivo cuando sea posible;
los valores numéricos están trazados;
Tbase está documentado;
Tupper está documentado cuando exista;
GDD/GDH están separados;
chilling hours/chill portions están separados;
los rangos se conservan;
los cultivares de referencia están documentados;
las diferencias varietales no eliminan automáticamente la evidencia;
los eventos fenológicos están identificados;
los biofix están documentados cuando existan;
las fuentes primarias han sido buscadas;
los DOI/URL están incluidos;
las contradicciones se conservan;
no se inventa ningún valor;
el JSON es válido;
el CSV es válido;
ambos contienen exactamente la misma información esencial.
30. VALIDACIÓN AUTOMÁTICA
Antes de entregar los archivos ejecuta:
import json
import csv

with open("phenology_external_evidence.json", encoding="utf-8") as f:
    data = json.load(f)

assert "sources" in data
assert "parameters" in data

crops = {
    "tomato",
    "lettuce",
    "pepper",
    "grape",
    "peach",
    "plum",
    "apple"
}

assert crops.issubset({
    p["crop"] for p in data["parameters"]
})

for p in data["parameters"]:
    if p.get("value") is not None:
        assert p.get("unit")
        assert p.get("source_id")

with open(
    "phenology_external_evidence.csv",
    encoding="utf-8",
    newline=""
) as f:
    rows = list(csv.DictReader(f))

assert len(rows) == len(data["parameters"])

Si alguna validación falla, corrige los archivos antes de entregarlos.
31. IMPORTANTE: NO ACTIVAR EL MODELO
Este trabajo es exclusivamente:
investigación + estructuración de evidencia.
NO debes:
modificar crop_config.json;
modificar CropEngine;
implementar GDD;
implementar chilling;
implementar forcing;
activar transiciones;
seleccionar definitivamente un parámetro cuando existan alternativas.
El JSON generado será utilizado posteriormente por el agente de código.
32. INFORME FINAL
Al terminar, proporciona un resumen con:
TOTAL FUENTES:
TOTAL PARÁMETROS:
TOMATO:
LETTUCE:
PEPPER:
GRAPE:
PEACH:
PLUM:
APPLE:

Después:
HIGH CONFIDENCE:
MEDIUM CONFIDENCE:
LOW CONFIDENCE:

Después:
CONFLICTOS:
DATOS FALTANTES:

Y finalmente:
FILES CREATED:
- phenology_external_evidence.json
- phenology_external_evidence.csv
- phenology_research_report.md

No afirmes que un archivo fue creado si realmente no existe en el sistema de archivos.
El objetivo final es que estos archivos puedan copiarse directamente al repositorio CropDigitalTwin y servir como entrada de la Fase 4.7.