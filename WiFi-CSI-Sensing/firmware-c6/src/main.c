/* WifiSensing C6 pair. SPDX-License-Identifier: MIT
 * ESP-IDF 5.4 / HT20 / MCS0 LGI. Queue-based CSI output on UART0 and native USB.
 * The gain API is Espressif esp_csi_gain_ctrl 0.1.5 (Apache-2.0).
 * No SSID, password or internet connection is used by this sensing link.
 */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_wifi.h"
#include "esp_now.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "driver/uart.h"
#include "driver/usb_serial_jtag.h"
#include "esp_csi_gain_ctrl.h"
#include "cJSON.h"

static const uint8_t sender_mac[6] = {0x02,0x57,0x53,0x32,0x06,0x01};
static const uint8_t broadcast_mac[6] = {255,255,255,255,255,255};
static QueueHandle_t samples;
static SemaphoreHandle_t output_lock;
static TaskHandle_t sender_task;
static int channel = 11;
static uint32_t sent, received, dropped, rejected, gain_samples;
static int64_t last_received;
static bool calibrated;
static volatile bool reset_gain;

typedef struct {
    int8_t iq[128];
    uint16_t len;
    int rssi, noise, rate, invalid;
    uint8_t agc;
    int8_t fft;
    uint32_t seq, local_timestamp;
    int64_t t;
    float gain;
    bool gain_ready;
} sample_t;

static void line_out(const char *line) {
    xSemaphoreTake(output_lock, portMAX_DELAY);
    size_t n = strlen(line);
    uart_write_bytes(UART_NUM_0, line, n);
    uart_write_bytes(UART_NUM_0, "\n", 1);
    // USB may be unplugged when only the UART bridge is used. Never block on it.
    usb_serial_jtag_write_bytes(line, n, 0);
    usb_serial_jtag_write_bytes("\n", 1, 0);
    xSemaphoreGive(output_lock);
}

static void status(void) {
    char buf[850];
    snprintf(buf,sizeof(buf),"{\"event\":\"status\",\"firmware\":\"WifiSensing-c6-pair-1\",\"chip\":\"esp32c6\",\"role\":\"%s\",\"state\":\"%s\",\"mode\":\"espnow\",\"channel\":%d,\"target_hz\":60,\"sent\":%lu,\"received\":%lu,\"dropped\":%lu,\"rejected\":%lu,\"gain_ready\":%s,\"gain_samples\":%lu,\"baud\":921600,\"protocol\":1}",
        WS_ROLE_TX?"transmitter":"receiver", WS_ROLE_TX?"transmitting":(esp_timer_get_time()-last_received<1000000&&last_received?"connected":"waiting_sender"),
        channel,(unsigned long)sent,(unsigned long)received,(unsigned long)dropped,(unsigned long)rejected,
        calibrated?"true":"false",(unsigned long)gain_samples);
    line_out(buf);
}

static void command_line(const char *line) {
    cJSON *o = cJSON_Parse(line);
    if (!o) return;
    cJSON *cmd = cJSON_GetObjectItem(o,"cmd");
    if (cJSON_IsString(cmd)) {
        if (!strcmp(cmd->valuestring,"calibrate")) reset_gain = true;
        if (!strcmp(cmd->valuestring,"configure")) {
            cJSON *ch = cJSON_GetObjectItem(o,"channel");
            if (cJSON_IsNumber(ch) && (ch->valueint==1 || ch->valueint==6 || ch->valueint==11)) {
                if (esp_wifi_set_channel(ch->valueint,WIFI_SECOND_CHAN_NONE)==ESP_OK) {
                    channel=ch->valueint;
                    nvs_handle_t h;
                    if (nvs_open("ws_pair",NVS_READWRITE,&h)==ESP_OK) {
                        nvs_set_i32(h,"channel",channel); nvs_commit(h); nvs_close(h);
                    }
                    reset_gain = true;
                }
            }
        }
        status();
    }
    cJSON_Delete(o);
}

