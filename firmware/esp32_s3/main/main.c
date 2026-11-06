/*
 * Puente RS485 PPI (S7-200) <-> Micro/WIN  —  ESP32-S3 / ESP-IDF
 *
 *   USB Serial/JTAG  ->  consola de logs (ESP_LOGI)
 *   UART0 (43/44)    ->  COM hacia Micro/WIN vía CH343
 *   UART1 (1/2/5)    ->  RS485 half-duplex al PLC, DE/RE en RTS (GPIO5)
 *                        - Aislado con módulo optoacoplador de 4 canales (PC817)
 *                        - Resistencias pull-up de 4.7k
 *
 *   9600 baudios, 8E1 (PPI estándar Siemens)
 *   Soporte completo de Memoria Permanente (Flash 16MB + NVS)
 */

#include <stdio.h>
#include <string.h>
#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "led_strip.h"

/* Headers de Memoria Permanente */
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_flash.h"
#include "esp_partition.h"

/* =================== CONFIGURACIÓN =================== */
#define PC_UART          UART_NUM_0
#define RS485_UART       UART_NUM_1

#define BAUD_RATE        9600
#define PC_TX_GPIO       43      /* default UART0 TX en ESP32-S3 */
#define PC_RX_GPIO       44      /* default UART0 RX en ESP32-S3 */
#define RS485_TX_GPIO    1       /* DI del MAX485 (GPIO1, libre de PSRAM) */
#define RS485_RX_GPIO    2       /* RO del MAX485 (GPIO2, libre de PSRAM) */
#define RS485_RTS_GPIO   5       /* DE/RE en RTS hardware (GPIO5) */
#define LED_GPIO         48

#define BUF_SIZE         1024
#define FRAME_MAX_BYTES  512
#define FRAME_GAP_MS     5       /* silencio que indica fin de telegrama */
#define LED_HOLD_MS      60
#define WDT_TIMEOUT_S    5

static const char *TAG = "PPI_BRIDGE";

/* =================== LED (NeoPixel WS2812) =================== */
static led_strip_handle_t s_led = NULL;

static void led_init(void)
{
    led_strip_config_t strip_cfg = {
        .strip_gpio_num = LED_GPIO,
        .max_leds = 1,
        .led_pixel_format = LED_PIXEL_FORMAT_GRB,
        .led_model = LED_MODEL_WS2812,
        .flags = { .invert_out = false },
    };
    led_strip_rmt_config_t rmt_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .flags = { .with_dma = false },
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &s_led));
    led_strip_clear(s_led);
}

static void led_set(uint8_t r, uint8_t g, uint8_t b)
{
    if (!s_led) return;
    led_strip_set_pixel(s_led, 0, r, g, b);
    led_strip_refresh(s_led);
}

/* =================== Memoria Permanente (Flash 16MB + NVS) =================== */
static uint32_t s_boot_count = 0;
static uint32_t s_nvs_tx_pkts = 0;
static uint32_t s_nvs_rx_pkts = 0;
static uint32_t s_nvs_tx_bytes = 0;
static uint32_t s_nvs_rx_bytes = 0;

