# Mosquitto

## Objetivo

Broker MQTT local para el MVP.

## Archivos

- `docker-compose.yml`
- `mosquitto/mosquitto.conf`
- `mosquitto/data/`
- `mosquitto/log/`

## Configuración MVP

- MQTT TCP en 1883;
- persistencia habilitada;
- logging;
- autenticación opcionalmente desactivada solo en desarrollo local.

## Producción

No exponer 1883 públicamente sin autenticación y TLS.

Añadir posteriormente:
- listeners TLS;
- usuarios/ACL;
- certificados;
- bridge si se conecta a broker externo.