static void input_task(void *arg) {
    char input[256]; int used=0; bool usb=(bool)(intptr_t)arg;
    for (;;) {
        uint8_t c;
        int n=usb?usb_serial_jtag_read_bytes(&c,1,pdMS_TO_TICKS(20)):uart_read_bytes(UART_NUM_0,&c,1,pdMS_TO_TICKS(20));
        if(n<=0) continue;
        if(c=='\n' || c=='\r') { if(used) {input[used]=0; command_line(input);} used=0; }
        else if(used<(int)sizeof(input)-1) input[used++]=c;
        else used=0;
    }
}

static void csi_received(void *ctx,wifi_csi_info_t *info) {
    if(!info || !info->buf || memcmp(info->mac,sender_mac,6)) return;
    if(info->len!=128 && info->len!=114) { rejected++; return; }
    sample_t s={0};
    s.len=info->len; memcpy(s.iq,info->buf,s.len);
    s.rssi=info->rx_ctrl.rssi; s.noise=info->rx_ctrl.noise_floor; s.rate=info->rx_ctrl.rate;
    s.invalid=info->first_word_invalid; s.local_timestamp=info->rx_ctrl.timestamp;
    s.t=esp_timer_get_time(); s.seq=received++;
    esp_csi_gain_ctrl_get_rx_gain(&info->rx_ctrl,&s.agc,&s.fft);
    last_received=s.t;
    // Copy only; serial I/O, JSON and gain-baseline work happen off the Wi-Fi task.
    if(xQueueSend(samples,&s,0)!=pdTRUE) dropped++;
}

static void output_task(void *arg) {
    sample_t s; char line[2100];
    for(;;) {
        if(xQueueReceive(samples,&s,pdMS_TO_TICKS(200))!=pdTRUE) continue;
        if(reset_gain) { esp_csi_gain_ctrl_reset_rx_gain_baseline(); gain_samples=0; calibrated=false; reset_gain=false; }
        if(gain_samples<120) {
            esp_csi_gain_ctrl_record_rx_gain(s.agc,s.fft); gain_samples++;
            if(gain_samples==120) {
                uint8_t agc; int8_t fft;
                calibrated=esp_csi_gain_ctrl_get_rx_gain_baseline(&agc,&fft)==ESP_OK;
            }
        }
        s.gain=1.0f;
        s.gain_ready=calibrated && esp_csi_gain_ctrl_get_gain_compensation(&s.gain,s.agc,s.fft)==ESP_OK && isfinite(s.gain) && s.gain>0;
        int n=snprintf(line,sizeof(line),"{\"timestamp\":%.6f,\"chip\":\"esp32c6\",\"layout\":\"%s\",\"csi_profile\":\"c6_espnow_ht20_v1\",\"rssi\":%d,\"noise_floor\":%d,\"rate\":%d,\"channel\":%d,\"agc_gain\":%u,\"fft_gain\":%d,\"gain_compensation\":%.8g,\"gain_ready\":%s,\"rx_seq\":%lu,\"dropped\":%lu,\"local_timestamp\":%lu,\"first_word_invalid\":%d,\"len\":%d,\"data\":[",
            s.t/1000000.,s.len==128?"c6_ht20_centered64":"c6_ht20_packed57",s.rssi,s.noise,s.rate,channel,s.agc,s.fft,
            s.gain,s.gain_ready?"true":"false",(unsigned long)s.seq,(unsigned long)dropped,(unsigned long)s.local_timestamp,s.invalid,s.len);
        for(int i=0;i<s.len;i++) n+=snprintf(line+n,sizeof(line)-n,"%s%d",i?",":"",s.iq[i]);
        snprintf(line+n,sizeof(line)-n,"]}"); line_out(line);
    }
}

static void send_tick(void *arg) { if(sender_task) xTaskNotifyGive(sender_task); }
static void transmit_task(void *arg) {
    uint32_t payload[3]={0x57533243,0,0};
    for(;;) {
        ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
        payload[1]=sent; payload[2]=(uint32_t)esp_timer_get_time();
        if(esp_now_send(broadcast_mac,(uint8_t*)payload,sizeof(payload))==ESP_OK) sent++;
        else dropped++;
    }
}

