/*
 * ESP32-S3 Dual Bridge: Bluetooth LE (Nordic UART Service) <-> FTDI USB Host <-> Siemens S7-200 PPI
 *
 * - BLE GAP/GATT Server    : "S7-200-PPI-BLE" (Nordic UART Service - NUS)
 * - USB OTG Port (Type-C)  : USB Host conectado al módulo FTDI FT232RL (RS485 PPI @ 9600 8E1)
 * - LED NeoPixel (GPIO 48) : Indicador de estado de conexión y tráfico:
 *                            - Amarillo : Esperando FTDI
 *                            - Cian     : FTDI listo, esperando cliente BLE
 *                            - Verde    : FTDI listo y Laptop BLE conectada
 *                            - Azul     : Tráfico Laptop -> PLC (TX)
 *                            - Rojo     : Tráfico PLC -> Laptop (RX)
 */

#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include <memory>
#include <vector>

#include "esp_log.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"

#include "driver/gpio.h"
#include "led_strip.h"

/* USB Host VCP */
#include "usb/cdc_acm_host.h"
#include "usb/vcp_ftdi.hpp"
#include "usb/vcp.hpp"
#include "usb/usb_host.h"

/* NimBLE Bluetooth LE */
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

extern "C" void ble_store_config_init(void);

using namespace esp_usb;

#define TAG              "PPI_BLE_BRIDGE"
#define LED_GPIO         48
#define PLC_BAUDRATE     9600
#define BLE_DEVICE_NAME  "S7-200-PPI-BLE"

/* --- Nordic UART Service (NUS) UUIDs (Little-Endian) --- */
/* Base: 6E400001-B5A3-F393-E0A9-E50E24DCCA9E */
static const ble_uuid128_t s_nus_svc_uuid =
    BLE_UUID128_INIT(0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
                     0x93, 0xf3, 0xa3, 0xb5, 0x01, 0x00, 0x40, 0x6e);

/* RX Char (Write / Write No Response): 6E400002-B5A3-F393-E0A9-E50E24DCCA9E */
static const ble_uuid128_t s_nus_rx_uuid =
    BLE_UUID128_INIT(0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
                     0x93, 0xf3, 0xa3, 0xb5, 0x02, 0x00, 0x40, 0x6e);

/* TX Char (Notify): 6E400003-B5A3-F393-E0A9-E50E24DCCA9E */
static const ble_uuid128_t s_nus_tx_uuid =
    BLE_UUID128_INIT(0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
                     0x93, 0xf3, 0xa3, 0xb5, 0x03, 0x00, 0x40, 0x6e);

/* Estructura para paquetes recibidos de BLE hacia FTDI */
struct BleToFtdiPacket {
    uint16_t len;
    uint8_t  data[256];
};

static led_strip_handle_t s_led = NULL;
static SemaphoreHandle_t s_dev_disconnect_sem = NULL;
static QueueHandle_t     s_ble_to_ftdi_queue = NULL;

static volatile bool     s_ftdi_ready = false;
static uint32_t          s_current_baudrate = PLC_BAUDRATE;
static uint16_t          s_ble_conn_handle = BLE_HS_CONN_HANDLE_NONE;
static uint16_t          s_ble_tx_val_handle = 0;
static uint16_t          s_ble_rx_val_handle = 0;
static volatile bool     s_ble_notify_enabled = false;
static uint8_t           s_own_addr_type = 0;

/* --- LED NeoPixel --- */
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
        .mem_block_symbols = 0,
        .flags = { .with_dma = false },
    };
    if (led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &s_led) == ESP_OK) {
        led_strip_clear(s_led);
    }
}

static void led_set_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    if (!s_led) return;
    led_strip_set_pixel(s_led, 0, r, g, b);
    led_strip_refresh(s_led);
}

