# Firmware

La capa de Firmware del proyecto existe para abstraer el manejo fino de los drivers TMC2209 (señales digitales, datagramas UART de comunicación y la generación de pulsos de avance paso a paso). La idea principal es otorgarle una herramienta a la PC Host que le permita controlar de forma simple e inteligente al sistema de transporte del material fílmico.

## Arquitectura

El módulo presenta tres componentes:

- Comunicación con el Driver (`tmc2209`).
- Comunicación con la PC (`rpc`).
- Código principal de orquestación e interfaces (`main`).

```mermaid
flowchart LR
    PC[PC Host] <-->|USB| RPC[rpc<br/>trama, CRC, despacho]
    RPC --> MAIN[main<br/>tabla de placa, backends,<br/>métodos RPC]
    MAIN --> TMC[tmc2209<br/>registros, líneas, pasos]
    TMC -->|punteros a función| MAIN
    MAIN -->|UART / GPIO / RMT| HW[TMC2209 físico]
```

`tmc2209` y `rpc` no conocen ESP-IDF: ambos declaran qué necesitan y `main` lo provee. Esa es la razón de que la flecha vuelva hacia arriba, y de que las dos librerías se compilen y testeen en la PC.

## Comunicación con el Driver: Librería `tmc2209`

La librería TMC2209 se decidió que tenga tres vías de control para manejar al driver, y cada una resuelve un problema distinto:

| Vía | Qué resuelve | Naturaleza |
| --- | --- | --- |
| UART | Configuración y salud del driver | Transaccional, bytes |
| Líneas de control | Habilitado o no, en qué sentido, qué falla reporta | Niveles instantáneos |
| Pulsos en STEP | Movimiento y velocidad | Temporal, asíncrona |

La librería cubre las tres, y las mantiene lo más separadas posible: la única cosa que las une es la estructura del dispositivo. Nada de lo que hay adentro sabe de un ESP32. Cada vía declara un *backend*, es decir un contrato de punteros a función que alguien de afuera debe cumplir:

- `tmc2209_port_t`: mover bytes. Sin reloj propio, el timeout baja como milisegundos y el port decide cómo esperar.
- `tmc2209_lines_t`: leer y escribir un nivel en un pin.
- `tmc2209_stepgen_t`: emitir un tren de pulsos.

Quien los implementa contra periféricos reales es [backends.c](../src/main/backends.c), con los números que declara [board.h](../src/main/board.h). Los tests unitarios implementan los mismos contratos contra arrays en memoria, y por eso corren sin hardware.

Una consecuencia de diseño que atraviesa todo lo que sigue: la librería informa condiciones y nunca decide respuestas. Qué significa `GSTAT.reset` es un hecho del driver; si eso debe frenar la bobina es política de control y vive más arriba.

### Bus UART

El driver expone 23 registros por un único cable half duplex que se maneja mediante el envío y recepción de datagramas UART.

Luego de un análisis de los mismos, se encontró que cada registro entra en una clasificación, según quién suele cambiar su valor y qué se suele hacer con él:

| Clasificación | Registros | Qué implica |
| --- | --- | --- |
| **A. Solo escritura del lado del driver, útiles para saber del lado de la librería** | `SLAVECONF`, `IHOLD_IRUN`, `TPOWERDOWN`, `TPWMTHRS`, `TCOOLTHRS`, `VACTUAL`, `SGTHRS`, `COOLCONF` | El driver no contesta una lectura hacia estos registros. El valor lo puso el firmware, así que el firmware es el único que lo sabe. Recordar la copia como variable es la única forma de que el dato exista en la librería. |
| **B. Escritura y lectura del lado del driver, pero el firmware los modifica** | `GCONF`, `CHOPCONF` | A estos registros podríamos leerlos preguntándole al driver, pero una copia local serviría para ahorrar el datagrama de consulta y de respuesta, y como el firmware mismo es el que los modifica, no nos tenemos que preocupar demasiado porque el valor local se haya invalidado con el tiempo. |
| **C. De fábrica, difícilmente modificados** | `FACTORY_CONF`, `OTP_READ`, `PWMCONF` | Nadie los escribe. Los dos primeros traen el trim y los fusibles de esa pieza en particular; `PWMCONF` el driver lo deja escribir, pero este diseño no lo toca porque con autoscale el ajuste fino aparece en `PWM_SCALE` y `PWM_AUTO`. Si nadie escribe, el valor no cambia nunca: alcanza con leerlos una vez. |
| **D. Modificación fuera del firmware** | `GSTAT`, `IFCNT`, `IOIN`, `TSTEP`, `SG_RESULT`, `MSCNT`, `DRV_STATUS`, `MSCURACT`, `PWM_SCALE`, `PWM_AUTO` | Los escribe el driver solamejnte: `GSTAT` late fallas por hardware, `IFCNT` se incrementa solo, `IOIN` refleja pines, `TSTEP` es una medición, `MSCNT` avanza con cada paso. Una copia sería falsa apenas se guarde por lo que el acceso al driver deberá ser permanente. |