static void init_permanent_memory(void)
{
    ESP_LOGI(TAG, "=======================================================");
    ESP_LOGI(TAG, "=== GESTOR DE MEMORIA PERMANENTE (FLASH & NVS) ===");

    /* 1. Diagnóstico de la memoria Flash física de 16MB */
    uint32_t flash_size_bytes = 0;
    esp_err_t err_flash = esp_flash_get_size(NULL, &flash_size_bytes);
    if (err_flash == ESP_OK) {
        ESP_LOGI(TAG, "[FLASH PERMANENTE] Tamano fisico: %lu MB (%lu bytes)",
                 (unsigned long)(flash_size_bytes / (1024 * 1024)),
                 (unsigned long)flash_size_bytes);
    } else {
        ESP_LOGE(TAG, "[FLASH PERMANENTE] Error leyendo tamano de flash: %s", esp_err_to_name(err_flash));
    }

    /* 2. Inicialización de NVS (Non-Volatile Storage) */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "[NVS] Particion corrupta o nueva version detectada; formateando particion NVS...");
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "[NVS PERMANENTE] Inicializado correctamente: 100%% OPERATIVO");
    } else {
        ESP_LOGE(TAG, "[NVS PERMANENTE] Fallo al inicializar: %s", esp_err_to_name(ret));
    }

    /* 3. Contador persistente de arranques y métricas acumuladas en Flash */
    nvs_handle_t nvs_h;
    esp_err_t nvs_err = nvs_open("ppi_storage", NVS_READWRITE, &nvs_h);
    if (nvs_err == ESP_OK) {
        nvs_get_u32(nvs_h, "boot_count", &s_boot_count);
        nvs_get_u32(nvs_h, "tx_pkts",    &s_nvs_tx_pkts);
        nvs_get_u32(nvs_h, "rx_pkts",    &s_nvs_rx_pkts);
        nvs_get_u32(nvs_h, "tx_bytes",   &s_nvs_tx_bytes);
        nvs_get_u32(nvs_h, "rx_bytes",   &s_nvs_rx_bytes);

        s_boot_count++;
        nvs_set_u32(nvs_h, "boot_count", s_boot_count);
        nvs_commit(nvs_h);
        nvs_close(nvs_h);

        ESP_LOGI(TAG, "[NVS PERMANENTE] Arranque persistente #%lu registrado en Flash", (unsigned long)s_boot_count);
        ESP_LOGI(TAG, "[NVS PERMANENTE] Historico acumulado en Flash: TX=%lu pkts (%lu B), RX=%lu pkts (%lu B)",
                 (unsigned long)s_nvs_tx_pkts, (unsigned long)s_nvs_tx_bytes,
                 (unsigned long)s_nvs_rx_pkts, (unsigned long)s_nvs_rx_bytes);
    } else {
        ESP_LOGW(TAG, "[NVS PERMANENTE] No se pudo abrir espacio 'ppi_storage': %s", esp_err_to_name(nvs_err));
    }

    /* 4. Verificación y listado de particiones en la Flash */
    ESP_LOGI(TAG, "[PARTICIONES] Mapa de la memoria Flash:");
    esp_partition_iterator_t it = esp_partition_find(ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, NULL);
    while (it != NULL) {
        const esp_partition_t *part = esp_partition_get(it);
        ESP_LOGI(TAG, "  -> '%-8s' | Tipo: 0x%02X | Subtipo: 0x%02X | Offset: 0x%06lX | Tamano: %7lu KB",
                 part->label, part->type, part->subtype,
                 (unsigned long)part->address,
                 (unsigned long)(part->size / 1024));
        it = esp_partition_next(it);
    }
    esp_partition_iterator_release(it);

    /* 5. Autocomprobación física de la partición de almacenamiento 'storage' (12 MB) */
    const esp_partition_t *storage_part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "storage");
    if (storage_part != NULL) {
        uint32_t sample_data = 0;
        esp_err_t read_err = esp_partition_read(storage_part, 0, &sample_data, sizeof(sample_data));
        if (read_err == ESP_OK) {
            ESP_LOGI(TAG, "[STORAGE PERMANENTE] Particion '%s' (11.87 MB): Acceso Flash verificado (100%% OK)", storage_part->label);
        } else {
            ESP_LOGW(TAG, "[STORAGE PERMANENTE] Error accediendo a particion 'storage': %s", esp_err_to_name(read_err));
        }
    }

    ESP_LOGI(TAG, "=======================================================");
}

/* Guardado periódico de estadísticas en NVS cuando no hay tráfico */
static void save_stats_to_nvs(void)
{
    nvs_handle_t nvs_h;
    if (nvs_open("ppi_storage", NVS_READWRITE, &nvs_h) == ESP_OK) {
        nvs_set_u32(nvs_h, "tx_pkts",  s_nvs_tx_pkts);
        nvs_set_u32(nvs_h, "rx_pkts",  s_nvs_rx_pkts);
        nvs_set_u32(nvs_h, "tx_bytes", s_nvs_tx_bytes);
        nvs_set_u32(nvs_h, "rx_bytes", s_nvs_rx_bytes);
        nvs_commit(nvs_h);
        nvs_close(nvs_h);
    }
}