static void led_update_idle_state(void)
{
    if (!s_ftdi_ready) {
        led_set_rgb(40, 40, 0); // Amarillo = Esperando FTDI
    } else if (s_ble_conn_handle == BLE_HS_CONN_HANDLE_NONE) {
        led_set_rgb(0, 30, 30); // Cian = FTDI OK, esperando conexión BLE
    } else {
        led_set_rgb(0, 40, 0);  // Verde = FTDI y BLE listos
    }
}

/* --- Callbacks USB CDC-ACM / FTDI --- */
static bool handle_rx(const uint8_t *data, size_t data_len, void *arg)
{
    if (data_len > 0) {
        ESP_LOGI(TAG, "PLC->ESP (%d bytes):", (int)data_len);
        ESP_LOG_BUFFER_HEX(TAG, data, data_len);
        led_set_rgb(40, 0, 0); // Rojo = Recibido del PLC

        /* Reenviar a la laptop vía BLE Notify */
        if (s_ble_conn_handle != BLE_HS_CONN_HANDLE_NONE && s_ble_notify_enabled) {
            struct os_mbuf *om = ble_hs_mbuf_from_flat(data, data_len);
            if (om != NULL) {
                int rc = ble_gatts_notify_custom(s_ble_conn_handle, s_ble_tx_val_handle, om);
                if (rc != 0) {
                    ESP_LOGE(TAG, "Error enviando BLE notify: %d", rc);
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(15));
        led_update_idle_state();
    }
    return true;
}

static void handle_event(const cdc_acm_host_dev_event_data_t *event, void *user_ctx)
{
    switch (event->type) {
    case CDC_ACM_HOST_ERROR:
        ESP_LOGE(TAG, "Error en CDC-ACM Host: %d", event->data.error);
        break;
    case CDC_ACM_HOST_DEVICE_DISCONNECTED:
        ESP_LOGW(TAG, "Módulo FTDI desconectado");
        s_ftdi_ready = false;
        led_update_idle_state();
        if (s_dev_disconnect_sem) {
            xSemaphoreGive(s_dev_disconnect_sem);
        }
        break;
    case CDC_ACM_HOST_SERIAL_STATE:
        ESP_LOGD(TAG, "Notificación Serial State: 0x%04X", event->data.serial_state.val);
        break;
    default:
        break;
    }
}

static void usb_lib_task(void *arg)
{
    while (1) {
        uint32_t event_flags;
        esp_err_t err = usb_host_lib_handle_events(portMAX_DELAY, &event_flags);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "usb_host_lib_handle_events err: %d", (int)err);
        }
        if (event_flags & USB_HOST_LIB_EVENT_FLAGS_NO_CLIENTS) {
            usb_host_device_free_all();
        }
    }
}

/* --- Callback GATT para Lectura/Escritura de BLE --- */
static int gatt_svr_access_cb(uint16_t conn_handle, uint16_t attr_handle,
                              struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (attr_handle == s_ble_rx_val_handle && ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        uint16_t om_len = OS_MBUF_PKTLEN(ctxt->om);
        if (om_len > 0 && om_len <= 256) {
            BleToFtdiPacket pkt;
            pkt.len = om_len;
            int rc = ble_hs_mbuf_to_flat(ctxt->om, pkt.data, sizeof(pkt.data), &pkt.len);
            if (rc == 0) {
                ESP_LOGI(TAG, "Laptop->ESP vía BLE (%d bytes):", (int)pkt.len);
                ESP_LOG_BUFFER_HEX(TAG, pkt.data, pkt.len);
                if (s_ble_to_ftdi_queue != NULL) {
                    xQueueSend(s_ble_to_ftdi_queue, &pkt, 0);
                }
            }
        }
        return 0;
    }
    return BLE_ATT_ERR_UNLIKELY;
}

