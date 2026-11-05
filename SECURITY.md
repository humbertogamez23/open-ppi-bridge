# Política de Seguridad de open-ppi-bridge

## Versiones Soportadas

Actualmente, el soporte activo de parches y mejoras de seguridad se concentra en la rama principal:

| Versión / Rama | Soportada |
| :---: | :---: |
| `main` (última versión) | :white_check_mark: |
| Versiones anteriores / forks | :x: |

---

## 🔒 Reporte de Vulnerabilidades

La seguridad de las comunicaciones y la integridad de las órdenes enviadas a la maquinaria industrial son de máxima prioridad.

Si descubres una vulnerabilidad de seguridad en las herramientas de comunicación PPI, en el firmware ESP32-S3 o en la aplicación móvil Flutter:

1. **No abras un Issue público inmediatamente.**
2. Envía un reporte detallado a Humberto Gámez a través del canal privado de seguridad en GitHub o mediante mensaje directo en su perfil ([@humbertogamez23](https://github.com/humbertogamez23)).
3. Incluye en tu reporte:
   * Descripción de la vulnerabilidad y vector de ataque (físico, BLE o serial).
   * Pasos reproducibles o script de prueba conceptual (PoC).
   * Impacto estimado en la operación o seguridad del autómata.

Nos comprometemos a revisar y responder a los reportes en un plazo menor a 48 horas y coordinar la publicación del parche correctivo antes de cualquier divulgación pública.

---

## ⚡ Descargo de Responsabilidad y Seguridad Industrial

* Este software interactúa directamente con puertos de comunicación industrial (RS-485 / PPI / S7comm) y memorias EEPROM de controladores lógicos programables.
* El usuario es el único responsable de garantizar que los enclavamientos mecánicos, térmicos y de parada de emergencia estén implementados mediante circuitos físicos cableados independientes del software (de acuerdo a las normas **ISO 13849-1 / IEC 62061**).
* Ni los autores ni los contribuidores se responsabilizan por daños a equipos, pérdidas operativas o incidentes derivados del uso de este software en entornos de producción sin supervisión cualificada.
