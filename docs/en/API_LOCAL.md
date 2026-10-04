# Local server API

*[Versión en español](../API_LOCAL.md)*

Every `/api/*` route requires an allowed `Origin` and the `X-LATTIMEX-Runtime-Token` header
(obtained from `GET /api/runtime`). See [SECURITY.md](SECURITY.md).

| Method and route | Use |
|---|---|
| `GET /health` | Server status (no data). |
| `GET /api/runtime` | Session token, engine version and loaded map. |
| `GET /api/map/roads` | Street layer `lattimex.roads.v1`. |
| `GET/POST/PUT/DELETE /api/catalog/vehicles[/id]` | Fleet: interior dimensions, maximum load, doors, fuel efficiency and costs. |
| `GET/POST/PUT/DELETE /api/catalog/operators[/id]` | Drivers: phone and cost per shift or hour. |
| `GET/POST/PUT/DELETE /api/instances[/id]` | Sets of shipments with their distribution center (deleting an instance also deletes its runs and files). |
| `POST /api/network/snap` | Snaps points to the road network. |
| `POST /api/network/paths` | Geometry of the routes along the streets. |
| `POST /api/engine/v1/solve` | Creates an optimization job (202 response with `id`). |
| `GET /api/engine/v1/jobs/<id>` | Status per stage (`map`, `solver`) and, when finished, the result. |
| `GET/PUT /api/planning-state` | Active instance and run in Planning; the Planner uses them to restore the last operation when you come back. |
| `GET/PUT/DELETE /api/capture-draft` | Draft of shipments captured but not yet saved as an instance; the Planner saves it automatically and recovers it when you come back. |
| `GET/PUT /api/settings/fuel` | Fuel price: mode (`auto` or `manual`), type (`regular`, `premium`, `diesel`), manual price and price in use. |
| `POST /api/settings/fuel/refresh` | In automatic mode, fetches the current CRE prices and stores the median of the stations near the distribution center. |
| `GET/POST /api/planning-runs[/id]` | Saved runs. |
| `DELETE /api/planning-runs[/id]` | Deletes a run (or all of them) and its result file. |
| `DELETE /api/instances/<id>/guides/<shipment>` | Removes a shipment from an instance. |

## Contract identifiers

Responses carry a `contract` field with values such as `pen3q.lattimex.solve.v1` or
`pen3q.3l.loading.result.v1`, which identify the message type and the protocol version between the
local server and the Planner.

## Example optimization request

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

Point 0 is the distribution center. Each destination needs at least one package. The result
includes `routes[].sequence`, `routes[].placements` (x, y, z and dimensions of each box), the
utilization and the unloading plan by door.