static const struct ble_gatt_svc_def s_gatt_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &s_nus_svc_uuid.u,
        .includes = NULL,
        .characteristics = (struct ble_gatt_chr_def[])
        {
            {
                /* RX Characteristic: Laptop escribe comandos para el PLC */
                .uuid = &s_nus_rx_uuid.u,
                .access_cb = gatt_svr_access_cb,
                .arg = NULL,
                .descriptors = NULL,
                .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP,
                .min_key_size = 0,
                .val_handle = &s_ble_rx_val_handle,
                .cpfd = NULL,
            },
            {
                /* TX Characteristic: ESP32 notifica respuestas del PLC a la Laptop */
                .uuid = &s_nus_tx_uuid.u,
                .access_cb = gatt_svr_access_cb,
                .arg = NULL,
                .descriptors = NULL,
                .flags = BLE_GATT_CHR_F_NOTIFY,
                .min_key_size = 0,
                .val_handle = &s_ble_tx_val_handle,
                .cpfd = NULL,
            },
            {
                0, /* Fin de características */
            }
        },
    },
    {
        0, /* Fin de servicios */
    },
};

static void ble_advertise(void);

static int ble_gap_event(struct ble_gap_event *event, void *arg)
{
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            s_ble_conn_handle = event->connect.conn_handle;
            ESP_LOGI(TAG, "¡Laptop / Cliente BLE CONECTADO! (conn_handle=%d)", s_ble_conn_handle);
            led_update_idle_state();
        } else {
            ESP_LOGE(TAG, "Fallo al conectar BLE: status=%d", event->connect.status);
            ble_advertise();
        }
        break;

    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGW(TAG, "Laptop / Cliente BLE DESCONECTADO (razón=%d)", event->disconnect.reason);
        s_ble_conn_handle = BLE_HS_CONN_HANDLE_NONE;
        s_ble_notify_enabled = false;
        led_update_idle_state();
        ble_advertise();
        break;

    case BLE_GAP_EVENT_SUBSCRIBE:
        if (event->subscribe.attr_handle == s_ble_tx_val_handle) {
            s_ble_notify_enabled = event->subscribe.cur_notify;
            ESP_LOGI(TAG, "Suscripción BLE a TX Notify: %s", s_ble_notify_enabled ? "ACTIVADA" : "DESACTIVADA");
        }
        break;

    case BLE_GAP_EVENT_MTU:
        ESP_LOGI(TAG, "BLE MTU actualizado a %d bytes", event->mtu.value);
        break;

    default:
        break;
    }
    return 0;
}

static void ble_advertise(void)
{
    struct ble_gap_adv_params adv_params;
    struct ble_hs_adv_fields fields;
    int rc;

    memset(&fields, 0, sizeof(fields));
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.tx_pwr_lvl_is_present = 1;
    fields.tx_pwr_lvl = BLE_HS_ADV_TX_PWR_LVL_AUTO;

    const char *name = ble_svc_gap_device_name();
    fields.name = (uint8_t *)name;
    fields.name_len = strlen(name);
    fields.name_is_complete = 1;

    rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "Error configurando campos de publicidad BLE: %d", rc);
        return;
    }

    memset(&adv_params, 0, sizeof(adv_params));
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    rc = ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER,
                           &adv_params, ble_gap_event, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "Error iniciando publicidad BLE: %d", rc);
        return;
    }
    ESP_LOGI(TAG, "Publicidad BLE iniciada como '%s'. Esperando conexión...", name);
}

static void ble_on_sync(void)
{
    int rc = ble_hs_id_infer_auto(0, &s_own_addr_type);
    if (rc != 0) {
        ESP_LOGE(TAG, "Error determinando tipo de dirección BLE: %d", rc);
        return;
    }
    ble_advertise();
}

static void ble_host_task(void *param)
{
    ESP_LOGI(TAG, "Tarea NimBLE BLE Host iniciada");
    nimble_port_run();
    nimble_port_freertos_deinit();
}

