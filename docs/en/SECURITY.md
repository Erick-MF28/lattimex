# Local server security

*[Versión en español](../SECURITY.md)*

The local server has access to operational data (addresses, phone numbers, costs). These are its
defenses, all covered by `tests/test_local_api.py`:

| Threat | Defense |
|---|---|
| Another computer on the network tries to connect | It listens on `127.0.0.1` only. |
| An arbitrary website tries to read or write data | Only requests whose `Origin` is on the allow list are accepted (by default `https://lattimex.com`). The CORS preflight from other origins receives 403. |
| DNS rebinding | The `Host` header must be `127.0.0.1:<port>` or `localhost:<port>`. |
| Request without preflight (CSRF) | Every data route requires the `X-LATTIMEX-Runtime-Token` header, which forces a preflight and changes on every start. |
| Tampered map (the graph is loaded with `pickle`) | Before loading it, its SHA-256 is compared with the one recorded when it was built (`data/maps/<name>.json`). Build maps yourself; do not load third-party `.gpickle` files. |
| Background map privacy | The browser requests from `tile.openstreetmap.org` only the tiles of the visible area (with `Referer` reduced to the origin). Shipments, routes, costs and addresses are never sent. The Planner's CSP only allows images from that domain. |
| Fuel price lookup | Automatic mode only: the server downloads two public CRE files (`publicacionexterna.azurewebsites.net`) at most every 12 hours. It sends no operational data; documents with a DTD and files larger than 40 MB are rejected. In manual mode there is no connection at all. |
| Huge requests | Maximum body of 5 MB, 1000 points and 300 s of computation per run. |

Residual risk: any script running inside an allowed origin (lattimex.com) can talk to the server
while it is on. That is why the Planner page loads no analytics and no inline scripts, and its CSP
only allows its own scripts and Leaflet.

Vulnerability reports: contacto@lattimex.com.
