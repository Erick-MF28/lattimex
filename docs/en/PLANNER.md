# Connecting the LATTIMEX Planner

*[Versión en español](../PLANNER.md)*

1. Start the server: `python -m lattimex serve` (listens on `http://127.0.0.1:8765`).
2. Open **https://lattimex.com/planner** in Chrome, Edge or Firefox.
3. The first time, Chrome and Edge ask whether lattimex.com may *access other apps and services on
   this device*. Accept: that is the connection to your local server.
4. The Planner header shows `● Motor local · <map> · v1.6.0`.

If the server is off, the Planner shows the installation instructions and connects by itself as soon
as the server responds. The Planner interface is currently in Spanish.

## Where your data is stored

Everything you capture in the Planner (fleet, drivers, shipments, instances and runs) is stored in
the data folder of the local server, `data/` inside the repository:

| File | Contents |
|---|---|
| `data/lattimex.sqlite3` | Local database: fleet, drivers, instances, shipments, runs and the active operation. |
| `data/resultados/` | Full result of each run (JSON). |
| `data/maps/` | Maps built with `python -m lattimex map`. |

If you close the Planner or turn off the computer, the last operation and its routes are there when
you come back. Shipments you captured but had not saved as an instance are kept as a draft and
recovered when you open **Guías**.

To use another folder, for example one per customer or a shared network folder:

```bash
python -m lattimex serve --data D:\operations\customer_a
```

The folder is created if it does not exist; copy `maps/` into it or build the map with
`python -m lattimex map --data D:\operations\customer_a ...`. You can also set it with the
`LATTIMEX_HOME` environment variable. The server prints the folder it is using when it starts.

## Fuel price

The cost of each route uses the price per liter chosen in **Flota → Combustible** (Fleet → Fuel):

- **Automatic (CRE).** The local server downloads the public list of current prices from Mexico's
  Energy Regulatory Commission (CRE) and uses the median of the stations within 25 km of the
  distribution center of the active operation (if there are fewer than five, the national median).
  It refreshes itself every 12 hours when the Planner opens, or with *Actualizar ahora* (refresh now).
  Choose the type: regular gasoline, premium gasoline or diesel.
- **Manual.** Enter the price your company pays; no lookup is made.

Planning shows the price in use next to the Optimize button. Each run stores the price it was
computed with, so earlier results do not change if the price changes later.

## Another port

```bash
python -m lattimex serve --port 9000
```

In the Planner's connection window, open *Otro puerto* (another port) and enter
`http://127.0.0.1:9000`. The address is remembered in that browser.

## Using the Planner from another origin

The server only accepts requests from the origin `https://lattimex.com`. For local tests or for a
deployment with the Planner hosted at another address:

```bash
python -m lattimex serve --allow-origin http://127.0.0.1:8080
```

## Browsers

| Browser | Status |
|---|---|
| Chrome, Edge (desktop) | Supported. Asks for local network access permission the first time. |
| Firefox (desktop) | Supported. |
| Safari | Not supported yet: it blocks connections from an HTTPS page to `http://127.0.0.1`. |
| Mobile | Not applicable: the server runs on a desktop computer. |

## What data travels

Between the browser and your local server: everything (fleet, shipments, results), without leaving
the computer. To lattimex.com: only the download of the Planner files. The Planner page has a
security policy (CSP) that **prevents** it from connecting to any destination other than
`127.0.0.1` or `localhost`; you can check it in your browser's developer tools. Leaflet is
downloaded from cdnjs.cloudflare.com.