Las dos primeras clasificaciones llegan a la misma implicación, guardar el valor y servir las lecturas desde ahí, así que se agrupan como si fuesen registros propios de la librería. De ahí salen las tres **clases** que maneja:

| Clase | Agrupa | Política |
| --- | --- | --- |
| `OWNED`, propios | A y B | Se escriben, se guarda la copia, se lee de la copia. Son diez, y son los que `tmc2209_bringup()` exige completos. |
| `CONSTANT`, constantes | C | Se leen una vez al principio y la copia vale para toda la sesión. Son los únicos que sobreviven a una invalidación: un brownout del driver no cambia el trim configurado de fábrica. |
| `VOLATILE`, volátiles | D | Nunca se guardan. Pedirlos cuesta siempre una transacción, y ese costo es el precio de que la respuesta sea cierta. |


Esa copia local es el *shadow*: un valor por registro (llamado slot) más un bit de validez. El bit importa tanto como el valor, porque dice si la copia todavía describe al driver. Un `GSTAT.reset` significa que el driver se reinició y perdió su configuración, y ahí todos los slots propios se invalidan de golpe.

Sobre el shadow y las clases se apoya la API pública, que se ordena en familias según qué devuelve cada llamada:

| Familia | Función | Qué hace |
| --- | --- | --- |
| Construcción | `tmc2209_init(dev, addr)` | Arma el dispositivo con su dirección. Todos los slots arrancan inválidos, y no existe backend de BUS UART aún para mandar ni recibir datagramas. |
| | `tmc2209_attach_bus(dev, bus)` | Acopla el canal UART con el que se podrá comunicar la librería. Un mismo bus lo pueden compartir hasta cuatro dispositivos, ya que hay dos bits de direccionamiento. |
| | `tmc2209_bringup(dev, config[], n, *at_bringup)` | Inicializa un driver a nivel físico: lee el contador de escritura para usar como base, se fija y devuelve las banderas de estado del driver antes de ser reseteadas, lee registros constantes y configura los registros propios. |
| Valores | `tmc2209_read(dev, reg, *out)` | Lee un registro shadow y no toca el bus nunca. Sirve propios y constantes; rechaza volátiles, porque de esos no hay copia que valga. |
| | `tmc2209_write(dev, ops[], n, *failed_at)` | El lote es la unidad de trabajo: `n` datagramas y una sola verificación al final, así diez registros cuestan once transacciones y no veinte. |
| Condiciones | `tmc2209_poll_health(dev, *conditions)` | Transacción real. Cruza `GSTAT` con `DRV_STATUS` y devuelve un conjunto de condiciones, no contenido de registro. |
| | `tmc2209_poll_load(dev, *out)` | La estimación de carga de StallGuard, junto con si se la puede creer. |
| | `tmc2209_poll_pins(dev, *out)` | `IOIN` decodificado: qué ve el driver en sus propios pines. |
| | `tmc2209_poll_version(dev, *version)` | La versión del driver. |
| | `tmc2209_poll_raw(dev, reg, *out)` | Cualquier registro legible, sin interpretar y sin tocar el shadow.|
| Veredictos | `tmc2209_verify_config(dev, *mismatched)` | Contrasta el shadow contra el driver. Solo `GCONF` y `CHOPCONF` se pueden verificar, que son los propios de lectura-escritura. |
| Runtime | `tmc2209_set_velocity(dev, v)` | Escribe `VACTUAL`, inmediato y verificado. |
| | `tmc2209_set_current(dev, *c)` | Escribe `IHOLD_IRUN`. Es runtime porque es deseable varias las corrientes ya que se relacionan directamente con el torque que el motor es capaz de hacer.|
| Passthrough | `tmc2209_bus_send(bus, tx[], tx_len, rx[], rx_len, *rx_got)` | Permite mandar y recibir bytes crudos, sin codificar ni decodificar. Saltea la construcción de framing, utilizado para poder enviar datagramas directamente en caso de que se requiera hacer un bypass de la librería.|

