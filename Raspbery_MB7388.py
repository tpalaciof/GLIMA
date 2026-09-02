import time
import serial


#************************* CONFIGURACIÓN *************************#

# Si utilizas el CP2102.
PUERTO = "/dev/ttyUSB1"

# Si conectaras el sensor al UART GPIO de la Raspberry,
# normalmente sería: "/dev/serial0"

BAUDIOS = 9600
DISTANCIA_MAXIMA_MM = 9998


#************************* PUERTO SERIAL *************************#

puertoSensor = serial.Serial(
    port=PUERTO,
    baudrate=BAUDIOS,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=0.250
)


#**************************** FUNCIÓN ****************************#


def setup():
    print()
    print("Iniciando comunicacion con el MB7388...")

    # Tiempo para que el MB7388 inicie sus mediciones.
    time.sleep(1)
   
    # Elimina cualquier trama incompleta recibida durante el encendido.
    puertoSensor.reset_input_buffer()

    print("MB7388 listo")
    print("Lectura del MB7388:")


def recibirRespuesta():

    if puertoSensor.in_waiting <= 0:
        return None

    # El sensor transmite:
    # R + cuatro dígitos en milímetros + retorno de carro.
    # Ejemplo: R1234\r
    trama = puertoSensor.read_until(b"\r")

    trama = trama.decode("ascii",errors="replace").strip()

    # Validación que anteriormente hacía tramaValida().
    if len(trama) != 5 or trama[0] != "R":
        print(f"Trama no válida: {trama!r}")
        return None

    for i in range(1, 5):
        if not trama[i].isdigit():
            print(f"Trama no válida: {trama!r}")
            return None

    distanciaMm = int(trama[1:])

    if distanciaMm == 9999:
        print(f"Trama: {trama}  -> sin objetivo detectado")

    elif distanciaMm <= DISTANCIA_MAXIMA_MM:
        print(
            f"Trama: {trama}  -> distancia: "
            f"{distanciaMm} mm "
            f"({distanciaMm / 1000.0:.3f} m)"
        )

        if distanciaMm < 500:
            print(
                "Aviso: está por debajo del rango "
                "especificado del MB7388."
            )

    return distanciaMm


#************************ PROGRAMA PRINCIPAL *********************#

try:
   
    setup()
    while True:
        recibirRespuesta()

        # Evita mantener innecesariamente ocupado el procesador.
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nPrograma detenido.")

finally:
    puertoSensor.close()