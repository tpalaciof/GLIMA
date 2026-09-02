#include <Arduino.h>

const int PIN_RX_SENSOR = 16; // TX RG-15 --> RX ESP32
const int PIN_TX_SENSOR = 17; // RX RG-15 --> TX ESP32

HardwareSerial puertoSensor(2);

//***************************** TEMP *******************************/
unsigned long tv_ant = 0;
const long PUBLISH_FREQUENCY = 200;
unsigned long tv_act = 0;

void enviarComando(const char *comando)
{
  puertoSensor.print(comando);
  puertoSensor.print('\n');

  Serial.print("ESP32 -> RG-15: ");
  Serial.println(comando);
}

void setup()
{
  Serial.begin(9600);

  //************************** CONF. SERIAL *******************************/
  puertoSensor.begin(9600, SERIAL_8N1, PIN_RX_SENSOR, PIN_TX_SENSOR);
  puertoSensor.setTimeout(250);

  Serial.println();
  Serial.println("Iniciando comunicacion con el RG-15...");
  // M: unidades metricas.
  // H: resolucion alta.
  // P: modo de consulta; el sensor responde cuando recibe R.
  enviarComando("M");
  delay(100);
  enviarComando("H");
  delay(100);
  enviarComando("P");
  delay(100);

  // Espera a que termine cualquier medición iniciada durante el encendido.
  while (puertoSensor.available())
  {
    puertoSensor.read();
  }

  Serial.println("RG-15 listo");

  Serial.println("Lectura del RG-15: ");

  // Serial.println("ADC | Voltaje (mV) | Distancia (mm) ");
}

void loop()
{

  while (puertoSensor.available() > 0)
  {
    String linea = puertoSensor.readStringUntil('\n');
    linea.trim();

    if (linea.length() > 0)
    {
      Serial.print("RG-15 -> ESP32: ");
      Serial.println(linea);
    }
  }

  tv_act = millis();
  if (tv_act - tv_ant >= PUBLISH_FREQUENCY)
  {
    tv_ant = tv_act;
    enviarComando("R");
  }
}