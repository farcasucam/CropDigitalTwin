# Decisiones de Arquitectura

## Fase 0

- El dominio se implementa con `dataclasses` inmutables y no importa MQTT, HTTP, almacenamiento ni frontend.
- Los contratos cruzan procesos usando un envelope JSON `1.0`. Los consumidores pueden ignorar propiedades adicionales, conforme a la especificación.
- `simulation_time` se expresa como texto ISO 8601 para preservar el contrato y evitar que el dominio obtenga tiempo de pared.
- `MQTTClient` es un puerto; `InMemoryMQTTClient` permite pruebas sin broker. El adaptador Paho se incorporará solo cuando un proceso MQTT de fase posterior lo necesite.
- Los modelos representan estado y validan invariantes; no incluyen dinámica de simulación, cultivo, actuadores o control.