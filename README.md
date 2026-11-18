<p><img src="docs/img/lattimex-marca.svg" width="245" alt="LATTIMEX · Rutas que caben."></p>

# Rutas y carga en un solo plan

Planifique qué vehículo atiende cada entrega, en qué orden visita las paradas y cómo acomodar las cajas para descargarlas. El motor se ejecuta en su computadora. El [Planner](https://lattimex.com/planner) muestra el resultado en el navegador.

**[Ver el ejemplo de Querétaro](#del-pedido-al-despacho) · [Instalar el motor](#instalar-el-motor) · [Consultar una implementación](#implementacion)**

![A la izquierda, paradas agrupadas por ruta en Querétaro. A la derecha, el acomodo de las cajas de la vagoneta Demo 1, de la cabina a la puerta.](docs/img/planner-rutas-y-carga.webp)

*Ejemplo incluido en el Planner con 300 entregas sintéticas, seis vagonetas y cinco operarios. Mapa © [colaboradores de OpenStreetMap](https://www.openstreetmap.org/copyright).*

Español · [English](README.en.md) · [![Última versión publicada](https://img.shields.io/github/v/release/Erick-MF28/lattimex?label=%C3%BAltima%20versi%C3%B3n%20publicada&color=2747d9)](https://github.com/Erick-MF28/lattimex/releases/latest)

## Del pedido al despacho

1. **Cargue las guías y la flota.** Indique dónde entregar, las medidas y el peso de los bultos y la capacidad de cada unidad.
2. **Revise las rutas y el acomodo.** Seleccione una unidad en el mapa para ver sus paradas, kilómetros y costo. En la vista 3D puede revisar qué cajas quedan junto a la puerta y qué descargas requieren apartar otras cajas.
3. **Entregue la hoja de ruta.** El operario recibe las paradas en orden, los bultos de cada entrega y las indicaciones de descarga.

![Hoja de ruta del ejemplo con la secuencia de paradas y las instrucciones de descarga.](docs/img/planner-hoja-ruta.webp)

<details>
<summary>Ver las pantallas del ejemplo</summary>

[Mapa de rutas](docs/img/planner-rutas.webp) · [Detalle de una ruta](docs/img/planner-ruta-detalle.webp) · [Acomodo 3D](docs/img/planner-acomodo-3d.webp) · [Indicadores](docs/img/planner-indicadores.webp) · [Flota](docs/img/planner-flota.webp) · [Guías](docs/img/planner-guias.webp)

</details>

## Qué aporta SENDA5

La **versión 1.3.0 en preparación** integra SENDA5 en el motor 1.9.0. El reloj corregido cuenta el pulido inicial dentro del tiempo asignado a cada corrida.

En la prueba de ruteo CVRP con un presupuesto calibrado de cuatro segundos, **SENDA5 resolvió las 100 instancias**. Su brecha media respecto de las mejores soluciones conocidas fue **0,549 %**. Hubo una corrida por instancia, con flota libre y un hilo. En las 98 instancias que resolvieron las siete herramientas, la brecha de SENDA5 fue **0,534 %**. Frente a AILS-II, la diferencia no fue estadísticamente significativa. [Resultados, tiempos medidos y límites](docs/SENDA5.md) · [Cambios de la versión](CHANGELOG.md)

## Instalar el motor

Para probar esta rama desde el código fuente necesita Python 3.10 o superior y un compilador C++. En Windows, use una ruta corta como `C:\lattimex`. Si no tiene compilador, instale uno con `python -m pip install ziglang`.

```bash
git clone --branch release-1.3.0 https://github.com/Erick-MF28/lattimex.git
cd lattimex
python -m pip install -r requirements.txt
python -m lattimex build
python -m lattimex map --bbox 20.47,-100.52,20.82,-100.22 --name queretaro
python -m lattimex serve
```

Deje el servidor en ejecución y abra el [Planner](https://lattimex.com/planner). Permita la conexión con el dispositivo si el navegador la solicita. En **Guías**, pulse **Cargar ejemplo**. En **Planificación**, pulse **Optimizar**. Al terminar, seleccione una vagoneta para revisar sus paradas y el acomodo de la carga.

<details>
<summary>Ventana de inicio, carpeta de datos y diagnóstico</summary>

Después de compilar puede usar `python -m lattimex app` para iniciar el servidor y abrir el Planner desde una ventana. Consulte el [empaquetado para Windows](packaging/windows/README.md). Para elegir otra carpeta de operación, arranque el servidor con `python -m lattimex serve --data D:\operaciones\cliente_a`. Compruebe la instalación con `python -m lattimex doctor` y la versión con `python -m lattimex --version`.

</details>

<a id="implementacion"></a>

## Implementación en su operación

| Pregunta | Cómo se aborda |
|---|---|
| ¿Dónde quedan los datos? | Las guías, la flota y los planes se guardan en el equipo del cliente. El servidor escucha en `127.0.0.1` y comprueba el origen y un token de sesión para las solicitudes de datos. [Seguridad](docs/SECURITY.md) |
| ¿Cómo se conecta con nuestro sistema? | El piloto puede empezar con un CSV exportado del ERP, WMS o TMS. Para una conexión por programa, la API local permite solicitar el cálculo y recuperar el plan. Validamos los campos con un archivo de ejemplo. [API local](docs/API_LOCAL.md) |
| ¿Se puede vincular con nuestro GPS? | Para enviar paradas a una plataforma GPS revisamos sus formatos y permisos. Si necesita seguimiento en tiempo real, evaluamos con el proveedor el desarrollo y el alcance. |
| ¿Cómo se cotiza? | El motor se distribuye bajo MIT. Para estimar la instalación, integración y capacitación, indíquenos centros de salida, unidades, entregas en un día típico y los sistemas que desea conectar. |

**Contacto de implementación:** [contacto@lattimex.com](mailto:contacto@lattimex.com) · [lattimex.com](https://lattimex.com)

## Desarrollo e investigación

```text
Planner (navegador)
  └─ Servidor local
       ├─ Mapa vial y datos de la operación
       └─ Ruteo SENDA5 → acomodo 3D con P3L → verificación
```

El motor completo conserva SENDA 1.0 en modo automático con menos de seis destinos por unidad. En CVRP independiente, el selector de SENDA5 empieza con SENDA2 por debajo de 125 nodos. [Arquitectura](docs/ARCHITECTURE.md) · [Mapas](docs/MAPS.md) · [Planner](docs/PLANNER.md)

| Para | Recurso |
|---|---|
| Probar ruteo o acomodo por separado | `python -m lattimex cvrp instancia.vrp --time 4` · `python -m lattimex pack cajas.json`. La CLI asigna al núcleo el 80 % de `--time`. [Protocolo del benchmark](docs/SENDA5.md) |
| Revisar mediciones y métodos | [Auditoría de SENDA5](docs/senda5_auditoria.json) · [Notas académicas](docs/ACADEMIC_NOTES.md) · [Guías históricas de SENDA](paper/guia_senda.pdf), [SENDA2](paper/guia_senda2.pdf) y [SENDA3](paper/guia_senda3.pdf) |
| Explorar el código | [Núcleos nativos](native/) · [Motor](lattimex/engine/) · [Servidor](lattimex/server.py) · [Pruebas](tests/) |

<details>
<summary>Ejecutar las pruebas y obtener la huella del motor</summary>

```bash
python -m unittest discover -s tests/engine
python -m unittest tests.test_senda3 tests.test_senda5 tests.test_local_api -v
python tests/native/test_pack3d_equivalencia.py
python -m lattimex probe
```

</details>

## Licencias

- **Motor, servidor local y generador de mapas:** [MIT](LICENSE). Puede usarlos, modificarlos y
  distribuirlos, también con fines comerciales, conservando los avisos de copyright y licencia.
- **LATTIMEX Planner** (lattimex.com/planner): uso gratuito; no se distribuye en este repositorio y
  no puede redistribuirse ni explotarse comercialmente por terceros. Ver
  [su licencia](https://lattimex.com/planner/licencia.html).
- **Guías educativas** (`paper/`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.es).
  Puede compartirla y adaptarla, incluso comercialmente, citando la fuente ([CITATION.cff](CITATION.cff)),
  enlazando la licencia e indicando los cambios realizados.
- **Datos de calles:** © colaboradores de OpenStreetMap, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/).
- **Marca:** "LATTIMEX" y su logotipo no están cubiertos por la licencia MIT. Ver [NOTICE](NOTICE).
- Dependencias: ver [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). Procedencia del código:
  [AUTHORSHIP.md](AUTHORSHIP.md).


## Donaciones

El motor LATTIMEX es gratuito y de código abierto. Si el motor, la guía o el Planner le son útiles, puede
apoyar su desarrollo con una donación: cada aporte financia mantenimiento, nuevas ciudades y más
material educativo.

<p align="center"><a href="https://www.paypal.com/donate/?hosted_button_id=ZAAQQDBG2C4ZE"><b>♥ Donar a LATTIMEX con PayPal</b></a></p>

Acepta donaciones únicas, mensuales o anuales, con tarjeta o con cuenta de PayPal.

¿Su empresa quiere patrocinar una función o una integración? Escriba a contacto@lattimex.com.
