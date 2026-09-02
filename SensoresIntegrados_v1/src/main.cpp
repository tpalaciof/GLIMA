#include <Arduino.h>

//******************************** PINES **********************************//

// MB7388
const int PIN_RX_SENSOR_DIS = 16;
HardwareSerial puertoSensor_dis(2);

// RG-15
const int PIN_RX_SENSOR_LLUV = 26; // TX RG-15 --> RX ESP32
const int PIN_TX_SENSOR_LLUV = 27; // RX RG-15 --> TX ESP32
HardwareSerial puertoSensor_lluv(1);

//***************************** VARIABLES *******************************//

unsigned long tv_ant = 0;
const unsigned long PUBLISH_FREQUENCY = 2000;
unsigned long tv_act = 0;

const int DISTANCIA_MAXIMA_MM = 9998;

//***************************** FUNCIONES *******************************//

void enviarComando(const char *comando)
{
  puertoSensor_lluv.print(comando);
  puertoSensor_lluv.print('\n');

  Serial.print("ESP32 -> RG-15: ");
  Serial.println(comando);
}

//---------------------------------------------------------------------
// Validación exclusiva para MB7388
//---------------------------------------------------------------------

bool tramaValidaMB7388(const String &trama)
{
  // Formato esperado: R1234

  if (trama.length() != 5 || trama[0] != 'R')
  {
    return false;
  }

  for (int i = 1; i < 5; i++)
  {
    if (!isDigit(trama[i]))
    {
      return false;
    }
  }

  return true;
}

//---------------------------------------------------------------------
// Lectura MB7388
//---------------------------------------------------------------------

void serial_dis()
{
  if (!puertoSensor_dis.available())
  {
    Serial.println("MB7388: no hay datos disponibles");
    return;
  }

  String trama = puertoSensor_dis.readStringUntil('\r');
  trama.trim();

  if (!tramaValidaMB7388(trama))
  {
    Serial.print("MB7388: trama no valida -> ");
    Serial.println(trama);
    return;
  }

  int distanciaMm = trama.substring(1).toInt();

  Serial.print("Trama MB7388 -> ESP32: ");
  Serial.print(trama);

  if (distanciaMm == 9999)
  {
    Serial.println(" -> sin objetivo detectado");
  }

  else if (distanciaMm <= DISTANCIA_MAXIMA_MM)
  {
    Serial.print(" -> distancia: ");
    Serial.print(distanciaMm);
    Serial.print(" mm (");
    Serial.print(distanciaMm / 1000.0, 3);
    Serial.println(" m)");

    if (distanciaMm < 500)
    {
      Serial.println(
          "Aviso: esta por debajo del rango especificado del MB7388.");
    }
  }
}

//---------------------------------------------------------------------
// Lectura RG-15
//---------------------------------------------------------------------

void serial_lluv()
{
  unsigned long tiempoInicio = millis();

  // Esperar hasta 500 ms una respuesta del RG-15
  while (millis() - tiempoInicio < 500)
  {
    if (puertoSensor_lluv.available())
    {
      String trama = puertoSensor_lluv.readStringUntil('\n');
      trama.trim();

      if (trama.length() > 0)
      {
        Serial.print("Trama RG-15 -> ESP32: ");
        Serial.println(trama);
      }
    }
  }
}

//---------------------------------------------------------------------
// SETUP
//---------------------------------------------------------------------

void setup()
{
  // Monitor Serial
  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println("==============================");
  Serial.println("INICIANDO SISTEMA");
  Serial.println("==============================");

  //========================== RG-15 ================================//

  puertoSensor_lluv.begin(
      9600,
      SERIAL_8N1,
      PIN_RX_SENSOR_LLUV,
      PIN_TX_SENSOR_LLUV);

  puertoSensor_lluv.setTimeout(250);

  delay(1000);

  Serial.println();
  Serial.println("Iniciando comunicacion con el RG-15...");

  enviarComando("M");
  delay(200);

  serial_lluv();

  enviarComando("H");
  delay(200);

  serial_lluv();

  enviarComando("P");
  delay(200);

  serial_lluv();

  Serial.println("RG-15 listo");

  //========================== MB7388 ===============================//

  puertoSensor_dis.begin(
      9600,
      SERIAL_8N1,
      PIN_RX_SENSOR_DIS);

  puertoSensor_dis.setTimeout(250);

  delay(1000);

  Serial.println("MB7388 listo");

  Serial.println();
  Serial.println("==============================");
  Serial.println("LECTURA DE SENSORES");
  Serial.println("==============================");
}

//---------------------------------------------------------------------
// LOOP
//---------------------------------------------------------------------

void loop()
{
  tv_act = millis();

  if (tv_act - tv_ant >= PUBLISH_FREQUENCY)
  {
    tv_ant = tv_act;

    Serial.println();
    Serial.println("------------------------------");

    // 1. Leer MB7388
    serial_dis();

    // 2. Solicitar lectura al RG-15
    enviarComando("R");

    // 3. Leer respuesta del RG-15
    serial_lluv();
  }
}
