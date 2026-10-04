# Conectar el LATTIMEX Planner

*[English version](en/PLANNER.md)*

1. Inicie el servidor: `python -m lattimex serve` (escucha en `http://127.0.0.1:8765`).
2. Abra **https://lattimex.com/planner** en Chrome, Edge o Firefox.
3. La primera vez, Chrome y Edge preguntan si lattimex.com puede *acceder a otras aplicaciones y
   servicios de este dispositivo*. Acepte: es la conexión con su servidor local.
4. En la cabecera del Planner aparece `● Motor local · <mapa> · v1.6.0`.

Si el servidor está apagado, el Planner muestra las instrucciones de instalación y se conecta solo en
cuanto el servidor responde.

## Dónde se guardan sus datos

Todo lo que captura en el Planner (flota, operarios, guías, instancias y ejecuciones) se guarda en la
carpeta de datos del servidor local, `data/` dentro del repositorio:

| Archivo | Contenido |
|---|---|
| `data/lattimex.sqlite3` | Base local: flota, operarios, instancias, guías, ejecuciones y la operación activa. |
| `data/resultados/` | Resultado completo de cada ejecución (JSON). |
| `data/maps/` | Mapas construidos con `python -m lattimex map`. |

Si cierra el Planner o apaga la computadora, al volver encuentra la última operación con sus rutas.
Las guías capturadas que todavía no guardó como instancia se conservan como borrador y se recuperan
al abrir **Guías**.

Para usar otra carpeta, por ejemplo una por cliente o una compartida en la red:

```bash
python -m lattimex serve --data D:\operaciones\cliente_a
```

La carpeta se crea si no existe; copie ahí `maps/` o construya el mapa con
`python -m lattimex map --data D:\operaciones\cliente_a ...`. También puede fijarla con la variable de
entorno `LATTIMEX_HOME`. El servidor muestra al arrancar qué carpeta está usando.

## Precio del combustible

El costo de cada ruta usa el precio por litro que se elige en **Flota → Combustible**:

- **Automático (CRE).** El servidor local descarga la lista pública de precios vigentes de la Comisión
  Reguladora de Energía y usa la mediana de las estaciones a 25 km del centro de distribución de la
  operación activa (si hay menos de cinco, la mediana nacional). Se actualiza sola cada 12 horas al
  abrir el Planner, o con *Actualizar ahora*. Elija el tipo: gasolina regular, premium o diésel.
- **Manual.** Escribe el precio que paga su empresa; no se hace ninguna consulta.

Planificación muestra el precio en uso junto al botón Optimizar. Cada ejecución guarda el precio con
el que se calculó, así que los resultados anteriores no cambian si el precio cambia después.

## Otro puerto

```bash
python -m lattimex serve --port 9000
```

En el Planner, en la ventana de conexión, abra *Otro puerto* y escriba `http://127.0.0.1:9000`.
La dirección se recuerda en ese navegador.

## Usar el Planner desde otro origen

El servidor solo acepta peticiones del origen `https://lattimex.com`. Para pruebas locales o para una
implementación con el Planner alojado en otra dirección:

```bash
python -m lattimex serve --allow-origin http://127.0.0.1:8080
```

## Navegadores

| Navegador | Estado |
|---|---|
| Chrome, Edge (escritorio) | Soportado. Pide permiso de acceso a la red local la primera vez. |
| Firefox (escritorio) | Soportado. |
| Safari | No soportado todavía: bloquea las conexiones de una página HTTPS a `http://127.0.0.1`. |
| Móviles | No aplica: el servidor corre en una computadora de escritorio. |

## Qué datos viajan

Entre el navegador y su servidor local: todo (flota, guías, resultados), sin salir de la computadora.
Hacia lattimex.com: solo la descarga de los archivos del Planner. La página del Planner tiene una
política de seguridad (CSP) que **impide** conectarse a cualquier otro destino que no sea
`127.0.0.1` o `localhost`; puede comprobarlo en las herramientas de desarrollador de su navegador.
Leaflet se descarga de cdnjs.cloudflare.com.