Por debajo, todo eso son datagramas armados en [tmc2209_frame.c](../src/components/tmc2209/tmc2209_frame.c), que es código stateless y sin I/O, puramente sobre arrays de bytes.

De esta forma, se puede apreciar la siguiente operación de escirtura y lectura:
```mermaid
sequenceDiagram
    autonumber
    participant App as main
    participant Lib as tmc2209
    participant Port as backend port
    participant Wire as cable (half duplex)
    participant Drv as TMC2209 @ addr

    App->>Lib: tmc2209_write(ops, n)
    Lib->>Lib: valida acceso y clase de cada op
    Lib->>Lib: descarta las que el shadow ya da por vigentes
    Lib->>Port: purge_rx(), descarta bytes viejos

    loop por cada op que sobrevive
        Lib->>Lib: arma 8 bytes: sync, addr, reg|W, dato, CRC
        Lib->>Port: tx(8)
        Port->>Wire: 8 bytes
        Wire->>Drv: 8 bytes
        Note over Wire,Drv: TX y RX comparten el cable,<br/>así que lo transmitido vuelve a entrar
        Wire-->>Port: los mismos 8 bytes
        Port-->>Lib: rx(8)
        Lib->>Lib: comparar contra lo enviado
        Note over Lib: eco alterado o corto = falla eléctrica,<br/>y se sabe antes de tocar el driver
        Drv->>Drv: si addr coincide y el CRC cierra,<br/>aplica el valor e incrementa IFCNT
        Note over Drv,Lib: una escritura no tiene respuesta:<br/>hasta acá nada confirma que se aplicó
    end

    Lib->>Port: tx(4), pedido de lectura de IFCNT
    Port->>Wire: 4 bytes
    Wire->>Drv: 4 bytes
    Wire-->>Port: eco de 4, verificado igual que antes
    Drv->>Wire: respuesta de 8 bytes
    Wire->>Port: 8 bytes
    Port-->>Lib: rx(8)
    Lib->>Lib: valida sync, dirección maestra, registro y CRC-8
    Lib->>Lib: IFCNT avanzó tantas veces como datagramas salieron
    Note over Lib: recién ahora los slots del lote quedan válidos
    Lib-->>App: TMC2209_OK
```

Si algo falla, todos los slots del lote quedan inválidos, incluidos los de las ops que ya habían salido: nada de un lote está confirmado hasta el `IFCNT` final. La recuperación es reenviar el lote, que es seguro porque escribir dos veces el mismo valor deja al driver igual.

Características:

