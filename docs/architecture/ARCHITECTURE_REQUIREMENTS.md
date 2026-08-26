# Especificación de Requisitos de Arquitectura

## 1. Objetivo

Construir un prototipo de Gemelo Digital Agrícola capaz de representar una parcela/cultivo en exterior o un cultivo protegido, acelerar el tiempo de simulación, generar clima determinista o pseudoaleatorio, modelar estado físico y agronómico, recibir perturbaciones naturales, accionar elementos artificiales, publicar todo mediante MQTT y exponer una interfaz web de visualización y control.

El sistema debe quedar preparado para evolucionar hacia un gemelo digital agrícola con sensores reales, estaciones meteorológicas, APIs meteorológicas, modelos de radiación, transferencia térmica, evapotranspiración, fotosíntesis, crecimiento, humedad del suelo, fertirrigación, PID, MPC, reinforcement learning, optimización, predicción, anomalías, dashboard y almacenamiento histórico.

## 2. Principios obligatorios

1. Python 3.11+.
2. Type hints.
3. `dataclasses` para modelos de dominio cuando sean apropiadas.
4. Funciones pequeñas y responsabilidades claras.
5. Sin estado global innecesario.
6. Logging estándar de Python.
7. Excepciones explícitas y recuperación controlada.
8. Configuración externa; no codificar parámetros físicos en clases.
9. MQTT como bus de eventos/datos entre procesos.
10. El dominio no debe depender de Paho MQTT.
11. El controlador emite comandos; no muta el estado físico.
12. Los eventos naturales modifican condiciones externas; el modelo físico calcula las consecuencias.
13. Actuadores mantienen estado solicitado y estado real.
14. El timestep físico es independiente del intervalo de publicación meteorológica.
15. Simulaciones reproducibles mediante seed y escenarios versionados.
16. Todo mensaje debe ser trazable a una simulación, parcela y timestamp.
17. El frontend nunca modifica directamente el estado del simulador.
18. El Motor de Enriquecimiento no modifica el estado del gemelo.
19. Las narrativas destinadas al LLM deben ser derivadas de datos estructurados y conservar referencias a sus evidencias.
20. El sistema debe funcionar aunque el LLM no esté disponible.

## 3. Arquitectura lógica

```text
                       ┌──────────────────────┐
                       │   Simulation Clock   │
                       └──────────┬───────────┘
                                  │
             ┌────────────────────┼────────────────────┐
             ▼                    ▼                    ▼
      Weather Engine       Scenario Engine       Manual Events
             │                    │                    │
             └────────────────────┴──────────┬─────────┘
                                             ▼
                                      ┌─────────────┐
                                      │ MQTT Broker │
                                      └──────┬──────┘
                                             │
                   ┌─────────────────────────┼────────────────────────┐
                   ▼                         ▼                        ▼
          Physical Simulator          Enrichment Engine         Data Logger
                   │                         │                        │
                   ▼                         ▼                        ▼
             Crop Engine              Semantic Packets          Storage
                   │
                   ▼
             State Publisher
                   │
                   ▼
              Controller
                   │
                   ▼
               Actuators
                   │
                   ▼
             Physical Model

      Web Browser
          │
          ▼
   Backend API / WebSocket
          │
          ├── read state/history
          ├── write simulation controls
          └── issue manual commands
```

## 4. Procesos independientes

El MVP debe permitir ejecutar por separado:

- `weather_generator`
- `simulation_engine` / `greenhouse_simulator`
- `controller`
- `manual_control`
- `enrichment_engine`
- `backend_api`
- `frontend`
- `logger`

Los procesos de simulación se comunican por MQTT. El backend web puede usar HTTP/WebSocket hacia el navegador y MQTT hacia el dominio.

## 5. Fases

### Fase 0 — Contratos y estructura

Entregables:
- estructura de paquetes;
- configuración;
- modelos tipados;
- schemas JSON;
- topics MQTT;
- docker-compose Mosquitto;
- logging;
- tests básicos.

Criterio de salida: todos los módulos importan sin ciclos y los contratos están validados.

### Fase 1 — Motor de tiempo

Implementar `SimulationClock`:
- fecha inicial;
- velocidad;
- pausa;
- reanudación;
- avance;
- cambio dinámico de velocidad;
- publicación del tiempo simulado;
- separación entre tiempo real y simulado.

Requisitos:
- speed=1: 1 s real = 1 s simulado;
- speed=3600: 1 s real = 1 h simulada;
- speed=86400: 1 s real = 1 día simulado.

### Fase 2 — Clima

Generar:
- temperatura exterior;
- humedad relativa;
- radiación solar;
- viento;
- dirección del viento;
- precipitación;
- presión.

Debe existir ciclo día/noche y variación suave. El generador debe poder recibir perturbaciones como lluvia, helada, ola de calor, viento y radiación.

### Fase 3 — Modelo físico

Implementar modelo simplificado:
- balance térmico;
- radiación interior;
- ventilación;
- humedad;
- CO2;
- suelo/VWC;
- riego;
- drenaje;
- evaporación/transpiración simplificadas.

No se busca precisión científica en MVP; se busca coherencia causal y posibilidad de reemplazo.

### Fase 4 — Cultivo

Cargar `crop_config.json`.

Debe soportar:
- `crop_key`;
- variedad;
- fase fenológica;
- umbrales térmicos;
- VPD;
- VWC;
- radiación;
- parámetros de riego.