/* =================== UART setup =================== */
static void uart_setup(void)
{
    uart_config_t cfg = {
        .baud_rate  = BAUD_RATE,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_EVEN,   /* 8E1, PPI */
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    /* --- UART0: lado PC (Micro/WIN via CH343) --- */
    ESP_ERROR_CHECK(uart_driver_install(PC_UART, BUF_SIZE * 2, BUF_SIZE * 2,
                                        0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(PC_UART, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(PC_UART, PC_TX_GPIO, PC_RX_GPIO,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));

    /* --- UART1: lado RS485 (S7-200), DE/RE en RTS (GPIO5) --- */
    ESP_ERROR_CHECK(uart_driver_install(RS485_UART, BUF_SIZE * 2, BUF_SIZE * 2,
                                        0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(RS485_UART, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(RS485_UART, RS485_TX_GPIO, RS485_RX_GPIO,
                                 RS485_RTS_GPIO, UART_PIN_NO_CHANGE));

    /* Invertir señales RX, TX y RTS por hardware debido a los optoacopladores PC817 */
    uart_set_line_inverse(RS485_UART, UART_SIGNAL_TXD_INV | UART_SIGNAL_RXD_INV | UART_SIGNAL_RTS_INV);

    /* Modo half-duplex del driver ESP-IDF por hardware */
    ESP_ERROR_CHECK(uart_set_mode(RS485_UART, UART_MODE_RS485_HALF_DUPLEX));

    ESP_LOGI(TAG, "UART0=PC(43/44) 8E1 | UART1=RS485(TX1/RX2) RTS=GPIO5 (optos inv) auto 8E1");
}

/* =================== Estado compartido y Concurrencia =================== */
static volatile TickType_t s_last_up = 0;     /* último tick PC->PLC */
static volatile TickType_t s_last_dn = 0;     /* último tick PLC->PC */
static volatile bool       s_tx_active = false; /* protección de bus contra eco cruzado */

/* =================== Tareas =================== */

/* PC (Micro/WIN) -----> PLC (S7-200) */
static void task_pc_to_plc(void *arg)
{
    (void)arg;
    uint8_t buf[FRAME_MAX_BYTES];
    esp_task_wdt_add(NULL);

    while (1) {
        esp_task_wdt_reset();
        int total = uart_read_bytes(PC_UART, buf, sizeof(buf), pdMS_TO_TICKS(10));
        if (total <= 0) {
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }

        /* Acumular telegrama por silencio de FRAME_GAP_MS */
        TickType_t gap_ticks = pdMS_TO_TICKS(FRAME_GAP_MS);
        if (gap_ticks == 0) gap_ticks = 1;

        while (total < FRAME_MAX_BYTES) {
            esp_task_wdt_reset();
            int more = uart_read_bytes(PC_UART, buf + total,
                                       sizeof(buf) - total,
                                       gap_ticks);
            if (more <= 0) break;
            total += more;
        }

        ESP_LOGI(TAG, "PC->PLC %d B (cab=0x%02X):", total, buf[0]);
        ESP_LOG_BUFFER_HEX(TAG, buf, total);

        /* Activar bandera de transmisión activa para que task_plc_to_pc descarte ecos */
        s_tx_active = true;

        /* Transmitir al bus RS485 */
        uart_write_bytes(RS485_UART, (const char *)buf, total);

        /* Timeout dinámico preciso: (bytes * 11 bits * 1000 ms) / BAUD_RATE + 40ms margen */
        uint32_t tx_ms = (uint32_t)((total * 11UL * 1000UL) / BAUD_RATE) + 40;
        TickType_t tx_ticks = pdMS_TO_TICKS(tx_ms);
        if (tx_ticks == 0) tx_ticks = 1;
        uart_wait_tx_done(RS485_UART, tx_ticks);

        /* Limpiar buffer RX de RS485 para purgar cualquier eco residual antes de reabrir recepción */
        uart_flush_input(RS485_UART);
        s_tx_active = false;

        /* Actualizar métricas acumuladas */
        s_nvs_tx_pkts++;
        s_nvs_tx_bytes += total;

        s_last_up = xTaskGetTickCount();
        esp_task_wdt_reset();
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

/* PLC (S7-200) -----> PC (Micro/WIN) */
static void task_plc_to_pc(void *arg)
{
    (void)arg;
    uint8_t buf[BUF_SIZE];
    esp_task_wdt_add(NULL);

    while (1) {
        esp_task_wdt_reset();

        /* Si la tarea PC->PLC está emitiendo al bus, esperar para evitar procesar ecos */
        if (s_tx_active) {
            vTaskDelay(pdMS_TO_TICKS(2));
            continue;
        }

        int n = uart_read_bytes(RS485_UART, buf, sizeof(buf), pdMS_TO_TICKS(10));
        if (n > 0) {
            if (!s_tx_active) {
                ESP_LOGI(TAG, "PLC->PC %d B:", n);
                ESP_LOG_BUFFER_HEX(TAG, buf, n);
                uart_write_bytes(PC_UART, (const char *)buf, n);

                s_nvs_rx_pkts++;
                s_nvs_rx_bytes += n;
                s_last_dn = xTaskGetTickCount();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}

/* Tarea de mantenimiento: LED de tráfico y persistencia NVS periódica */
static void task_maintenance(void *arg)
{
    (void)arg;
    esp_task_wdt_add(NULL);

    uint8_t cur_r = 0, cur_g = 0, cur_b = 0;
    TickType_t last_nvs_save = xTaskGetTickCount();
    uint32_t last_saved_tx = 0, last_saved_rx = 0;

    while (1) {
        TickType_t now = xTaskGetTickCount();
        bool up_act = (now - s_last_up) < pdMS_TO_TICKS(LED_HOLD_MS);
        bool dn_act = (now - s_last_dn) < pdMS_TO_TICKS(LED_HOLD_MS);

        uint8_t r = 0, g = 0, b = 0;
        if      (up_act && dn_act) { r = 40; b = 40; } /* magenta: bidir   */
        else if (up_act)           { b = 40; }          /* azul:   PC->PLC  */
        else if (dn_act)           { r = 40; }          /* rojo:   PLC->PC  */

        if (r != cur_r || g != cur_g || b != cur_b) {
            led_set(r, g, b);
            cur_r = r; cur_g = g; cur_b = b;
        }

        /* Si ha transcurrido más de 10 segundos y hubo nuevo tráfico, persistir métricas en Flash */
        if ((now - last_nvs_save) > pdMS_TO_TICKS(10000)) {
            if (s_nvs_tx_bytes != last_saved_tx || s_nvs_rx_bytes != last_saved_rx) {
                save_stats_to_nvs();
                last_saved_tx = s_nvs_tx_bytes;
                last_saved_rx = s_nvs_rx_bytes;
            }
            last_nvs_save = now;
        }

        esp_task_wdt_reset();
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

/* =================== Watchdog =================== */
static void wdt_setup(void)
{
    esp_task_wdt_config_t wdt_cfg = {
        .timeout_ms    = WDT_TIMEOUT_S * 1000,
        .idle_core_mask = 0,
        .trigger_panic  = true,
    };
    /* Reconfigurar el TWDT que ESP-IDF inicializa por defecto sin generar error */
    esp_err_t err = esp_task_wdt_reconfigure(&wdt_cfg);
    if (err != ESP_OK) {
        esp_task_wdt_init(&wdt_cfg);
    }
}

/* =================== app_main =================== */
void app_main(void)
{
    ESP_LOGI(TAG, "=== Puente RS485 PPI (Modo Hardware RTS + Optoacopladores) ===");
    ESP_LOGI(TAG, "  Micro/WIN   -> UART0 (CH343, GPIO43/44)");
    ESP_LOGI(TAG, "  PLC S7-200  -> UART1 RS485 (TX1/RX2, RTS=GPIO5) via PC817");

    led_init();
    led_set(0, 0, 0);

    /* Verde corto = arranque OK */
    led_set(0, 40, 0);
    vTaskDelay(pdMS_TO_TICKS(200));
    led_set(0, 0, 0);

    wdt_setup();

    /* Inicializar y diagnosticar memoria permanente (Flash 16MB + NVS) */
    init_permanent_memory();

    uart_setup();

    xTaskCreatePinnedToCore(task_pc_to_plc,   "pc2plc",      4096, NULL, 10, NULL, 0);
    xTaskCreatePinnedToCore(task_plc_to_pc,   "plc2pc",      4096, NULL, 10, NULL, 1);
    xTaskCreate(task_maintenance,             "maintenance", 3072, NULL,  3, NULL);

    ESP_LOGI(TAG, "Puente activo. Esperando trafico PPI...");
}