- **`IFCNT` como acuse de recibo.** Una escritura no tiene respuesta, así que la única evidencia de que un datagrama llegó es que el contador de escrituras del driver haya avanzado. Es un registro volátil, pero el valor que la librería guarda no es caché y nunca se lee de ahí: es la línea base contra la cual comparar la próxima lectura real. El passthrough también lo incrementa, así que un shadow inválido implica una línea base sospechosa y se debe volver a tomar el valor inicial del contador.
- **El eco como primera validación.** El half duplex obliga a leer de vuelta lo que uno mismo transmitió, y eso se puede tirar o se puede usar. Se usa: un eco alterado o corto es evidencia de un problema eléctrico que ninguna otra lectura da, y aparece antes de que el driver haya tenido oportunidad de contestar.
- **El bus es compartido porque el datagrama lleva dirección.** El segundo byte de un datagrama es la dirección del driver al que va dirijida, que a su vez se fija por los svalores de los pines MS1/MS2 del driver, así que hasta cuatro drivers pueden usar el mismo canal UART y cada uno ignora lo que no es para él. Por eso el bus es una estructura aparte del dispositivo.
- **El backend puede ser cualquier cosa.** El contrato son cuatro punteros a función sobre bytes. Detrás puede haber un periférico UART del ESP32, un puerto serie de la PC, un socket UDP contra un simulador, un descriptor de archivo o un array en memoria en un test. La única cosa que sí necesita saber es si ese canal hace eco, porque un backend full duplex no devuelve lo transmitido, y eso lo declara el propio port.
- **`VACTUAL` se debe tratar con cuidado.** Un `VACTUAL` distinto dejasin efecto al pin STEP, en silencio y sin levantar ninguna falla. Los pulsos siguen saliendo y siguen contándose, pero no mueven nada.
- **Reintentos acotados.** Un CRC malo o un timeout se reintentan tantas veces como declare el bus, con la salvedad de que un reintento puede inflar al contador de escrituras `IFCNT` por demás. Por eso la verificación compara contra una cota y no contra una igualdad exacta.
- **El passthrough.** `tmc2209_bus_send()` es la vía para diagnosticar al driver: nada de la respuesta se juzga, ni siquiera un CRC malo, porque quien llama por acá sospecha del driver. Una respuesta corta se informa con cuántos bytes llegaron, en vez de descartarse.

### Líneas de Control

UART configura al driver, pero no es suficiente. Existen cuatro pines que modifican el estado del driver, pero que dependen de un módulo GPIO y niveles lógicos en vez de una transmisión serie por UART: `ENN`, `DIR`, `STEP` y `DIAG`.

Igual que en el port, este componente también es agnóstico. El backend escribe y lee niveles, nada más. Sostener un nivel un tiempo mínimo, y emitir trenes a una tasa, es temporización, y eso es problema del generador de pasos.

El backend trae además una máscara `wired`, un bit por línea. Una línea que la placa no conecta no se simula ni se ignora en silencio: toda llamada que la nombre responde `TMC2209_ERR_UNWIRED`. Esto es lo que permite que el mismo binario sirva a una placa con un driver que maneja el pin enable por otro lado.

Sobre esa base, cada línea tiene su particularidad:

- **DIAG** es entrada. Escribirla se rechaza con `TMC2209_ERR_ACCESS`.
- **ENN** se decidió invertirlo en la API pública, para que la función `tmc2209_enable(dev, true)` que es fácil de leer y de escribir signifique lo que el driver necesita (que haya un cero lógico en su entrada `ENN`, enable-not).
- **DIR** depende del mundo externo. Qué nivel es "adelante" lo decide `GCONF.shaft` combinado con cómo esté montado el motor, así que la línea sola no alcanza y el sentido real se sabrá al mover realmente el motor. Además queda tomado mientras haya una corrida en vuelo, por lo que se explica en generación de pasos.
- **STEP** deja de pertenecer a esta API en cuanto se le adjunta un generador de pasos. Un periférico atado al pin y un `gpio_set_level()` sobre el mismo pin es un conflicto, así que a partir de ahí `tmc2209_line_write()` sobre STEP se rechaza.

Vale la pena notar que `tmc2209_line_read()` sobre una salida devuelve el nivel que se está manejando desde el ESP32, mientras que `IOIN` (por UART) devuelve lo que ve el driver en ese mismo pin. Son los dos extremos de la misma pista, y que discrepen es evidencia de algun fallo.

El siguiente diagrama sigue una habilitación del driver y su comprobación desde los dos extremos:

