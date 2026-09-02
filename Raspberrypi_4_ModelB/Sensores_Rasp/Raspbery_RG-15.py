import time

import serial


PUERTO = "/dev/ttyUSB0"
BAUDIOS = 9600

tv_ant = 0
PUBLISH_FREQUENCY = 200  # milisegundos


puertoSensor = serial.Serial(
    port=PUERTO,
    baudrate=BAUDIOS,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=0.250
)

def millis():
    return int(time.monotonic() * 1000)


def enviarComando(comando):
    puertoSensor.write((comando + "\n").encode("ascii"))

    print(f"Raspberry -> RG-15: {comando}")


def setup():
    print()
    print("Iniciando comunicacion con el RG-15...")

    time.sleep(1)
    
    # M: unidades metricas.
    # H: resolucion alta.
    # P: modo de consulta; el sensor responde cuando recibe R.
    enviarComando("M")
    time.sleep(0.1)

    enviarComando("H")
    time.sleep(0.1)

    enviarComando("P")
    time.sleep(0.1)

    # Elimina las respuestas y mensajes recibidos durante el encendido.
    puertoSensor.reset_input_buffer()

    print("RG-15 listo")
    print("Lectura del RG-15:")


def loop():
    global tv_ant

    # Leer las respuestas disponibles.
    while puertoSensor.in_waiting > 0:
        linea = puertoSensor.readline() #b"Acc 0.000 mm\r\n" --> lee hasta \n
        linea = linea.decode("ascii", errors="replace").strip() # Strip() Elimina espacios en blanco  y \r\n

        if len(linea) > 0:
            print(f"RG-15 -> Raspberry: {linea}")

    # Enviar R cada 200 ms.
    tv_act = millis()

    if tv_act - tv_ant >= PUBLISH_FREQUENCY:
        tv_ant = tv_act
        enviarComando("R")

    # Evita mantener el procesador de la Raspberry ocupado innecesariamente.
    time.sleep(0.005)


try:
    setup()

    while True:
        loop()

except KeyboardInterrupt:
    print("\nPrograma detenido.")

finally:
    puertoSensor.close()