Calcular:
- estrés hídrico;
- estrés térmico;
- estrés por VPD;
- biomasa;
- LAI;
- desarrollo.

### Fase 5 — Actuadores y control

Implementar:
- ventanas;
- toldo;
- HVAC;
- irrigación.

Cada actuador:
- recibe comando;
- valida límites;
- evoluciona hacia el estado solicitado;
- puede fallar;
- publica estado solicitado/real.

Controladores:
- manual;
- basado en reglas.

La arquitectura debe permitir sustituirlos por PID/MPC/IA.

### Fase 6 — Eventos naturales y escenarios

Eventos:
- rain;
- heatwave;
- frost;
- wind;
- solar_radiation;
- temperature_override;
- humidity_override.

Los eventos no escriben directamente una variable interna no causal. Por ejemplo, `rain=20` cambia la precipitación exterior; el modelo calcula después humedad, VWC y demás consecuencias.

### Fase 7 — Persistencia

MVP: SQLite.

Persistir:
- estados;
- clima;
- eventos;
- comandos;
- estados de actuadores;
- fallos;
- métricas;
- paquetes semánticos.

Preparar interfaz para PostgreSQL/TimescaleDB/InfluxDB.

### Fase 8 — Motor de Enriquecimiento y Serialización Semántica

Construir un proceso independiente que:
1. consuma estados y métricas;
2. calcule métricas derivadas;
3. detecte situaciones significativas;
4. agrupe señales relacionadas;
5. determine contexto;
6. genere hechos estructurados;
7. produzca narrativas controladas;
8. serialice un `SemanticContextPacket` versionado;
9. publique por MQTT;
10. opcionalmente exponga los paquetes por API.

No debe inventar datos ni actuar sobre el gemelo.

Debe funcionar sin LLM mediante plantillas deterministas.

### Fase 9 — Backend web

Backend:
- REST para configuración y comandos;
- WebSocket para estado en tiempo real;
- autenticación simple en fases posteriores;
- puente MQTT;
- validación de comandos;
- historial;
- escenarios.

### Fase 10 — Frontend

Dashboard:
- reloj real/simulado;
- temperatura;
- HR;
- VPD;
- radiación;
- VWC;
- lluvia;
- viento;
- estado del cultivo;
- estrés;
- biomasa;
- actuadores;
- eventos;
- alarmas;
- narrativas semánticas.

Controles:
- velocidad del reloj;
- pausa/reanudación;
- fecha inicial si el backend lo permite;
- lluvia;
- temperatura;
- radiación;
- helada;
- ola de calor;
- viento;
- ventanas;
- toldo;
- HVAC;
- irrigación.

Todos los controles generan comandos/eventos; nunca mutan directamente el estado.

### Fase 11 — Escenarios reproducibles

Permitir:
- crear;
- guardar;
- ejecutar;
- pausar;
- repetir;
- comparar escenarios.

Registrar métricas:
- temperatura media/máxima;
- horas fuera de rango;
- humedad media;
- VPD;
- consumo HVAC;
- agua;
- radiación;
- estrés térmico;
- estrés hídrico;
- biomasa final.

### Fase 12 — Hardening

Añadir:
- validación de schemas;
- reconnect MQTT;
- idempotencia;
- correlation IDs;
- health checks;
- métricas;
- pruebas de integración;
- pruebas de carga;
- pruebas de reproducibilidad.

## 6. Requisitos funcionales

### FR-001 Tiempo
El usuario puede cambiar speed desde UI y el sistema debe propagarlo sin reiniciar la simulación.

### FR-002 Clima
El sistema genera clima temporalmente coherente.

### FR-003 Perturbaciones
El usuario puede inyectar eventos naturales.

### FR-004 Actuación
El usuario puede ordenar actuadores artificiales.

### FR-005 Estado
El usuario ve estado actualizado en tiempo real.

### FR-006 Causalidad
Una acción modifica un actuador/condición externa y el modelo calcula las consecuencias.

### FR-007 Cultivo
El estado agronómico se actualiza según ambiente y fase.

### FR-008 Semántica
El sistema genera un contexto estructurado apto para un LLM.

### FR-009 Histórico
El sistema permite consultar series temporales.

### FR-010 Reproducibilidad
La misma semilla + configuración + escenario debe producir resultados equivalentes.

## 7. Requisitos no funcionales

- Modularidad.
- Testabilidad.
- Determinismo configurable.
- Observabilidad.
- Tolerancia a desconexiones MQTT.
- Versionado de contratos.
- Backward compatibility de mensajes durante el MVP.
- Baja latencia de UI.
- No bloquear el simulador por el frontend ni por el LLM.

## 8. Definition of Done global

El proyecto se considera MVP cuando:
1. Mosquitto arranca con Docker Compose.
2. El reloj acelera correctamente.
3. El clima publica por MQTT.
4. El simulador consume clima.
5. Lluvia, helada y ola de calor pueden inyectarse.
6. Ventanas, toldo, HVAC y riego reciben comandos.
7. El modelo físico cambia el estado de forma progresiva.
8. El cultivo calcula estrés y biomasa.
9. El controlador automático funciona.
10. El estado aparece en el frontend en tiempo real.
11. El usuario puede actuar desde frontend.
12. El Motor de Enriquecimiento genera paquetes semánticos.
13. SQLite conserva el histórico.
14. Tests unitarios e integración pasan.
15. Un escenario puede repetirse.