```mermaid
sequenceDiagram
    autonumber
    participant App as main
    participant Lib as tmc2209
    participant Pins as backend lines
    participant Trace as pista
    participant Drv as TMC2209

    App->>Lib: tmc2209_enable(dev, true)
    Lib->>Lib: ¿hay backend de líneas?
    Lib->>Lib: ¿ENN está en la máscara wired?
    Note over Lib: si la placa no conecta la línea,<br/>TMC2209_ERR_UNWIRED y no se mueve ningún pin
    Lib->>Lib: aplica la polaridad: habilitar = nivel bajo
    Lib->>Pins: write(ENN, 0)
    Pins->>Trace: GPIO en bajo
    Trace->>Drv: ENN = 0, etapa de potencia encendida
    Pins-->>Lib: 0, el pin se movió
    Lib-->>App: TMC2209_OK

    App->>Lib: tmc2209_is_enabled(dev, &on)
    Lib->>Pins: read(ENN)
    Pins-->>Lib: nivel que el ESP32 está manejando
    Lib-->>App: on = true, según este extremo de la pista

    App->>Lib: tmc2209_poll_pins(dev, &ioin)
    Note over Lib,Drv: esto ya no es una línea:<br/>es una transacción UART como las de arriba
    Lib->>Drv: lectura de IOIN
    Drv-->>Lib: estado vivo de los pines del driver
    Lib-->>App: ioin.enn, según el otro extremo
    Note over App: las dos lecturas describen la misma pista.<br/>Si negamos ioin.enn y discrepan, hay un problema
```

### Generación de pasos

`STEP` es la cuarta línea del driver y no se parece a las otras tres. `ENN` y `DIR` se sostienen en un nivel, `DIAG` es también un nivel que se lee, pero a `STEP` lo que le importa no es en qué nivel está sino cuántas veces cambió y cuán separados en el tiempo estuvieron esos cambios (pulsos), ya que cada flanco avanza un microstep. Un nivel es un estado, y un tren de pulsos es una función del tiempo, así que las dos cosas deberían tener backends distintos.

Las consecuencias de esa diferencia son tres, y cada una empuja el diseño en una dirección distinta.

La primera es que **hace falta un periférico.** Cuatro mil microsteps a diez mil pulsos por segundo son cuatrocientos milisegundos de flancos que tienen que salir parejos, y sacarlos desde código sería ocupar el procesador entero para hacer algo que un RMT, un MCPWM o un timer hacen solos. Por eso el generador de pasos es su propio backend, con su propio contrato, y no una función más del backend de líneas: este backend entocnes deberá interactuar con el tiempo de manera cotidiana. Es el único de los tres que lo hace (sin contar los timeouts de UART).

La segunda es que **la API tiene que ser asíncrona**. Una llamada que volviera cuando el movimiento terminó dejaría al lazo de control congelado esos cuatrocientos milisegundos, justo mientras el motor se mueve, que es cuando hay algo para vigilar. Entonces `tmc2209_move()` vuelve apenas los pulsos están en camino, y queda el movimiento ocurriendo de fondo con un estado. Consultarlo es a través de `tmc2209_motion()`.

La tercera es que **el movimiento no puede empezar ni terminar de golpe**. Un motor paso a paso al que se le pide más aceleración de la que puede dar se queda atrás, patina, y se mueve una distancia desconocida. Por eso una corrida no se describe con una velocidad sino con un perfil:

![Perfil de una corrida: rampa de aceleración desde pullin_pps hasta cruise_pps, tramo de crucero, y rampa de frenado simétrica](media/stepgen_plot.png)

`pullin_pps` es la tasa más rápida a la que este motor con esta carga puede arrancar desde quieto y frenar en seco sin perder sincronismo, así que es una propiedad del mecanismo y viene de la tabla de la placa. El último pulso importa tanto como el primero: frenar de golpe desde la velocidad crucero pierde sincronismo igual que arrancar en crucero. Una corrida demasiado corta para terminar de acelerar nunca llega a `cruise_pps` y el perfil se vuelve un triángulo, que igual tiene que aterrizar en la cuenta exacta de pulsos pedida.

Lo que el backend debe garantizar es entonces:

| Garantía | Por qué |
| --- | --- |
| Cuenta exacta | Una corrida acotada emite esa cantidad de pulsos y ni uno más. Solo puede emitir menos si se la frena, y entonces debe informar cuántos salieron. |
| Contador veraz | La cuenta sobrevive al final de la corrida y a una frenada inmediata. Es el único registro físico de cuánto se movió el film, así que un contador que era correcto hasta la última interrupción es peor que inútil. |
| Corridas cortas | Dos pulsos con una rampa larga son un triángulo que nunca llega a crucero, y aterrizan igual en exactamente dos. |
| Ancho mínimo | Todo pulso dura al menos `min_pulse_ns`, a cualquier tasa. El backend declara ese número y la librería lo contrasta contra los 100 ns que pide la hoja de datos al momento de acoplarlo. |

