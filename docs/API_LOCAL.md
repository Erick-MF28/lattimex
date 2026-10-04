# API del servidor local

*[English version](en/API_LOCAL.md)*

Todas las rutas `/api/*` exigen `Origin` permitido y la cabecera `X-LATTIMEX-Runtime-Token`
(que se obtiene de `GET /api/runtime`). Ver [SECURITY.md](SECURITY.md).

| Método y ruta | Uso |
|---|---|
| `GET /health` | Estado del servidor (sin datos). |
| `GET /api/runtime` | Token de sesión, versión del motor y mapa cargado. |
| `GET /api/map/roads` | Capa de calles `lattimex.roads.v1`. |
| `GET/POST/PUT/DELETE /api/catalog/vehicles[/id]` | Flota: medidas interiores, carga máxima, puertas, rendimiento y costos. |
| `GET/POST/PUT/DELETE /api/catalog/operators[/id]` | Operarios: teléfono y costo por jornada u hora. |
| `GET/POST/PUT/DELETE /api/instances[/id]` | Conjuntos de guías con su centro de distribución (borrar una instancia elimina también sus corridas y archivos). |
| `POST /api/network/snap` | Ubica puntos sobre la red vial. |
| `POST /api/network/paths` | Geometría de las rutas sobre las calles. |
| `POST /api/engine/v1/solve` | Crea un trabajo de optimización (respuesta 202 con `id`). |
| `GET /api/engine/v1/jobs/<id>` | Estado por etapa (`map`, `solver`) y, al terminar, el resultado. |
| `GET/PUT /api/planning-state` | Instancia y corrida activas en Planificación; con ellas el Planner restaura la última operación al volver. |
| `GET/PUT/DELETE /api/capture-draft` | Borrador de la captura de guías que aún no se guarda como instancia; el Planner lo guarda solo y lo recupera al volver. |
| `GET/PUT /api/settings/fuel` | Precio del combustible: modo (`auto` o `manual`), tipo (`regular`, `premium`, `diesel`), precio manual y precio en uso. |
| `POST /api/settings/fuel/refresh` | En modo automático, consulta los precios vigentes de la CRE y guarda la mediana de las estaciones cercanas al centro de distribución. |
| `GET/POST /api/planning-runs[/id]` | Corridas guardadas. |
| `DELETE /api/planning-runs[/id]` | Borra una corrida (o todas) y su archivo de resultados. |
| `DELETE /api/instances/<id>/guides/<guía>` | Quita una guía de una instancia. |

## Identificadores de contrato

Las respuestas llevan un campo `contract` con valores como `pen3q.lattimex.solve.v1` o
`pen3q.3l.loading.result.v1`, que identifican el tipo de mensaje y la versión del protocolo entre
el servidor local y el Planner.

## Ejemplo de solicitud de optimización

```json
{
  "points": [{"lat": 20.5888, "lng": -100.3899}, {"lat": 20.5879, "lng": -100.3819}],
  "fleet": [{"cargo_cm": [365, 139, 165], "max_weight_kg": 1900, "doors": ["rear"]}],
  "fleet_count": 1,
  "packages": [{"id": "QRO-181", "node": 1, "dims_cm": [45, 35, 25], "weight_kg": 6.2}],
  "constraints": {"support": true, "fragility": false, "lifo": false},
  "budget_sec": 10
}
```

El punto 0 es el centro de distribución. Cada destino necesita al menos un paquete. El resultado
incluye `routes[].sequence`, `routes[].placements` (x, y, z y medidas de cada caja), la ocupación y el
plan de descarga por puertas.
