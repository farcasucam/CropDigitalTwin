# MQTT Component

## Responsabilidad

Abstraer Paho MQTT.

## Cliente

Crear `MQTTClient` con:
- connect;
- disconnect;
- publish;
- subscribe;
- callbacks;
- reconnect;
- QoS configurable;
- retained configurable.

## Requisitos

- no dispersar strings de topics;
- JSON UTF-8;
- mensajes versionados;
- correlation_id;
- simulation_id;
- plot_id;
- timestamp real;
- simulation_time;
- type;
- data.

## QoS

MVP:
- telemetría: QoS 0 o 1;
- comandos: QoS 1;
- eventos críticos/fallos: QoS 1;
- configuración/estado retenido: QoS 1 si procede.

## Desacoplamiento

Ningún módulo de dominio debe importar Paho.