El backend cuenta flancos y nada más: no se fija ni en el sentido de movimiento ni en la resolución de microstep. Y por otro lado, todo lo que le da sentido a esa cuenta de flancos vive del lado de la librería, y es la misma división que hace que `tmc2209_enable()` exista para que nadie tenga que recordar que `ENN` está invertido.

Sobre esa base, la API pública:

| Función | Qué hace |
| --- | --- |
| `tmc2209_attach_stepgen(dev, stepgen)` | Acopla la fuente de pulsos, una por driver. Rechaza un backend al que le falte cualquiera de sus cuatro llamadas, uno que declare `max_pps` cero, o uno que no garantice el ancho mínimo. A partir de acá el pin `STEP` es suyo y `tmc2209_line_write()` sobre `STEP` se rechaza. |
| `tmc2209_is_running(dev, *running)` | Pregunta si están saliendo pulsos, y nada más. Es lo que consulta un supervisor, porque no recoge la cuenta. |
| `tmc2209_move(dev, *m)` | Arranca una corrida según un plan de acción que marca sentido, velocidades, aceleración y cotas. La única llamada asíncrona de toda la librería y vuelve enseguida. |
| `tmc2209_retarget(dev, cruise_pps)` | Cambia la tasa de crucero de una corrida en vuelo, manteniendo la rampa con la aceleración del plan de acción original. |
| `tmc2209_halt(dev, immediate)` | Termina la corrida, cortando en el próximo pulso o desacelerando hasta `pullin_pps`. |
| `tmc2209_poll_motion(dev, *out)` | Recoge los pulsos de la corrida, la tasa actual y si todavía está andando. Recogerla una vez terminada la corrida es lo que habilita la siguiente. |

La librería no lleva posición. Sin encoder, una posición es una suma de cuentas de corridas y nada más, y sumarlas ya es decidir qué significaron esos pulsos: hacia dónde es positivo, cuántos milímetros vale un pulso, si la película patinó. Nada de eso se puede saber acá, así que se informa la cuenta de cada corrida y quien acumula es `main`, o la capa que venga después.

Lo que sí garantiza la librería es que ninguna cuenta se pierda en el camino. El backend guarda una sola, la de la corrida en curso o la última, así que arrancar una segunda corrida pisa un total que quizás nadie miró, y esos pulsos ya movieron película. Por eso un `tmc2209_move()` con una cuenta pendiente responde `TMC2209_ERR_UNREAD`, y un `tmc2209_poll_motion()` después de que la corrida terminó es lo que la salda. Consultar en el medio no salda nada, porque el total que estaría reconociendo todavía no existe.

`tmc2209_move()` es donde se junta todo, porque `DIR` es una línea, `STEP` es una tasa, y las dos tienen que estar de acuerdo antes del primer flanco. Además el sentido no se deduce: la corrida declara el nivel de `DIR` que quiere y el `GCONF.shaft` con el que está contando, y si el driver tiene el otro se rechaza en vez de moverse al revés. Qué combinación es "adelante" depende de cómo esté montado el motor, y eso no es un dato que este componente pueda tener.

