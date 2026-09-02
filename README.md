# GLIMA

Plataforma experimental para la adquisición, transmisión, almacenamiento y visualización de variables hidrológicas y ambientales, desarrollada en el contexto del Grupo G-LIMA.

Este repositorio reúne programas para ESP32, Raspberry Pi y sensores de campo, junto con las hojas de datos necesarias para reproducir las pruebas. La implementación vigente mide distancia con un sensor ultrasónico MB7388, transmite las lecturas mediante módulos XBee-PRO 900HP y registra los resultados en una Raspberry Pi 4 Model B. La Raspberry conserva copias locales en CSV y TXT y envía telemetría a ThingsBoard Cloud.

> **Estado del proyecto:** prototipo académico y de investigación en desarrollo. La versión operativa actual utiliza únicamente el sensor de distancia MB7388. Los programas del pluviómetro RG-15 y las integraciones anteriores se conservan como antecedentes y material de prueba.

## Contenido

- [Objetivo](#objetivo)
- [Funcionamiento general](#funcionamiento-general)
- [Arquitectura del sistema](#arquitectura-del-sistema)
- [Hardware](#hardware)
- [Conexiones](#conexiones)
- [Formato de los mensajes](#formato-de-los-mensajes)
- [Procesamiento de los datos](#procesamiento-de-los-datos)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Programas vigentes](#programas-vigentes)
- [Requisitos de software](#requisitos-de-software)
- [Instalación y puesta en marcha](#instalación-y-puesta-en-marcha)
- [Archivos generados](#archivos-generados)
- [ThingsBoard](#thingsboard)
- [Solución de problemas](#solución-de-problemas)
- [Seguridad](#seguridad)
- [Documentación técnica](#documentación-técnica)

## Objetivo

El proyecto busca construir una plataforma modular de adquisición de datos capaz de:

1. leer sensores hidrológicos o ambientales en campo;
2. validar y organizar las mediciones en una unidad ESP32;
3. transmitir los datos de forma inalámbrica mediante XBee;
4. recibir y procesar la información en una Raspberry Pi;
5. mantener un respaldo local legible y estructurado;
6. visualizar la telemetría de manera remota en un dashboard;
7. evaluar la calidad y continuidad de los datos recibidos.

Aunque el repositorio contiene ensayos con el sensor de lluvia Hydreon RG-15, la configuración vigente se concentra en el sensor ultrasónico de distancia MB7388.

## Funcionamiento general

El MB7388 transmite continuamente tramas seriales con el formato R####. La ESP32 valida cada trama, clasifica el resultado y envía al XBee una línea que incluye un número de secuencia, la distancia y el estado de la medición.

La Raspberry Pi recibe los mensajes mediante un XBee conectado por USB. Durante intervalos de 30 segundos acumula las distancias válidas, calcula la moda, actualiza un indicador acumulativo de calidad, escribe una fila en archivos CSV y TXT y envía la misma medición a ThingsBoard.

La adquisición y el almacenamiento local pueden continuar aunque la conexión con ThingsBoard no esté disponible.

## Arquitectura del sistema

~~~mermaid
flowchart TD
    A["Sensor MB7388<br/>distancia en mm"]
    B["ESP32 DevKit V1<br/>validación y secuencia"]
    C["XBee-PRO 900HP<br/>enlace DigiMesh"]
    D["Raspberry Pi 4 Model B<br/>procesamiento y respaldo"]
    E["ThingsBoard Cloud<br/>dashboard y telemetría"]

    A -->|UART2, 9600 bit/s| B
    B -->|UART1, 9600 bit/s| C
    C -->|XBee remoto a XBee USB| D
    D -->|MQTT| E
~~~

El flujo principal es:

1. **MB7388 → ESP32:** el sensor entrega una trama R seguida de cuatro dígitos.
2. **ESP32 → XBee:** la ESP32 transmite un mensaje CSV corto con secuencia, distancia y estado.
3. **XBee → Raspberry Pi:** el módulo receptor entrega los mensajes por un adaptador USB-serial.
4. **Raspberry Pi → archivos:** cada 30 segundos se almacenan la moda y el porcentaje de datos correctos.
5. **Raspberry Pi → ThingsBoard:** los mismos valores se publican como telemetría MQTT.

## Hardware

| Componente | Función |
|---|---|
| ESP32 DevKit V1 / ESP-WROOM-32 | Lectura del sensor, validación y transmisión |
| MaxBotix MB7388 HRXL-MaxSonar-WR | Medición ultrasónica de distancia |
| 2 × XBee-PRO 900HP | Enlace inalámbrico entre la ESP32 y la Raspberry Pi |
| Adaptador XBee USB | Conexión del XBee receptor a la Raspberry Pi |
| Raspberry Pi 4 Model B | Recepción, procesamiento, almacenamiento y envío a la nube |
| Fuente regulada y cableado | Alimentación estable y tierra común entre los equipos |

Los XBee deben estar configurados para comunicarse entre sí en la misma red y trabajar con los parámetros seriales usados por los programas. La configuración actual del código utiliza 9600 bit/s, 8 bits de datos, sin paridad y un bit de parada.

## Conexiones

### MB7388 a ESP32

| MB7388 | ESP32 | Descripción |
|---|---|---|
| TX serial | GPIO16 | Entrada RX de UART2 |
| GND | GND | Tierra común |
| Alimentación | Fuente adecuada | Seguir la hoja de datos del sensor |

La ESP32 únicamente recibe información del MB7388; no se utiliza una línea TX hacia el sensor.

### XBee remoto a ESP32

| XBee | ESP32 | Descripción |
|---|---|---|
| DOUT | GPIO26 | RX de UART1 |
| DIN | GPIO27 | TX de UART1 |
| GND | GND | Tierra común |
| VCC | Fuente regulada apropiada | No alimentar el XBee directamente desde un pin GPIO |

> Los módulos XBee trabajan con niveles y requisitos de alimentación específicos. Utilice una placa adaptadora o una fuente regulada capaz de suministrar la corriente requerida por el modelo XBee-PRO 900HP.

### XBee receptor a Raspberry Pi

El segundo XBee se conecta a un puerto USB de la Raspberry Pi mediante su adaptador. El programa supone inicialmente:

    /dev/ttyUSB0

El nombre puede cambiar entre equipos o después de reconectar dispositivos. Puede comprobar los puertos disponibles con:

    ls -l /dev/ttyUSB*
    python3 -m serial.tools.list_ports

## Formato de los mensajes

La ESP32 transmite una línea por medición:

    D,secuencia,distancia_mm,estado

Ejemplo:

    D,25,1340,0

| Campo | Descripción |
|---|---|
| D | Identificador de mensaje de distancia |
| secuencia | Contador uint32 incrementado por la ESP32 |
| distancia_mm | Distancia en milímetros, 9999 o -1 según el estado |
| estado | Clasificación de la medición |

### Estados

| Estado | Distancia | Significado |
|---:|---:|---|
| 0 | 0 a 9998 | Distancia válida |
| 1 | 9999 | El sensor respondió correctamente, pero no detectó un objetivo |
| 2 | -1 | No llegó una trama R#### válida durante el intervalo de la ESP32 |

El número de secuencia permite advertir mensajes repetidos, posibles pérdidas y reinicios de la ESP32. Estas advertencias se muestran en la terminal de la Raspberry Pi.

## Procesamiento de los datos

### En la ESP32

- recibe continuamente las tramas del MB7388;
- acepta únicamente el formato R seguido de cuatro dígitos;
- conserva la lectura válida más reciente;
- asigna un estado a cada resultado;
- incrementa el número de secuencia;
- transmite un mensaje por XBee cada 2 segundos en la configuración actual.

La constante que controla este intervalo es:

    FRECUENCIA_ENVIO_MS = 2000

### En la Raspberry Pi

- valida que cada mensaje tenga cuatro campos;
- comprueba la correspondencia entre distancia y estado;
- acumula las distancias válidas durante 30 segundos;
- calcula la moda del intervalo;
- en caso de empate, selecciona la moda que apareció más recientemente;
- conserva 9999 si solo hubo respuestas sin objetivo;
- utiliza un valor vacío si no hubo una medición utilizable;
- genera archivos rotativos por hora;
- publica los datos en ThingsBoard.

### Indicador de calidad

El porcentaje almacenado se calcula para las filas del archivo vigente:

    filas con una moda válida / total de filas guardadas × 100

Con la configuración actual, el contador se reinicia al comenzar un archivo horario nuevo. Una distancia entre 0 y 9998 mm se considera correcta. Los valores 9999 y las filas sin distancia disminuyen el porcentaje.

Este indicador evalúa la validez de las mediciones consolidadas cada 30 segundos. No representa directamente el porcentaje de paquetes XBee recibidos; las pérdidas o repeticiones de paquetes se diagnostican por separado mediante el número de secuencia.

## Estructura del repositorio

    GLIMA/
    ├── Datasheets/
    │   ├── CP2102.PDF
    │   ├── ESP32.PDF
    │   ├── Esp32_DevKitC_Pinoutpng.png
    │   ├── HRXL-MaxSonar-WR_Datasheet.pdf
    │   ├── XBee-PRO900HP_DigiMesh_KitUserGuide.pdf
    │   ├── Xbee_pinout.pdf
    │   └── rg-15_instructions.pdf
    ├── PlatformIO_ESP32_DOIT_DEVKITC/
    │   ├── Sensores_Esp32/
    │   │   ├── Prueba_RG-15/
    │   │   ├── Prueba_SensorMB7388/
    │   │   └── SensoresIntegrados_v1/
    │   └── Xbee_Esp32/
    │       └── Xbee_Esp32_2_Rasp_v1/
    └── Raspberrypi_4_ModelB/
        ├── Sensores_Rasp/
        └── Xbee_Rasp/

### Descripción de las carpetas

| Ruta | Contenido |
|---|---|
| **Datasheets** | Manuales, hojas de datos y diagramas de pines |
| **PlatformIO_ESP32_DOIT_DEVKITC/Sensores_Esp32** | Pruebas individuales e integración anterior de sensores |
| **PlatformIO_ESP32_DOIT_DEVKITC/Xbee_Esp32** | Programa vigente de ESP32 para MB7388 y XBee |
| **Raspberrypi_4_ModelB/Sensores_Rasp** | Programas anteriores con sensores conectados directamente a la Raspberry Pi |
| **Raspberrypi_4_ModelB/Xbee_Rasp** | Receptores XBee para Raspberry Pi, incluida la versión vigente |

## Programas vigentes

### ESP32

**Ruta:**

    PlatformIO_ESP32_DOIT_DEVKITC/Xbee_Esp32/
    Xbee_Esp32_2_Rasp_v1/

El archivo **src/main.cpp** recibe el MB7388 por UART2 y transmite por UART1 al XBee. El archivo **platformio.ini** configura una ESP32 DOIT DevKit V1 y el monitor serial a 115200 bit/s.

### Raspberry Pi

**Ruta:**

    Raspberrypi_4_ModelB/Xbee_Rasp/
    distancia_xbee_esp32_v2_dashb_plus_csv.py

Este es el receptor vigente. Incluye recepción serial, verificación de secuencia, cálculo de la moda, indicador de calidad, generación de CSV y TXT y telemetría hacia ThingsBoard.

El archivo **distancia_xbee_esp32.py** es una versión anterior orientada a la recepción y prueba del enlace.

### Programas históricos

La carpeta **Sensores_Rasp** conserva versiones anteriores que trabajaban con el RG-15 y el MB7388 conectados directamente a la Raspberry Pi. Algunos archivos también reflejan pruebas previas con otras plataformas de visualización. No deben confundirse con la arquitectura vigente basada en XBee y ThingsBoard.

## Requisitos de software

### Computador de desarrollo

- Visual Studio Code;
- extensión PlatformIO IDE;
- plataforma Espressif 32;
- framework Arduino para ESP32;
- controlador USB correspondiente a la placa ESP32.

### Raspberry Pi

- Raspberry Pi OS;
- Python 3.9 o posterior;
- acceso a Internet para ThingsBoard;
- paquetes de Python **pyserial** y **tb-mqtt-client**;
- acceso del usuario al puerto serial USB.

## Instalación y puesta en marcha

### 1. Clonar el repositorio

    git clone https://github.com/tpalaciof/GLIMA.git
    cd GLIMA

### 2. Preparar y cargar la ESP32

Abra en PlatformIO la carpeta:

    PlatformIO_ESP32_DOIT_DEVKITC/Xbee_Esp32/
    Xbee_Esp32_2_Rasp_v1

Desde la terminal de PlatformIO también puede utilizar:

    pio run
    pio run --target upload
    pio device monitor

El monitor serial trabaja a 115200 bit/s. Las comunicaciones con el MB7388 y el XBee trabajan a 9600 bit/s; son interfaces distintas y no necesitan usar la misma velocidad que el monitor USB.

Antes de cargar el programa, compruebe:

- TX del MB7388 conectado a GPIO16;
- DOUT del XBee conectado a GPIO26;
- DIN del XBee conectado a GPIO27;
- tierras comunes;
- alimentación estable;
- dos XBee configurados en la misma red y con parámetros seriales compatibles.

### 3. Preparar la Raspberry Pi

Entre a la carpeta del receptor:

    cd Raspberrypi_4_ModelB/Xbee_Rasp

Se recomienda utilizar un entorno virtual:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install pyserial tb-mqtt-client

Utilice siempre **python -m pip** dentro del entorno activo. De esta forma, las dependencias se instalan en el mismo intérprete que ejecutará el programa y se evitan conflictos entre el paquete **pyserial** del sistema y el del entorno virtual.

Si el usuario no tiene permiso para abrir el puerto serial:

    sudo usermod -aG dialout $USER

Cierre la sesión y vuelva a entrar para que el cambio de grupo tenga efecto.

### 4. Configurar el receptor

Abra **distancia_xbee_esp32_v2_dashb_plus_csv.py** y revise:

| Constante | Función | Valor inicial |
|---|---|---|
| PUERTO_XBEE | Puerto del adaptador XBee USB | /dev/ttyUSB0 |
| BAUDIOS | Velocidad serial | 9600 |
| ZONA_HORARIA | Zona usada en los registros | America/Bogota |
| FRECUENCIA_GUARDADO_SEGUNDOS | Intervalo de consolidación | 30 |
| FRECUENCIA_ARCHIVO | Rotación de archivos | hora |
| THINGSBOARD_SERVER | Servidor MQTT | mqtt.thingsboard.cloud |
| ACCESS_TOKEN | Credencial del dispositivo | Debe configurarse de forma privada |

Las opciones admitidas para **FRECUENCIA_ARCHIVO** son:

- hora;
- diario;
- mensual;
- unico.

### 5. Configurar ThingsBoard

1. Cree un dispositivo en ThingsBoard Cloud.
2. Obtenga el token de acceso del dispositivo.
3. Configure el servidor y el token en el receptor.
4. Cree widgets usando las claves de telemetría descritas en la sección [ThingsBoard](#thingsboard).
5. No publique el token ni lo incluya en capturas, documentación o commits.

### 6. Ejecutar el receptor

Con el entorno virtual activo:

    python distancia_xbee_esp32_v2_dashb_plus_csv.py

Una ejecución correcta muestra mensajes similares a:

    Iniciando comunicación con el XBee...
    XBee listo
    Conectando con ThingsBoard...
    Iniciando recepción y registro de distancia...

Para detener el programa manualmente, presione **Ctrl+C**.

## Archivos generados

Los archivos se crean junto al programa, dentro de:

    datos_sensores/

Con la configuración horaria actual, la estructura es:

    datos_sensores/
    ├── mediciones_distancia_2026-09-02_11.txt
    └── csv/
        └── mediciones_distancia_2026-09-02_11.csv

### Columnas del CSV

| Columna | Descripción |
|---|---|
| fecha | Fecha local en formato AAAA-MM-DD |
| hora | Hora local en formato HH:MM:SS |
| distancia_moda_mm | Moda de las distancias del intervalo |
| porcentaje_datos_correctos_distancia | Porcentaje acumulado dentro del archivo vigente |

El TXT contiene los mismos datos en una tabla alineada para inspección humana. El CSV se recomienda para análisis, gráficas y procesamiento posterior.

## ThingsBoard

El receptor publica telemetría por MQTT en:

    mqtt.thingsboard.cloud

Claves disponibles:

| Clave | Unidad | Uso sugerido |
|---|---|---|
| distancia_moda_mm | mm | Serie temporal, indicador o gráfica de nivel/distancia |
| porcentaje_datos_correctos_distancia | % | Indicador de calidad de la información |

La marca de tiempo se genera en la Raspberry Pi con la zona **America/Bogota** y se envía a ThingsBoard en milisegundos desde Unix epoch.

Si falla Internet o ThingsBoard, el programa conserva el registro local e intenta restablecer la conexión en un intervalo posterior.

## Solución de problemas

### No aparece el puerto USB

Compruebe:

    lsusb
    ls -l /dev/ttyUSB*
    dmesg | tail -n 30

Desconecte y conecte nuevamente el adaptador e identifique qué puerto fue asignado. Actualice **PUERTO_XBEE** si es necesario.

### Permission denied al abrir el puerto

Verifique los grupos del usuario:

    groups

Añádalo al grupo serial y vuelva a iniciar sesión:

    sudo usermod -aG dialout $USER

### No module named serial

Active el entorno virtual correcto e instale **pyserial** con el mismo intérprete:

    source .venv/bin/activate
    python -m pip install pyserial
    python -c "import serial; print(serial.__file__)"

No instale un paquete llamado únicamente **serial**; el módulo esperado pertenece a **pyserial**.

### No llegan mensajes XBee

- confirme 9600 bit/s y configuración 8N1 en ambos extremos;
- compruebe que los dos XBee pertenecen a la misma red;
- revise DOUT, DIN y GND;
- confirme que la ESP32 imprime mensajes D,secuencia,distancia,estado;
- pruebe primero el XBee receptor con un monitor serial.

### Llegan mensajes no válidos

- revise que cada línea tenga exactamente cuatro campos;
- confirme que la ESP32 y la Raspberry usan el mismo protocolo;
- evite mezclar el programa vigente con versiones anteriores;
- elimine ruido eléctrico y utilice una alimentación estable.

### El MB7388 no entrega distancias

- confirme TX del sensor hacia GPIO16;
- verifique la tierra común;
- revise la alimentación y el rango de operación;
- compruebe en el monitor de PlatformIO si aparecen tramas no válidas;
- recuerde que R9999 significa que el sensor respondió, pero no detectó un objetivo.

### ThingsBoard no muestra datos

- confirme conexión a Internet;
- verifique el servidor MQTT;
- compruebe el token del dispositivo;
- revise que los widgets usen exactamente las claves de telemetría;
- confirme primero que los CSV y TXT se estén generando localmente.

## Seguridad

- No publique tokens de ThingsBoard, contraseñas ni credenciales.
- Si una credencial fue incluida alguna vez en un repositorio público, debe revocarse y reemplazarse.
- Para una versión de producción, se recomienda leer el token desde una variable de entorno o un archivo local excluido mediante **.gitignore**.
- No utilice el mismo token para estaciones diferentes.
- Limite los permisos y el acceso físico a la Raspberry Pi.
- Mantenga copias de respaldo de los datos y de la configuración de los XBee.

## Documentación técnica

Las principales referencias incluidas en el repositorio son:

- [Hoja de datos del MB7388](Datasheets/HRXL-MaxSonar-WR_Datasheet.pdf)
- [Guía del kit XBee-PRO 900HP DigiMesh](Datasheets/XBee-PRO900HP_DigiMesh_KitUserGuide.pdf)
- [Diagrama de pines XBee](Datasheets/Xbee_pinout.pdf)
- [Hoja de datos de la ESP32](Datasheets/ESP32.PDF)
- [Diagrama de pines ESP32 DevKitC](Datasheets/Esp32_DevKitC_Pinoutpng.png)
- [Manual del RG-15](Datasheets/rg-15_instructions.pdf)
- [SDK oficial de ThingsBoard para Python](https://github.com/thingsboard/thingsboard-python-client-sdk)
- [Documentación de PlatformIO](https://docs.platformio.org/)

## Observación final

Este repositorio documenta una plataforma en evolución. Para reproducir el montaje, utilice como referencia principal los programas indicados en [Programas vigentes](#programas-vigentes) y considere los demás archivos como pruebas, versiones anteriores o posibles extensiones del sistema.
