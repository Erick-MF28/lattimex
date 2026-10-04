# Seguridad del servidor local

*[English version](en/SECURITY.md)*

El servidor local tiene acceso a datos de la operación (direcciones, teléfonos, costos). Estas son sus
defensas, todas cubiertas por `tests/test_local_api.py`:

| Amenaza | Defensa |
|---|---|
| Otra computadora de la red intenta conectarse | Solo escucha en `127.0.0.1`. |
| Un sitio web cualquiera intenta leer o escribir datos | Solo se aceptan peticiones con `Origin` en la lista permitida (por defecto `https://lattimex.com`). El preflight CORS de otros orígenes recibe 403. |
| Reencuadre de DNS (*DNS rebinding*) | La cabecera `Host` debe ser `127.0.0.1:<puerto>` o `localhost:<puerto>`. |
| Petición sin preflight (CSRF) | Toda ruta de datos exige la cabecera `X-LATTIMEX-Runtime-Token`, que fuerza el preflight y cambia en cada arranque. |
| Mapa manipulado (el grafo se carga con `pickle`) | Antes de cargarlo se compara su SHA-256 con el registrado al construirlo (`data/maps/<nombre>.json`). Construya los mapas usted mismo; no cargue `.gpickle` de terceros. |
| Privacidad del mapa de fondo | El navegador pide a `tile.openstreetmap.org` solo las teselas del área visible (con `Referer` reducido al origen). Guías, rutas, costos y direcciones nunca se envían. La CSP del Planner solo permite imágenes de ese dominio. |
| Consulta del precio del combustible | Solo en modo automático: el servidor descarga dos archivos públicos de la CRE (`publicacionexterna.azurewebsites.net`) como máximo cada 12 horas. No envía ningún dato de la operación; se rechazan documentos con DTD y archivos de más de 40 MB. En modo manual no hay ninguna conexión. |
| Solicitudes enormes | Cuerpo máximo de 5 MB, 1000 puntos y 300 s de cómputo por corrida. |

Riesgo residual: cualquier script que se ejecute dentro de un origen permitido (lattimex.com) puede
hablar con el servidor mientras está encendido. Por eso la página del Planner no carga analítica ni
scripts en línea, y su CSP solo permite scripts propios y Leaflet.

Reporte de vulnerabilidades: contacto@lattimex.com.
