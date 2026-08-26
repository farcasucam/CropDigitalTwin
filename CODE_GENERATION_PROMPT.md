# Prompt para el modelo de creación de código

Actúa como un arquitecto de software senior y desarrollador Python.

Debes implementar el Gemelo Digital Agrícola siguiendo TODOS los documentos dentro de `docs/`, como `architecture/`, `components/`, `data_contracts/`, `mqtt/` y `docker/`.

## Reglas

1. No inventes contratos incompatibles con la especificación.
2. Si necesitas una decisión no especificada, elige la solución más simple y documenta la decisión.
3. Mantén el dominio desacoplado de MQTT, HTTP, frontend, SQLite y LLM.
4. Implementa por fases.
5. Después de cada fase ejecuta tests.
6. No sustituyas causalidad por random.
7. No hagas que el controlador escriba directamente el estado.
8. No hagas que el frontend escriba directamente el estado.
9. No hagas que el LLM controle actuadores.
10. El Motor de Enriquecimiento no puede bloquear el simulador.
11. Todos los contratos deben estar versionados.
12. Usa logging y correlation IDs.
13. Añade tests unitarios para cada comportamiento físico.
14. Añade tests de integración MQTT.
15. Añade tests de reproducibilidad.
16. Implementa primero el MVP determinista.
17. Deja interfaces para sustituir modelos simplificados por modelos científicos posteriores.

## Entregables

- código Python;
- tests pytest;
- requirements/pyproject;
- configuración;
- JSON schemas;
- Docker Compose;
- Mosquitto;
- backend;
- frontend;
- escenarios;
- README;
- documentación de decisiones arquitectónicas.

## Criterio

Una funcionalidad está terminada solo cuando:
- está implementada;
- tiene test;
- tiene logging;
- tiene contrato si cruza procesos;
- está documentada;
- no rompe las fases anteriores.
