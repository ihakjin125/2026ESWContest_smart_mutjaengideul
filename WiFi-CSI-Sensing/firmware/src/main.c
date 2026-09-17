/* WifiSensing router CSI firmware. ESP-IDF 5.4, ESP32-S3/C3.
 * Router ping/LLTF approach: Espressif esp-csi csi_recv_router example.
 * No credentials are written to flash or echoed to the serial stream. */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "driver/uart.h"
#include "ping/ping_sock.h"
#include "cJSON.h"

typedef struct {
    int8_t iq[128];
    int rssi, channel, invalid;
    uint32_t local_timestamp;
    int64_t time_us;
} sample_t;
static QueueHandle_t samples;
static SemaphoreHandle_t output_mutex;
static esp_netif_t *netif;
static esp_ping_handle_t ping_handle;
static uint8_t ap_mac[6];
static volatile bool connected;
static volatile unsigned dropped;

static void send_line(const char *line) {
    xSemaphoreTake(output_mutex, portMAX_DELAY);
    uart_write_bytes(UART_NUM_0, line, strlen(line));
    uart_write_bytes(UART_NUM_0, "\n", 1);
    xSemaphoreGive(output_mutex);
}
static void send_json(cJSON *object) {
    char *text = cJSON_PrintUnformatted(object);
    if (text) { send_line(text); free(text); }
    cJSON_Delete(object);
}
static void status(const char *state, int reason) {
    cJSON *msg = cJSON_CreateObject();
    cJSON_AddStringToObject(msg, "event", "status");
    cJSON_AddStringToObject(msg, "firmware", "WifiSensing-router-uart-2");
    cJSON_AddStringToObject(msg, "chip", CONFIG_IDF_TARGET);
    cJSON_AddStringToObject(msg, "state", state);
    cJSON_AddNumberToObject(msg, "reason", reason);
    cJSON_AddNumberToObject(msg, "dropped", dropped);
    cJSON_AddNumberToObject(msg, "baud", 921600);
    send_json(msg);
}
static void csi_received(void *ctx, wifi_csi_info_t *info) {
    if (!connected || !info || !info->buf || info->len < 128 || memcmp(info->mac, ap_mac, 6)) return;
    sample_t sample;
    memcpy(sample.iq, info->buf, 128);
    sample.rssi = info->rx_ctrl.rssi;
    sample.channel = info->rx_ctrl.channel;
    sample.invalid = info->first_word_invalid;
    sample.local_timestamp = info->rx_ctrl.timestamp;
    sample.time_us = esp_timer_get_time();
    if (xQueueSend(samples, &sample, 0) != pdTRUE) dropped++;
}
static void output_task(void *arg) {
    sample_t sample;
    char line[1500];
    while (true) {
        if (xQueueReceive(samples, &sample, portMAX_DELAY) != pdTRUE) continue;
        int n = snprintf(line, sizeof(line), "{\"timestamp\":%.6f,\"rssi\":%d,\"channel\":%d,\"local_timestamp\":%lu,\"first_word_invalid\":%d,\"len\":128,\"data\":[",
                         sample.time_us / 1000000.0, sample.rssi, sample.channel,
                         (unsigned long)sample.local_timestamp, sample.invalid);
        for (int i = 0; i < 128; i++) n += snprintf(line+n, sizeof(line)-n, "%s%d", i ? "," : "", sample.iq[i]);
        snprintf(line+n, sizeof(line)-n, "]}");
        send_line(line);
    }
}
static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        connected = false;
        if (ping_handle) esp_ping_stop(ping_handle);
        esp_wifi_set_csi(false);
        status("disconnected", ((wifi_event_sta_disconnected_t *)data)->reason);
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        wifi_ap_record_t ap;
        if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) return;
        memcpy(ap_mac, ap.bssid, 6);
        wifi_csi_config_t config = {.lltf_en = true, .htltf_en = false, .stbc_htltf2_en = false,
            .ltf_merge_en = true, .channel_filter_en = true, .manu_scale = false, .shift = 0};
        ESP_ERROR_CHECK(esp_wifi_set_csi_config(&config));
        ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_received, NULL));
        connected = true;
        ESP_ERROR_CHECK(esp_wifi_set_csi(true));
        if (ping_handle) { esp_ping_delete_session(ping_handle); ping_handle = NULL; }
        esp_netif_ip_info_t ip;
        esp_netif_get_ip_info(netif, &ip);
        esp_ping_config_t ping = ESP_PING_DEFAULT_CONFIG();
        ping.count = 0;
        ping.interval_ms = 20;
        ping.timeout_ms = 100;
        ping.data_size = 16;
        ping.task_stack_size = 3072;
        ping.target_addr.type = ESP_IPADDR_TYPE_V4;
        ping.target_addr.u_addr.ip4.addr = ip.gw.addr;
        esp_ping_callbacks_t callbacks = {0};
        ESP_ERROR_CHECK(esp_ping_new_session(&ping, &callbacks, &ping_handle));
        ESP_ERROR_CHECK(esp_ping_start(ping_handle));
        status("connected", 0);
    }
}
static void command(char *line) {
    cJSON *root = cJSON_Parse(line);
    if (!root) return;
    const cJSON *cmd = cJSON_GetObjectItemCaseSensitive(root, "cmd");
    if (!cJSON_IsString(cmd)) { cJSON_Delete(root); return; }
    if (!strcmp(cmd->valuestring, "status")) status(connected ? "connected" : "ready", 0);
    else if (!strcmp(cmd->valuestring, "scan")) {
        if (connected) { status("stop_before_scan", 0); cJSON_Delete(root); return; }
        wifi_scan_config_t config = {.show_hidden = false};
        esp_err_t err = esp_wifi_scan_start(&config, true);
        if (err != ESP_OK) status("scan_failed", err);
        else {
            uint16_t count = 30;
            wifi_ap_record_t *records = calloc(count, sizeof(wifi_ap_record_t));
            if (records && esp_wifi_scan_get_ap_records(&count, records) == ESP_OK) {
                cJSON *msg = cJSON_CreateObject(), *networks = cJSON_AddArrayToObject(msg, "networks");
                cJSON_AddStringToObject(msg, "event", "scan");
                for (int i = 0; i < count; i++) {
                    cJSON *ap = cJSON_CreateObject();
                    char bssid[18];
                    snprintf(bssid, sizeof(bssid), "%02x:%02x:%02x:%02x:%02x:%02x", records[i].bssid[0], records[i].bssid[1], records[i].bssid[2], records[i].bssid[3], records[i].bssid[4], records[i].bssid[5]);
                    cJSON_AddStringToObject(ap, "ssid", (char *)records[i].ssid);
                    cJSON_AddStringToObject(ap, "bssid", bssid);
                    cJSON_AddNumberToObject(ap, "rssi", records[i].rssi);
                    cJSON_AddNumberToObject(ap, "channel", records[i].primary);
                    cJSON_AddBoolToObject(ap, "secured", records[i].authmode != WIFI_AUTH_OPEN);
                    cJSON_AddItemToArray(networks, ap);
                }
                send_json(msg);
            }
            free(records);
        }
    } else if (!strcmp(cmd->valuestring, "connect")) {
        cJSON *ssid = cJSON_GetObjectItemCaseSensitive(root, "ssid");
        cJSON *pass = cJSON_GetObjectItemCaseSensitive(root, "password");
        cJSON *bssid = cJSON_GetObjectItemCaseSensitive(root, "bssid");
        if (cJSON_IsString(ssid) && cJSON_IsString(pass) && strlen(ssid->valuestring) > 0 && strlen(ssid->valuestring) <= 32 && strlen(pass->valuestring) <= 63) {
            wifi_config_t config = {0};
            memcpy(config.sta.ssid, ssid->valuestring, strlen(ssid->valuestring));
            memcpy(config.sta.password, pass->valuestring, strlen(pass->valuestring));
            if (cJSON_IsString(bssid)) {
                unsigned values[6];
                if (sscanf(bssid->valuestring, "%x:%x:%x:%x:%x:%x", &values[0], &values[1], &values[2], &values[3], &values[4], &values[5]) == 6) {
                    config.sta.bssid_set = true;
                    for (int i = 0; i < 6; i++) config.sta.bssid[i] = values[i];
                }
            }
            if (connected) { esp_wifi_disconnect(); vTaskDelay(pdMS_TO_TICKS(300)); }
            esp_err_t err = esp_wifi_set_config(WIFI_IF_STA, &config);
            memset(&config, 0, sizeof(config));
            if (err == ESP_OK) err = esp_wifi_connect();
            status(err == ESP_OK ? "connecting" : "connect_failed", err);
        } else status("invalid_credentials", 0);
    } else if (!strcmp(cmd->valuestring, "disconnect")) {
        esp_wifi_disconnect();
    }
    cJSON_Delete(root);
}
void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }
    output_mutex = xSemaphoreCreateMutex();
    samples = xQueueCreate(64, sizeof(sample_t));
    uart_config_t uart = {.baud_rate = 921600, .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE, .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE, .source_clk = UART_SCLK_DEFAULT};
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0, &uart));
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 8192, 0, NULL, 0));
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    netif = esp_netif_create_default_wifi_sta();
    wifi_init_config_t wifi = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20));
    xTaskCreate(output_task, "csi_output", 4096, NULL, 5, NULL);
    status("ready", 0);
    char line[1024];
    size_t used = 0;
    bool overflow = false;
    while (true) {
        uint8_t ch;
        if (uart_read_bytes(UART_NUM_0, &ch, 1, pdMS_TO_TICKS(100)) <= 0) continue;
        if (ch == '\n') {
            line[used] = 0;
            if (!overflow) command(line);
            memset(line, 0, sizeof(line));
            used = 0;
            overflow = false;
        } else if (ch != '\r') {
            if (used < sizeof(line)-1) line[used++] = ch;
            else overflow = true;
        }
    }
}