```mermaid
sequenceDiagram
    autonumber
    participant App as main
    participant Lib as tmc2209
    participant Pins as backend lines
    participant Gen as backend stepgen
    participant Drv as TMC2209

    App->>Lib: tmc2209_move(dev, {dir, shaft, pulses, perfil})
    Lib->>Lib: ¿el perfil describe una rampa que existe?
    Note over Lib: crucero por debajo del pull-in, o sin<br/>rampa cuando hace falta: ERR_ARG.<br/>Por encima de max_pps: ERR_RATE
    Lib->>Gen: state()
    Gen-->>Lib: no hay nada corriendo
    Lib->>Lib: ¿quedó alguna cuenta sin recoger?
    Note over Lib: la anterior sin leer se perdería<br/>al arrancar esta: ERR_UNREAD
    Lib->>Lib: compara el shaft declarado contra GCONF del shadow
    Note over Lib: slot inválido: ERR_INVALID_SLOT.<br/>El driver tiene el otro: ERR_MISMATCH
    Lib->>Lib: lee VACTUAL del shadow
    Note over Lib: distinto de cero significa que el driver<br/>no está mirando su pin STEP: ERR_ACCESS

    Lib->>Pins: write(DIR, dir)
    Pins->>Drv: DIR establecido
    Note over Lib,Drv: DIR primero, siempre. El driver lo quiere quieto<br/>antes del primer flanco, y queda tomado hasta<br/>que salga el último: escribirlo da ERR_BUSY
    Lib->>Gen: run(plan)
    Gen-->>Lib: aceptado
    Lib-->>App: TMC2209_OK, la corrida quedó en vuelo

    par el periférico emite por su cuenta
        Gen->>Drv: tren de pulsos en STEP, rampa y crucero
    and el lazo de control sigue vivo
        loop una vez por frame
            App->>Lib: tmc2209_poll_motion(dev, &out)
            Lib->>Gen: state()
            Gen-->>Lib: emitidos, tasa, corriendo
            Lib-->>App: progreso, la cuenta sigue pendiente
        end
    end

    Gen->>Gen: sale el último pulso
    App->>Lib: tmc2209_poll_motion(dev, &out)
    Lib->>Gen: state()
    Gen-->>Lib: emitidos, corriendo = false
    Lib->>Lib: cuenta recogida: DIR se libera y el<br/>próximo move ya puede arrancar
    Lib-->>App: total de la corrida
```

Características:

- **Consultar es una pregunta, no una transacción.** `tmc2209_poll_motion()` devuelve lo que el backend informa: durante la corrida, los pulsos que ya salieron; terminada, el total. Consultarla de más no cambia ningún número. Lo único que cambia es que una corrida terminada deja de estar pendiente.
- **Recoger la cuenta y vigilar la corrida son dos cosas distintas.** El watchdog necesita saber si el motor todavía se mueve, pero si preguntara con `tmc2209_poll_motion()` estaría saldando una cuenta que su dueño nunca vio, y el próximo `move()` arrancaría sobre un reconocimiento que nadie hizo. Por eso existe `tmc2209_is_running()`, que responde lo mismo sin recoger nada.
- **`DIR` queda tomado mientras dura la corrida.** Se fija antes del primer flanco y no se puede tocar hasta que salga el último. El sentido es entonces una propiedad de la corrida entera, que es lo que hace que una sola cuenta alcance para describirla: si el nivel cambiara en el medio, los pulsos de antes y los de después caerían bajo el mismo número. `ENN` sigue disponible durante todo el movimiento, porque cortar la etapa de potencia es lo único que nunca se puede rechazar.
- **La cuenta es de pulsos emitidos, no de pasos exitosos.** Coinciden mientras el motor no pierda sincronismo ni ocurra un `TMC2209_DRIVER_RESET` por ejemplo, que es el aviso de que pueden haber dejado de coincidir.
- **Una tasa por encima de `max_pps` se rechaza, no se recorta.** Un movimiento que anduvo más lento de lo pedido es un problema de cadencia y puede devenir en un error de posición.
- **`halt()` no es una parada de emergencia.** Incluso la forma inmediata termina el pulso en curso, y la rampeada sigue pisando hasta `pullin_pps`. Lo verdaderamente urgente es cortar la etapa de potencia con `tmc2209_enable(dev, false)`, que es sincrónico y no necesita que ningún periférico coopere.
- **Una corrida sin fin es una función, no un descuido.** `pulses = 0` corre hasta que se la frene, y es lo que sirve para una bobina: la tensión depende del radio, el radio cambia mientras se enrolla, y `tmc2209_retarget()` mueve la tasa sin meter una frenada y un arranque en el medio del lazo. Por eso ahí sí se acepta una tasa por debajo del pull-in: el pull-in acota arrancar y frenar, no andar.
- **`VACTUAL` y `STEP` se pelean el motor.** Es el mismo conflicto que aparece en el bus UART, visto desde este lado. Se revisa solo cuando el shadow puede contestar, porque una negativa fabricada a partir de un slot inválido es peor que la ausencia del chequeo.

### Comunicación con la PC: Librería `rpc`