void app_main(void) {
    esp_err_t err=nvs_flash_init();
    if(err==ESP_ERR_NVS_NO_FREE_PAGES || err==ESP_ERR_NVS_NEW_VERSION_FOUND) { ESP_ERROR_CHECK(nvs_flash_erase()); err=nvs_flash_init(); }
    ESP_ERROR_CHECK(err);
    nvs_handle_t h;
    if(nvs_open("ws_pair",NVS_READONLY,&h)==ESP_OK) { int32_t saved; if(nvs_get_i32(h,"channel",&saved)==ESP_OK && (saved==1||saved==6||saved==11)) channel=saved; nvs_close(h); }
    output_lock=xSemaphoreCreateMutex(); samples=xQueueCreate(96,sizeof(sample_t));
    uart_config_t u={.baud_rate=921600,.data_bits=UART_DATA_8_BITS,.parity=UART_PARITY_DISABLE,.stop_bits=UART_STOP_BITS_1,.flow_ctrl=UART_HW_FLOWCTRL_DISABLE,.source_clk=UART_SCLK_DEFAULT};
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0,4096,8192,0,NULL,0));
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0,&u));
    ESP_ERROR_CHECK(uart_set_pin(UART_NUM_0,16,17,UART_PIN_NO_CHANGE,UART_PIN_NO_CHANGE));
    usb_serial_jtag_driver_config_t usb={.tx_buffer_size=8192,.rx_buffer_size=2048};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
    ESP_ERROR_CHECK(esp_netif_init()); ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t cfg=WIFI_INIT_CONFIG_DEFAULT(); ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM)); ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    if(WS_ROLE_TX) ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA,sender_mac));
    ESP_ERROR_CHECK(esp_wifi_start()); ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_band_mode(WIFI_BAND_MODE_2G_ONLY));
    wifi_protocols_t protocol={.ghz_2g=WIFI_PROTOCOL_11N};
    wifi_bandwidths_t bandwidth={.ghz_2g=WIFI_BW_HT20};
    ESP_ERROR_CHECK(esp_wifi_set_protocols(WIFI_IF_STA,&protocol));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidths(WIFI_IF_STA,&bandwidth));
    ESP_ERROR_CHECK(esp_wifi_set_channel(channel,WIFI_SECOND_CHAN_NONE));
    if(WS_ROLE_TX) {
        ESP_ERROR_CHECK(esp_now_init());
        esp_now_peer_info_t peer={.channel=0,.ifidx=WIFI_IF_STA,.encrypt=false}; memcpy(peer.peer_addr,broadcast_mac,6);
        ESP_ERROR_CHECK(esp_now_add_peer(&peer));
        esp_now_rate_config_t rate={.phymode=WIFI_PHY_MODE_HT20,.rate=WIFI_PHY_RATE_MCS0_LGI,.ersu=false,.dcm=false};
        ESP_ERROR_CHECK(esp_now_set_peer_rate_config(broadcast_mac,&rate));
        xTaskCreate(transmit_task,"ws_send",4096,NULL,5,&sender_task);
        esp_timer_handle_t timer; esp_timer_create_args_t tc={.callback=send_tick,.name="ws_60hz"};
        ESP_ERROR_CHECK(esp_timer_create(&tc,&timer)); ESP_ERROR_CHECK(esp_timer_start_periodic(timer,16667));
    } else {
        ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
        wifi_csi_config_t c={.enable=true,.acquire_csi_legacy=false,.acquire_csi_ht20=true,.acquire_csi_ht40=false,.acquire_csi_su=false,.acquire_csi_mu=false,.acquire_csi_dcm=false,.acquire_csi_beamformed=false,.acquire_csi_he_stbc=2,.val_scale_cfg=false,.dump_ack_en=false};
        ESP_ERROR_CHECK(esp_wifi_set_csi_config(&c)); ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_received,NULL));
        ESP_ERROR_CHECK(esp_wifi_set_csi(true)); xTaskCreate(output_task,"ws_csi",6144,NULL,4,NULL);
    }
    xTaskCreate(input_task,"ws_uart",4096,(void*)0,3,NULL); xTaskCreate(input_task,"ws_usb",4096,(void*)1,3,NULL);
    for(;;) { status(); vTaskDelay(pdMS_TO_TICKS(1000)); }
}