/* --- Tarea principal de gestión VCP y puente de paquetes hacia el FTDI --- */
static void vcp_task(void *arg)
{
    ESP_LOGI(TAG, "Instalando driver CDC-ACM Host...");
    ESP_ERROR_CHECK(cdc_acm_host_install(NULL));

    ESP_LOGI(TAG, "Registrando driver FTDI FT232R...");
    VCP::register_driver<FT23x>();

    const cdc_acm_host_device_config_t dev_config = {
        .connection_timeout_ms = 1000,
        .out_buffer_size = 512,
        .in_buffer_size = 0,
        .event_cb = handle_event,
        .data_cb = handle_rx,
        .user_arg = NULL,
    };

    while (1) {
        led_update_idle_state();

        auto vcp = std::unique_ptr<CdcAcmDevice>(VCP::open(&dev_config));
        if (vcp == nullptr) {
            vTaskDelay(pdMS_TO_TICKS(1500));
            continue;
        }

        ESP_LOGI(TAG, "=================================================");
        ESP_LOGI(TAG, "¡Módulo FTDI FT232R DETECTADO Y ENUMERADO EN USB!");
        ESP_LOGI(TAG, "=================================================");

        /* Configurar 9600 baudios, 8E1 (8 datos, paridad par, 1 stop) */
        cdc_acm_line_coding_t line_coding = {
            .dwDTERate = PLC_BAUDRATE,
            .bCharFormat = 0,
            .bParityType = 2,
            .bDataBits = 8,
        };
        esp_err_t err = vcp->line_coding_set(&line_coding);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Error configurando line_coding: %s", esp_err_to_name(err));
        }

        vcp->set_control_line_state(true, true);
        s_ftdi_ready = true;
        led_update_idle_state();

        /* Bucle de reenvío: todo lo recibido por BLE se transmite al FTDI */
        BleToFtdiPacket pkt;
        while (s_ftdi_ready) {
            /* Esperar paquete de BLE con timeout de 20ms */
            if (xQueueReceive(s_ble_to_ftdi_queue, &pkt, pdMS_TO_TICKS(20)) == pdTRUE) {
                /* Conmutación dinámica de Baudrate vía comando de control BLE */
                if (pkt.len >= 7 && memcmp(pkt.data, "++BAUD:", 7) == 0) {
                    uint32_t new_baud = 0;
                    if (pkt.len >= 11 && memcmp(pkt.data + 7, "9600", 4) == 0) {
                        new_baud = 9600;
                    } else if (pkt.len >= 12 && memcmp(pkt.data + 7, "19200", 5) == 0) {
                        new_baud = 19200;
                    } else if (pkt.len >= 13 && memcmp(pkt.data + 7, "187500", 6) == 0) {
                        new_baud = 187500;
                    }
                    if (new_baud > 0) {
                        cdc_acm_line_coding_t new_coding = {
                            .dwDTERate = new_baud,
                            .bCharFormat = 0,
                            .bParityType = 2, /* 8E1 estándar Siemens PPI */
                            .bDataBits = 8,
                        };
                        esp_err_t b_err = vcp->line_coding_set(&new_coding);
                        if (b_err == ESP_OK) {
                            s_current_baudrate = new_baud;
                            ESP_LOGI(TAG, "⚡ [AUTO-BAUD] Baudrate conmutado con éxito a %lu baudios 8E1", (unsigned long)new_baud);
                        } else {
                            ESP_LOGE(TAG, "⚡ [AUTO-BAUD] Error cambiando baudrate: %s", esp_err_to_name(b_err));
                        }

                        /* Notificar confirmación a la Laptop vía BLE Notify */
                        char resp_msg[32];
                        int r_len = snprintf(resp_msg, sizeof(resp_msg), "++BAUD:OK:%lu\n", (unsigned long)new_baud);
                        if (s_ble_conn_handle != BLE_HS_CONN_HANDLE_NONE && s_ble_notify_enabled) {
                            struct os_mbuf *om = ble_hs_mbuf_from_flat(resp_msg, r_len);
                            if (om != NULL) {
                                ble_gatts_notify_custom(s_ble_conn_handle, s_ble_tx_val_handle, om);
                            }
                        }
                    }
                    continue; /* ¡No enviar la orden de control al bus RS485 del PLC! */
                }

                if (pkt.len >= 7 && memcmp(pkt.data, "++BAUD?", 7) == 0) {
                    char resp_msg[32];
                    int r_len = snprintf(resp_msg, sizeof(resp_msg), "++BAUD:CURR:%lu\n", (unsigned long)s_current_baudrate);
                    if (s_ble_conn_handle != BLE_HS_CONN_HANDLE_NONE && s_ble_notify_enabled) {
                        struct os_mbuf *om = ble_hs_mbuf_from_flat(resp_msg, r_len);
                        if (om != NULL) {
                            ble_gatts_notify_custom(s_ble_conn_handle, s_ble_tx_val_handle, om);
                        }
                    }
                    continue;
                }

                ESP_LOGI(TAG, ">>> Reenviando por FTDI hacia PLC (%d bytes)...", pkt.len);
                led_set_rgb(0, 0, 40); // Azul = TX hacia PLC
                err = vcp->tx_blocking(pkt.data, pkt.len, 200);
                if (err != ESP_OK) {
                    ESP_LOGE(TAG, "Error transmitiendo por FTDI: %s", esp_err_to_name(err));
                }
                vTaskDelay(pdMS_TO_TICKS(15));
                led_update_idle_state();
            }

            /* Verificar si el FTDI se desconectó */
            if (xSemaphoreTake(s_dev_disconnect_sem, 0) == pdTRUE) {
                ESP_LOGW(TAG, "FTDI desconectado durante bucle");
                break;
            }
        }

        ESP_LOGI(TAG, "Reiniciando ciclo VCP...");
        s_ftdi_ready = false;
        led_update_idle_state();
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "=============================================================");
    ESP_LOGI(TAG, "=== ESP32-S3 BLE UART <-> FTDI USB HOST <-> SIEMENS PPI ===");
    ESP_LOGI(TAG, "=============================================================");

    led_init();
    led_set_rgb(0, 0, 40); // Azul arranque
    vTaskDelay(pdMS_TO_TICKS(200));
    led_set_rgb(0, 0, 0);

    /* 1. Inicializar NVS (para calibración de RF y Bluetooth) */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    s_dev_disconnect_sem = xSemaphoreCreateBinary();
    s_ble_to_ftdi_queue = xQueueCreate(16, sizeof(BleToFtdiPacket));

    /* 2. Inicializar NimBLE Bluetooth LE */
    ESP_LOGI(TAG, "Inicializando NimBLE BLE...");
    ESP_ERROR_CHECK(nimble_port_init());

    ble_hs_cfg.sync_cb = ble_on_sync;

    /* Registrar servicios GATT */
    ble_svc_gap_init();
    ble_svc_gatt_init();
    ESP_ERROR_CHECK(ble_gatts_count_cfg(s_gatt_svcs));
    ESP_ERROR_CHECK(ble_gatts_add_svcs(s_gatt_svcs));
    ESP_ERROR_CHECK(ble_svc_gap_device_name_set(BLE_DEVICE_NAME));

    ble_store_config_init();
    nimble_port_freertos_init(ble_host_task);

    /* 3. Inicializar USB Host Library */
    ESP_LOGI(TAG, "Instalando USB Host Library...");
    usb_host_config_t host_config = {};
    host_config.skip_phy_setup = false;
    host_config.intr_flags = ESP_INTR_FLAG_LEVEL1;
    ESP_ERROR_CHECK(usb_host_install(&host_config));

    /* 4. Tarea de gestión de eventos USB */
    xTaskCreatePinnedToCore(usb_lib_task, "usb_lib", 4096, NULL, 10, NULL, 0);

    /* 5. Tarea de VCP y puente de paquetes */
    xTaskCreatePinnedToCore(vcp_task, "vcp_task", 4096, NULL, 5, NULL, 1);

    ESP_LOGI(TAG, "Sistema iniciado. BLE activo y esperando FTDI...");
}
